from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def cache_path(root: Path) -> Path:
    return root / "config" / "gui_profile_cache.json"


def load_profile_cache(root: Path) -> dict[str, Any]:
    path = cache_path(root)
    if not path.exists():
        return {"pinned": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"pinned": {}}
    if not isinstance(data, dict):
        return {"pinned": {}}
    pinned = data.get("pinned", {})
    if not isinstance(pinned, dict):
        pinned = {}
    return {"pinned": pinned}


def save_profile_cache(root: Path, cache: dict[str, Any]) -> None:
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def pinned_profiles(root: Path, field_id: str) -> list[str]:
    cache = load_profile_cache(root)
    raw = cache.get("pinned", {}).get(field_id, [])
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item).strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def set_profile_pin(root: Path, field_id: str, profile_id: str, pinned: bool) -> None:
    cache = load_profile_cache(root)
    cache.setdefault("pinned", {})
    pinned_map = cache["pinned"]
    current = pinned_profiles(root, field_id)
    profile_id = str(profile_id).strip()
    if not profile_id:
        return
    if pinned and profile_id.lower() not in {item.lower() for item in current}:
        current.insert(0, profile_id)
    if not pinned:
        current = [item for item in current if item.lower() != profile_id.lower()]
    pinned_map[field_id] = current
    save_profile_cache(root, cache)

