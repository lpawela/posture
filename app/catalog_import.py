"""Load the local MuscleWiki dataset into the exercise catalog.

The dataset is kept locally in ``data/musclewiki_exercises.json`` (mirrored from
MuscleWiki). This module normalises it and upserts it into whatever store is
configured. Run with ``python -m app.catalog_import`` (honours
``POSTURE_DATABASE_URL``); idempotent, so it's safe to re-run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from app.catalog import CatalogExercise, normalize_musclewiki

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "musclewiki_exercises.json"


def load_musclewiki(path: Path = DATA_FILE) -> List[CatalogExercise]:
    """Read and normalise the local MuscleWiki dataset."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return normalize_musclewiki(raw)


def import_catalog(store, path: Path = DATA_FILE) -> int:
    """Normalise the local dataset and upsert it into ``store``."""
    return store.upsert_catalog_exercises(load_musclewiki(path))


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from app.server import build_default_store

    store = build_default_store()
    n = import_catalog(store)
    print(f"Imported {n} exercises — catalog now holds {store.catalog_count()}.")


if __name__ == "__main__":
    main()
