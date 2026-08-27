from __future__ import annotations

from pathlib import Path
from typing import Any
import json


MAX_RECENT_PATHS = 200


def _default_cache(root: Path) -> dict[str, Any]:
    return {
        "source_path": str(root / "Source"),
        "output_path": str(root / "Transcoded"),
        "recent_source_paths": [str(root / "Source")],
        "recent_output_paths": [str(root / "Transcoded")],
        "pinned_source_paths": [],
        "pinned_output_paths": [],
    }


def _clean_path(value: Any) -> str:
    text = str(value or "").strip().strip('"')
    return text


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_path(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def cache_path(root: Path) -> Path:
    return root / "config" / "gui_path_cache.json"


def load_path_cache(root: Path) -> dict[str, Any]:
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
    for key in ["recent_source_paths", "recent_output_paths", "pinned_source_paths", "pinned_output_paths"]:
        value = merged.get(key, [])
        merged[key] = _dedupe(value if isinstance(value, list) else [])
    merged["source_path"] = _clean_path(merged.get("source_path")) or defaults["source_path"]
    merged["output_path"] = _clean_path(merged.get("output_path")) or defaults["output_path"]
    return merged


def save_path_cache(root: Path, cache: dict[str, Any]) -> None:
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _default_cache(root)
    normalized.update(cache)
    for key in ["recent_source_paths", "recent_output_paths", "pinned_source_paths", "pinned_output_paths"]:
        value = normalized.get(key, [])
        normalized[key] = _dedupe(value if isinstance(value, list) else [])
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_cached_path(root: Path, value: Any, fallback: Path) -> Path:
    text = _clean_path(value)
    if not text:
        return fallback
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def cached_source_path(root: Path) -> Path:
    cache = load_path_cache(root)
    return resolve_cached_path(root, cache.get("source_path"), root / "Source")


def cached_output_path(root: Path) -> Path:
    cache = load_path_cache(root)
    return resolve_cached_path(root, cache.get("output_path"), root / "Transcoded")


def update_path_cache(root: Path, role: str, path_value: str, *, pinned: bool | None = None) -> dict[str, Any]:
    if role not in {"source", "output"}:
        raise ValueError(f"Unknown path cache role: {role}")

    cache = load_path_cache(root)
    target_path = resolve_cached_path(
        root,
        path_value,
        root / ("Source" if role == "source" else "Transcoded"),
    )
    text = str(target_path)
    current_key = f"{role}_path"
    recent_key = f"recent_{role}_paths"
    pinned_key = f"pinned_{role}_paths"

    cache[current_key] = text
    cache[recent_key] = _dedupe([text, *list(cache.get(recent_key, []))])[:MAX_RECENT_PATHS]

    pinned_values = _dedupe(list(cache.get(pinned_key, [])))
    if pinned is True and text.lower() not in {item.lower() for item in pinned_values}:
        pinned_values.insert(0, text)
    elif pinned is False:
        pinned_values = [item for item in pinned_values if item.lower() != text.lower()]
    cache[pinned_key] = pinned_values

    save_path_cache(root, cache)
    return cache
