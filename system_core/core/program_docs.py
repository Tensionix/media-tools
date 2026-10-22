"""The reference part of the documents, made from the map of the program (core\\program_map.py): `media_cli.cmd map --docs`.

Nothing here is written from memory of the code. The sections and their modes come from the layout of the window, the
operations, fields, choices and presets with their tooltips from the manifest, the wrappers from config\\wrappers.yaml - so
the window, the console command and the documents say one thing.

    Docs\\OPERATIONS_RU.md, _EN.md   section -> operation -> presets and fields, the call of the console command, the wrappers
    Docs\\SCRIPTS_RU.md, _EN.md      the 95 wrappers of Scripts\\: what each does and the same through the console command
    blocks of written documents     a table between <!-- map:NAME --> and <!-- /map -->; the text around them is the person's

A document is written only when its text changed; `check` says which are out of date without writing them.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .program_map import as_text

GENERATED = {
    "en": "Made from the data of the program by `media_cli.cmd map --docs`: the manifest of the operations "
          "(`config\\tool_manifest.yaml`), the layout of the window (`config\\window_layout.yaml`) and the table of the "
          "wrappers (`config\\wrappers.yaml`). It is not edited by hand: a text is changed there and the command is run again.",
    "ru": "Собрано из данных программы командой `media_cli.cmd map --docs`: манифест операций (`config\\tool_manifest.yaml`), "
          "раскладка окна (`config\\window_layout.yaml`) и таблица обёрток (`config\\wrappers.yaml`). Руками не правится: текст "
          "меняется там, и команда запускается снова.",
}

WORDS = {
    "en": {
        "operations": "Operations", "scripts": "Wrappers of Scripts", "modes": "Modes of the ribbon", "call": "Call",
        "wrappers": "Wrappers", "presets": "Presets", "fields": "Fields", "field": "Field", "kind": "Kind",
        "default": "Default", "choices": "Choices", "when": "When", "about": "What it is", "preset": "Preset",
        "sets": "What it sets", "service": "SERVICE: checks and installers", "details": "SOURCE INFO",
        "buttons": "Buttons beside a field", "own": "What the window does itself", "beside": "Beside", "runs": "Runs",
        "operation": "Operation", "takes": "Takes", "wrapper": "Wrapper", "same": "The same through the console command",
        "environment": "Environment variables the wrappers read", "names": "Variables", "advanced": "rare",
        "own_text": "The window clears the working folders through the Recycle Bin; the console command does not run these "
                    "operations, they delete for good.",
        "scripts_intro": "Every wrapper is a door of `media_cli.cmd wrapper NAME`: a file of its own name that runs one or "
                         "more operations of the program with the values written for it. The environment variables of the "
                         "table at the end are read by the wrappers as they always were.",
        "rare_note": "*rare* - a field of the block «Additional», at the end of the form.",
    },
    "ru": {
        "operations": "Операции", "scripts": "Обёртки Scripts", "modes": "Режимы ленты", "call": "Вызов",
        "wrappers": "Обёртки", "presets": "Пресеты", "fields": "Поля", "field": "Поле", "kind": "Вид",
        "default": "По умолчанию", "choices": "Варианты", "when": "Когда", "about": "Что это", "preset": "Пресет",
        "sets": "Что ставит", "service": "СЕРВИС: проверки и установка", "details": "СВЕДЕНИЯ",
        "buttons": "Кнопки у полей", "own": "Что окно делает само", "beside": "Рядом с полем", "runs": "Запуски",
        "operation": "Операция", "takes": "Принимает", "wrapper": "Обёртка", "same": "То же через консольную команду",
        "environment": "Переменные среды, которые читают обёртки", "names": "Переменные", "advanced": "редкое",
        "own_text": "Рабочие папки окно очищает само, через Корзину; консольная команда эти операции не запускает - они "
                    "удаляют насовсем.",
        "scripts_intro": "Каждая обёртка - дверь `media_cli.cmd wrapper ИМЯ`: файл со своим именем, который запускает одну "
                         "или несколько операций программы с записанными для неё значениями. Переменные среды из таблицы в "
                         "конце обёртки читают, как читали всегда.",
        "rare_note": "*редкое* - поле блока «Дополнительно», в конце формы.",
    },
}

KINDS = {
    "en": {"radio": "choice", "select": "choice", "remux_format": "container", "checkboxes": "ticks", "checkbox": "tick",
           "text": "text", "timecode": "timecode", "file": "file", "number": "number", "int": "number", "integer": "number", "float": "number",
           "profile_buttons": "presets", "profile_select": "presets", "preset_buttons": "presets", "lut_select": "LUT",
           "trim_file": "file of the trim", "trim_variants": "pieces of the trim", "trim_points": "points of a split",
           "trim_player": "player"},
    "ru": {"radio": "выбор", "select": "выбор", "remux_format": "контейнер", "checkboxes": "флажки", "checkbox": "флажок",
           "text": "текст", "timecode": "таймкод", "file": "файл", "number": "число", "int": "число", "integer": "число", "float": "число",
           "profile_buttons": "пресеты", "profile_select": "пресеты", "preset_buttons": "пресеты", "lut_select": "LUT",
           "trim_file": "файл нарезки", "trim_variants": "куски нарезки", "trim_points": "точки разделения",
           "trim_player": "плеер"},
}


def _pick(item: dict[str, Any], key: str, language: str) -> str:
    """The text of a key in the language, the other language when it has none."""
    if language == "ru":
        return str(item.get(f"{key}_ru") or item.get(key) or "")
    return str(item.get(key) or item.get(f"{key}_ru") or "")


def _cell(text: Any) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _value(value: Any) -> str:
    text = as_text(value)
    return f"`{text}`" if text else "-"


def _tip(field: dict[str, Any], language: str) -> str:
    return _pick(field, "tooltip", language) or _pick(field, "hint", language) or _pick(field, "description", language)


def _field_rows(field: dict[str, Any], language: str) -> str:
    words = WORDS[language]
    name = _pick(field, "label", language) or field["id"]
    if field.get("advanced"):
        name += f" ({words['advanced']})"
    kind = KINDS[language].get(str(field.get("kind")), str(field.get("kind")))
    choices = "; ".join(f"`{as_text(option['value']) or chr(34) * 2}` {_pick(option, 'label', language)}".strip()
                        + (f" ({_pick(option, 'when', language)})" if _pick(option, "when", language) else "")
                        for option in field.get("options") or [])
    return (f"| {_cell(name)} `{field['id']}` | {_cell(kind)} | {_cell(_value(field.get('default')))} | {_cell(choices) or '-'} | "
            f"{_cell(_pick(field, 'when', language)) or '-'} | {_cell(_tip(field, language)) or '-'} |")


def _preset_rows(field: dict[str, Any], language: str) -> list[str]:
    rows = []
    for preset in field.get("presets") or []:
        sets = ", ".join(f"{key}={as_text(value)}" for key, value in (preset.get("values") or {}).items())
        rows.append(f"| `{preset['id']}` {_cell(_pick(preset, 'label', language))} | {_cell(_pick(preset, 'description', language)) or '-'} | "
                     f"{_cell(sets) or '-'} |")
    return rows


def _operation(lines: list[str], operation: dict[str, Any], language: str, mode: tuple[str, list[dict[str, Any]]] | None,
               level: str = "###") -> None:
    words = WORDS[language]
    lines += [f"{level} {_pick(operation, 'title', language)} - `{operation['id']}`", ""]
    about = _pick(operation, "description", language)
    if about:
        lines += [about, ""]
    lines += [f"{words['call']}: `{operation['call']}`"]
    if mode:
        field, modes = mode
        listed = ", ".join(f"{_pick(item, 'title', language)} `{field}={as_text(item.get('value'))}`" for item in modes)
        lines += ["", f"{words['modes']}: {listed}."]
    if operation.get("wrappers"):
        names = ", ".join(f"`{name}`" for name in operation["wrappers"])
        lines += ["", f"{words['wrappers']}: {names}."]
    lines.append("")
    mode_field = mode[0] if mode else ""
    fields = [field for field in operation.get("fields") or [] if not field.get("hidden") and field["id"] != mode_field]
    for field in fields:
        if field.get("presets"):
            lines += [f"**{words['presets']}** - {_cell(_pick(field, 'label', language))} `{field['id']}`", "",
                      f"| {words['preset']} | {words['about']} | {words['sets']} |", "|---|---|---|", *_preset_rows(field, language), ""]
    plain = [field for field in fields if not field.get("presets")]
    if plain:
        lines += [f"**{words['fields']}**", "",
                  f"| {words['field']} | {words['kind']} | {words['default']} | {words['choices']} | {words['when']} | {words['about']} |",
                  "|---|---|---|---|---|---|", *(_field_rows(field, language) for field in plain), ""]


def operations_doc(told: dict[str, Any], language: str) -> str:
    words = WORDS[language]
    other = "OPERATIONS_EN.md" if language == "ru" else "OPERATIONS_RU.md"
    other_word = "English" if language == "ru" else "Русский"
    scripts = f"SCRIPTS_{language.upper()}.md"
    lines = [f"# {told['program']['name']} - {words['operations'].lower() if language == 'ru' else words['operations']}", "",
             f"[{other_word}]({other}) · [{words['scripts']}]({scripts})", "", f"> {GENERATED[language]}", "",
             words["rare_note"], ""]
    operations = told["operations"]
    done: set[str] = set()
    for section in told["sections"]:
        lines += [f"## {_pick(section, 'title', language)} - {_pick(section, 'about', language)}", ""]
        field = section.get("mode_field") or ""
        if field:
            operation = operations[section["op"]]
            modes = [mode for mode in section["modes"] if mode.get("field")]
            _operation(lines, operation, language, (field, modes))
            done.add(operation["id"])
        for mode in section["modes"]:
            if mode.get("field"):
                continue
            if mode["op"] not in done:
                _operation(lines, operations[mode["op"]], language, None)
                done.add(mode["op"])
    for title_key, ids in (("details", told.get("details") or []), ("service", told.get("service") or [])):
        lines += [f"## {words[title_key]}", ""]
        for operation_id in ids:
            _operation(lines, operations[operation_id], language, None)
            done.add(operation_id)
    buttons = told.get("buttons") or []
    if buttons:
        lines += [f"## {words['buttons']}", ""]
        for button in buttons:
            operation = operations[button["op"]]
            lines += [f"### {_pick(operation, 'title', language)} - `{operation['id']}`", "",
                      _pick(operation, "description", language), "",
                      f"{words['beside']}: `{button['beside']}`. {words['call']}: `{operation['call']}`.", ""]
            done.add(operation["id"])
    own = told.get("own") or []
    if own:
        lines += [f"## {words['own']}", "", words["own_text"], ""]
        lines += [f"- {_pick(operations[item], 'title', language)} - `{item}`" for item in own if item in operations]
        lines.append("")
        done.update(own)
    rest = [operation_id for operation_id in operations if operation_id not in done]
    if rest:
        lines += [f"## {words['operations']}", ""]
        for operation_id in rest:
            _operation(lines, operations[operation_id], language, None)
    return "\n".join(lines).rstrip() + "\n"


def scripts_doc(told: dict[str, Any], language: str) -> str:
    words = WORDS[language]
    other = "SCRIPTS_EN.md" if language == "ru" else "SCRIPTS_RU.md"
    other_word = "English" if language == "ru" else "Русский"
    lines = [f"# {told['program']['name']} - {'обёртки Scripts' if language == 'ru' else words['scripts']}", "",
             f"[{other_word}]({other}) · [{words['operations']}](OPERATIONS_{language.upper()}.md)", "", f"> {GENERATED[language]}", "",
             words["scripts_intro"], "",
             f"| {words['wrapper']} | {words['about']} | {words['takes']} | {words['same']} |", "|---|---|---|---|"]
    for name, entry in told["wrappers"].items():
        runs = "<br>".join(f"`{_cell(call)}`" for call in entry.get("as_runs") or [])
        lines.append(f"| `{name}` | {_cell(_pick(entry, 'about', language)) or '-'} | {_cell(entry.get('takes') or '-')} | {runs or '-'} |")
    environment = told.get("environment") or {}
    if environment:
        lines += ["", f"## {words['environment']}", "", f"| {words['field']} | {words['names']} |", "|---|---|"]
        lines += [f"| `{field}` | {', '.join(f'`{name}`' for name in names)} |" for field, names in sorted(environment.items())]
    return "\n".join(lines).rstrip() + "\n"


def blocks(told: dict[str, Any], language: str) -> dict[str, str]:
    """The tables that stand in written documents between <!-- map:NAME --> and <!-- /map -->."""
    words = WORDS[language]
    operations = told["operations"]
    rows = [f"| {'Раздел' if language == 'ru' else 'Section'} | {'Режим' if language == 'ru' else 'Mode'} | {words['call']} |",
            "|---|---|---|"]
    for section in told["sections"]:
        for mode in section["modes"]:
            call = operations[mode["op"]]["call"]
            if mode.get("field"):
                call += f" --set {mode['field']}={as_text(mode.get('value'))}"
            rows.append(f"| {_pick(section, 'title', language)} | {_pick(mode, 'title', language)} | `{call}` |")
    service = [f"| {words['operation']} | {words['about']} |", "|---|---|"]
    for operation_id in [*(told.get("details") or []), *(told.get("service") or []), *[button["op"] for button in told.get("buttons") or []]]:
        operation = operations[operation_id]
        service.append(f"| `{operation_id}` | {_cell(_pick(operation, 'title', language))}: {_cell(_pick(operation, 'description', language))} |")
    return {"sections": "\n".join(rows), "service": "\n".join(service)}


BLOCK = re.compile(r"(<!-- map:(?P<name>[\w-]+) -->\n)(?P<body>.*?)(<!-- /map -->)", re.S)


def fill(text: str, made: dict[str, str]) -> str:
    """The blocks of a written document filled anew; an unknown block name is left as it is."""
    return BLOCK.sub(lambda match: match.group(1) + made.get(match.group("name"), match.group("body").rstrip("\n")) + "\n" + match.group(4)
                     if match.group("name") in made else match.group(0), text)


WRITTEN = {"SKILL.md": "en", "Docs/AI_AGENT_GUIDE_EN.md": "en", "Docs/AI_AGENT_GUIDE_RU.md": "ru", "Docs/CLI_EN.md": "en",
           "Docs/CLI_RU.md": "ru"}


def documents(told: dict[str, Any], root: Path) -> dict[Path, str]:
    """Every document the map makes or fills, with its text as it should be."""
    docs = Path(root) / "Docs"
    made: dict[Path, str] = {}
    for language in ("ru", "en"):
        made[docs / f"OPERATIONS_{language.upper()}.md"] = operations_doc(told, language)
        made[docs / f"SCRIPTS_{language.upper()}.md"] = scripts_doc(told, language)
    for name, language in WRITTEN.items():
        path = Path(root) / name
        if path.is_file():
            text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
            made[path] = fill(text, blocks(told, language))
    return made


def stale(told: dict[str, Any], root: Path) -> list[Path]:
    """The documents whose text is not what the map makes."""
    return [path for path, text in documents(told, root).items()
            if not path.is_file() or path.read_bytes().decode("utf-8").replace("\r\n", "\n") != text]


def write(told: dict[str, Any], root: Path) -> list[Path]:
    """The documents out of date written anew - UTF-8 without BOM, with the line endings the file had (LF for a new one);
    the rest left alone."""
    made = documents(told, root)
    written = []
    for path in stale(told, root):
        crlf = path.is_file() and b"\r\n" in path.read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = made[path]
        path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
        written.append(path)
    return written
