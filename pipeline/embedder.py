"""
OmniContext — Text embedder using sentence-transformers.
Lazy-loads the model; falls back gracefully if not installed.
"""

import logging
from typing import Optional

import numpy as np

from config import EMBEDDING_MODEL, EMBEDDING_DIM, MAX_OCR_FOR_EMBED

logger = logging.getLogger(__name__)

_model = None
_model_available = False


def _get_model():
    global _model, _model_available
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model '%s'…", EMBEDDING_MODEL)
            _model = SentenceTransformer(EMBEDDING_MODEL)
            _model_available = True
            logger.info("Embedding model ready (dim=%d).", EMBEDDING_DIM)
        except ImportError:
            logger.warning("sentence-transformers not installed — embeddings disabled.")
        except Exception as exc:
            logger.error("Embedding model init failed: %s", exc)
    return _model


def embed(text: str) -> np.ndarray:
    """
    Encode text into a float32 vector of shape (EMBEDDING_DIM,).
    Returns a zero vector if the model is unavailable.
    """
    model = _get_model()
    if model is None or not text.strip():
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    try:
        vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vec.astype(np.float32)
    except Exception as exc:
        logger.error("Embedding failed: %s", exc)
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)


def build_embed_text(
    summary: str,
    entities: list,
    topics: list,
    ocr_text: str,
    window_title: str = "",
    app_name: str = "",
) -> str:
    """
    Construct the text blob that gets embedded for an event.
    Combines the most semantically rich fields.
    """
    parts = [
        summary,
        window_title,
        app_name,
        " ".join(entities),
        " ".join(topics),
        ocr_text[:MAX_OCR_FOR_EMBED],
    ]
    return " ".join(p for p in parts if p).strip()


def is_available() -> bool:
    return _model_available or (_get_model() is not None)
