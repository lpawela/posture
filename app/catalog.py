"""Exercise catalog: local database of MuscleWiki exercises.

Separate from the pose *analyzers* (squat/deadlift) — this is the broad
reference library of all exercises, sourced from MuscleWiki and kept locally
(see ``data/musclewiki_exercises.json`` and :mod:`app.catalog_import`).

This module holds the storage-agnostic pieces: the :class:`CatalogExercise`
dataclass, the MuscleWiki normaliser, and the shared filter/paginate helpers
used identically by both store backends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MUSCLEWIKI = "musclewiki"


@dataclass
class CatalogExercise:
    source: str
    source_id: int
    name: str
    slug: str
    category: str                       # equipment family (Barbell, Dumbbells, …)
    difficulty: Optional[str]
    force: Optional[str]
    grips: Optional[str]
    primary_muscles: List[str] = field(default_factory=list)
    secondary_muscles: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    details: str = ""
    aka: Optional[str] = None
    video_urls: List[str] = field(default_factory=list)
    youtube_url: Optional[str] = None
    id: Optional[int] = None            # DB primary key (assigned on insert)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "source_id": self.source_id,
            "name": self.name,
            "slug": self.slug,
            "category": self.category,
            "difficulty": self.difficulty,
            "force": self.force,
            "grips": self.grips,
            "primary_muscles": list(self.primary_muscles),
            "secondary_muscles": list(self.secondary_muscles),
            "steps": list(self.steps),
            "details": self.details,
            "aka": self.aka,
            "video_urls": list(self.video_urls),
            "youtube_url": self.youtube_url,
        }


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "exercise"


def _clean_str(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def normalize_musclewiki(raw: List[dict]) -> List[CatalogExercise]:
    """Convert the raw MuscleWiki dataset into :class:`CatalogExercise` records.

    Names repeat across equipment variants, so slugs are de-duplicated by
    appending the stable MuscleWiki id when a base slug is already taken.
    """
    seen_slugs: set[str] = set()
    exercises: List[CatalogExercise] = []
    for item in raw:
        name = str(item.get("exercise_name", "")).strip() or "Unnamed exercise"
        source_id = int(item["id"])
        base = slugify(name)
        slug = base if base not in seen_slugs else f"{base}-{source_id}"
        seen_slugs.add(slug)

        target = item.get("target") or {}
        aka = item.get("Aka")
        exercises.append(
            CatalogExercise(
                source=MUSCLEWIKI,
                source_id=source_id,
                name=name,
                slug=slug,
                category=str(item.get("Category") or "").strip() or "Other",
                difficulty=_clean_str(item.get("Difficulty")),
                force=_clean_str(item.get("Force")),
                grips=_clean_str(item.get("Grips")),
                primary_muscles=_as_list(target.get("Primary")),
                secondary_muscles=_as_list(target.get("Secondary")),
                steps=_as_list(item.get("steps")),
                details=str(item.get("details") or ""),
                aka="; ".join(_as_list(aka)) or None,
                video_urls=_as_list(item.get("videoURL")),
                youtube_url=_clean_str(item.get("youtubeURL")),
            )
        )
    return exercises


# --- shared query helpers (identical behaviour across both stores) -------- #


def _matches(ex: CatalogExercise, muscle, category, difficulty, q) -> bool:
    if muscle:
        muscles = [m.lower() for m in ex.primary_muscles + ex.secondary_muscles]
        if muscle.lower() not in muscles:
            return False
    if category and (ex.category or "").lower() != category.lower():
        return False
    if difficulty and (ex.difficulty or "").lower() != difficulty.lower():
        return False
    if q and q.lower() not in ex.name.lower():
        return False
    return True


def filter_and_paginate(
    items: List[CatalogExercise],
    *,
    muscle: Optional[str] = None,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[CatalogExercise], int]:
    """Filter, sort (by name) and paginate. Returns ``(page, total_matches)``."""
    matched = sorted(
        (e for e in items if _matches(e, muscle, category, difficulty, q)),
        key=lambda e: (e.name.lower(), e.source_id),
    )
    total = len(matched)
    if offset:
        matched = matched[offset:]
    if limit is not None:
        matched = matched[:limit]
    return matched, total


def distinct_filters(items: List[CatalogExercise]) -> dict:
    """Sorted distinct values usable as filter options."""
    muscles, categories, difficulties = set(), set(), set()
    for e in items:
        muscles.update(e.primary_muscles)
        muscles.update(e.secondary_muscles)
        if e.category:
            categories.add(e.category)
        if e.difficulty:
            difficulties.add(e.difficulty)
    return {
        "muscles": sorted(muscles),
        "categories": sorted(categories),
        "difficulties": sorted(difficulties),
    }
