"""The reference part of the documents (`media_cli.cmd map --docs`, core\\program_docs.py) against the map.

Docs\\OPERATIONS_*, Docs\\SCRIPTS_* and the tables between `<!-- map:NAME -->` and `<!-- /map -->` of SKILL.md, the agent
guides and the CLI guides are made from the data of the program, never written by hand. A document the map makes otherwise
is written again here - the build of the window runs this test, and a stale document is not a reason to stop it; what
cannot be made current is.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest

from system_core.core import program_docs, program_map

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def told() -> dict[str, Any]:
    from system_core import cli

    paths, manifest = cli.project(str(PROJECT))
    return program_map.build(paths, manifest, version=cli.project_version(paths), environment=cli.WRAPPER_ENVIRONMENT)


def test_the_documents_follow_the_map(told: dict[str, Any]) -> None:
    written = program_docs.write(told, PROJECT)
    if written:
        warnings.warn("written again from the map: " + ", ".join(str(path.relative_to(PROJECT)) for path in written))
    assert program_docs.stale(told, PROJECT) == []


def test_every_guide_keeps_its_tables() -> None:
    for name in program_docs.WRITTEN:
        text = (PROJECT / name).read_text(encoding="utf-8")
        found = {match.group("name") for match in program_docs.BLOCK.finditer(text)}
        assert found == {"sections", "service"}, name


def test_the_operations_document_names_every_operation(told: dict[str, Any]) -> None:
    for language in ("ru", "en"):
        text = (PROJECT / "Docs" / f"OPERATIONS_{language.upper()}.md").read_text(encoding="utf-8")
        for operation in told["operations"]:
            assert f"`{operation}`" in text, (language, operation)


def test_fill_changes_only_what_is_between_the_marks() -> None:
    text = "Before.\n<!-- map:sections -->\nold table\n<!-- /map -->\nBetween.\n<!-- map:service -->\n<!-- /map -->\nAfter.\n"
    made = program_docs.fill(text, {"sections": "| A |", "service": "| B |"})
    assert made == "Before.\n<!-- map:sections -->\n| A |\n<!-- /map -->\nBetween.\n<!-- map:service -->\n| B |\n<!-- /map -->\nAfter.\n"
    assert program_docs.fill("No marks here.\n", {"sections": "| A |"}) == "No marks here.\n"
    # A block the map does not know stays as it is.
    assert program_docs.fill("<!-- map:other -->\nkept\n<!-- /map -->\n", {"sections": "x"}) == "<!-- map:other -->\nkept\n<!-- /map -->\n"
