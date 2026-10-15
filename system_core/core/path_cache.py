from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from .paths import INPUT_DIR, OUTPUT_DIR


MAX_RECENT_PATHS = 200
# The Source and the Target a process was started with: the console command names them for the run, and the
# wrappers have always read the same two names. Without them - the folders the window last pointed at.
SOURCE_ENV = "AUDION_SOURCE"
OUTPUT_ENV = "AUDION_OUTPUT"
# The kinds of file a run of the console command takes, when it narrows them (a wrapper MKV -> MP4 takes MKV alone).
ONLY_FORMATS_ENV = "AUDION_ONLY_FORMATS"


def only_formats() -> set[str]:
    """The kinds of file this process is narrowed to; empty - no narrowing."""
    return {item.strip().lower().lstrip(".") for item in os.environ.get(ONLY_FORMATS_ENV, "").split(",") if item.strip()}


def _default_cache(root: Path) -> dict[str, Any]:
    return {
        "source_path": str(root / INPUT_DIR),
        "output_path": str(root / OUTPUT_DIR),
        "recent_source_paths": [str(root / INPUT_DIR)],
        "recent_output_paths": [str(root / OUTPUT_DIR)],
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
    given = os.environ.get(SOURCE_ENV, "").strip()
    if given:
        return resolve_cached_path(root, given, root / INPUT_DIR)
    cache = load_path_cache(root)
    return resolve_cached_path(root, cache.get("source_path"), root / INPUT_DIR)


def cached_output_path(root: Path) -> Path:
    given = os.environ.get(OUTPUT_ENV, "").strip()
    if given:
        return resolve_cached_path(root, given, root / OUTPUT_DIR)
    cache = load_path_cache(root)
    return resolve_cached_path(root, cache.get("output_path"), root / OUTPUT_DIR)


def update_path_cache(root: Path, role: str, path_value: str, *, pinned: bool | None = None) -> dict[str, Any]:
    if role not in {"source", "output"}:
        raise ValueError(f"Unknown path cache role: {role}")

    cache = load_path_cache(root)
    target_path = resolve_cached_path(
        root,
        path_value,
        root / (INPUT_DIR if role == "source" else OUTPUT_DIR),
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
