"""
OmniContext — Cluster engine for the Digital Brain view.
Computes time-windowed topic clusters from entity co-occurrence.
No external graph library needed — pure Python + SQLite.
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Dict

from storage.database import get_events_since, get_top_entities, get_co_entities

logger = logging.getLogger(__name__)


def _window_cutoff(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _compute_clusters(hours: int, top_n: int = 8) -> List[Dict]:
    """
    For events in the last `hours`, compute entity-based topic clusters.
    Each cluster = a hub entity with event count + dominant app.
    """
    events = get_events_since(_window_cutoff(hours), limit=2000)
    if not events:
        return []

    entity_events: Dict[str, List] = defaultdict(list)
    entity_apps: Dict[str, Counter] = defaultdict(Counter)

    for ev in events:
        for ent in (ev.entities or []):
            entity_events[ent].append(ev.id)
            entity_apps[ent][ev.app_name or "unknown"] += 1

    # Build cluster records, filter noise (≥2 mentions)
    clusters = []
    for entity, ev_ids in entity_events.items():
        if len(ev_ids) < 2:
            continue
        top_app = entity_apps[entity].most_common(1)[0][0]
        clusters.append({
            "name": entity,
            "event_count": len(ev_ids),
            "dominant_app": top_app,
        })

    # Sort by event count descending, take top N
    clusters.sort(key=lambda c: c["event_count"], reverse=True)
    return clusters[:top_n]


def get_brain_view() -> Dict:
    """
    Returns the full Digital Brain home-screen data:
    {
      "today":      [ {name, event_count, dominant_app, co_entities}, ... ],
      "this_week":  [ ... ],
      "this_month": [ ... ],
      "top_entities": [ {name, mention_count}, ... ]
    }
    """
    today = _compute_clusters(hours=24)
    week  = _compute_clusters(hours=24 * 7)
    month = _compute_clusters(hours=24 * 30)

    # Enrich with co-entities (related topics) — lightweight
    for cluster_list in (today, week, month):
        for cluster in cluster_list:
            cluster["co_entities"] = get_co_entities(cluster["name"], top_k=5)

    top_entities = get_top_entities(limit=20)

    return {
        "today":        today,
        "this_week":    week,
        "this_month":   month,
        "top_entities": top_entities,
    }


def get_cluster_detail(entity_name: str) -> Dict:
    """
    Drill-down data for a single cluster/entity:
    event_ids, co-entities, first/last seen.
    """
    from storage.database import get_entity_event_ids, get_event
    event_ids = get_entity_event_ids(entity_name, limit=50)
    events = [e for eid in event_ids if (e := get_event(eid)) is not None]
    co = get_co_entities(entity_name, top_k=8)

    return {
        "entity": entity_name,
        "event_count": len(events),
        "co_entities": co,
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "app_name": e.app_name,
                "window_title": e.window_title,
                "summary": e.summary,
                "screenshot_path": e.screenshot_path,
            }
            for e in events
        ],
    }
