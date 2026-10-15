"""The map of the program, from its data alone.

The sections and modes of the window, every operation with its fields, choices and presets and their texts in both
languages, the conditions a field is shown under in words, the wrappers of Scripts\\ with the call of the console
command each makes, the environment they read. `media_cli.cmd map` writes it; the documents of the program are built
from it, never from a memory of the code (the owner, 15.10.2026: "генерацию документов программы не вспоминая код").
What has no text in one of the two languages is named in `missing`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import operation_model as model
from . import window_layout
from .config import load_yaml_or_json

WORDS = {
    "en": {"is": "is", "one_of": "is one of", "not": "not", "all": "all of", "any": "any of", "and": " and ", "set": "is set",
           "empty": "is empty", "on": "is on", "off": "is off", "shown": "shown when", "hidden": "hidden when",
           "disabled": "not offered when", "offered": "offered only when"},
    "ru": {"is": "=", "one_of": "- одно из", "not": "не", "all": "все из", "any": "любое из", "and": " и ", "set": "задано",
           "empty": "пусто", "on": "включено", "off": "выключено", "shown": "видно, когда", "hidden": "скрыто, когда",
           "disabled": "недоступно, когда", "offered": "доступно, только когда"},
}
# A condition of the manifest and the words it is told in: (its keys, the word that begins it).
CONDITION_KINDS = ((("visible_if", "show_if"), "shown"), (("hidden_if", "hide_if"), "hidden"),
                   (("disabled_if", "disable_if"), "disabled"), (("enabled_if", "enable_if"), "offered"))


def _value_words(key: str, expected: Any, language: str) -> str:
    words = WORDS[language]
    if isinstance(expected, dict):
        if "not" in expected:
            return f"{words['not']} ({_value_words(key, expected['not'], language)})"
        if "neq" in expected:
            return f"{words['not']} ({_value_words(key, expected['neq'], language)})"
        if "in" in expected:
            return _value_words(key, expected["in"], language)
        if "exists" in expected:
            return f"{key} {words['set'] if expected['exists'] else words['empty']}"
    if isinstance(expected, (list, tuple, set)):
        return f"{key} {words['one_of']} {', '.join(str(item) for item in expected)}"
    if isinstance(expected, bool):
        return f"{key} {words['on'] if expected else words['off']}"
    return f"{key} {words['is']} {expected}"


def condition_words(condition: Any, language: str = "en") -> str:
    """A condition of the manifest told in words - the grammar Form.holds reads."""
    words = WORDS[language]
    if not condition:
        return ""
    if isinstance(condition, (list, tuple)):
        return words["and"].join(condition_words(item, language) for item in condition)
    if not isinstance(condition, dict):
        return str(condition)
    if "all" in condition:
        return f"{words['all']} ({'; '.join(condition_words(item, language) for item in condition.get('all') or [])})"
    if "any" in condition:
        return f"{words['any']} ({'; '.join(condition_words(item, language) for item in condition.get('any') or [])})"
    if "not" in condition:
        return f"{words['not']} ({condition_words(condition['not'], language)})"
    return words["and"].join(_value_words(str(key), expected, language) for key, expected in condition.items())


def _when(item: dict[str, Any]) -> dict[str, str]:
    """When a field or a choice is shown or offered, in both languages; nothing when always."""
    told: dict[str, str] = {}
    for language in ("en", "ru"):
        parts = []
        for keys, word in CONDITION_KINDS:
            condition = next((item[key] for key in keys if item.get(key)), None)
            if condition:
                parts.append(f"{WORDS[language][word]} {condition_words(condition, language)}")
        if parts:
            told["when" if language == "en" else "when_ru"] = "; ".join(parts)
    return told


def load_wrappers(config: Path) -> dict[str, Any]:
    raw = load_yaml_or_json(Path(config) / "wrappers.yaml")
    return dict(raw.get("wrappers") or {}) if isinstance(raw, dict) else {}


def wrapper_runs(entry: dict[str, Any]) -> list[dict[str, Any]]:
    if entry.get("runs"):
        return [dict(run) for run in entry["runs"]]
    return [{"op": entry.get("op"), "set": dict(entry.get("set") or {}), "fixed": dict(entry.get("fixed") or {}),
             "only": entry.get("only") or []}]


def as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def run_call(run: dict[str, Any]) -> str:
    """One run of a wrapper as the console command is called for it."""
    values = {**(run.get("set") or {}), **(run.get("fixed") or {})}
    parts = ["media_cli.cmd", "run", "--operation", str(run.get("op"))]
    for key, value in values.items():
        text = as_text(value)
        parts += ["--set", f'"{key}={text}"' if not text or any(char in text for char in ' &*') else f"{key}={text}"]
    if run.get("only"):
        parts += ["--only", as_text(run["only"])]
    return " ".join(parts)


def _missing_pair(where: str, item: dict[str, Any], english: str, russian: str) -> list[str]:
    has_en, has_ru = bool(str(item.get(english) or "").strip()), bool(str(item.get(russian) or "").strip())
    if has_en and has_ru:
        return []
    return [f"{where}: {english if not has_en else russian}"] if has_en or has_ru else [f"{where}: {english}, {russian}"]


def build(paths: Any, manifest: Any, *, version: str = "", environment: dict[str, tuple[str, ...]] | None = None) -> dict[str, Any]:
    described = model.describe(manifest)
    layout = window_layout.for_window(window_layout.load(paths.config), manifest)
    wrappers = load_wrappers(paths.config)
    by_operation: dict[str, list[str]] = {}
    for name, entry in sorted(wrappers.items()):
        for run in wrapper_runs(entry):
            names = by_operation.setdefault(str(run.get("op")), [])
            if name not in names:
                names.append(name)

    missing: list[str] = []
    for section in layout["sections"]:
        where = f"section {section['id']}"
        missing += _missing_pair(where, section, "title", "title_ru") + _missing_pair(where, section, "about", "about_ru")
        for mode in section["modes"]:
            missing += _missing_pair(f"{where}, mode {mode.get('value') or mode['op']}", mode, "title", "title_ru")

    operations: dict[str, Any] = {}
    for operation_id, node in described["operations"].items():
        told = dict(node)
        where = f"operation {operation_id}"
        missing += _missing_pair(where, told, "title", "title_ru") + _missing_pair(where, told, "description", "description_ru")
        fields = []
        for field in told["fields"]:
            field = {**field, **_when(field)}
            spot = f"{where}, field {field['id']}"
            if not field.get("hidden"):
                missing += _missing_pair(spot, field, "label", "label_ru")
                if not any(field.get(key) for key in ("tooltip", "tooltip_ru", "hint", "hint_ru")):
                    missing.append(f"{spot}: tooltip, tooltip_ru")
                else:
                    for english, russian in (("tooltip", "tooltip_ru"), ("hint", "hint_ru")):
                        if field.get(english) or field.get(russian):
                            missing += _missing_pair(spot, field, english, russian)
            if "options" in field:
                field["options"] = [{**option, **_when(option)} for option in field["options"]]
                for option in field["options"]:
                    for english, russian in (("tooltip", "tooltip_ru"), ("description", "description_ru"), ("hint", "hint_ru")):
                        if option.get(english) or option.get(russian):
                            missing += _missing_pair(f"{spot}, choice {option['value']}", option, english, russian)
            if "presets" in field:
                field["presets"] = [{**preset, **_when(preset)} for preset in field["presets"]]
                for preset in field["presets"]:
                    pin = f"{spot}, preset {preset['id']}"
                    missing += _missing_pair(pin, preset, "label", "label_ru") + _missing_pair(pin, preset, "description", "description_ru")
            fields.append(field)
        told["fields"] = fields
        told["call"] = f"media_cli.cmd run --operation {operation_id}"
        told["wrappers"] = by_operation.get(operation_id, [])
        operations[operation_id] = told

    told_wrappers: dict[str, Any] = {}
    for name, entry in sorted(wrappers.items()):
        runs = wrapper_runs(entry)
        missing += _missing_pair(f"wrapper {name}", entry, "about", "about_ru")
        missing += [f"wrapper {name}: no operation {run.get('op')!r}" for run in runs if str(run.get("op")) not in operations]
        told_wrappers[name] = {
            "about": entry.get("about", ""), "about_ru": entry.get("about_ru", ""), "takes": entry.get("takes", ""),
            "runs": [{"op": run.get("op"), "set": run.get("set") or {}, "fixed": run.get("fixed") or {}, "only": run.get("only") or []}
                     for run in runs],
            "file": f"Scripts\\{name}.cmd", "call": f"media_cli.cmd wrapper {name}", "as_runs": [run_call(run) for run in runs],
        }

    # The groups of the manifest - the sections of the former window; the ribbon of window_layout.yaml stands in their place,
    # their texts head the operations in the documents.
    groups = []
    for group in manifest.operation_groups:
        leaves = [node.id for node in model.iter_nodes([group]) if node.id in operations]
        groups.append({"id": group.id, "title": group.title, "title_ru": group.title_ru, "description": group.description,
                       "description_ru": group.description_ru, "operations": leaves})
        missing += _missing_pair(f"group {group.id}", groups[-1], "title", "title_ru")

    tool = described.get("tool", {})
    return {
        "program": {"id": tool.get("id", ""), "name": tool.get("name", ""), "version": version},
        "sections": layout["sections"], "service": layout["service"], "details": layout["details"], "own": layout["own"],
        "buttons": layout["buttons"], "paste": layout["paste"],
        "groups": groups, "operations": operations, "wrappers": told_wrappers,
        "environment": {field: list(names) for field, names in (environment or {}).items()},
        "missing": missing,
    }
