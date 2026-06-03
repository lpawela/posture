import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.catalog import normalize_musclewiki  # noqa: E402
from app.server import create_app  # noqa: E402
from app.store import Store  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "musclewiki_sample.json"


@pytest.fixture()
def client():
    store = Store()
    store.upsert_catalog_exercises(normalize_musclewiki(json.loads(FIXTURE.read_text())))
    return TestClient(create_app(store))


def test_catalog_list_is_public(client):
    res = client.get("/api/catalog")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert {e["slug"] for e in body["items"]} == {"barbell-curl", "barbell-curl-1", "air-squat"}


def test_catalog_filtering(client):
    assert client.get("/api/catalog", params={"muscle": "Biceps"}).json()["total"] == 2
    assert client.get("/api/catalog", params={"category": "Bodyweight"}).json()["total"] == 1
    assert client.get("/api/catalog", params={"q": "air"}).json()["total"] == 1


def test_catalog_pagination(client):
    body = client.get("/api/catalog", params={"limit": 1, "offset": 1}).json()
    assert body["total"] == 3 and body["count"] == 1 and body["limit"] == 1


def test_catalog_filters_endpoint(client):
    filters = client.get("/api/catalog/filters").json()
    assert "Biceps" in filters["muscles"]
    assert "Bodyweight" in filters["categories"]


def test_catalog_get_by_slug_and_404(client):
    got = client.get("/api/catalog/air-squat")
    assert got.status_code == 200
    body = got.json()
    assert body["name"] == "Air Squat" and body["steps"]
    assert client.get("/api/catalog/nope").status_code == 404
