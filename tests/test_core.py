from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes as routes
import config as cfg
import storage.database as db
import storage.vector_store as vector_store
from storage.models import Event


def _use_temp_db(monkeypatch, tmp_path):
    db.close_db()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "omnicontext-test.db")
    db.init_db()


def _use_temp_vector_store(monkeypatch, tmp_path):
    monkeypatch.setattr(vector_store, "FAISS_INDEX_PATH", tmp_path / "faiss.index")
    monkeypatch.setattr(vector_store, "FAISS_META_PATH", tmp_path / "faiss_meta.json")
    vector_store._store = None
    return vector_store.get_vector_store()


def test_storage_roundtrip_and_natural_language_fts(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)

    event = Event(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        app_name="Code",
        window_title="Alpha Project",
        ocr_text="Planning notes for the Alpha launch",
        summary="Worked on Alpha launch planning.",
        topics=["alpha", "planning"],
        processed=True,
    )
    db.insert_event(event)

    assert db.count_events() == 1
    assert db.get_event(event.id).summary == "Worked on Alpha launch planning."
    assert db.fts_search("what was the alpha project?")[0][0] == event.id

    db.delete_event(event.id)
    assert db.get_event(event.id) is None
    assert db.fts_search("alpha") == []
    db.close_db()


def test_vector_store_skips_zero_vectors_and_persists_deletes(monkeypatch, tmp_path):
    store = _use_temp_vector_store(monkeypatch, tmp_path)

    assert store.add("empty", np.zeros(cfg.EMBEDDING_DIM, dtype=np.float32)) == -1
    assert store.total == 0

    vector = np.zeros(cfg.EMBEDDING_DIM, dtype=np.float32)
    vector[0] = 1.0
    assert store.add("event-1", vector) == 0
    assert store.search(vector, top_k=5)[0][0] == "event-1"

    store.remove("event-1")
    store.save()
    vector_store._store = None

    reloaded = vector_store.get_vector_store()
    assert reloaded.search(vector, top_k=5) == []


def test_settings_patch_updates_runtime_config(monkeypatch):
    monkeypatch.setattr(cfg, "CAPTURE_INTERVAL_SECONDS", 90)
    monkeypatch.setattr(cfg, "IDLE_THRESHOLD_SECONDS", 120)
    monkeypatch.setattr(cfg, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(cfg, "SCREENSHOT_QUALITY", 75)

    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.patch(
        "/settings",
        json={
            "capture_interval_seconds": 3,
            "idle_threshold_seconds": 5,
            "ollama_base_url": "http://localhost:11434/",
            "screenshot_quality": 150,
        },
    )
    assert response.status_code == 200

    settings = client.get("/settings").json()
    assert settings["capture_interval_seconds"] == 5
    assert settings["idle_threshold_seconds"] == 10
    assert settings["ollama_base_url"] == "http://localhost:11434"
    assert settings["screenshot_quality"] == 100


def test_delete_event_removes_db_screenshot_and_vector(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    store = _use_temp_vector_store(monkeypatch, tmp_path)

    screenshot = tmp_path / "capture.webp"
    screenshot.write_bytes(b"fake image")

    event = Event(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        app_name="Code",
        window_title="Delete Me",
        screenshot_path=str(screenshot),
        summary="Temporary capture.",
        processed=True,
    )
    db.insert_event(event)

    vector = np.zeros(cfg.EMBEDDING_DIM, dtype=np.float32)
    vector[0] = 1.0
    store.add(event.id, vector)

    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.delete(f"/events/{event.id}")
    assert response.status_code == 200
    assert response.json() == {"deleted": event.id}
    assert db.get_event(event.id) is None
    assert not screenshot.exists()

    vector_store._store = None
    assert vector_store.get_vector_store().search(vector, top_k=5) == []
    db.close_db()
