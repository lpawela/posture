import json
from pathlib import Path

import pytest

from app.catalog import distinct_filters, filter_and_paginate, normalize_musclewiki, slugify
from app.catalog_import import DATA_FILE, import_catalog, load_musclewiki
from app.store import NotFound, Store

FIXTURE = Path(__file__).parent / "fixtures" / "musclewiki_sample.json"


@pytest.fixture(params=["memory", "sql"])
def store(request):
    if request.param == "sql":
        pytest.importorskip("sqlalchemy")
        from app.sql_store import SqlStore

        return SqlStore("sqlite://", create_all=True)
    return Store()


def sample_raw():
    return json.loads(FIXTURE.read_text())


# ----- normalisation ------------------------------------------------------ #


def test_slugify():
    assert slugify("Barbell Curl") == "barbell-curl"
    assert slugify("90/90 Hip Stretch!") == "90-90-hip-stretch"


def test_normalize_maps_fields_and_dedupes_slugs():
    items = normalize_musclewiki(sample_raw())
    assert [e.slug for e in items] == ["barbell-curl", "barbell-curl-1", "air-squat"]

    bb = items[0]
    assert bb.source == "musclewiki" and bb.source_id == 0
    assert bb.primary_muscles == ["Biceps"] and bb.secondary_muscles == ["Forearms"]
    assert bb.difficulty == "Beginner" and bb.force == "Pull" and bb.grips == "Underhand"
    assert bb.youtube_url == "https://www.youtube.com/embed/abc123"
    assert len(bb.video_urls) == 2 and bb.aka == "EZ-Bar Curl"

    minimal = items[1]  # missing difficulty/force/grips/secondary; empty youtube
    assert minimal.difficulty is None and minimal.force is None and minimal.grips is None
    assert minimal.secondary_muscles == [] and minimal.youtube_url is None


def test_filter_and_paginate_and_distinct():
    items = normalize_musclewiki(sample_raw())
    biceps, total = filter_and_paginate(items, muscle="biceps")
    assert total == 2 and {e.slug for e in biceps} == {"barbell-curl", "barbell-curl-1"}

    body, total = filter_and_paginate(items, category="Bodyweight")
    assert total == 1 and body[0].slug == "air-squat"

    page, total = filter_and_paginate(items, limit=1, offset=1)
    assert total == 3 and len(page) == 1

    filters = distinct_filters(items)
    assert "Biceps" in filters["muscles"] and "Bodyweight" in filters["categories"]


# ----- store contract (both backends) ------------------------------------ #


def test_upsert_list_get_idempotent(store):
    items = normalize_musclewiki(sample_raw())
    assert store.upsert_catalog_exercises(items) == 3
    assert store.catalog_count() == 3

    page, total = store.list_catalog_exercises()
    assert total == 3

    by_slug = store.get_catalog_exercise("air-squat")
    assert by_slug.name == "Air Squat"
    by_id = store.get_catalog_exercise(by_slug.id)
    assert by_id.slug == "air-squat"

    with pytest.raises(NotFound):
        store.get_catalog_exercise("does-not-exist")

    # Re-importing the same data is idempotent (no duplicate rows).
    assert store.upsert_catalog_exercises(normalize_musclewiki(sample_raw())) == 3
    assert store.catalog_count() == 3


def test_store_filters(store):
    store.upsert_catalog_exercises(normalize_musclewiki(sample_raw()))
    _, total = store.list_catalog_exercises(muscle="Biceps")
    assert total == 2
    page, total = store.list_catalog_exercises(q="air")
    assert total == 1 and page[0].slug == "air-squat"
    assert "Biceps" in store.catalog_filters()["muscles"]


def test_import_from_fixture(store):
    assert import_catalog(store, FIXTURE) == 3
    assert store.catalog_count() == 3


# ----- the real local dataset -------------------------------------------- #


@pytest.mark.skipif(not DATA_FILE.exists(), reason="local MuscleWiki dataset not present")
def test_local_dataset_normalizes_with_unique_slugs():
    items = load_musclewiki()
    assert len(items) > 900  # the full MuscleWiki catalog
    slugs = [e.slug for e in items]
    assert len(slugs) == len(set(slugs))  # de-duplication holds across the dataset
    assert all(e.source == "musclewiki" and e.name and e.category for e in items)
