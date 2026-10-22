"""How the form of an operation becomes what the operation is run with.

One copy of the rules. Until 3.0.0 they lived in the window on NiceGUI (ui_nicegui\\app.py), and an
operation could be run "as the window runs it" only from the window. They are taken from there as they
were and held to a record of what that window did: tests\\former_window_parameters.json, 1206 states of
the forms of 18 operations, each with the clicks that led to it.

The window changed a form in two places, and both are here:

- on a click: a preset writes its values; MXF pulls the sound to PCM 24 and MOV takes FLAC to PCM 24;
  MP3 brings 384k down to 320k; a stream mode of a remux restores its targets; a colour script sets its
  gamma;
- while it drew a panel: every field shown took its default; a preset not yet applied wrote its values
  (a preset list - not its ticks and lists); a switch on a choice that is off or gone moved to the first
  one allowed; a row of ticks kept what may be ticked, in the order of its options; the LUT and the take
  of a trim were picked from their folders.

A `Form` goes through the same steps: `open` draws the panel, `click` does what the control did and draws
again when the window did. The console command fills a form the same way - the presets first, then every
value given - and runs what it holds.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Iterable

# The fields that are not of a form: the window keeps the Source and the Target beside the journal.
ROUTE_FIELDS = frozenset({
    "source", "source_dir", "source_path", "source_folder", "source_file", "input", "input_dir", "input_path",
    "input_folder", "destination", "destination_dir", "destination_path", "output", "output_dir", "output_path",
    "output_folder",
})
ROUTE_ROLES = frozenset({"source", "target", "destination", "output", "input"})
TARGET_ROLES = frozenset({"target", "destination", "output"})

PRESET_BUTTONS = frozenset({"preset_buttons", "presets", "profile_buttons", "profiles"})
PRESET_LISTS = frozenset({"profile_select", "profile-select", "preset_select", "preset-select"})
LUT_PICKS = frozenset({"lut_select", "lut-select"})
REMUX_TARGETS = frozenset({"remux_format", "remux-format"})
SWITCHES = frozenset({"radio", "radiobuttons", "radio-buttons"})
LISTS = frozenset({"select", "choice", "format"})
NUMBERS = frozenset({"number", "int", "integer", "float"})
TICKS = frozenset({"checkbox", "bool", "boolean", "toggle"})
TICK_ROWS = frozenset({"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"})
TRIM_TAKES = frozenset({"trim_file_pick", "file_badge"})
SEGMENTED = frozenset({"segmented", "tabs", "buttons", "button-toggle", "button_toggle"})

# A section of the panel for a field without a `group` of its own, as the window sorted them.
SECTION_OF_KEY = {
    **dict.fromkeys(("youtube_url", "batch_file", "youtube_source_mode", "input_formats"), "source"),
    "target_codecs": "codecs",
    **dict.fromkeys(("encode_backend", "backend"), "backend"),
    **dict.fromkeys(("decode_backend", "decode_stack", "decode_hw"), "decode"),
    **dict.fromkeys(("audio_mode", "audio_bitrate", "audio_format", "audio_sample_rate", "audio_bit_depth", "audio_lufs",
                     "downmix_stereo", "matrix_51", "mp3_lame_preset"), "audio"),
    **dict.fromkeys(("youtube_profile", "youtube_resolution", "youtube_video_codec", "youtube_audio_format",
                     "youtube_container"), "format"),
    **dict.fromkeys(("youtube_options", "subtitle_options", "parallel_fragments", "download_archive"), "options"),
    **dict.fromkeys(("remux_profile", "remux_task", "remux_source_format", "remux_target_format",
                     "remux_audio_source_format", "remux_audio_target_format"), "package"),
    **dict.fromkeys(("fps_mode", "fps_target", "fps_output_profile"), "fps"),
    **dict.fromkeys(("lut_file", "grading_profile", "script_preset", "pre_gamma"), "color"),
    **dict.fromkeys(("output_container", "output_resolution", "scan_mode", "encoder_preset", "cpu_encoder_preset", "nvenc_preset",
                     "qsv_encoder_preset", "amf_quality", "av1_preset", "pix_fmt", "crf", "cq", "encode_tuning"), "encoding"),
    **dict.fromkeys(("overwrite", "limit_first_file", "dry_run"), "run"),
}
ADVANCED_PRIORITIES = frozenset({"advanced", "expert", "rare"})

LANGUAGES = ("en", "ru")
WORDS = {
    "en": {"tick": "Select at least one item: {field}",
           "split_duration": "Enter a positive part length as a timecode: 01:29:00,000."},
    "ru": {"tick": "Выберите хотя бы один пункт: {field}",
           "split_duration": "Введите положительную длительность части таймкодом: 01:29:00,000."},
}


def safe_language(language: str | None) -> str:
    return language if language in LANGUAGES else "en"


# --- a field ---------------------------------------------------------------------------------


def field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("name") or "").strip()


def field_kind(field: dict[str, Any]) -> str:
    return str(field.get("type", field.get("kind", "text"))).lower()


def field_label(field: dict[str, Any], language: str = "en") -> str:
    if language == "ru" and field.get("label_ru"):
        return str(field["label_ru"])
    return str(field.get("label") or field.get("title") or field_id(field))


def is_route_field(field: dict[str, Any]) -> bool:
    if field_id(field).lower() in ROUTE_FIELDS:
        return True
    return str(field.get("role") or field.get("ui_role") or "").strip().lower() in ROUTE_ROLES


def is_target_field(field: dict[str, Any]) -> bool:
    key = field_id(field).lower()
    role = str(field.get("role") or field.get("ui_role") or "").strip().lower()
    return role in TARGET_ROLES or key.startswith(("target", "destination", "output"))


def form_fields(node: Any) -> list[dict[str, Any]]:
    """The fields a form shows: all of the node but the Source and the Target."""
    return [field for field in node.fields if not is_route_field(field)]


def option_value(option: Any) -> Any:
    if isinstance(option, dict):
        return option.get("value", option.get("id", option.get("label", "")))
    return option


def field_default(field: dict[str, Any]) -> Any:
    if "default" in field:
        return field["default"]
    options = field.get("options", [])
    if field_kind(field) in TICK_ROWS:
        if not isinstance(options, list):
            return []
        return [option.get("value", option.get("id", option.get("label"))) for option in options
                if isinstance(option, dict) and option.get("default", False)]
    if isinstance(options, list) and options:
        first = options[0]
        return first.get("value", first.get("id", "")) if isinstance(first, dict) else first
    return ""


def step_is_whole(field: dict[str, Any]) -> bool:
    try:
        return float(field.get("step", 1)).is_integer()
    except (TypeError, ValueError):
        return True


def is_whole_number(field: dict[str, Any]) -> bool:
    return field_kind(field) in {"number", "int", "integer"} and step_is_whole(field)


def normalize(field: dict[str, Any], value: Any) -> Any:
    """A number of a whole field as a whole number: 2.0 and "2,0" are 2."""
    if value is None or value == "" or not is_whole_number(field):
        return value
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else value


def refreshes_layout(field: dict[str, Any]) -> bool:
    return bool(field.get("refresh_on_change") or field.get("refresh_layout") or field.get("affects_layout"))


def is_advanced(field: dict[str, Any]) -> bool:
    if bool(field.get("advanced", False)):
        return True
    return str(field.get("priority") or field.get("section") or "").strip().lower() in ADVANCED_PRIORITIES


def section_of(field: dict[str, Any]) -> str:
    explicit = str(field.get("group") or field.get("ui_group") or "").strip().lower()
    if explicit:
        return explicit
    if field_kind(field) in PRESET_BUTTONS | PRESET_LISTS:
        return "preset"
    return SECTION_OF_KEY.get(field_id(field), "parameters")


def sections(fields: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """The fields in the blocks of the panel, in the order the window drew them."""
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    index: dict[str, int] = {}
    for field in fields:
        name = section_of(field)
        if name not in index:
            index[name] = len(groups)
            groups.append((name, [field]))
        else:
            groups[index[name]][1].append(field)
    if "workflow" in index and "preset" in index and index["workflow"] > index["preset"]:
        workflow = groups.pop(index["workflow"])
        at = next((place for place, (name, _) in enumerate(groups) if name == "preset"), 0)
        groups.insert(at, workflow)
    names = [name for name, _ in groups]
    if "decode" in names and "backend" in names and names.index("decode") > names.index("backend"):
        decode = groups.pop(names.index("decode"))
        groups.insert(names.index("backend"), decode)
    return groups


# --- presets -----------------------------------------------------------------------------------


def preset_id(preset: dict[str, Any]) -> str:
    return str(preset.get("id") or preset.get("value") or preset.get("label") or "").strip()


def presets_of(field: dict[str, Any]) -> list[dict[str, Any]]:
    raw = field.get("presets", field.get("options", []))
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict) and preset_id(item)]


# --- the conditions of the manifest ----------------------------------------------------------


def _matches_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if "not" in expected:
            return not _matches_value(actual, expected["not"])
        if "neq" in expected:
            return not _matches_value(actual, expected["neq"])
        if "in" in expected:
            return _matches_value(actual, expected["in"])
        if "exists" in expected:
            return (actual not in {None, "", []}) if bool(expected["exists"]) else (actual in {None, "", []})
    if isinstance(expected, (list, tuple, set)):
        wanted = {str(item).strip().lower() for item in expected}
        if isinstance(actual, (list, tuple, set)):
            return bool({str(item).strip().lower() for item in actual} & wanted)
        return str(actual).strip().lower() in wanted
    if isinstance(expected, bool):
        return bool(actual) is expected
    return str(actual).strip().lower() == str(expected).strip().lower()


# --- dynamic choices -----------------------------------------------------------------------------


def dynamic_options(field: dict[str, Any], root: Path) -> list[Any]:
    """Choices a function of the engine gives (`options_source`): the takes staged for a trim."""
    source = str(field.get("options_source") or field.get("source") or "").strip()
    if not source:
        return []
    try:
        if ":" not in source:
            raise RuntimeError(f"Dynamic option source must use module:function syntax: {source}")
        module_name, function_name = source.split(":", 1)
        provider = getattr(importlib.import_module(module_name), function_name)
        try:
            options = provider(root)
        except TypeError:
            options = provider()
        if not isinstance(options, list):
            raise RuntimeError(f"Dynamic option source returned {type(options).__name__}, expected list.")
    except Exception as exc:  # noqa: BLE001 - the window showed the failure as its one choice
        message = f"Option source failed: {exc.__class__.__name__}: {exc}"
        options = [{"value": "", "label": message, "label_ru": message}]
    return options


# --- a form ----------------------------------------------------------------------------------


class Form:
    """The form of one operation, as the window held it: its values, the presets it applied, what it drew."""

    def __init__(self, node: Any, root: Path, source: Path | str | None = None, target: Path | str | None = None) -> None:
        from system_core.core.paths import INPUT_DIR, OUTPUT_DIR

        self.node = node
        self.root = Path(root)
        self.source = Path(source) if source else self.root / INPUT_DIR
        self.target = Path(target) if target else self.root / OUTPUT_DIR
        self.values: dict[str, Any] = {}
        self.applied: dict[str, str] = {}
        self._fields = {field_id(field): field for field in node.fields if field_id(field)}

    # ---- reading the form -------------------------------------------------------------------
    def field(self, key: str) -> dict[str, Any]:
        return self._fields.get(key, {})

    def actual(self, key: str) -> Any:
        """A value a condition reads: the one set, or the default of a field not drawn yet."""
        if key in self.values:
            return self.values[key]
        field = self._fields.get(key)
        return field_default(field) if field is not None else None

    def holds(self, condition: Any) -> bool:
        if not condition:
            return False
        if isinstance(condition, dict):
            if "all" in condition:
                return all(self.holds(item) for item in condition.get("all") or [])
            if "any" in condition:
                return any(self.holds(item) for item in condition.get("any") or [])
            if "not" in condition:
                return not self.holds(condition["not"])
            for key, expected in condition.items():
                if key in {"all", "any", "not"}:
                    continue
                if not _matches_value(self.actual(str(key)), expected):
                    return False
            return True
        if isinstance(condition, (list, tuple, set)):
            return all(self.holds(item) for item in condition)
        return False

    def visible(self, field: dict[str, Any]) -> bool:
        if bool(field.get("hidden", field.get("ui_hidden", False))):
            return False
        shown_if = field.get("visible_if", field.get("show_if"))
        if shown_if and not self.holds(shown_if):
            return False
        hidden_if = field.get("hidden_if", field.get("hide_if"))
        return not (hidden_if and self.holds(hidden_if))

    def option_visible(self, option: Any) -> bool:
        if not isinstance(option, dict):
            return True
        shown_if = option.get("visible_if", option.get("show_if"))
        if shown_if and not self.holds(shown_if):
            return False
        hidden_if = option.get("hidden_if", option.get("hide_if"))
        return not (hidden_if and self.holds(hidden_if))

    def option_disabled(self, option: Any) -> bool:
        if not isinstance(option, dict):
            return False
        disabled_if = option.get("disabled_if", option.get("disable_if"))
        if disabled_if and self.holds(disabled_if):
            return True
        enabled_if = option.get("enabled_if", option.get("enable_if"))
        return bool(enabled_if and not self.holds(enabled_if))

    def options(self, field: dict[str, Any]) -> list[Any]:
        dynamic = dynamic_options(field, self.root)
        if dynamic:
            return dynamic
        options = field.get("options", [])
        return options if isinstance(options, list) else []

    def choices(self, field: dict[str, Any]) -> list[tuple[Any, bool]]:
        """The choices of a field the panel shows, each with whether it is switched off."""
        return [(option_value(option), self.option_disabled(option)) for option in self.options(field) if self.option_visible(option)]

    def shown_fields(self) -> list[dict[str, Any]]:
        return [field for field in form_fields(self.node) if self.visible(field)]

    # ---- what a control does ----------------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        """A value set by a control, and what the window set with it (`set_field_value`)."""
        values = self.values
        values[key] = value
        if key == "output_container":
            container = str(value or "").strip().lower()
            audio_mode = str(values.get("audio_mode") or "source").strip().lower()
            if container == "mxf" and audio_mode not in {"pcm_s16", "pcm_s24", "none"}:
                values["audio_mode"] = "pcm_s24"
            elif container == "mov" and audio_mode == "flac":
                # MOV cannot hold FLAC; PCM 24-bit is the closest lossless choice.
                values["audio_mode"] = "pcm_s24"
        if key in {"audio_mode", "audio_format"} and str(value or "").strip().lower() == "mp3":
            # 384k belongs to the AAC scale; MPEG-1 Layer III stops at 320.
            if str(values.get("audio_bitrate") or "").strip().lower() == "384k":
                values["audio_bitrate"] = "320k"
        if key == "remux_stream_mode":
            self.remux_defaults()

    def remux_defaults(self) -> None:
        self.values.setdefault("remux_stream_mode", "video_audio")
        self.values.setdefault("remux_target_format", "mp4")
        self.values.setdefault("remux_audio_target_format", "mka")

    def set_script(self, script: Any) -> None:
        """A colour script, and the gamma before its LUT that it brings."""
        script = str(script or "").strip()
        self.values["script_preset"] = script
        self.values["pre_gamma"] = self.script_gamma(script)

    def script_gamma(self, script: str) -> float | str:
        from system_core.core.ffmpeg_escape import ffmpeg_filter_number
        from system_core.core.script_profiles import script_profile

        profile = script_profile(self.root, script) if script else {}
        kind = str(profile.get("color_filter") or "").strip().lower()
        lowered = script.lower()
        if kind == "preexpose_lut" or "preexpose" in lowered:
            return float(ffmpeg_filter_number(profile.get("pre_gamma") or "1.15", name="pre_gamma"))
        if kind == "pregamma_lut" or "pregamma" in lowered:
            return float(ffmpeg_filter_number(profile.get("pre_gamma") or "0.85", name="pre_gamma"))
        return ""

    def set_for_field(self, field: dict[str, Any], value: Any) -> None:
        if field_id(field) == "script_preset":
            self.set_script(value)
            return
        self.set(field_id(field), normalize(field, value))

    def apply_preset_values(self, preset: dict[str, Any], skip_ticks: bool = False) -> None:
        given = preset.get("values", {})
        if not isinstance(given, dict):
            return
        for key, value in given.items():
            if skip_ticks and isinstance(value, (bool, list)):
                continue
            self.values[str(key)] = value

    # ---- the panel drawn ----------------------------------------------------------------------
    def current(self, field: dict[str, Any]) -> Any:
        key = field_id(field)
        if key not in self.values:
            self.values[key] = field_default(field)
        return self.values[key]

    def current_preset(self, field: dict[str, Any]) -> str:
        value = str(self.current(field) or "").strip()
        if value:
            return value
        presets = presets_of(field)
        return preset_id(presets[0]) if presets else ""

    def draw(self) -> None:
        """What drawing the panel did to the form (`command_tree` of the window)."""
        fields = form_fields(self.node)
        primary = [field for field in fields if not is_advanced(field)]
        advanced = [field for field in fields if is_advanced(field)]
        for grid in (primary, advanced):
            if not grid:
                continue
            if any(field_id(field).startswith("remux_") for field in grid):
                self.remux_defaults()
            for _name, block in sections(grid):
                # A block decides what it shows before it draws any of it.
                for field in [field for field in block if self.visible(field)]:
                    self.draw_field(field)

    def draw_field(self, field: dict[str, Any]) -> None:
        key, kind = field_id(field), field_kind(field)
        if not key:
            return
        value = self.current(field)
        if kind in PRESET_BUTTONS or kind in PRESET_LISTS:
            listed = kind in PRESET_LISTS
            presets = presets_of(field) if listed else [preset for preset in presets_of(field) if self.option_visible(preset)]
            selected = self.current_preset(field)
            if selected and self.applied.get(key) != selected:
                preset = next((item for item in presets if preset_id(item) == selected), None)
                if preset:
                    # A preset list leaves the ticks and the lists of the form as they are.
                    self.apply_preset_values(preset, skip_ticks=listed)
                self.set(key, selected)
                self.applied[key] = selected
            return
        if kind in LUT_PICKS:
            self.values[key] = self.current_lut(field)
            return
        if kind in SWITCHES:
            choices = self.choices(field)
            allowed = [choice for choice, off in choices if not off]
            every = [choice for choice, _ in choices]
            if value not in every or any(choice == value and off for choice, off in choices):
                self.set(key, allowed[0] if allowed else (every[0] if every else value))
            return
        if kind in TICK_ROWS:
            selected = set(value if isinstance(value, list) else [])
            self.set(key, [choice for choice, off in self.choices(field) if choice in selected and not off])
            return
        if kind in TRIM_TAKES:
            names = self.trim_names()
            if names:
                current = str(self.values.get(key) or "").strip()
                if current not in names:
                    current = names[0]
                    self.values[key] = current
                self.values["trim_media_kind"] = self.trim_kind(current)

    def current_lut(self, field: dict[str, Any]) -> str:
        from system_core.core.lut_cache import load_lut_cache, scan_luts

        selected = str(self.values.get(field_id(field)) or "").strip().strip('"')
        if not selected:
            selected = str(load_lut_cache(self.root).get("selected_lut") or "").strip()
        if not selected:
            found = scan_luts(self.root)
            selected = found[0] if found else ""
        return str(Path(selected).expanduser().resolve()) if selected else ""

    def trim_names(self) -> list[str]:
        try:
            from system_core.services.media_service import trim_source_file_names

            return list(trim_source_file_names(self.root))
        except Exception:  # noqa: BLE001 - no takes to show, as the window had it
            return []

    @staticmethod
    def trim_kind(name: str) -> str:
        try:
            from system_core.services.media_service import trim_media_kind

            return str(trim_media_kind(name))
        except Exception:  # noqa: BLE001
            return "video"

    # ---- the steps of a person ------------------------------------------------------------------
    def open(self) -> "Form":
        """The operation chosen: an empty form, drawn."""
        self.values, self.applied = {}, {}
        self.draw()
        return self

    def click(self, action: str, key: str, value: Any) -> None:
        """One control used as the window's control did it, and the panel drawn again when the window did."""
        field = self.field(key)
        redraw = refreshes_layout(field)
        if action == "preset":
            preset = next((item for item in presets_of(field) if preset_id(item) == str(value)), None)
            if preset is None:
                raise ValueError(f"{key}: no preset {value!r}")
            self.apply_preset_values(preset)
            self.set(key, preset_id(preset))
            self.applied[key] = preset_id(preset)
            redraw = True
        elif action == "profile":
            self.set(key, str(value))
            preset = next((item for item in presets_of(field) if preset_id(item) == str(value)), None)
            if preset:
                self.apply_preset_values(preset)
                self.set(key, str(value))
                self.applied[key] = str(value)
            redraw = True
        elif action == "lut":
            from system_core.core.lut_cache import resolve_lut_path

            self.values[key] = str(resolve_lut_path(self.root, value))
            redraw = True
        elif action == "remux":
            self.values[key] = str(value).strip().lower()
            redraw = True
        elif action == "choose":
            self.set(key, value)
            # A row of buttons redraws only when its field says so; radio buttons always did.
            redraw = redraw if str(field.get("style") or field.get("choice_style") or field.get("variant") or "").strip().lower() in SEGMENTED else True
        elif action in {"select", "number"}:
            self.set_for_field(field, value)
        elif action in {"tick", "ticks"}:
            self.set(key, list(value) if action == "ticks" else bool(value))
        elif action == "type":
            self.set(key, value)
            redraw = False
        elif action == "take":
            if str(value or "") != str(self.values.get("trim_file") or ""):
                # Another take: the points of the old one describe someone else's material (the window on NiceGUI).
                self.values.update({"trim_start": "", "trim_end": "", "trim_rows": [], "trim_points": []})
            self.set("trim_file", value)
            redraw = True
        elif action == "trim_action":
            self.set("trim_action", value)
            redraw = True
        elif action == "point":
            row, which, text = value
            self.trim_point(int(row), str(which), str(text))
            redraw = False
        elif action == "split_point":
            index, text = value
            self.split_point(int(index), str(text))
            redraw = False
        elif action == "add_row":
            self.trim_add()
            redraw = False
        else:
            raise ValueError(f"unknown action {action!r}")
        if redraw:
            self.draw()

    def fill(self, given: dict[str, Any]) -> "Form":
        """Values of a caller, set as a person sets them: the presets first, then every other field in its order.

        Each value goes through the click of its control, so a preset writes its values and a link pulls its
        field as in the window; the panel is drawn at the end, as the window showed it before its run.
        """
        fields = [field for field in form_fields(self.node) if field_id(field) in given]
        presets = [field for field in fields if field_kind(field) in PRESET_BUTTONS | PRESET_LISTS]
        for field in presets + [field for field in fields if field not in presets]:
            self.click(action_of(field), field_id(field), given[field_id(field)])
        self.draw()
        return self

    def changed(self, given: dict[str, Any]) -> list[tuple[str, Any, Any]]:
        """The values the form took otherwise than given: a link, or a choice that was off in the form as it stood."""
        return [(key, value, self.values.get(key)) for key, value in given.items()
                if key in self.values and self.values.get(key) != value and action_of(self.field(key)) not in {"preset", "profile", "lut"}]

    # ---- the rows of a trim -------------------------------------------------------------------
    def trim_rows(self) -> list[dict[str, str]]:
        raw = self.values.get("trim_rows")
        return [{"start": str(row.get("start") or ""), "end": str(row.get("end") or "")}
                for row in (raw if isinstance(raw, list) else []) if isinstance(row, dict)]

    def split_points(self) -> list[str]:
        raw = self.values.get("trim_points")
        points = [str(item or "") for item in raw] if isinstance(raw, list) else []
        return points or [""]

    def trim_point(self, index: int, which: str, text: str) -> None:
        """`which` is "start" or "end"; row 0 is IN and OUT themselves."""
        if index <= 0:
            self.values["trim_start" if which == "start" else "trim_end"] = text
            return
        rows = self.trim_rows()
        while len(rows) < index:
            rows.append({"start": "", "end": ""})
        rows[index - 1][which] = text
        self.values["trim_rows"] = rows

    def split_point(self, index: int, text: str) -> None:
        points = self.split_points()
        while len(points) <= index:
            points.append("")
        points[index] = text
        self.values["trim_points"] = points

    def trim_action(self) -> str:
        return str(self.actual("trim_action") or "keep").strip().lower()

    def trim_can_add(self) -> bool:
        from system_core.core.trim_contract import SPLIT_MAX_POINTS, TRIM_MAX_VARIANTS

        action = self.trim_action()
        if action == "split":
            if self.actual("trim_split_mode") == "duration":
                return False
            points = self.split_points()
            return bool(points[-1].strip()) and len(points) < SPLIT_MAX_POINTS
        rows = [{"start": str(self.values.get("trim_start") or ""), "end": str(self.values.get("trim_end") or "")}, *self.trim_rows()]
        last = rows[-1]
        filled = (bool(last["start"].strip()) and bool(last["end"].strip())) if action == "cut" else (bool(last["start"].strip()) or bool(last["end"].strip()))
        return filled and len(rows) < TRIM_MAX_VARIANTS

    def trim_add(self) -> bool:
        if not self.trim_can_add():
            return False
        if self.trim_action() == "split":
            self.values["trim_points"] = [*self.split_points(), ""]
        else:
            self.values["trim_rows"] = [*self.trim_rows(), {"start": "", "end": ""}]
        return True

    # ---- what is run ----------------------------------------------------------------------------
    def refusal(self, language: str = "en") -> str:
        """Why the form may not be run - the first reason, as the window gave it; "" when it may.

        The window counted the ticks of every row of the form, shown or not.
        """
        words = WORDS[safe_language(language)]
        if self.trim_action() == "split" and self.actual("trim_split_mode") == "duration":
            from system_core.core.trim_contract import parse_split_interval

            try:
                parse_split_interval(self.actual("trim_split_duration"))
            except ValueError:
                return words["split_duration"]
        for field in form_fields(self.node):
            if field_kind(field) not in TICK_ROWS:
                continue
            least = int(field.get("min_selected", 0) or 0)
            if least <= 0:
                continue
            chosen = self.values.get(field_id(field), field_default(field))
            if not isinstance(chosen, list) or len(chosen) < least:
                return words["tick"].format(field=field_label(field, language))
        return ""

    def parameters(self) -> dict[str, Any]:
        """What the service of the operation is handed (`operation_from_pending_command`)."""
        parameters = dict(self.node.parameters)
        for field in self.node.fields:
            key = field_id(field)
            if not key:
                continue
            if is_route_field(field):
                parameters[key] = str((self.target if is_target_field(field) else self.source).resolve())
            else:
                parameters[key] = normalize(field, self.values.get(key, field_default(field)))
        return parameters


def action_of(field: dict[str, Any]) -> str:
    """The click of a field's control, as Form.click names it."""
    kind = field_kind(field)
    for kinds, action in ((PRESET_BUTTONS, "preset"), (PRESET_LISTS, "profile"), (LUT_PICKS, "lut"), (REMUX_TARGETS, "remux"),
                          (SWITCHES, "choose"), (LISTS, "select"), (NUMBERS, "number"), (TICKS, "tick"), (TICK_ROWS, "ticks"),
                          (TRIM_TAKES, "take")):
        if kind in kinds:
            return action
    return "type"


# --- a caller's values -------------------------------------------------------------------------


def unknown_values(node: Any, values: dict[str, Any]) -> list[str]:
    known = {field_id(field) for field in form_fields(node)}
    return sorted(name for name in values if name not in known)


def coerce(field: dict[str, Any], text: str) -> Any:
    """`--set name=value`: the text of a console as the value its field holds."""
    import json

    kind = field_kind(field)
    stripped = text.strip()
    if stripped[:1] in {"[", "{"}:
        # Rows of a trim, points of a split, ticks given whole: JSON as it stands.
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    if kind in TICK_ROWS:
        return [part.strip() for part in text.split(",") if part.strip()]
    if kind in TICKS:
        lowered = stripped.lower()
        if lowered in {"1", "true", "yes", "on", "да"}:
            return True
        if lowered in {"0", "false", "no", "off", "нет", ""}:
            return False
        raise ValueError(f"true or false is expected, got {text!r}")
    if kind in NUMBERS and stripped != "":
        try:
            number = float(stripped.replace(",", "."))
        except ValueError as error:
            raise ValueError(f"a number is expected, got {text!r}") from error
        return int(number) if number.is_integer() and kind != "float" else number
    for option in field.get("options") or []:
        value = option_value(option)
        if not isinstance(value, str) and str(value).lower() == stripped.lower():
            return value
    return text


def wrong_choices(node: Any, values: dict[str, Any], root: Path, language: str = "en") -> list[str]:
    """A value that is none of the choices of its field: the window could not set one, a caller can."""
    form = Form(node, root)
    wrong: list[str] = []
    for field in form_fields(node):
        key = field_id(field)
        if key not in values:
            continue
        kind = field_kind(field)
        if kind in PRESET_BUTTONS | PRESET_LISTS:
            allowed = [preset_id(preset) for preset in presets_of(field)]
        elif kind in SWITCHES | LISTS | TICK_ROWS | REMUX_TARGETS:
            allowed = [option_value(option) for option in form.options(field)]
        elif kind in TRIM_TAKES:
            allowed = form.trim_names()
        else:
            continue
        given = values[key] if isinstance(values[key], list) else [values[key]]
        if kind in REMUX_TARGETS:
            given = [str(item).strip().lower() for item in given]
        label = field_label(field, language)
        wrong += [f"{label} ({key}): no such choice - {item!r}; choices: {', '.join(map(str, allowed))}"
                  for item in given if item not in allowed]
    return wrong


# --- the tone of a choice --------------------------------------------------------------------
# The colour a choice wears: copy, uncompressed, lossless, lossy. The window on NiceGUI worked it out from the
# words of a choice every time it drew one, and for the fields of formats and codecs the words won over the
# `tone` of the manifest. Here it is worked out once, by the same words, and told to the window as data.

FORMAT_TONE_FIELDS = frozenset({
    "audio_mode", "audio_format", "audio_copy_container", "audio_video_container", "fps_audio_pcm_depth", "input_formats",
    "output_container", "remux_target_format", "remux_audio_target_format", "target_codecs", "youtube_audio_format",
    "youtube_container", "youtube_video_codec",
})
FORMAT_TONE_HINTS = ("format", "formats", "codec", "codecs", "container")
UNCOMPRESSED_TOKENS = frozenset({"aif", "aiff", "au", "caf", "dff", "dsf", "f32", "pcm", "pcm_f32", "pcm_s16", "pcm_s24", "raw",
                                 "s16", "s24", "snd", "wav", "w64", "wave"})
LOSSLESS_TOKENS = frozenset({"alac", "ape", "dnx", "dnxhr", "dnxhr_hq", "dnxhr_hqx", "ffv1", "flac", "mka", "mov", "mxf", "prores",
                             "prores_422", "prores_hq", "prores_lt", "prores_proxy", "tak", "tta", "wv", "x264_lossless"})
LOSSY_TOKENS = frozenset({"3gp", "aac", "aac_320", "ac3", "amr", "av1", "avc", "avi", "awb", "dts", "eac3", "e_ac3", "h264", "h265",
                          "hevc", "hevc_x265", "m2ts", "m4a", "m4b", "m4v", "mkv", "mp3", "mp4", "mpc", "mpeg", "mpg", "mts", "ogg",
                          "oga", "opus", "spx", "svt_av1", "ts", "vp9", "webm", "x264", "x265"})


def _format_tokens(value: Any, label: str) -> set[str]:
    import re

    raw = f"{value} {label}".lower()
    raw = raw.replace("e-ac3", "eac3").replace("h.264", "h264").replace("h.265", "h265").replace("svt-av1", "svt_av1")
    compact = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    tokens = {part for part in re.split(r"[^a-z0-9]+", raw) if part}
    if compact:
        tokens.add(compact)
    joined = (({"svt", "av1"}, "svt_av1"), ({"x264", "lossless"}, "x264_lossless"), ({"prores", "proxy"}, "prores_proxy"),
              ({"prores", "lt"}, "prores_lt"), ({"prores", "hq"}, "prores_hq"), ({"dnxhr", "hq"}, "dnxhr_hq"), ({"dnxhr", "hqx"}, "dnxhr_hqx"))
    for parts, token in joined:
        if parts <= tokens:
            tokens.add(token)
    if {"x265", "hevc"} & tokens:
        tokens.add("hevc_x265")
    if "pcm" in tokens and "16" in tokens:
        tokens.add("pcm_s16")
    if "pcm" in tokens and "24" in tokens:
        tokens.add("pcm_s24")
    if "pcm" in tokens and ("float" in tokens or "32" in tokens or "32f" in tokens):
        tokens.add("pcm_f32")
    return tokens


def option_tone(field: dict[str, Any], option: Any, language: str = "en") -> str:
    """The tone the window drew a choice in (`choice_option_tone` of the former window)."""
    key = field_id(field).lower()
    group = str(field.get("group") or "").strip().lower()
    if key in FORMAT_TONE_FIELDS or any(hint in key for hint in FORMAT_TONE_HINTS) or any(hint in group for hint in FORMAT_TONE_HINTS):
        label = str(option.get("label_ru") if language == "ru" and isinstance(option, dict) and option.get("label_ru")
                    else (option.get("label") or option.get("title") or option_value(option)) if isinstance(option, dict) else option)
        tokens = _format_tokens(option_value(option), label)
        if tokens & UNCOMPRESSED_TOKENS:
            return "uncompressed"
        if tokens & LOSSLESS_TOKENS:
            return "lossless"
        if tokens & LOSSY_TOKENS:
            return "lossy"
    if isinstance(option, dict) and (option.get("tone") or option.get("category") or option.get("group")):
        text = str(option.get("tone") or option.get("category") or option.get("group") or "").strip().lower()
        return "".join(char if char.isalnum() else "-" for char in text).strip("-")
    return ""


# --- the swatches of COLOUR ------------------------------------------------------------------


def gamma_preview(values: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """Where the gamma before the LUT takes 18% gray - two swatches under the colour block (the window on NiceGUI,
    render_color_gamma_preview): mode "gamma" with the gamma, both grays as #rrggbb, the percent it lands at and its tone
    (lighter, darker, same); "hdr" - an HDR-to-SDR operation, where 18% gray is the reference of the tone map; "error" - a
    gamma that is no number. None - the form has no colour operation."""
    from .ffmpeg_escape import ffmpeg_filter_number
    from .script_profiles import script_profile

    script = str(values.get("script_preset") or "ff-grade-lut-only-x264.cmd").strip()
    if not script:
        return None

    def gray(value: float) -> str:
        channel = max(0, min(255, int(round(value * 255))))
        return f"#{channel:02x}{channel:02x}{channel:02x}"

    profile = script_profile(root, script)
    kind = str(profile.get("color_filter") or "").strip().lower()
    lowered = script.lower()
    if kind == "hdr2sdr_hable" or "hdr2sdr" in lowered or "hable" in lowered:
        return {"mode": "hdr", "source": gray(0.18), "target": gray(0.18), "percent": 18.0, "tone": "same"}
    given = str(values.get("pre_gamma") or profile.get("pre_gamma") or "").strip()
    try:
        if kind == "preexpose_lut" or "preexpose" in lowered:
            gamma = float(ffmpeg_filter_number(given or "1.15", name="pre_gamma"))
        elif kind == "pregamma_lut" or "pregamma" in lowered:
            gamma = float(ffmpeg_filter_number(given or "0.85", name="pre_gamma"))
        else:
            gamma = 1.0
    except ValueError as error:
        return {"mode": "error", "error": str(error)}
    source = 0.18
    target = source if gamma == 1.0 or gamma <= 0 else max(0.0, min(1.0, source ** (1.0 / gamma)))
    tone = "same" if abs(target - source) < 0.002 else "lighter" if target > source else "darker"
    return {"mode": "gamma", "gamma": gamma, "source": gray(source), "target": gray(target), "percent": round(target * 100.0, 1),
            "tone": tone}


# --- what the window draws -------------------------------------------------------------------

CONDITIONS = ("visible_if", "show_if", "hidden_if", "hide_if", "disabled_if", "disable_if", "enabled_if", "enable_if")
TEXTS = ("label", "label_ru", "tooltip", "tooltip_ru", "hint", "hint_ru", "description", "description_ru", "placeholder",
         "add_tooltip", "add_tooltip_ru", "add_point_tooltip", "add_point_tooltip_ru", "point_tooltip", "point_tooltip_ru")


def window_option(field: dict[str, Any], option: Any) -> dict[str, Any]:
    given = option if isinstance(option, dict) else {}
    told = {"value": option_value(option), "label": str(given.get("label") or given.get("title") or option_value(option)),
            "tone": option_tone(field, option, "en"), "tone_ru": option_tone(field, option, "ru")}
    for key in ("label_ru", "tooltip", "tooltip_ru", "hint", "hint_ru", "description", "description_ru", *CONDITIONS):
        if key in given:
            told[key] = given[key]
    return told


def window_preset(preset: dict[str, Any]) -> dict[str, Any]:
    told = {"id": preset_id(preset), "values": dict(preset.get("values") or {})}
    for key in ("label", "label_ru", "description", "description_ru", "tooltip", "tooltip_ru", "tone", "group", "group_label",
                "group_label_ru", *CONDITIONS):
        if key in preset:
            told[key] = preset[key]
    return told


def window_field(field: dict[str, Any]) -> dict[str, Any]:
    """A field of a form as the window draws it: what the manifest says, the default worked out, its block named."""
    kind = field_kind(field)
    told: dict[str, Any] = {
        "id": field_id(field), "kind": kind, "action": action_of(field), "default": field_default(field),
        "section": section_of(field), "advanced": is_advanced(field), "hidden": bool(field.get("hidden", field.get("ui_hidden", False))),
        "redraws": refreshes_layout(field), "whole": is_whole_number(field),
        "style": str(field.get("style") or field.get("choice_style") or field.get("variant") or "").strip().lower(),
    }
    for key in (*TEXTS, *CONDITIONS, "min", "max", "step", "min_selected", "span", "layout", "columns", "file_filter",
                "options_source"):
        if key in field:
            told[key] = field[key]
    if kind in PRESET_BUTTONS | PRESET_LISTS:
        told["presets"] = [window_preset(preset) for preset in presets_of(field)]
    elif isinstance(field.get("options"), list):
        told["options"] = [window_option(field, option) for option in field["options"]]
    return told


def window_node(node: Any) -> dict[str, Any]:
    """An operation as the window draws it. The Source and the Target are not of a form and are not told."""
    return {
        "id": node.id, "title": node.title, "title_ru": node.title_ru,
        "description": node.description, "description_ru": node.description_ru,
        "kind": node.kind, "runs": bool(node.service), "fields": [window_field(field) for field in form_fields(node)],
    }


def describe(manifest: Any) -> dict[str, Any]:
    tool = manifest.raw.get("tool", {}) if isinstance(manifest.raw.get("tool"), dict) else {}
    operations = [node for node in all_nodes(manifest) if node.service and not node.children]
    operations += [operation for operation in [*manifest.operations, *manifest.maintenance_operations] if operation.id not in {node.id for node in operations}]
    return {"tool": {"id": tool.get("id", ""), "name": tool.get("name", "")},
            "operations": {node.id: window_node(node) for node in operations}}


# --- the manifest ----------------------------------------------------------------------------


def iter_nodes(nodes: Iterable[Any]) -> Iterable[Any]:
    for node in nodes:
        yield node
        yield from iter_nodes(getattr(node, "children", ()))


def all_nodes(manifest: Any) -> list[Any]:
    return list(iter_nodes(manifest.operation_groups))


def find_node(manifest: Any, operation_id: str) -> Any | None:
    """The operation of the name: a leaf of the tree that runs something, or one of the service operations."""
    for node in all_nodes(manifest):
        if node.id == operation_id and node.service and not node.children:
            return node
    for operation in [*manifest.operations, *manifest.maintenance_operations]:
        if operation.id == operation_id:
            return operation
    return None
