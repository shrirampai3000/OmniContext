"""
OmniContext - Main entry point.
Mounts the API router on NiceGUI's internal FastAPI app (single-server architecture).
Starts capture monitor + pipeline worker in background threads, then hands off to NiceGUI.
"""

import logging
import os
import queue
import signal
import sys
import threading
import time

from config import API_HOST, APP_NAME, HOTKEY, UI_PORT
from storage.database import init_db, close_db
from storage.vector_store import get_vector_store
from capture.monitor import ActivityMonitor
from pipeline.processor import PipelineWorker, reprocess_unprocessed
from api.routes import router, set_monitor
from ui.app import run_ui
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# -- Global state -------------------------------------------------------------
_monitor: ActivityMonitor = None
_worker: PipelineWorker = None
_event_queue = queue.Queue(maxsize=100)


def _shutdown_handler(signum, frame):
    logger.info("Shutdown signal received. Stopping threads...")
    if _monitor:
        _monitor.stop()
    if _worker:
        _worker.stop()
    close_db()
    sys.exit(0)


def _register_hotkey():
    try:
        import keyboard
        import webbrowser
        keyboard.add_hotkey(HOTKEY, lambda: webbrowser.open(f"http://127.0.0.1:{UI_PORT}"))
        logger.info("Hotkey registered: %s → opens UI", HOTKEY)
    except Exception as exc:
        logger.warning("Could not register hotkey (%s): %s — try running as Administrator", HOTKEY, exc)


def main():
    global _monitor, _worker

    # Register signal handlers for clean exit
    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    # 1. Initialize storage
    logger.info("Initializing %s...", APP_NAME)
    init_db()
    # Pre-warm FAISS lazily
    get_vector_store()

    # 2. Check if we should start paused via env var
    start_paused = os.getenv("OMNICONTEXT_START_PAUSED", "0").lower() in ("1", "true", "yes")

    # 3. Start pipeline worker (consumer)
    logger.info("Starting pipeline worker thread...")
    _worker = PipelineWorker(queue=_event_queue)
    _worker.start()

    # 4. Enqueue previously unprocessed events (e.g. from a crash)
    logger.info("Checking for unprocessed events...")
    reprocess_unprocessed(_event_queue)

    # 5. Start capture monitor (producer)
    logger.info("Starting capture monitor thread (paused=%s)...", start_paused)
    _monitor = ActivityMonitor(queue=_event_queue, start_paused=start_paused)
    _monitor.start()

    # Share monitor with API so the UI can toggle pause state
    set_monitor(_monitor)

    # 6. Mount the API router into NiceGUI's underlying FastAPI app
    # NiceGUI uses its own FastAPI instance internally (`nicegui.app`).
    from nicegui import app as nicegui_app
    nicegui_app.include_router(router, prefix="/api")

    # Tighten CORS for security
    nicegui_app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://127.0.0.1:{UI_PORT}", f"http://localhost:{UI_PORT}"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("API routes mounted on NiceGUI app under /api")


    # 8. Hotkey (may need admin on Windows)
    _register_hotkey()

    # 9. Build and run NiceGUI UI (blocks main thread)
    from ui.app import run_ui
    logger.info("UI → http://127.0.0.1:%d", UI_PORT)
    logger.info("API → http://127.0.0.1:%d/api", UI_PORT)
    logger.info("Docs → http://127.0.0.1:%d/api/docs", UI_PORT)
    run_ui()


if __name__ == "__main__":
    main()
