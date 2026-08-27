from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import load_yaml_or_json


SCRIPT_PROFILES_PATH = Path("config") / "script_profiles.yaml"


def _profile_id(script_name: str) -> str:
    return Path(str(script_name).strip().strip('"')).stem.lower()


@lru_cache(maxsize=8)
def load_script_profiles(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    path = project_root / SCRIPT_PROFILES_PATH
    if not path.exists():
        return {"defaults": {}, "profiles": {}}
    data = load_yaml_or_json(path)
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        data["profiles"] = {}
    else:
        data["profiles"] = {_profile_id(key): value for key, value in profiles.items()}
    defaults = data.get("defaults")
    if not isinstance(defaults, dict):
        data["defaults"] = {}
    return data


def script_profile(root: str | Path, script_name: str) -> dict[str, Any]:
    profiles = load_script_profiles(root).get("profiles", {})
    profile = profiles.get(_profile_id(script_name), {})
    return profile if isinstance(profile, dict) else {}
