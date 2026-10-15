"""The four themes of the window hold one set of keys, and every key the window takes is in them (Source\\App.axaml).

A key one theme lacks is no error in Avalonia: the control takes nothing, and the part goes transparent or black in that
theme alone. A key the window asks for and no theme holds is the same, in every theme.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "Source"
KEY = "{http://schemas.microsoft.com/winfx/2006/xaml}Key"


def resources() -> tuple[dict[str, set[str]], set[str]]:
    """The keys of each theme by its name, and the keys outside the themes - fonts, sizes, those set in code."""
    root = ET.parse(SOURCE / "App.axaml").getroot()
    themes: dict[str, set[str]] = {}
    common: set[str] = set()
    for holder in root.iter():
        if holder.tag.endswith("ThemeDictionaries"):
            for theme in holder:
                name = re.sub(r"^\{x:Static local:App\.(\w+)\}$", r"\1", theme.get(KEY, ""))
                themes[name] = {item.get(KEY) for item in theme.iter() if item is not theme and item.get(KEY)}
    inside = {id(item) for holder in root.iter() if holder.tag.endswith("ThemeDictionaries") for item in holder.iter()}
    common |= {item.get(KEY) for item in root.iter() if item.get(KEY) and id(item) not in inside}
    common |= set(re.findall(r'Resources\["(\w+)"\]\s*=', (SOURCE / "App.axaml.cs").read_text(encoding="utf-8")))
    return themes, common


def used() -> set[str]:
    """Every key the window asks for: DynamicResource of the markup, Ink and TryGetResource of the code."""
    found: set[str] = set()
    for path in SOURCE.rglob("*"):
        if {"bin", "obj"} & set(path.parts) or path.suffix not in {".axaml", ".cs"}:
            continue
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"DynamicResource (\w+)", text))
        found |= set(re.findall(r'Ink\((?:[\w.]+, )?"(\w+)"\)', text))
        found |= set(re.findall(r'TryGetResource\("(\w+)"', text))
    return found


def test_the_four_themes_hold_one_set_of_keys() -> None:
    themes, _common = resources()
    assert set(themes) == {"Dark", "Light", "CodeDark", "VaultDark"}
    dark = themes["Dark"]
    for name, keys in themes.items():
        assert keys == dark, f"{name}: lacks {sorted(dark - keys)}, has besides {sorted(keys - dark)}"


def test_every_key_the_window_takes_is_held() -> None:
    themes, common = resources()
    missing = sorted(used() - themes["Dark"] - common)
    assert not missing, f"asked for and held by no theme: {missing}"
