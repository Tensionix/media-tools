"""The signs of the window: every one it asks for is in Source\\Icons.cs, and the table carries no sign nobody asks for.

A sign the table lacks draws nothing - the button is empty, and no error says so. A sign nobody asks for is weight the
window carries for a window it is not (the lists of Image Tools and Setup Tools were the start of this one).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "Source"


def table() -> tuple[set[str], set[str]]:
    """The Lucide signs of Icons.cs, and every name of it - the brand marks too."""
    text = (SOURCE / "Icons.cs").read_text(encoding="utf-8")
    lucide = text[:text.index(" Brand = ")]
    return set(re.findall(r'\["([a-z0-9-]+)"\]', lucide)), set(re.findall(r'\["([a-z0-9-]+)"\]', text))


def code() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in SOURCE.rglob("*")
                     if path.suffix in {".cs", ".axaml"} and path.name != "Icons.cs" and not ({"bin", "obj"} & set(path.parts)))


def layout_icons() -> set[str]:
    """The icons of config\\window_layout.yaml: of the sections, the modes, the buttons beside a field."""
    found: set[str] = set()

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "icon" and isinstance(item, str) and item:
                    found.add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(yaml.safe_load((ROOT / "config" / "window_layout.yaml").read_text(encoding="utf-8")))
    return found


def asked() -> set[str]:
    """What the window asks for by name: a sign of its markup, of its code, and of the layout."""
    text = code()
    names = set(re.findall(r'<Path [^>]*Classes="icon[^"]*"[^>]*Tag="([a-z0-9-]+)"', text))
    names |= set(re.findall(r'<Path [^>]*Tag="([a-z0-9-]+)"[^>]*Classes="icon', text))
    names |= set(re.findall(r'Icons\.(?:Sign|Glyph)\("([a-z0-9-]+)"\)', text))
    return names | layout_icons()


def test_every_sign_the_window_asks_for_is_in_the_table() -> None:
    _lucide, every = table()
    missing = sorted(asked() - every)
    assert not missing, f"asked for and not in Icons.cs: {missing}"


def test_the_table_carries_no_sign_nobody_asks_for() -> None:
    lucide, _every = table()
    text, layout = code(), layout_icons()
    unused = sorted(name for name in lucide if f'"{name}"' not in text and name not in layout)
    assert not unused, f"in Icons.cs, asked for by nobody - out of Source\\Tools\\build_icons.py with them: {unused}"
