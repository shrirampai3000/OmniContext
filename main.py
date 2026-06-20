"""
OmniContext — Main entry point.
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omnicontext")

# ── Shared pipeline queue ─────────────────────────────────────────────────
_pipeline_queue: queue.Queue = queue.Queue(maxsize=500)


def _register_hotkey():
    try:
        import keyboard
        import webbrowser
        keyboard.add_hotkey(HOTKEY, lambda: webbrowser.open(f"http://127.0.0.1:{UI_PORT}"))
        logger.info("Hotkey registered: %s → opens UI", HOTKEY)
    except Exception as exc:
        logger.warning("Could not register hotkey (%s): %s — try running as Administrator", HOTKEY, exc)


def _shutdown(monitor: ActivityMonitor, worker: PipelineWorker, *args):
    logger.info("Shutting down OmniContext…")
    monitor.stop()
    worker.stop()
    get_vector_store().save()
    close_db()
    logger.info("Goodbye.")
    sys.exit(0)


def main():
    logger.info("=" * 50)
    logger.info("  OmniContext v0.1.0 — starting up")
    logger.info("=" * 50)

    # 1. DB
    init_db()
    logger.info("Database ready.")

    # 2. FAISS
    get_vector_store()
    logger.info("Vector store ready.")

    # 3. Capture monitor
    monitor = ActivityMonitor(_pipeline_queue)
    set_monitor(monitor)
    start_paused = os.getenv("OMNICONTEXT_START_PAUSED", "").lower() in {"1", "true", "yes", "on"}

    # 4. Pipeline worker
    worker = PipelineWorker(_pipeline_queue)
    worker.start()

    # Re-queue previously unprocessed events
    if start_paused:
        logger.info("Start-paused mode: skipping unprocessed event requeue.")
    else:
        reprocess_unprocessed(_pipeline_queue)

    # 5. Capture monitor (background threads)
    if start_paused:
        monitor.pause()
    monitor.start()
    logger.info("Activity monitor started.")

    # 6. Mount API router on NiceGUI's internal FastAPI app
    from nicegui import app as nicegui_app
    from fastapi.middleware.cors import CORSMiddleware
    nicegui_app.include_router(router, prefix="/api")
    nicegui_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("API routes mounted on NiceGUI app under /api")

    # 7. Shutdown hooks
    signal.signal(signal.SIGINT, lambda *a: _shutdown(monitor, worker))
    signal.signal(signal.SIGTERM, lambda *a: _shutdown(monitor, worker))

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
