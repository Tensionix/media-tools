from __future__ import annotations

from pathlib import Path
from typing import Any
import json


MAX_RECENT_LUTS = 200
LUT_EXTENSIONS = {".cube", ".3dl", ".lut"}


def cache_path(root: Path) -> Path:
    return root / "config" / "gui_lut_cache.json"


def _clean(value: Any) -> str:
    return str(value or "").strip().strip('"')


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def resolve_lut_path(root: Path, value: Any) -> Path:
    text = _clean(value)
    if not text:
        return root / "LUTs"
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def scan_luts(root: Path) -> list[str]:
    lut_dir = root / "LUTs"
    if not lut_dir.exists():
        return []
    return [
        str(path.resolve())
        for path in sorted(lut_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in LUT_EXTENSIONS
    ]


def _default_cache(root: Path) -> dict[str, Any]:
    files = scan_luts(root)
    return {
        "selected_lut": files[0] if files else "",
        "recent_luts": files[:MAX_RECENT_LUTS],
        "pinned_luts": [],
    }


def load_lut_cache(root: Path) -> dict[str, Any]:
    defaults = _default_cache(root)
    path = cache_path(root)
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    merged = {**defaults, **data}
    scanned = scan_luts(root)
    merged["recent_luts"] = _dedupe([*list(merged.get("recent_luts", [])), *scanned])[:MAX_RECENT_LUTS]
    merged["pinned_luts"] = _dedupe(list(merged.get("pinned_luts", [])))
    merged["selected_lut"] = _clean(merged.get("selected_lut")) or (scanned[0] if scanned else "")
    return merged


def save_lut_cache(root: Path, cache: dict[str, Any]) -> None:
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _default_cache(root)
    normalized.update(cache)
    normalized["recent_luts"] = _dedupe(list(normalized.get("recent_luts", [])))[:MAX_RECENT_LUTS]
    normalized["pinned_luts"] = _dedupe(list(normalized.get("pinned_luts", [])))
    normalized["selected_lut"] = _clean(normalized.get("selected_lut"))
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def update_lut_cache(root: Path, value: str, *, pinned: bool | None = None) -> dict[str, Any]:
    cache = load_lut_cache(root)
    path = resolve_lut_path(root, value)
    text = str(path)
    cache["selected_lut"] = text
    cache["recent_luts"] = _dedupe([text, *list(cache.get("recent_luts", [])), *scan_luts(root)])[:MAX_RECENT_LUTS]
    pinned_values = _dedupe(list(cache.get("pinned_luts", [])))
    if pinned is True and text.lower() not in {item.lower() for item in pinned_values}:
        pinned_values.insert(0, text)
    elif pinned is False:
        pinned_values = [item for item in pinned_values if item.lower() != text.lower()]
    cache["pinned_luts"] = pinned_values
    save_lut_cache(root, cache)
    return cache
