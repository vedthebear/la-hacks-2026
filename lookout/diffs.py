"""Helpers for computing StepContext fields (pixel diff, DOM diff)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops


def pixel_diff_pct(before_path: str | Path, after_path: str | Path) -> float:
    """Percent of pixels that differ between two PNG screenshots. Resizes after to before's size if needed.

    Returns 0.0 if either image is missing/unreadable. Range: 0.0 to 100.0.
    """
    try:
        a = Image.open(before_path).convert("RGB")
        b = Image.open(after_path).convert("RGB")
    except (FileNotFoundError, OSError):
        return 0.0

    if a.size != b.size:
        b = b.resize(a.size)

    diff = ImageChops.difference(a, b)
    bbox = diff.getbbox()
    if bbox is None:
        return 0.0

    # Count non-zero pixels via grayscale sum > 0
    gray = diff.convert("L")
    total = gray.width * gray.height
    if total == 0:
        return 0.0
    # histogram[0] = count of pixels with value 0 (identical)
    nonzero = total - gray.histogram()[0]
    return 100.0 * nonzero / total
