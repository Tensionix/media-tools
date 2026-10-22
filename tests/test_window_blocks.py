"""Every block of a form has a name in the window: a section of the manifest (operation_model.section_of) is a case of
Form.GroupName in Source\\Views\\Form.cs, and its Russian words have their English pair in Source\\config\\i18n.json. A block
without one is headed by its own id - TRIM in a Russian window.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from system_core.core import operation_model as model
from system_core.core.manifest import load_manifest

PROJECT = Path(__file__).resolve().parent.parent
FORM = PROJECT / "Source" / "Views" / "Form.cs"


def named() -> dict[str, str]:
    """The cases of GroupName: the block and what it is called."""
    text = FORM.read_text(encoding="utf-8-sig")
    body = text[text.index("public static string GroupName(string block)"):]
    body = body[:body.index("};")]
    return dict(re.findall(r'^\s*"([a-z_]+)" => (.+?),\s*$', body, re.M))


def test_every_section_of_the_manifest_has_a_name() -> None:
    manifest = load_manifest(PROJECT / "config" / "tool_manifest.yaml")
    sections = {model.section_of(field) for node in model.all_nodes(manifest) for field in model.form_fields(node)}
    names = named()
    assert sections - set(names) == set(), sorted(sections - set(names))


def test_every_russian_name_has_its_english_pair() -> None:
    pairs = json.loads((PROJECT / "Source" / "config" / "i18n.json").read_text(encoding="utf-8"))
    words = [match for said in named().values() for match in re.findall(r'Lang\.T\("([^"]+)"\)', said)]
    assert words and [word for word in words if word not in pairs] == []
