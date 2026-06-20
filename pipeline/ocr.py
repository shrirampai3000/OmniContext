"""
OmniContext — EasyOCR wrapper.
Lazy-loads the reader on first use to keep startup fast.
"""

import logging
from pathlib import Path

import config as cfg

logger = logging.getLogger(__name__)

_reader = None
_ocr_available = False
_reader_config = None


def _get_reader():
    global _reader, _ocr_available, _reader_config
    current_config = (tuple(cfg.OCR_LANGUAGES), cfg.OCR_GPU)
    if _reader is None or _reader_config != current_config:
        try:
            import easyocr
            logger.info(
                "Loading EasyOCR (lang=%s, gpu=%s) — first run downloads ~200 MB…",
                cfg.OCR_LANGUAGES,
                cfg.OCR_GPU,
            )
            _reader = easyocr.Reader(cfg.OCR_LANGUAGES, gpu=cfg.OCR_GPU, verbose=False)
            _reader_config = current_config
            _ocr_available = True
            logger.info("EasyOCR ready.")
        except ImportError:
            logger.warning("easyocr not installed — OCR disabled.")
        except Exception as exc:
            logger.error("EasyOCR init failed: %s", exc)
    return _reader


def extract_text(image_path: str) -> str:
    """
    Run OCR on an image file and return extracted text as a single string.
    Returns empty string if OCR unavailable or fails.
    """
    reader = _get_reader()
    if reader is None or not image_path:
        return ""

    path = Path(image_path)
    if not path.exists():
        logger.warning("OCR: image not found: %s", image_path)
        return ""

    try:
        results = reader.readtext(str(path), detail=0, paragraph=True)
        text = "\n".join(results)
        # Strip very short fragments that are likely noise
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 3]
        return "\n".join(lines)
    except Exception as exc:
        logger.error("OCR extraction failed (%s): %s", image_path, exc)
        return ""


def is_available() -> bool:
    return _ocr_available or (_get_reader() is not None)
