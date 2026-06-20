"""
OmniContext — Local AI summariser via Ollama.
Sends image + OCR text to a multimodal model and extracts
summary, entities, and topics.
Falls back to text-only if vision model unavailable.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import httpx

import config as cfg

logger = logging.getLogger(__name__)

_VISION_PROMPT = """\
You are an AI assistant analysing a screenshot. Given the image and the OCR text below, provide:
1. A 1-2 sentence summary of what the user was doing.
2. Key entities (people, apps, files, URLs, topics) as a JSON list.
3. Topics/tags as a JSON list (2-5 short tags).

OCR text:
{ocr_text}

Respond ONLY with valid JSON in this exact format:
{{
  "summary": "...",
  "entities": ["...", "..."],
  "topics": ["...", "..."]
}}
"""

_TEXT_PROMPT = """\
You are an AI assistant. Given this window title and OCR text from a screenshot, provide:
1. A 1-2 sentence summary of what the user was doing.
2. Key entities as a JSON list.
3. Topics/tags as a JSON list (2-5 short tags).

Window: {window_title}
App: {app_name}
OCR text:
{ocr_text}

Respond ONLY with valid JSON:
{{
  "summary": "...",
  "entities": ["...", "..."],
  "topics": ["...", "..."]
}}
"""


def _parse_response(text: str) -> Dict:
    """Extract JSON from model response (handles markdown code fences)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON block inside the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    logger.warning("Could not parse model response as JSON")
    return {"summary": text[:300], "entities": [], "topics": []}


def _ollama_chat(model: str, messages: list, timeout: int) -> str:
    """POST to Ollama /api/chat and return the assistant message content."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{cfg.OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")


def is_ollama_available() -> bool:
    """Quick ping to check if Ollama is running."""
    try:
        with httpx.Client(timeout=3) as client:
            resp = client.get(f"{cfg.OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
        return True
    except Exception:
        return False


def summarise(
    screenshot_path: str,
    ocr_text: str,
    window_title: str = "",
    app_name: str = "",
) -> Dict[str, object]:
    """
    Returns {"summary": str, "entities": list[str], "topics": list[str]}.
    Falls back through: vision → text-only → heuristic.
    """
    default = {
        "summary": f"Used {app_name or 'an app'}: {window_title[:100]}",
        "entities": [e for e in [app_name, window_title[:40]] if e],
        "topics": [app_name] if app_name else [],
    }

    if not is_ollama_available():
        logger.debug("Ollama not available — using heuristic summary.")
        return default

    # ── Try vision model ───────────────────────────────────────────────────
    img_path = Path(screenshot_path)
    if img_path.exists():
        try:
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()

            prompt = _VISION_PROMPT.format(ocr_text=ocr_text[:1500])
            messages = [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64],
                }
            ]
            raw = _ollama_chat(cfg.OLLAMA_VISION_MODEL, messages, cfg.OLLAMA_TIMEOUT)
            result = _parse_response(raw)
            if result.get("summary"):
                return result
        except Exception as exc:
            logger.warning("Vision model failed (%s): %s", cfg.OLLAMA_VISION_MODEL, exc)

    # ── Fallback: text-only model ──────────────────────────────────────────
    try:
        prompt = _TEXT_PROMPT.format(
            window_title=window_title,
            app_name=app_name,
            ocr_text=ocr_text[:1500],
        )
        messages = [{"role": "user", "content": prompt}]
        raw = _ollama_chat(cfg.OLLAMA_TEXT_MODEL, messages, cfg.OLLAMA_TIMEOUT)
        result = _parse_response(raw)
        if result.get("summary"):
            return result
    except Exception as exc:
        logger.warning("Text model failed (%s): %s", cfg.OLLAMA_TEXT_MODEL, exc)

    return default
