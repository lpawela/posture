"""FastAPI app: serves the web client, the management API and the live monitor.

Endpoints
---------
* ``GET  /health``          -- liveness probe.
* ``GET  /api/exercises``   -- exercises + metadata + reference videos.
* ``/api/...``              -- auth, doctor/patient, assignments, scores, messages
                               (see :mod:`app.api`).
* ``WS   /ws/analyze``      -- live, whole-workout monitoring; records the
                               result for authenticated patients.
* ``GET  /``                -- the static web client.

Pose estimation happens in the browser; only the 33 landmarks per frame are
streamed here. The server runs the shared analyzers, aggregates reps into sets,
scores form, and (for a logged-in patient) stores the finished workout.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import build_api_router
from app.exercises.registry import get_analyzer, list_exercises
from app.landmarks import PoseFrame
from app.models import Role
from app.store import Conflict, NotFound, PermissionDenied, Store, StoreError
from app.workout import WorkoutSession

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_STATUS_FOR_ERROR = {
    Conflict: 409,
    NotFound: 404,
    PermissionDenied: 403,
}


def build_default_store():
    """Pick a store from the environment.

    If ``POSTURE_DATABASE_URL`` is set, run migrations and use the persistent
    SQLAlchemy-backed store (SQLite or Postgres). Otherwise fall back to the
    in-memory store — which is also what tests inject explicitly.
    """
    url = os.environ.get("POSTURE_DATABASE_URL")
    if not url:
        return Store()
    from app.migrate import run_migrations
    from app.sql_store import SqlStore

    run_migrations(url)  # schema is built/maintained via Alembic, not create_all
    return SqlStore(url)


def create_app(store=None) -> FastAPI:
    app = FastAPI(title="Posture", version=__version__)
    app.state.store = store if store is not None else build_default_store()

    @app.exception_handler(StoreError)
    async def _store_error_handler(_request: Request, exc: StoreError):
        status = _STATUS_FOR_ERROR.get(type(exc), 400)
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/exercises")
    def exercises() -> dict:
        return {"exercises": list_exercises()}

    app.include_router(build_api_router())

    @app.websocket("/ws/analyze")
    async def analyze(websocket: WebSocket) -> None:
        await websocket.accept()
        store: Store = websocket.app.state.store
        params = websocket.query_params

        user = store.user_for_token(params.get("token"))

        # If a patient connects with their own assignment, drive the session
        # from the prescription (exercise + set/rep targets).
        assignment = None
        if params.get("assignment_id") and user and user.role is Role.PATIENT:
            try:
                candidate = store.get_assignment(int(params["assignment_id"]))
                if candidate.patient_id == user.id:
                    assignment = candidate
            except (ValueError, NotFound):
                assignment = None

        if assignment is not None:
            exercise = assignment.exercise
            target_sets, target_reps = assignment.target_sets, assignment.target_reps
        else:
            exercise = params.get("exercise", "squat")
            target_sets = target_reps = None

        try:
            analyzer = get_analyzer(exercise)
        except ValueError as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close()
            return

        can_record = user is not None and user.role is Role.PATIENT
        session = WorkoutSession(exercise, target_sets, target_reps)

        await websocket.send_json(
            {
                "type": "ready",
                "exercise": exercise,
                "target_sets": target_sets,
                "target_reps": target_reps,
                "recording": can_record,
            }
        )

        def session_state() -> dict:
            return {
                "completed_sets": session.completed_sets,
                "current_set_reps": session.current_set_reps,
                "total_reps": session.total_reps,
                "target_sets": target_sets,
                "target_reps": target_reps,
            }

        try:
            while True:
                message = await websocket.receive_json()
                kind = message.get("type")

                if kind == "reset":
                    analyzer.reset()
                    session = WorkoutSession(exercise, target_sets, target_reps)
                    await websocket.send_json({"type": "reset_ok", "rep_count": 0})
                    continue

                if kind == "end_set":
                    session.end_set()
                    await websocket.send_json(
                        {"type": "set_complete", **session_state()}
                    )
                    continue

                if kind == "finish":
                    summary = session.finish()
                    payload = {"type": "summary", **summary.to_dict()}
                    if can_record:
                        record = store.record_workout(
                            user.id,
                            summary,
                            assignment.id if assignment else None,
                        )
                        payload["record_id"] = record.id
                    await websocket.send_json(payload)
                    await websocket.close()
                    return

                landmarks = message.get("landmarks")
                if not landmarks:
                    continue
                try:
                    frame = PoseFrame.from_list(landmarks)
                except (ValueError, TypeError, KeyError) as exc:
                    await websocket.send_json(
                        {"type": "error", "message": f"bad frame: {exc}"}
                    )
                    continue

                result = analyzer.update(frame)
                if result.rep_score is not None:
                    session.record_rep(result.rep_score)

                payload = result.to_dict()
                payload["type"] = "analysis"
                payload["session"] = session_state()
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            return

    # Mounted last so the API/WS routes above take precedence.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()
