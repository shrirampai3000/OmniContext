"""
OmniContext — Activity monitor.
Polls active window title + process name + clipboard.
Decides *when* to capture and puts raw events onto a queue.
"""

import logging
import queue
import threading
import time
from datetime import datetime
from typing import Optional

import psutil
import pyperclip

try:
    import win32gui
    import win32process
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

from capture.screenshot import capture_screenshot
from capture.session import SessionTracker
from storage.database import insert_event
from storage.models import Event
from storage.settings import get_settings

logger = logging.getLogger(__name__)


import os

def _get_active_context() -> dict:
    """Returns dict of context: title, app, cwd, repo, file, url"""
    ctx = {"title": "", "app": "", "cwd": "", "repo": "", "file": "", "url": ""}
    if not _WIN32_AVAILABLE:
        return ctx
    try:
        hwnd = win32gui.GetForegroundWindow()
        ctx["title"] = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        ctx["app"] = proc.name()
        
        try:
            cwd = proc.cwd()
            if cwd:
                ctx["cwd"] = cwd
                ctx["repo"] = os.path.basename(cwd)
        except Exception:
            pass

        # Heuristics based on app
        if "Code.exe" in ctx["app"]:
            parts = ctx["title"].split(" - ")
            if len(parts) >= 2:
                filename = parts[0].strip()
                # Best-effort file path
                if ctx["cwd"]:
                    ctx["file"] = os.path.join(ctx["cwd"], filename)
                else:
                    ctx["file"] = filename
        
        return ctx
    except Exception:
        return ctx


def _is_excluded(window_title: str, process_name: str, settings) -> bool:
    title_lower = window_title.lower()
    proc_lower = process_name.lower()
    for excl in settings.excluded_apps:
        if excl.lower() in proc_lower:
            return True
    for excl in settings.excluded_titles:
        if excl.lower() in title_lower:
            return True
    return False


class ActivityMonitor:
    """
    Background thread that watches:
    - Active window changes
    - Clipboard changes
    - Periodic capture interval

    Emits captured Events directly into the DB (pre-AI) and onto the
    pipeline queue for downstream processing.
    """

    def __init__(self, pipeline_queue: queue.Queue, start_paused: bool = False) -> None:
        self._queue = pipeline_queue
        self._session = SessionTracker()
        self._running = False
        self._paused = start_paused

        self._last_title: str = ""
        self._last_app: str = ""
        self._last_clipboard: str = ""
        self._last_capture_time: float = 0.0
        self._last_activity_time: float = time.time()

        self._thread: Optional[threading.Thread] = None
        self._clipboard_thread: Optional[threading.Thread] = None

    # ── Public control ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._window_loop, name="omni-monitor", daemon=True
        )
        self._clipboard_thread = threading.Thread(
            target=self._clipboard_loop, name="omni-clipboard", daemon=True
        )
        self._thread.start()
        self._clipboard_thread.start()
        logger.info("Activity monitor started.")

    def stop(self) -> None:
        self._running = False
        self._session.flush()
        logger.info("Activity monitor stopped.")

    def pause(self) -> None:
        self._paused = True
        logger.info("Capture paused.")

    def resume(self) -> None:
        self._paused = False
        logger.info("Capture resumed.")

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ── Internal loops ────────────────────────────────────────────────────────

    def _window_loop(self) -> None:
        while self._running:
            try:
                settings = get_settings()
                ctx = _get_active_context()
                title, app = ctx["title"], ctx["app"]
                now = time.time()

                # Track last activity time
                if title != self._last_title or app != self._last_app:
                    self._last_activity_time = now

                should_capture = False
                reason = ""

                if not self._paused and not _is_excluded(title, app, settings):
                    # 1. Window changed
                    if title and (title != self._last_title or app != self._last_app):
                        should_capture = True
                        reason = "window_change"

                    # 2. Periodic interval during active work
                    elif (
                        title
                        and (now - self._last_capture_time) >= settings.capture_interval_seconds
                        and (now - self._last_activity_time) < settings.idle_threshold_seconds
                    ):
                        should_capture = True
                        reason = "periodic"

                if should_capture:
                    self._do_capture(ctx, "", reason)

                self._last_title = title
                self._last_app = app

            except Exception as exc:
                logger.error("Monitor loop error: %s", exc, exc_info=True)

            time.sleep(0.5)

    def _clipboard_loop(self) -> None:
        while self._running:
            try:
                settings = get_settings()
                if not self._paused and settings.clipboard_capture_enabled:
                    try:
                        clip = pyperclip.paste() or ""
                    except pyperclip.PyperclipException as exc:
                        logger.warning("Could not access clipboard: %s", exc)
                        clip = ""

                    if clip and clip != self._last_clipboard:
                        ctx = _get_active_context()
                        title, app = ctx["title"], ctx["app"]
                        if not _is_excluded(title, app, settings):
                            self._do_capture(ctx, clip, "clipboard")
                        self._last_clipboard = clip

            except Exception as exc:
                logger.error("Clipboard loop error: %s", exc, exc_info=True)

            time.sleep(1.0)

    def _do_capture(
        self,
        ctx: dict,
        clipboard_text: str,
        reason: str,
    ) -> None:
        screenshot_path = capture_screenshot()
        self._last_capture_time = time.time()

        event = Event(
            timestamp=datetime.utcnow(),
            app_name=ctx.get("app", ""),
            window_title=ctx.get("title", ""),
            clipboard_text=clipboard_text[:2000],     # cap clipboard length
            screenshot_path=screenshot_path,
            cwd=ctx.get("cwd", ""),
            repo=ctx.get("repo", ""),
            file_path=ctx.get("file", ""),
            url=ctx.get("url", ""),
        )

        # Assign session
        self._session.register_event(event)

        # Persist raw (unprocessed) event
        insert_event(event)

        # Push to AI pipeline queue. If the pipeline falls behind, keep the
        # monitor responsive and leave the event unprocessed for startup retry.
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("Pipeline queue is full; event %s will be retried on restart.", event.id)

        logger.debug(
            "Captured [%s]: app=%s title=%s",
            reason, ctx.get("app", "")[:40], ctx.get("title", "")[:60],
        )
