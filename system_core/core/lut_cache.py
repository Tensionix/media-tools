from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import shutil


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


def listed_luts(root: Path, current: str = "") -> list[tuple[str, str]]:
    """The LUTs a window lists, as (path, name): the pinned first, then the chosen one, the recent ones and the rest of
    LUTs\\; a name is the path within LUTs\\, a LUT elsewhere keeps its whole path (the window on NiceGUI: lut_options)."""
    cache = load_lut_cache(root)
    ordered = [*cache.get("pinned_luts", []), current, cache.get("selected_lut", ""), *cache.get("recent_luts", []), *scan_luts(root)]
    lut_root = (root / "LUTs").resolve()
    listed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in ordered:
        text = _clean(item)
        if not text:
            continue
        path = resolve_lut_path(root, text)
        if str(path).casefold() in seen or not path.is_file():
            continue
        seen.add(str(path).casefold())
        try:
            name = str(path.relative_to(lut_root))
        except ValueError:
            name = str(path)
        listed.append((str(path), name))
    return listed


def pinned_luts(root: Path) -> list[str]:
    return [str(resolve_lut_path(root, item)) for item in load_lut_cache(root).get("pinned_luts", [])]


def import_luts(root: Path, files: list[str] | None = None, folder: str = "") -> list[Path]:
    """LUT files copied into LUTs\\ of the program: files one by one, a folder with its tree under its own name. What is not
    a LUT is passed over; a file already in LUTs\\ stays where it is. The copies, in order."""
    lut_root = (root / "LUTs").resolve()
    lut_root.mkdir(parents=True, exist_ok=True)
    pairs: list[tuple[Path, Path]] = []
    if folder:
        source_root = Path(folder).resolve()
        target_root = lut_root if source_root == lut_root else lut_root / source_root.name
        pairs = [(source, target_root / source.relative_to(source_root)) for source in sorted(source_root.rglob("*"))]
    for name in files or []:
        source = Path(name).resolve()
        pairs.append((source, lut_root / source.name))
    copied: list[Path] = []
    for source, target in pairs:
        if not source.is_file() or source.suffix.lower() not in LUT_EXTENSIONS:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target.resolve():
            shutil.copy2(source, target)
        copied.append(target.resolve())
    return copied


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
