"""The forms of the window, held while the window is open: `media_cli.cmd form`.

The window draws the forms and runs nothing itself, and the rules of a form - what a preset writes, which
choice is off, what a click pulls along with it - live in one place, operation_model.Form, held to the record of
the former window. So the window keeps this process open and asks it: a page opened, a control used, the folders
changed; it answers with the form as it stands. One JSON object a line, each way.

A page is a section and a mode of the ribbon (config\\window_layout.yaml): every page has a form of its own (the
owner, 15.10.2026: "формы раздельные"), and a mode that is a choice of a field is that field set on it. The fields
of the machine - the encoder and the decoder - are one for every page: set on one, they are set on all.

The state of a page:

  values   every field of the form with the value it has now
  shown    the fields in sight, in the order of the form
  blocks   the fields in sight by the blocks of the form, as the former window drew them: name, advanced, fields
  choices  for every field in sight with choices: [value, off] each, and the label of a choice the engine made
           (the LUTs of the folder, the takes of a trim)
  presets  the preset of every preset field that stands on
  pinned   the pinned LUTs of a LUT field
  gamma    of a colour operation: where its gamma before the LUT takes 18% gray (operation_model.gamma_preview)
  refusal  why the form may not be run now; "" when it may
  set      the values a person would type: what differs from the form as it opened, the mode always

A trim page answers two questions more: `take` - the file it points at, for the rows and the player - and `probe` -
what ffprobe knows of that file. A page with a LUT field pins a LUT (`lut_pin`) and copies LUT files into LUTs\\ of the
program (`lut_add`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import operation_model as model
from .path_cache import OUTPUT_ENV, SOURCE_ENV

# One value for the whole window: the machine, not the task.
SHARED = frozenset({"encode_backend", "decode_backend"})


class Page:
    def __init__(self, node: Any, root: Path, mode: dict[str, Any] | None) -> None:
        self.node = node
        self.root = root
        self.mode = mode or {}
        self.form = self.fresh()
        # What the page is when nobody has touched it: what the line of the journal is counted from.
        self.baseline = dict(self.form.values)

    def fresh(self) -> model.Form:
        form = model.Form(self.node, self.root, os.environ.get(SOURCE_ENV) or None, os.environ.get(OUTPUT_ENV) or None).open()
        if self.mode.get("field"):
            field = form.field(str(self.mode["field"]))
            form.click(model.action_of(field), str(self.mode["field"]), self.mode.get("value"))
        return form

    def mode_field(self) -> str:
        return str(self.mode.get("field") or "")


def as_text(value: Any) -> str:
    """A value as `--set` takes it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        return ",".join(str(item) for item in value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "" if value is None else str(value)


class Pages:
    def __init__(self, root: Path, manifest: Any, language: str = "en") -> None:
        self.root = Path(root)
        self.manifest = manifest
        self.language = model.safe_language(language)
        self.pages: dict[str, Page] = {}

    # ---- the answers ------------------------------------------------------------------------------
    def state(self, key: str) -> dict[str, Any]:
        page = self.pages[key]
        form = page.form
        fields = model.form_fields(page.node)
        shown = [field for field in fields if form.visible(field) and model.field_id(field) != page.mode_field()]
        choices: dict[str, list[list[Any]]] = {}
        presets: dict[str, str] = {}
        pinned: dict[str, list[str]] = {}
        for field in shown:
            kind, key_of = model.field_kind(field), model.field_id(field)
            if kind in model.PRESET_BUTTONS | model.PRESET_LISTS:
                presets[key_of] = form.current_preset(field)
                continue
            if kind in model.LUT_PICKS:
                # The LUTs as the window on NiceGUI listed them: the pinned first, the chosen one, the recent ones, the rest
                # of LUTs\, by their names within it; the one in the form among them even when it lies elsewhere.
                from .lut_cache import listed_luts, pinned_luts

                choices[key_of] = [[path, False, name] for path, name in listed_luts(page.root, str(form.values.get(key_of) or ""))]
                pinned[key_of] = pinned_luts(page.root)
                continue
            options = form.options(field)
            if not options:
                continue
            made = bool(field.get("options_source") or field.get("source"))
            told = []
            for option in options:
                if not form.option_visible(option):
                    continue
                entry: list[Any] = [model.option_value(option), form.option_disabled(option)]
                if made:
                    entry.append(str(option.get("label") or model.option_value(option)) if isinstance(option, dict) else str(option))
                told.append(entry)
            choices[key_of] = told
        # The blocks of the form in the order the former window drew them: the usual fields, then the rare ones.
        blocks = [{"name": name, "advanced": rare, "fields": [model.field_id(field) for field in block]}
                  for rare in (False, True)
                  for name, block in model.sections([field for field in shown if model.is_advanced(field) == rare])]
        values = {model.field_id(field): form.values.get(model.field_id(field), model.field_default(field)) for field in fields}
        typed = {name: as_text(value) for name, value in values.items()
                 if name == page.mode_field() or page.baseline.get(name, model.field_default(form.field(name))) != value}
        told = {"page": key, "operation": page.node.id, "values": values, "shown": [model.field_id(field) for field in shown],
                "blocks": blocks, "choices": choices, "presets": presets, "pinned": pinned, "refusal": form.refusal(self.language), "set": typed}
        # A colour operation: where its gamma before the LUT takes 18% gray, for the swatches under the colour block.
        if any(model.field_id(field) == "script_preset" for field in fields):
            told["gamma"] = model.gamma_preview(values, page.root)
        return told

    # ---- the questions ----------------------------------------------------------------------------
    def open(self, key: str, operation: str, mode: dict[str, Any] | None, values: dict[str, Any] | None) -> dict[str, Any]:
        node = model.find_node(self.manifest, operation)
        if node is None:
            raise ValueError(f"the manifest has no operation {operation!r}")
        page = Page(node, self.root, mode)
        self.pages[key] = page
        if values:
            known = {model.field_id(field) for field in model.form_fields(node)}
            kept = {name: value for name, value in values.items() if name in known and name != page.mode_field()}
            if kept:
                page.form.fill(kept)
        return self.state(key)

    def click(self, key: str, action: str, field: str, value: Any) -> dict[str, Any]:
        page = self.pages[key]
        page.form.click(action, field, value)
        if action == "lut":
            # A LUT chosen is the chosen and the most recent one of the list (config\gui_lut_cache.json), as the window had it.
            from .lut_cache import update_lut_cache

            update_lut_cache(page.root, str(page.form.values.get(field) or value))
        # What the window shows is what would run: the form drawn after every control, as a run fills it.
        page.form.draw()
        if field in SHARED:
            for other_key, other in self.pages.items():
                if other_key != key and other.form.field(field):
                    other.form.click(action, field, value)
                    other.form.draw()
        return self.state(key)

    def reset(self, key: str) -> dict[str, Any]:
        page = self.pages[key]
        shared = {name: page.form.values[name] for name in SHARED if name in page.form.values}
        page.form = page.fresh()
        for name, value in shared.items():
            page.form.click(model.action_of(page.form.field(name)), name, value)
        page.form.draw()
        return self.state(key)

    def folders(self, source: str, target: str) -> dict[str, Any]:
        """The Source and the Target the window points at: the takes of a trim and the LUTs are read anew."""
        for name, value in ((SOURCE_ENV, source), (OUTPUT_ENV, target)):
            if value:
                os.environ[name] = value
        for page in self.pages.values():
            page.form.source = Path(source) if source else page.form.source
            page.form.target = Path(target) if target else page.form.target
            page.form.draw()
        return {"folders": {"source": source, "target": target}}

    def take(self, key: str) -> dict[str, Any]:
        """The take a trim page points at: what the window needs to draw its rows and to show it in the player.

        name and path of the file ("" when Source holds no take), its kind (audio or video), how long it plays and how
        long a frame of it lasts - the step of the last section of a point; null for a sound file, which steps by the
        millisecond - and the names of every take, in the order the arrows walk them.
        """
        from system_core.services import media_service as media

        form = self.pages[key].form
        name = str(form.values.get("trim_file") or "")
        path = media.trim_source_path(name, self.root) if name else None
        return {"take": {
            "name": name if path else "",
            "path": str(path) if path else "",
            "kind": media.trim_media_kind(name) if name else "video",
            "seconds": media.trim_file_seconds(name, self.root) if path else None,
            "frame": media.trim_file_frame_seconds(name, self.root) if path else None,
            "names": form.trim_names(),
        }}

    def probe(self, key: str) -> dict[str, Any]:
        """What ffprobe knows of the take of a trim page, as rows of a table."""
        from system_core.services import media_service as media

        return {"probe": media.trim_probe_table(str(self.pages[key].form.values.get("trim_file") or ""), self.root)}

    def lut_pin(self, key: str, value: str, pinned: bool) -> dict[str, Any]:
        """A LUT pinned stands first in every list of LUTs; let go, it takes its place again."""
        from .lut_cache import update_lut_cache

        page = self.pages[key]
        current = str(next((page.form.values.get(model.field_id(field)) for field in model.form_fields(page.node)
                            if model.field_kind(field) in model.LUT_PICKS), "") or "")
        update_lut_cache(page.root, value, pinned=pinned)
        # A pin is no choice: the LUT the form holds stays the chosen one.
        if current:
            update_lut_cache(page.root, current)
        return self.state(key)

    def lut_add(self, key: str, field: str, files: list[str], folder: str) -> dict[str, Any]:
        """LUT files or a folder of them copied into LUTs\\ of the program; the first of them is chosen."""
        from .lut_cache import import_luts, update_lut_cache

        page = self.pages[key]
        added = import_luts(page.root, files, folder)
        for path in reversed(added):
            update_lut_cache(page.root, str(path))
        if added:
            return {**self.click(key, "lut", field, str(added[0])), "added": len(added)}
        return {**self.state(key), "added": 0}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        do = str(request.get("do") or "")
        key = str(request.get("page") or "")
        if "language" in request:
            self.language = model.safe_language(str(request.get("language")))
        if do == "open":
            return self.open(key, str(request.get("operation") or ""), request.get("mode"), request.get("values"))
        if key not in self.pages and do in {"click", "reset", "state", "take", "probe", "lut_pin", "lut_add"}:
            raise ValueError(f"no page {key!r} is open")
        if do == "click":
            return self.click(key, str(request.get("action") or ""), str(request.get("field") or ""), request.get("value"))
        if do == "reset":
            return self.reset(key)
        if do == "state":
            return self.state(key)
        if do == "folders":
            return self.folders(str(request.get("source") or ""), str(request.get("target") or ""))
        if do == "take":
            return self.take(key)
        if do == "probe":
            return self.probe(key)
        if do == "lut_pin":
            return self.lut_pin(key, str(request.get("value") or ""), bool(request.get("pinned")))
        if do == "lut_add":
            files = request.get("files")
            return self.lut_add(key, str(request.get("field") or ""), [str(item) for item in files] if isinstance(files, list) else [],
                                str(request.get("folder") or ""))
        if do == "language":
            return {"language": self.language}
        raise ValueError(f"unknown request {do!r}")


def serve(pages: Pages, read, write) -> None:
    """Lines in, lines out, until the window closes its end. A request that fails is answered with why."""
    for line in iter(read, ""):
        line = line.strip()
        if not line:
            continue
        ident: Any = None
        try:
            request = json.loads(line)
            ident = request.get("id")
            answer = {"id": ident, "ok": True, **pages.handle(request)}
        except Exception as error:  # noqa: BLE001 - the window is told, the process goes on
            answer = {"id": ident, "ok": False, "error": f"{type(error).__name__}: {error}"}
        write(json.dumps(answer, ensure_ascii=False, default=str) + "\n")
