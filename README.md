# Posture — webcam exercise form coach

Estimates human pose from a webcam feed and gives live form feedback for two
exercises: **squat** and **deadlift**. It runs in any modern browser, so the
same app works on a **phone/tablet** and on the **desktop web**.

It also has a small **clinical layer**: **doctors** monitor **patients**,
prescribe exercises (e.g. *3 sets of 12 deadlifts*), and review the scores
their patients earn. The app monitors a whole workout — counting **sets** and
**reps** and scoring how far each rep is from the ideal — and doctors and
patients can **message** each other.

This repository is the **skeleton**: a clean, tested architecture you can build
on. Rep counting and form heuristics are first-pass and intentionally simple.

## How it works

```
 Browser (phone / tablet / desktop)            Backend (FastAPI)
 ┌─────────────────────────────────┐          ┌──────────────────────────┐
 │ getUserMedia → <video>          │          │ /health                  │
 │ MediaPipe PoseLandmarker (WASM) │  33 land-│ /api/exercises           │
 │   → 33 landmarks/frame          │  marks   │ /ws/analyze  (WebSocket) │
 │ canvas skeleton overlay         │ ───JSON─▶│   → SquatAnalyzer        │
 │ WebSocket client                │ ◀──reps──│   → DeadliftAnalyzer     │
 └─────────────────────────────────┘  feedback└──────────────────────────┘
```

Pose estimation happens **in the browser** (fast on phones, and no video ever
leaves the device). Only the 33 landmark points per frame are sent to the
backend, which runs the shared, unit-tested analyzers, **aggregates reps into
sets, scores form**, and — for a logged-in patient — **stores the finished
workout** so their doctor can review it. Keeping the analysis in Python means
one source of truth that is fully covered by tests.

## Users, assignments, scoring & messaging

* **Roles.** Register as a `patient` or a `doctor`. Auth is token-based
  (PBKDF2-hashed passwords, opaque bearer tokens). Two **admin** tiers also
  exist (see below) but cannot be self-registered.
* **Monitoring.** A doctor adds a patient and assigns an exercise with a target
  (e.g. `deadlift`, 3×12). The patient launches that assignment; the camera
  monitors the whole workout and the server counts **sets** + **reps**.
* **Scoring (distance from ideal).** Each exercise declares scoring rules over
  the rep's metric *extremes* (squat depth = min knee angle, fold-over = max
  torso lean; deadlift lockout = max hip angle, etc.). A rep starts at **100**
  and loses points the further a metric drifts past a tolerance band around its
  ideal. Reps roll up to a **set score**, a **form score** (mean rep score) and
  an **overall score** that also factors *completion* (reps done vs prescribed).
  See [`app/scoring.py`](app/scoring.py) and [`app/workout.py`](app/workout.py).
* **Scores for doctors.** `GET /api/doctor/patients/{id}/workouts` (linked
  doctors only). Patients see their own at `GET /api/me/workouts`.
* **Messaging.** Linked doctor/patient pairs can message each other
  (`POST /api/messages`, `GET /api/messages/{other_id}`).

### Admin tiers

Two tiers of admin account, with a strict access boundary:

| Tier | Role | Can see |
|------|------|---------|
| **Basic** | `admin_basic` | **General user data only** — the account roster (`GET /api/admin/users`), per-user general profile, and role counts (`GET /api/admin/stats`). **No medical records.** |
| **Super** | `admin_super` | **Complete access** — everything above **plus** each user's medical records: links (who treats whom), assignments, workout scores and messages (`GET /api/admin/users/{id}/medical`, `GET /api/admin/workouts`), and the ability to create other admins. |

A basic admin requesting any medical endpoint gets **403**. "Medical record
info" = assignments (prescriptions), workout records (scores) and messages;
"general user data" = account identity + role + aggregate counts.

Admins are **never** self-registered:

* **Bootstrap the first super admin** (only works while no admin exists):
  ```bash
  curl -X POST localhost:8000/api/admin/bootstrap \
    -H 'Content-Type: application/json' \
    -d '{"username":"root","password":"secret","display_name":"Root"}'
  ```
* A **super admin** creates further admins of either tier via
  `POST /api/admin/admins` (`{"username","password","tier":"basic"|"super"}`) —
  or in the web UI under *Admin accounts*.

## Storage, migrations & seed data

There are two interchangeable storage backends behind one `Store` interface:

* **In-memory** ([`app/store.py`](app/store.py)) — the default; fast and
  dependency-free. Used by the test suite (a fresh store per test).
* **SQLAlchemy** ([`app/sql_store.py`](app/sql_store.py)) — persistent, works
  with **SQLite** (default) or **Postgres**. ORM rows
  ([`app/db_models.py`](app/db_models.py)) are converted to the same domain
  dataclasses, so the API/analyzers don't change.

Selection is by environment: if **`POSTURE_DATABASE_URL`** is set, the app runs
migrations and uses the SQL store; otherwise it stays in-memory.

```bash
make migrate    # alembic upgrade head   (schema via migrations, not create_all)
make seed       # one user per role + sample data (idempotent)
make serve      # migrate-on-startup + seed + serve
# Postgres instead of SQLite:
make serve DB_URL='postgresql+psycopg://posture:posture@db/posture'
```

* **Migrations** are real [Alembic](https://alembic.sqlalchemy.org/) revisions
  in [`migrations/`](migrations/); the app applies them on startup and
  [`app/migrate.py`](app/migrate.py) exposes them programmatically. `make serve`
  is the source of truth for the schema — `create_all` is only used in tests.
* **Seed data** ([`app/seed.py`](app/seed.py)) creates one account **per role**
  — `root` (super admin), `frontdesk` (basic admin), `dr.house` (doctor),
  `jdoe` (patient), password `password123` — plus a doctor↔patient link, two
  assignments, a completed workout, and a message thread.

## Exercise library (local MuscleWiki catalog)

Beyond the two pose-analyzed lifts, the app ships a **local catalog of 954
exercises** sourced from [MuscleWiki](https://musclewiki.com) — name, equipment,
difficulty, force, target muscles, step instructions and demo video URLs.

* The dataset is kept **locally** in
  [`data/musclewiki_exercises.json`](data/musclewiki_exercises.json) (committed),
  normalised by [`app/catalog.py`](app/catalog.py), and loaded into the database
  by [`app/catalog_import.py`](app/catalog_import.py) — idempotent, so re-runs
  just upsert.

  ```bash
  make catalog        # import the local dataset into the DB
  # (make seed and the served app import it automatically)
  ```

* Browse/search it via the API (public, no auth) or the web *Exercise library*
  page:

  ```
  GET /api/catalog?muscle=Biceps&category=Barbell&difficulty=Beginner&q=curl
  GET /api/catalog/filters        # available muscles / equipment / levels
  GET /api/catalog/{slug|id}      # one exercise (steps, muscles, video URLs)
  ```

> Only the structured catalog is stored locally; demo media stays referenced by
> its MuscleWiki CDN URL rather than re-hosted. The catalog is separate from the
> squat/deadlift **analyzers**, which add live pose scoring on top.

## Project layout

| Path | Purpose |
|------|---------|
| `app/geometry.py`, `app/landmarks.py` | pure angle helpers + BlazePose model |
| `app/exercises/` | rep-counting analyzers, scoring rules, registry |
| `app/scoring.py` | form-deviation scoring scheme |
| `app/workout.py` | `WorkoutSession` — sets/reps/score aggregation |
| `app/models.py`, `app/auth.py` | domain dataclasses, password hashing |
| `app/store.py` | in-memory store (the `Store` contract) |
| `app/sql_store.py`, `app/db_models.py` | SQLAlchemy store + ORM models |
| `app/migrate.py`, `migrations/` | Alembic migrations |
| `app/seed.py` | per-role seed data |
| `app/api.py` | REST API (auth, doctor/patient, assignments, scores, messages, admin) |
| `app/server.py` | FastAPI app (static client + API + session WebSocket) |
| `web/` | browser client (`index.html`, `app.js`, `pose.js`, `styles.css`) |
| `tests/` | pytest suite + synthetic pose factory |

## Reference form videos

Verified live via YouTube oEmbed (see `reference_videos.json` / the registry):

- **Squat** — [How To Squat: Layne Norton's Squat Tutorial](https://www.youtube.com/watch?v=t2b8UdqmlFs) (Bodybuilding.com)
- **Deadlift** — ["How To" Deadlift](https://www.youtube.com/watch?v=Y1IGeJEXpF4) (Alan Thrall, Untamed Strength)

They are surfaced in the UI and returned from `GET /api/exercises`.

## Running the tests (Docker)

Local tests run **in a Docker container** — no local Python setup required:

```bash
make test                         # build image + run pytest in a container
# or, equivalently:
docker compose run --rm tests
```

Escape hatch if you already have the deps locally:

```bash
make test-local                   # just `pytest`
```

The Python suite (**160 tests**) covers geometry, the landmark model, both
analyzers (rep counting + every form rule, plus side-on / occluded-side and
degenerate-frame handling), the scoring scheme, the `WorkoutSession`
aggregator, password hashing, the **data store contract run against *both* the
in-memory and SQLAlchemy backends**, the REST API (auth, logout/revoke, linking,
assignments, scores, messaging — including permission checks), the
session-recording WebSocket (including foreign-assignment rejection), the
**admin tiers** (general-vs-medical access boundary), the **Alembic migrations**
(schema build + idempotency), the **seed data**, the API running on the SQL
store, and the **exercise catalog** (MuscleWiki normalisation + slug
de-duplication, store parity, import, API, and a sanity check over the real
local dataset).

### Front-end tests

The browser client has its own unit tests (Node's test runner + jsdom),
covering the pure HUD logic in [`web/hud.js`](web/hud.js) (set/rep label, tint
mapping, the rep-feedback latch, the navigate-away decision) and the
`PoseWorkout` **camera/WebSocket lifecycle** in [`web/pose.js`](web/pose.js)
(start/stop/restart, finish-and-release, disconnect recovery, and the
superseded-socket race), plus a jsdom check that `app.js` applies those
decisions to the real DOM:

```bash
make test-web                     # node:20 container; installs jsdom, runs the tests
# or locally, if you have Node 20+:  cd web && npm install && npm test
```

## Running the app

```bash
make serve                        # or: docker compose up app
```

Then open <http://localhost:8000>. **Register** as a doctor or a patient:

* As a **doctor**: add a patient by username, assign an exercise (sets × reps),
  and review each patient's scores; message your patients.
* As a **patient**: open *My exercises*, press **Start** on an assignment, and
  perform the workout in front of the camera. When you **Finish**, your sets,
  reps and score are saved for your doctor. Message your doctor from *Messages*.

(For a quick anonymous try without an account, the camera/WS still streams live
feedback; it just won't be recorded.)

If port 8000 is already in use, pick another host port:

```bash
make serve PORT=8001              # or: PORT=8001 docker compose up app
```

> **Camera permissions:** browsers only grant camera access on a *secure
> context* — `http://localhost` is fine on desktop, but to use a **phone/tablet**
> on your LAN you'll need HTTPS (e.g. put it behind a reverse proxy with TLS, or
> tunnel with a tool like `ngrok`). Stand **side-on** with your whole body in
> frame for the most reliable angles.

## What's implemented vs. next steps

**Implemented (this skeleton):** camera capture, in-browser pose estimation +
skeleton overlay, squat & deadlift rep counting, depth/lean/lockout form checks,
**form scoring**, **whole-workout monitoring (sets + reps + scores)**,
**patient/doctor accounts**, doctor↔patient links, **exercise assignments**,
**doctor access to patient scores**, **messaging**, **two-tier admin accounts
(general-only vs full/medical access)**, **persistent SQLAlchemy storage
(SQLite/Postgres) with Alembic migrations and per-role seed data**, a **local
954-exercise MuscleWiki catalog (browse/search/filter)**, reference
videos, role-based web dashboards, and containerised tests.

**Natural next steps:** calibrate score thresholds against real footage, detect
camera angle (front vs. side), add a fully offline mode (port analyzers to
WASM/JS), connection pooling/async DB sessions for higher load, and more
exercises via the registry.
