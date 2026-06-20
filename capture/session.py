"""
OmniContext — Session grouper.
Groups raw events into sessions based on idle gaps and app domain.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from config import SESSION_GAP_SECONDS
from storage.database import insert_session, update_session
from storage.models import Session, Event

logger = logging.getLogger(__name__)


class SessionTracker:
    """
    Maintains the current open session and closes it when a gap is detected.
    Call `register_event(event)` every time a new event is captured.
    """

    def __init__(self) -> None:
        self._current: Optional[Session] = None
        self._last_event_time: Optional[datetime] = None
        self._app_counts: dict = {}

    def register_event(self, event: Event) -> str:
        """
        Assign a session_id to the event (mutating event.session_id).
        Returns the session_id.
        """
        now = event.timestamp

        # Determine if we need a new session
        gap_exceeded = (
            self._last_event_time is not None
            and (now - self._last_event_time).total_seconds() > SESSION_GAP_SECONDS
        )

        if self._current is None or gap_exceeded:
            self._close_current(now)
            self._open_new(now)

        # Track app usage for topic heuristic
        app = event.app_name or "unknown"
        self._app_counts[app] = self._app_counts.get(app, 0) + 1

        self._current.event_count += 1
        self._current.end_time = now
        self._current.topic = self._dominant_app()
        update_session(self._current)

        self._last_event_time = now
        event.session_id = self._current.id
        return self._current.id

    def _open_new(self, when: datetime) -> None:
        session = Session(start_time=when, end_time=when)
        insert_session(session)
        self._current = session
        self._app_counts = {}
        logger.debug("New session opened: %s", session.id)

    def _close_current(self, when: datetime) -> None:
        if self._current:
            self._current.end_time = when
            update_session(self._current)
            logger.debug(
                "Session closed: %s (%d events)", self._current.id, self._current.event_count
            )
            self._current = None
            self._app_counts = {}

    def _dominant_app(self) -> str:
        if not self._app_counts:
            return ""
        return max(self._app_counts, key=self._app_counts.get)

    def flush(self) -> None:
        """Call on shutdown to close any open session."""
        if self._current:
            self._close_current(datetime.utcnow())
