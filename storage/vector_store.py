"""
OmniContext — FAISS vector store wrapper.
Manages an in-memory index with disk persistence.
Stores metadata (event_id ↔ FAISS row) separately as JSON.
"""

import json
import logging
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from config import FAISS_INDEX_PATH, FAISS_META_PATH, EMBEDDING_DIM

logger = logging.getLogger(__name__)

try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False
    logger.warning("faiss-cpu not installed — vector search disabled.")


class VectorStore:
    """
    Thread-safe FAISS IndexFlatIP with cosine similarity (via L2 normalisation).
    Metadata: list of event_ids indexed by FAISS row number.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._meta: List[str] = []          # index → event_id
        self._index: Optional[object] = None

        if _FAISS_AVAILABLE:
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
            self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if FAISS_INDEX_PATH.exists() and FAISS_META_PATH.exists():
            try:
                self._index = faiss.read_index(str(FAISS_INDEX_PATH))
                self._meta = json.loads(FAISS_META_PATH.read_text(encoding="utf-8"))
                logger.info(
                    "Loaded FAISS index (%d vectors) from disk.", self._index.ntotal
                )
            except Exception as exc:
                logger.error("Failed to load FAISS index: %s — starting fresh.", exc)
                self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
                self._meta = []

    def save(self) -> None:
        if not _FAISS_AVAILABLE or self._index is None:
            return
        with self._lock:
            try:
                faiss.write_index(self._index, str(FAISS_INDEX_PATH))
                FAISS_META_PATH.write_text(json.dumps(self._meta), encoding="utf-8")
                logger.info("FAISS index saved (%d vectors).", self._index.ntotal)
            except Exception as exc:
                logger.error("Failed to save FAISS index: %s", exc)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add(self, event_id: str, vector: np.ndarray) -> int:
        """
        Add a normalised embedding. Returns the FAISS row index assigned.
        """
        if not _FAISS_AVAILABLE or self._index is None:
            return -1

        vec = vector.astype(np.float32).reshape(1, -1)
        if vec.shape[1] != EMBEDDING_DIM:
            logger.error("Embedding for %s has dimension %d, expected %d.", event_id, vec.shape[1], EMBEDDING_DIM)
            return -1
        if not np.isfinite(vec).all() or float(np.linalg.norm(vec)) == 0.0:
            logger.debug("Skipping empty embedding for event %s.", event_id)
            return -1
        faiss.normalize_L2(vec)

        with self._lock:
            for i, eid in enumerate(self._meta):
                if eid == event_id:
                    self._meta[i] = "__deleted__"
            row = self._index.ntotal
            self._index.add(vec)
            self._meta.append(event_id)

        return row

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> List[Tuple[str, float]]:
        """
        Returns list of (event_id, score) sorted by descending cosine similarity.
        """
        if not _FAISS_AVAILABLE or self._index is None or self._index.ntotal == 0:
            return []

        vec = query_vector.astype(np.float32).reshape(1, -1)
        if vec.shape[1] != EMBEDDING_DIM:
            logger.error("Query embedding has dimension %d, expected %d.", vec.shape[1], EMBEDDING_DIM)
            return []
        if not np.isfinite(vec).all() or float(np.linalg.norm(vec)) == 0.0:
            return []
        faiss.normalize_L2(vec)

        k = min(top_k, self._index.ntotal)
        with self._lock:
            distances, indices = self._index.search(vec, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            if idx < len(self._meta):
                event_id = self._meta[idx]
                if event_id not in ("__deleted__", ""):
                    results.append((event_id, float(dist)))

        return results

    def remove(self, event_id: str) -> None:
        """
        FAISS IndexFlatIP doesn't support removal; we mark the slot as removed
        by nulling the meta entry. The vector stays but never surfaces in results.
        """
        with self._lock:
            for i, eid in enumerate(self._meta):
                if eid == event_id:
                    self._meta[i] = "__deleted__"

    def compact(self) -> None:
        """
        Rebuilds the FAISS index to permanently remove tombstones.
        """
        if not _FAISS_AVAILABLE or self._index is None:
            return
        with self._lock:
            try:
                new_index = faiss.IndexFlatIP(EMBEDDING_DIM)
                new_meta = []
                for i, eid in enumerate(self._meta):
                    if eid not in ("__deleted__", ""):
                        vec = self._index.reconstruct(i)
                        new_index.add(vec.reshape(1, -1))
                        new_meta.append(eid)
                self._index = new_index
                self._meta = new_meta
                logger.info("FAISS index compacted (%d vectors).", self._index.ntotal)
            except Exception as exc:
                logger.error("Failed to compact FAISS index: %s", exc)

    @property
    def total(self) -> int:
        if not _FAISS_AVAILABLE or self._index is None:
            return 0
        return self._index.ntotal

    @property
    def available(self) -> bool:
        return _FAISS_AVAILABLE


# Module-level singleton
_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
