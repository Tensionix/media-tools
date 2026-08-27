"""Shared video scaling contract for the GUI services and the CLI runner.

Scaling is height-driven with an even auto width, so a non-16:9 source keeps its
aspect ratio instead of being stretched into a fixed frame.
"""

from __future__ import annotations

from typing import Any


SOURCE_RESOLUTIONS = {"", "source", "native", "original", "auto"}


def scale_filter(value: Any) -> str:
    """`scale=...` for a target height, or an empty string to keep the source size."""
    raw = str(value if value is not None else "source").strip().lower()
    if raw in SOURCE_RESOLUTIONS:
        return ""
    if raw.endswith("p"):
        raw = raw[:-1]
    if "x" in raw:
        raw = raw.rsplit("x", 1)[-1]
    try:
        height = int(raw)
    except ValueError:
        return ""
    if height <= 0:
        return ""
    return f"scale=-2:{height}:flags=lanczos"
