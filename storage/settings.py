import json
import logging
import threading
from pathlib import Path
from typing import Optional

from config import DATA_DIR
from storage.models import Settings, SettingsPatch

logger = logging.getLogger(__name__)

_SETTINGS_FILE = DATA_DIR / "settings.json"
_settings_lock = threading.RLock()
_current_settings: Optional[Settings] = None

def get_settings() -> Settings:
    global _current_settings
    with _settings_lock:
        if _current_settings is None:
            _load_settings()
        return _current_settings.model_copy()

def _load_settings() -> None:
    global _current_settings
    if _SETTINGS_FILE.exists():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            _current_settings = Settings(**data)
            return
        except Exception as exc:
            logger.error("Failed to load settings from %s: %s", _SETTINGS_FILE, exc)
    
    # Defaults
    _current_settings = Settings()
    _save_settings()

def _save_settings() -> None:
    global _current_settings
    if _current_settings is None:
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(_current_settings.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save settings: %s", exc)

def update_settings(patch: SettingsPatch) -> None:
    global _current_settings
    with _settings_lock:
        if _current_settings is None:
            _load_settings()
        
        update_data = patch.model_dump(exclude_unset=True)
        current_data = _current_settings.model_dump()
        current_data.update(update_data)
        
        # Enforce bounds
        if "capture_interval_seconds" in current_data:
            current_data["capture_interval_seconds"] = max(5, min(3600, current_data["capture_interval_seconds"]))
        if "idle_threshold_seconds" in current_data:
            current_data["idle_threshold_seconds"] = max(5, min(3600, current_data["idle_threshold_seconds"]))
        if "screenshot_quality" in current_data:
            current_data["screenshot_quality"] = max(1, min(100, current_data["screenshot_quality"]))
        if "ollama_base_url" in current_data and current_data["ollama_base_url"]:
            current_data["ollama_base_url"] = current_data["ollama_base_url"].rstrip("/")
            
        _current_settings = Settings(**current_data)
        _save_settings()
