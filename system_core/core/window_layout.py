"""Where every operation stands in the window: config\\window_layout.yaml read and checked.

The manifest says what an operation is, the layout - where it stands: a section of the ribbon, and inside
it the ribbon of its modes. A mode is an operation of its own, or a choice of one field of the section's
operation (the mode field), which is then not drawn in the form. The console command hands the layout to
the window in `describe`; the window draws what it is told and knows no operation by its name.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_yaml_or_json

SECTION_TEXTS = ("title", "title_ru", "about", "about_ru", "icon")


def load(config: Path) -> dict[str, Any]:
    path = Path(config) / "window_layout.yaml"
    raw = load_yaml_or_json(path) if path.is_file() else {}
    return raw if isinstance(raw, dict) else {}


def _names(items: Any) -> list[str]:
    return [str(item).strip() for item in items or [] if str(item).strip()]


def describe(layout: dict[str, Any]) -> dict[str, Any]:
    """The layout as written: every mode with its operation, and its field and value when it is a choice."""
    sections = []
    for section in layout.get("sections") or []:
        told = {key: str(section.get(key, "")) for key in ("id", *SECTION_TEXTS)}
        op, field = str(section.get("op", "")).strip(), str(section.get("mode_field", "")).strip()
        told["op"], told["mode_field"] = op, field
        modes = []
        for mode in section.get("modes") or []:
            mode = mode if isinstance(mode, dict) else {"op": str(mode)}
            value = mode.get("value")
            modes.append({
                "op": str(mode.get("op") or op).strip(),
                "field": field if value is not None else "",
                "value": value,
                "title": str(mode.get("title", "")), "title_ru": str(mode.get("title_ru", "")),
                "icon": str(mode.get("icon", "")),
            })
        told["modes"] = modes
        # Blocks of the form drawn at its very end, under the rare fields: a block seldom wanted (AUDIO: the filter of the Source).
        told["blocks_last"] = _names(section.get("blocks_last"))
        sections.append(told)
    return {"sections": sections, "service": _names(layout.get("service")), "details": _names(layout.get("details")),
            "own": _names(layout.get("own")), "buttons": _buttons(layout.get("buttons")), "paste": _names(layout.get("paste"))}


def _buttons(value: Any) -> list[dict[str, Any]]:
    """Operations a page runs with its own values, as a button beside one of its fields: [{op, beside, icon, words}];
    words false - the sign alone, the name in its tooltip."""
    return [{"op": str(item.get("op") or "").strip(), "beside": str(item.get("beside") or "").strip(),
             "icon": str(item.get("icon") or "").strip(), "words": item.get("words", True) is not False}
            for item in value or [] if isinstance(item, dict)]


def placed(layout: dict[str, Any]) -> list[str]:
    """Every operation the layout names: a section's once, however many of its modes are choices of a field."""
    told = describe(layout)
    names: list[str] = []
    for section in told["sections"]:
        seen: list[str] = []
        for mode in section["modes"]:
            if mode["op"] not in seen:
                seen.append(mode["op"])
        names += seen
    return names + told["service"] + told["details"] + told["own"] + [button["op"] for button in told["buttons"]]


def problems(layout: dict[str, Any], manifest: Any) -> list[str]:
    """What is wrong between the layout and the manifest; nothing when every operation stands once."""
    from . import operation_model as model

    operations = {node.id for node in model.all_nodes(manifest) if node.service and not node.children}
    operations |= {operation.id for operation in [*manifest.operations, *manifest.maintenance_operations]}
    names = placed(layout)
    wrong = [f"stands nowhere in the window: {name}" for name in sorted(operations - set(names))]
    wrong += [f"is not an operation of the manifest: {name}" for name in sorted(set(names) - operations)]
    wrong += [f"stands more than once: {name}" for name in sorted({name for name in names if names.count(name) > 1})]
    told = describe(layout)
    ids = [section["id"] for section in told["sections"]]
    wrong += [f"a section without an id or with one taken: {name!r}" for name in sorted({i for i in ids if not i or ids.count(i) > 1})]
    for section in told["sections"]:
        name = section["id"]
        wrong += [f"the section {name} has no {key}" for key in SECTION_TEXTS if not section[key]]
        if not section["modes"]:
            wrong.append(f"the section {name} has no mode")
        blocks = {model.section_of(field) for mode in section["modes"] if (node := model.find_node(manifest, mode["op"]))
                  for field in model.form_fields(node)}
        wrong += [f"the section {name}: no form of it has the block {block!r} of blocks_last" for block in section["blocks_last"]
                  if block not in blocks]
        field_id = section["mode_field"]
        if not field_id:
            wrong += [f"the section {name}: a mode of a value without a mode field" for mode in section["modes"] if mode["value"] is not None]
            continue
        node = model.find_node(manifest, section["op"])
        field = next((item for item in (node.fields if node else ()) if model.field_id(item) == field_id), None)
        if field is None:
            wrong.append(f"the section {name}: {section['op']} has no field {field_id}")
            continue
        choices = [model.option_value(option) for option in field.get("options") or []]
        # A mode that is an operation of its own stands beside the choices of the field (PACKAGE: SUBTITLES).
        given = [mode["value"] for mode in section["modes"] if mode["field"]]
        wrong += [f"the section {name}: no mode for the choice {choice!r} of {field_id}" for choice in choices if choice not in given]
        wrong += [f"the section {name}: {value!r} is no choice of {field_id}" for value in given if value not in choices]
    fields = {model.field_id(field) for node in model.all_nodes(manifest) for field in node.fields}
    wrong += [f"a button of {button['op']} stands beside no field: {button['beside']!r}" for button in told["buttons"]
              if button["beside"] not in fields]
    kinds = {model.field_id(field): model.field_kind(field) for node in model.all_nodes(manifest) for field in node.fields}
    wrong += [f"PASTE stands beside no field of a text or a path: {name!r}" for name in told["paste"]
              if kinds.get(name) not in {"text", "file"}]
    return wrong


def for_window(layout: dict[str, Any], manifest: Any, language: str = "en") -> dict[str, Any]:
    """The layout as the window reads it: every mode with its title in both languages and its operation."""
    from . import operation_model as model

    told = describe(layout)
    sections = []
    for section in told["sections"]:
        modes = []
        for mode in section["modes"]:
            node = model.find_node(manifest, mode["op"])
            if node is None:
                raise ValueError(f"the layout names an operation the manifest does not have: {mode['op']}")
            title, title_ru = mode["title"], mode["title_ru"]
            if mode["field"] and not (title and title_ru):
                field = next(item for item in node.fields if model.field_id(item) == mode["field"])
                option = next((item for item in field.get("options") or [] if model.option_value(item) == mode["value"]), {})
                title = title or str(option.get("label", mode["value"]))
                title_ru = title_ru or str(option.get("label_ru") or option.get("label", mode["value"]))
            modes.append({**mode, "title": title or node.title, "title_ru": title_ru or node.title_ru})
        sections.append({key: section[key] for key in ("id", *SECTION_TEXTS, "op", "mode_field", "blocks_last")} | {"modes": modes})
    return {"sections": sections, "service": told["service"], "details": told["details"], "own": told["own"], "buttons": told["buttons"],
            "paste": told["paste"]}
