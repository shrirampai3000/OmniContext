"""
OmniContext — Pydantic data models.
These are the core domain objects shared across all layers.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Core domain models ──────────────────────────────────────────────────────

class Session(BaseModel):
    id: str = Field(default_factory=_new_id)
    start_time: datetime
    end_time: Optional[datetime] = None
    topic: str = ""
    summary: str = ""
    event_count: int = 0


class Event(BaseModel):
    id: str = Field(default_factory=_new_id)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    app_name: str = ""
    window_title: str = ""
    clipboard_text: str = ""
    screenshot_path: str = ""
    ocr_text: str = ""
    summary: str = ""
    entities: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    session_id: str = ""
    embedding_id: str = ""        # FAISS row index (stored as string)
    file_path: str = ""
    url: str = ""
    repo: str = ""
    cwd: str = ""
    context_type: str = "unknown"
    context_confidence: float = 0.0
    page_title: str = ""
    processed: bool = False       # True once AI pipeline has run


class EmbeddingRecord(BaseModel):
    """Metadata stored alongside FAISS vectors."""
    faiss_row: int
    event_id: str
    object_type: str = "event"


# ── API request / response models ───────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    top_k: int = 10
    time_filter_hours: Optional[float] = None   # e.g. 24.0 → last 24 h only


class SearchResult(BaseModel):
    event: Event
    score: float
    rank: int


class QueryResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total: int


class StatusResponse(BaseModel):
    capturing: bool
    event_count: int
    session_count: int
    unprocessed_count: int
    ollama_available: bool
    version: str


class Settings(BaseModel):
    capture_interval_seconds: int = 90
    idle_threshold_seconds: int = 120
    excluded_apps: List[str] = [
        "keepass", "1password", "bitwarden", "lastpass", "dashlane",
        "enpass", "roboform", "passwordsafe", "authy", "authenticator"
    ]
    excluded_titles: List[str] = ["private", "incognito", "inprivate", "- private browsing"]
    ollama_base_url: str = "http://localhost:11434"
    ollama_vision_model: str = "llava"
    ollama_text_model: str = "mistral"
    ocr_gpu: bool = False
    screenshot_quality: int = 75
    # Privacy controls
    clipboard_capture_enabled: bool = False
    capture_paused_on_startup: bool = True
    retention_days: int = 30


class SettingsPatch(BaseModel):
    capture_interval_seconds: Optional[int] = None
    idle_threshold_seconds: Optional[int] = None
    excluded_apps: Optional[List[str]] = None
    excluded_titles: Optional[List[str]] = None
    ollama_base_url: Optional[str] = None
    ollama_vision_model: Optional[str] = None
    ollama_text_model: Optional[str] = None
    ocr_gpu: Optional[bool] = None
    screenshot_quality: Optional[int] = None
    clipboard_capture_enabled: Optional[bool] = None
    capture_paused_on_startup: Optional[bool] = None
    retention_days: Optional[int] = None
