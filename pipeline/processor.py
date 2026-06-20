"""
OmniContext — AI pipeline worker.
Consumes raw Events from a queue and runs OCR → summarise → embed.
Runs in a background thread (CPU-bound work; avoids asyncio).
"""

import logging
import queue
import threading
import time
from typing import Optional

from pipeline.ocr import extract_text
from pipeline.summarizer import summarise
from pipeline.embedder import embed, build_embed_text
from storage.database import update_event_ai_fields
from storage.models import Event
from storage.vector_store import get_vector_store

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.5    # Seconds to wait when queue is empty
_RETRY_DELAY = 5.0      # Seconds before retrying after an error


class PipelineWorker:
    """
    Background worker that processes Event objects from a queue.
    Steps per event: OCR → summarise → embed → update DB + FAISS.
    """

    def __init__(self, pipeline_queue: queue.Queue) -> None:
        self._queue = pipeline_queue
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_count = 0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="omni-pipeline", daemon=True
        )
        self._thread.start()
        logger.info("Pipeline worker started.")

    def stop(self) -> None:
        self._running = False
        logger.info("Pipeline worker stopped (processed %d events).", self._processed_count)

    def _run(self) -> None:
        while self._running:
            try:
                try:
                    event: Event = self._queue.get(timeout=_POLL_INTERVAL)
                except queue.Empty:
                    continue

                try:
                    if self._process(event):
                        self._processed_count += 1
                finally:
                    self._queue.task_done()

            except Exception as exc:
                logger.error("Pipeline worker loop error: %s", exc)
                time.sleep(_RETRY_DELAY)

    def _process(self, event: Event) -> bool:
        logger.debug("Processing event %s (app=%s)", event.id[:8], event.app_name)

        try:
            # ── Step 1: OCR ──────────────────────────────────────────────
            ocr_text = extract_text(event.screenshot_path) if event.screenshot_path else ""

            # ── Step 2: Summarise ────────────────────────────────────────
            ai = summarise(
                screenshot_path=event.screenshot_path,
                ocr_text=ocr_text,
                window_title=event.window_title,
                app_name=event.app_name,
            )
            summary = ai.get("summary", "")
            entities = ai.get("entities", [])
            topics = ai.get("topics", [])

            # ── Step 3: Embed ────────────────────────────────────────────
            text_to_embed = build_embed_text(
                summary=summary,
                entities=entities,
                topics=topics,
                ocr_text=ocr_text,
                window_title=event.window_title,
                app_name=event.app_name,
            )
            vector = embed(text_to_embed)

            # ── Step 4: Store in FAISS ───────────────────────────────────
            store = get_vector_store()
            faiss_row = store.add(event.id, vector)
            embedding_id = str(faiss_row)

            # ── Step 5: Update DB ────────────────────────────────────────
            update_event_ai_fields(
                event_id=event.id,
                ocr_text=ocr_text,
                summary=summary,
                entities=entities,
                topics=topics,
                embedding_id=embedding_id,
            )
            if faiss_row >= 0:
                store.save()

            logger.debug(
                "Event %s processed: summary=%r topics=%s",
                event.id[:8],
                summary[:60],
                topics,
            )
            return True

        except Exception as exc:
            logger.error("Failed to process event %s: %s", event.id[:8], exc)
            return False


def reprocess_unprocessed(pipeline_queue: queue.Queue, limit: int = 50) -> None:
    """
    On startup, enqueue events that failed processing in a previous run.
    """
    from storage.database import get_unprocessed_events
    events = get_unprocessed_events(limit=limit)
    for ev in events:
        pipeline_queue.put(ev)
    if events:
        logger.info("Re-queued %d unprocessed events.", len(events))
