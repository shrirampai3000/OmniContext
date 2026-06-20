"""
OmniContext — Screenshot capture using mss.
Saves compressed WebP frames to the screenshots directory.
"""

import logging
import time
from pathlib import Path
from datetime import datetime

import mss
import mss.tools
from PIL import Image

import config as cfg

logger = logging.getLogger(__name__)


def capture_screenshot(monitor_index: int = 1) -> str:
    """
    Capture the specified monitor and save as WebP.

    Args:
        monitor_index: 1 = primary monitor, 0 = all monitors combined.

    Returns:
        Absolute path to the saved WebP file, or "" on failure.
    """
    try:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        filename = f"{timestamp}.webp"
        output_path = cfg.SCREENSHOTS_DIR / filename

        with mss.mss() as sct:
            monitor = sct.monitors[monitor_index]
            sct_img = sct.grab(monitor)

            # Convert raw BGRA → PIL RGB
            img = Image.frombytes(
                "RGB",
                (sct_img.width, sct_img.height),
                sct_img.rgb,
            )

            # Optionally downscale large screens to reduce size
            max_width = 1920
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            img.save(str(output_path), "WEBP", quality=cfg.SCREENSHOT_QUALITY)

        logger.debug("Screenshot saved: %s", output_path)
        return str(output_path)

    except Exception as exc:
        logger.error("Screenshot capture failed: %s", exc)
        return ""
