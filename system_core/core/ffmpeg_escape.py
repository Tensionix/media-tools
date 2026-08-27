from __future__ import annotations

import math
from pathlib import Path


_FILTER_OPTION_VALUE_SPECIALS = {"\\", "'", ":"}
_FILTERGRAPH_SPECIALS = {"\\", "'", "[", "]", ",", ";"}


def _escape_chars(text: str, special_chars: set[str]) -> str:
    return "".join(f"\\{char}" if char in special_chars else char for char in text)


def ffmpeg_filter_option_value(value: str) -> str:
    """Escape a filter option value for direct embedding in a filtergraph."""
    return _escape_chars(_escape_chars(value, _FILTER_OPTION_VALUE_SPECIALS), _FILTERGRAPH_SPECIALS)


def ffmpeg_filter_path(path: Path) -> str:
    text = str(path).replace("\\", "/")
    return ffmpeg_filter_option_value(text)


def ffmpeg_filter_number(value: object, *, name: str = "value") -> str:
    text = str(value).strip()
    if isinstance(value, bool) or not text:
        raise ValueError(f"Invalid {name}: {value!r}. Expected a finite number.")
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}: {value!r}. Expected a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"Invalid {name}: {value!r}. Expected a finite number.")
    return f"{number:g}"
