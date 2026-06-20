"""
OmniContext — Hybrid search engine.
Combines FTS5 keyword search, FAISS vector search, and recency scoring
using Reciprocal Rank Fusion (RRF).
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict

from config import SEARCH_TOP_K, RECENCY_BOOST_HALF_LIFE_HOURS
from pipeline.embedder import embed
from storage.database import fts_search, get_event, count_events
from storage.models import Event, SearchResult
from storage.vector_store import get_vector_store

logger = logging.getLogger(__name__)

_RRF_K = 60     # RRF constant (higher = smoother rank fusion)


def _recency_score(timestamp: datetime) -> float:
    """
    Exponential decay: score=1.0 at time of event, decays by half every
    RECENCY_BOOST_HALF_LIFE_HOURS hours.
    """
    now = datetime.now(timezone.utc)
    # Make timestamp timezone-aware if naive
    if timestamp.tzinfo is None:
        ts = timestamp.replace(tzinfo=timezone.utc)
    else:
        ts = timestamp
    hours_ago = (now - ts).total_seconds() / 3600.0
    return math.exp(-math.log(2) * hours_ago / RECENCY_BOOST_HALF_LIFE_HOURS)


def _rrf_merge(
    ranked_lists: List[List[Tuple[str, float]]],
    weights: Optional[List[float]] = None,
) -> List[Tuple[str, float]]:
    """
    Reciprocal Rank Fusion over multiple ranked lists.
    Each item in a list is (event_id, original_score).
    Returns merged list of (event_id, fused_score) sorted descending.
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)

    scores: Dict[str, float] = {}
    for rank_list, weight in zip(ranked_lists, weights):
        for rank, (event_id, _) in enumerate(rank_list):
            if event_id in ("__deleted__", ""):
                continue
            scores[event_id] = scores.get(event_id, 0.0) + weight / (_RRF_K + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def hybrid_search(
    query: str,
    top_k: int = SEARCH_TOP_K,
    time_filter_hours: Optional[float] = None,
) -> List[SearchResult]:
    """
    Full hybrid search pipeline.
    1. FTS5 keyword search
    2. FAISS vector nearest-neighbours
    3. RRF merge
    4. Recency boost (post-processing)
    5. Fetch full Event objects
    6. Optional time filter

    Returns a list of SearchResult ordered by final score (best first).
    """
    if not query.strip():
        return []

    # ── 1. FTS5 ──────────────────────────────────────────────────────────────
    fts_results = fts_search(query, limit=top_k * 2)
    logger.debug("FTS returned %d results for %r", len(fts_results), query)

    # ── 2. FAISS ─────────────────────────────────────────────────────────────
    query_vec = embed(query)
    store = get_vector_store()
    vec_results = store.search(query_vec, top_k=top_k * 2)
    # Filter out deleted slots
    vec_results = [(eid, sc) for eid, sc in vec_results if eid not in ("__deleted__", "")]
    logger.debug("FAISS returned %d results for %r", len(vec_results), query)

    # ── 3. RRF merge ─────────────────────────────────────────────────────────
    merged = _rrf_merge(
        [fts_results, vec_results],
        weights=[1.2, 1.0],    # Slightly favour keyword matches
    )

    # ── 4. Fetch events + recency boost ──────────────────────────────────────
    cutoff: Optional[datetime] = None
    if time_filter_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=time_filter_hours)

    results: List[SearchResult] = []
    rank = 0
    for event_id, rrf_score in merged:
        if len(results) >= top_k:
            break

        event = get_event(event_id)
        if event is None:
            continue

        # Apply time filter
        if cutoff is not None:
            ts = event.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue

        # Recency boost: multiply RRF score by [0.0 – 1.0] decay factor
        recency = _recency_score(event.timestamp)
        final_score = rrf_score * (1 + 0.3 * recency)   # 30% max boost from recency

        results.append(SearchResult(event=event, score=final_score, rank=rank))
        rank += 1

    # Re-sort after recency adjustment (usually already sorted, but be safe)
    results.sort(key=lambda r: r.score, reverse=True)
    for i, r in enumerate(results):
        r.rank = i

    return results
