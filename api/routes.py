"""
OmniContext — FastAPI REST API routes.
Mounts on the shared app instance created in main.py.
"""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse

import config as cfg
from pipeline.summarizer import is_ollama_available
from search.retrieval import hybrid_search
from storage.database import (
    count_events,
    count_sessions,
    count_unprocessed,
    delete_event,
    get_event,
    get_events,
    get_sessions,
)
from storage.models import (
    Event,
    QueryRequest,
    QueryResponse,
    SearchResult,
    Session,
    SettingsPatch,
    StatusResponse,
)
from storage.vector_store import get_vector_store

logger = logging.getLogger(__name__)
router = APIRouter()

# Reference to the ActivityMonitor, injected by main.py
_monitor = None


def set_monitor(monitor) -> None:
    global _monitor
    _monitor = monitor


@router.get("/docs", include_in_schema=False)
def api_docs_redirect():
    return RedirectResponse(url="/docs")


# ── Query ───────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse, tags=["search"])
def query_memory(body: QueryRequest):
    """Natural-language hybrid search over captured memories."""
    results = hybrid_search(
        query=body.query,
        top_k=body.top_k,
        time_filter_hours=body.time_filter_hours,
    )
    return QueryResponse(query=body.query, results=results, total=len(results))


# ── Events ───────────────────────────────────────────────────────────────────

@router.get("/events", response_model=List[Event], tags=["events"])
def list_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session_id: Optional[str] = None,
):
    return get_events(limit=limit, offset=offset, session_id=session_id)


@router.get("/events/{event_id}", response_model=Event, tags=["events"])
def get_single_event(event_id: str):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/events/{event_id}/screenshot", tags=["events"])
def get_screenshot(event_id: str):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not event.screenshot_path or not Path(event.screenshot_path).exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(event.screenshot_path, media_type="image/webp")


@router.delete("/events/{event_id}", tags=["events"])
def remove_event(event_id: str):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    # Remove from FAISS meta (vector stays, won't surface in results)
    store = get_vector_store()
    store.remove(event_id)
    store.save()
    # Delete screenshot
    if event.screenshot_path:
        p = Path(event.screenshot_path)
        if p.exists():
            p.unlink(missing_ok=True)
    # Remove from DB (triggers FTS cleanup)
    delete_event(event_id)
    return {"deleted": event_id}


# ── Sessions ─────────────────────────────────────────────────────────────────

@router.get("/sessions", response_model=List[Session], tags=["sessions"])
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return get_sessions(limit=limit, offset=offset)


# ── Status ───────────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusResponse, tags=["system"])
def get_status():
    return StatusResponse(
        capturing=not (_monitor and _monitor.is_paused),
        event_count=count_events(),
        session_count=count_sessions(),
        unprocessed_count=count_unprocessed(),
        ollama_available=is_ollama_available(),
        version=cfg.APP_VERSION,
    )


# ── Capture control ───────────────────────────────────────────────────────────

@router.post("/capture/pause", tags=["system"])
def pause_capture():
    if _monitor:
        _monitor.pause()
    return {"capturing": False}


@router.post("/capture/resume", tags=["system"])
def resume_capture():
    if _monitor:
        _monitor.resume()
    return {"capturing": True}


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings", tags=["settings"])
def get_settings():
    return {
        "capture_interval_seconds": cfg.CAPTURE_INTERVAL_SECONDS,
        "idle_threshold_seconds": cfg.IDLE_THRESHOLD_SECONDS,
        "excluded_apps": cfg.EXCLUDED_APPS,
        "excluded_titles": cfg.EXCLUDED_TITLES,
        "ollama_base_url": cfg.OLLAMA_BASE_URL,
        "ollama_vision_model": cfg.OLLAMA_VISION_MODEL,
        "ollama_text_model": cfg.OLLAMA_TEXT_MODEL,
        "embedding_model": cfg.EMBEDDING_MODEL,
        "ocr_gpu": cfg.OCR_GPU,
        "screenshot_quality": cfg.SCREENSHOT_QUALITY,
    }


@router.patch("/settings", tags=["settings"])
def patch_settings(body: SettingsPatch):
    """
    Runtime patch — updates the in-memory config values.
    Changes persist only until restart; write to config.py for permanence.
    """
    if body.capture_interval_seconds is not None:
        cfg.CAPTURE_INTERVAL_SECONDS = max(5, min(3600, body.capture_interval_seconds))
    if body.idle_threshold_seconds is not None:
        cfg.IDLE_THRESHOLD_SECONDS = max(10, min(24 * 3600, body.idle_threshold_seconds))
    if body.excluded_apps is not None:
        cfg.EXCLUDED_APPS = body.excluded_apps
    if body.excluded_titles is not None:
        cfg.EXCLUDED_TITLES = body.excluded_titles
    if body.ollama_base_url is not None:
        cfg.OLLAMA_BASE_URL = body.ollama_base_url.rstrip("/")
    if body.ollama_vision_model is not None:
        cfg.OLLAMA_VISION_MODEL = body.ollama_vision_model
    if body.ollama_text_model is not None:
        cfg.OLLAMA_TEXT_MODEL = body.ollama_text_model
    if body.ocr_gpu is not None:
        cfg.OCR_GPU = body.ocr_gpu
    if body.screenshot_quality is not None:
        cfg.SCREENSHOT_QUALITY = max(1, min(100, body.screenshot_quality))
    return {"updated": True}
