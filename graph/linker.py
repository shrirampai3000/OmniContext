"""
OmniContext — Memory linker.
Called after each event is AI-processed. Creates entity registry entries
and memory_links between co-occurring events.
"""

import logging
from typing import List

from storage.database import upsert_entity, insert_link, get_entity_event_ids
from storage.models import Event

logger = logging.getLogger(__name__)


def link_event(event: Event) -> None:
    """
    Register entities and build graph edges for a newly processed event.
    Non-blocking — any error is caught and logged, never raised.
    """
    try:
        ts = event.timestamp.isoformat()

        # ── 1. Upsert all entities ────────────────────────────────────────────
        for entity in event.entities:
            if entity and len(entity) < 120:
                upsert_entity(entity, ts)

        # ── 2. Entity → event links ───────────────────────────────────────────
        for entity in event.entities:
            if entity:
                insert_link(
                    source_id=event.id,
                    target_id=entity,
                    target_type="entity",
                    link_type="mentions",
                    weight=1.0,
                )

        # ── 3. Same-session link (to most recent prior event in session) ──────
        if event.session_id:
            insert_link(
                source_id=event.id,
                target_id=event.session_id,
                target_type="session",
                link_type="same_session",
                weight=1.0,
            )

        # ── 4. Co-entity links (events that share an entity → weakly related) ─
        for entity in event.entities[:5]:   # cap at 5 entities to limit work
            related_ids = get_entity_event_ids(entity, limit=5)
            for rel_id in related_ids:
                if rel_id != event.id:
                    insert_link(
                        source_id=event.id,
                        target_id=rel_id,
                        target_type="event",
                        link_type="same_entity",
                        weight=0.5,
                    )

    except Exception as exc:
        logger.warning("link_event failed for %s: %s", event.id[:8], exc)
