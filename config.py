"""
OmniContext - Central configuration.
All tuneable knobs live here so nothing is scattered across modules.
"""

import os
from pathlib import Path
from typing import List

# -- Paths ------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
_LOCALAPPDATA = os.getenv("LOCALAPPDATA", str(Path.home() / ".local" / "share"))
DATA_DIR = Path(os.getenv("OMNICONTEXT_DATA_DIR", Path(_LOCALAPPDATA) / "OmniContext"))
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
DB_PATH = DATA_DIR / "omnicontext.db"
FAISS_INDEX_PATH = DATA_DIR / "faiss.index"
FAISS_META_PATH = DATA_DIR / "faiss_meta.json"

# Ensure directories exist at import time
DATA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# -- Capture settings --------------------------------------------------------
CAPTURE_INTERVAL_SECONDS: int = 90        # Periodic screenshot interval
IDLE_THRESHOLD_SECONDS: int = 120         # Don't capture if user idle longer than this
CLIPBOARD_POLL_INTERVAL: float = 1.0      # Seconds between clipboard checks
WINDOW_POLL_INTERVAL: float = 0.5         # Seconds between window title checks
SCREENSHOT_QUALITY: int = 75             # WebP quality (0-100)

# -- Excluded apps (process name fragments, case-insensitive) ----------------
EXCLUDED_APPS: List[str] = [
    "keepass",
    "1password",
    "bitwarden",
    "lastpass",
    "dashlane",
    "enpass",
    "roboform",
    "passwordsafe",
    "authy",
    "authenticator",
    "msteams",          # optional — remove if you want Teams captured
]

# Excluded window title fragments (case-insensitive)
EXCLUDED_TITLES: List[str] = [
    "private",
    "incognito",
    "inprivate",
    "- private browsing",
]

# -- Session settings --------------------------------------------------------
SESSION_GAP_SECONDS: int = 300           # Idle gap that triggers a new session

# -- AI / Pipeline settings -------------------------------------------------
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_VISION_MODEL: str = "llava"       # or "llava:13b", "bakllava", etc.
OLLAMA_TEXT_MODEL: str = "mistral"       # Fallback text-only model
OLLAMA_TIMEOUT: int = 60                 # Seconds before giving up on a response

EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
EMBEDDING_DIM: int = 384

OCR_LANGUAGES: List[str] = ["en"]
OCR_GPU: bool = False                   # Set True if you have a CUDA GPU

# Maximum OCR text length fed to embedder (characters)
MAX_OCR_FOR_EMBED: int = 512

# -- Search settings ---------------------------------------------------------
SEARCH_TOP_K: int = 10
RECENCY_BOOST_HALF_LIFE_HOURS: float = 24.0  # Events decay in score over time

# -- API / UI settings ------------------------------------------------------
API_HOST: str = "127.0.0.1"
UI_PORT: int = 7071
HOTKEY: str = "ctrl+shift+space"

# -- Tray / UX --------------------------------------------------------------
APP_NAME: str = "OmniContext"
APP_VERSION: str = "0.1.0"
