from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
import atexit
import argparse
import ctypes
import importlib
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import app as nicegui_app, run, ui  # type: ignore

AUDION_CANONICAL_TOOLTIP_DELAY_MS = 1500
AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS = 100
AUDION_CANONICAL_TOOLTIP_TRANSITION_MS = 100


def install_audion_canonical_tooltip_defaults() -> None:
    try:
        from nicegui.elements.tooltip import Tooltip as NiceGuiTooltip  # type: ignore
    except Exception:
        return
    if getattr(NiceGuiTooltip, "_audion_canonical_tooltip_defaults", False):
        return
    original_init = NiceGuiTooltip.__init__

    def audion_tooltip_init(self: Any, text: str = "") -> None:
        original_init(self, text)
        self.props["delay"] = AUDION_CANONICAL_TOOLTIP_DELAY_MS
        self.props["hide-delay"] = AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS
        self.props["transition-duration"] = AUDION_CANONICAL_TOOLTIP_TRANSITION_MS
        self.classes("audion-tooltip")

    NiceGuiTooltip.__init__ = audion_tooltip_init  # type: ignore[method-assign]
    NiceGuiTooltip._audion_canonical_tooltip_defaults = True  # type: ignore[attr-defined]


install_audion_canonical_tooltip_defaults()


AUDION_CANONICAL_UI_CSS = """
<style id="audion-canonical-tooltip-icon-style">
  html body .q-tooltip,
  html body .audion-tooltip {
    background: rgb(23, 33, 43) !important;
    background-color: rgb(23, 33, 43) !important;
    color: #f4f8fb !important;
    border: 1px solid rgba(88, 166, 255, 0.24) !important;
    border-radius: 8px !important;
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.34) !important;
  }
  html body .q-icon.material-icons,
  html body .q-icon.material-symbols-outlined,
  html body .q-icon.material-symbols-rounded,
  html body i.material-icons,
  html body i.material-symbols-outlined,
  html body i.material-symbols-rounded,
  html body .q-btn .q-icon,
  html body .q-btn .material-icons,
  html body .q-btn .material-symbols-outlined,
  html body .q-btn .material-symbols-rounded,
  html body .q-field .q-field__append .q-icon,
  html body .q-field .q-field__prepend .q-icon,
  html body .q-item .q-icon,
  html body .q-menu .q-icon,
  html body .audion-label-icon,
  html body .audion-path-option-pin,
  html body .audion-select-option-pin {
    font-size: 14px !important;
    width: 14px !important;
    min-width: 14px !important;
    height: 14px !important;
    line-height: 14px !important;
  }
  html body .material-icons,
  html body .q-icon.material-icons {
    font-family: "Material Icons" !important;
  }
  html body .material-symbols-outlined,
  html body .q-icon.material-symbols-outlined {
    font-family: "Material Symbols Outlined" !important;
  }
  html body .material-symbols-rounded,
  html body .q-icon.material-symbols-rounded {
    font-family: "Material Symbols Rounded" !important;
  }
</style>
"""


def add_audion_canonical_ui_styles() -> None:
    ui.add_head_html(AUDION_CANONICAL_UI_CSS)



def audion_tooltip_path_text(path_value: Any) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        return str(path)
    except Exception:
        return raw


def audion_folder_button_tooltip(folder_id: str, path_value: Any) -> str:
    key = str(folder_id or "folder").strip().lower()
    path_text = audion_tooltip_path_text(path_value)
    if getattr(settings, "language", "ru") == "ru":
        descriptions = {
            "logs": "папку логов запусков и вывода терминала",
            "report": "папку отчётов и результатов операций",
            "reports": "папку отчётов и результатов операций",
            "config": "папку конфигурации проекта: manifest, GUI-настройки и кэши",
            "state": "папку рабочего состояния GUI",
            "project": "корневую папку проекта",
            "root": "корневую папку проекта",
            "data": "папку данных проекта",
            "pipeline": "папку pipeline-артефактов и промежуточных результатов",
            "github": "папку GitHub-артефактов проекта",
            "install": "папку install/runtime-артефактов проекта",
        }
        description = descriptions.get(key, f"папку {folder_id}")
        return f"Открыть {description}: {path_text}" if path_text else f"Открыть {description}."
    descriptions = {
        "logs": "the logs folder with run and terminal output",
        "report": "the reports/results folder",
        "reports": "the reports/results folder",
        "config": "the project config folder with manifest, GUI settings, and caches",
        "state": "the GUI state folder",
        "project": "the project root folder",
        "root": "the project root folder",
        "data": "the project data folder",
        "pipeline": "the pipeline artifacts and intermediate results folder",
        "github": "the project GitHub artifacts folder",
        "install": "the project install/runtime artifacts folder",
    }
    description = descriptions.get(key, f"the {folder_id} folder")
    return f"Open {description}: {path_text}" if path_text else f"Open {description}."


def audion_terminal_action_tooltip(action: str) -> str:
    key = str(action or "").strip().lower()
    if getattr(settings, "language", "ru") == "ru":
        tips = {
            "clear_terminal_window": "Очистить только видимое окно терминала. Файлы логов, отчёты и результаты операций не удаляются.",
            "expand": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "expand_log": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "pin_command": "Закрепить текущую команду в истории терминала для быстрого повторного запуска.",
            "unpin_command": "Открепить текущую команду от верхней части истории терминала.",
            "clear_history": "Очистить историю команд терминала. Закреплённые команды и файлы логов не удаляются.",
            "terminal_shell": "Выбрать оболочку, в которой будут запускаться команды терминала.",
            "terminal_history": "Выбрать ранее сохранённую или закреплённую команду терминала.",
            "terminal_command": "Команда, которая будет выполнена из выбранной рабочей папки.",
            "terminal_cwd": "Рабочая папка терминала. Команда будет запущена именно отсюда.",
            "pick_folder": "Выбрать рабочую папку терминала через системный диалог.",
            "terminal_run": "Запустить введённую команду в выбранной оболочке и рабочей папке.",
            "latest_report": "Открыть последний созданный отчёт, если он уже есть.",
            "command_preview": "Показать команду, которая будет запущена с текущими параметрами, без выполнения операции.",
            "report_view": "Открыть встроенный список отчётов без перехода в проводник.",
            "close": "Закрыть большое окно терминала и вернуться к основной панели.",
        }
    else:
        tips = {
            "clear_terminal_window": "Clear only the visible terminal window. Log files, reports, and operation results are not deleted.",
            "expand": "Open the terminal in a large window for reading long output comfortably.",
            "expand_log": "Open the terminal in a large window for reading long output comfortably.",
            "pin_command": "Pin the current terminal command for quick reuse.",
            "unpin_command": "Remove the current command from the pinned command list.",
            "clear_history": "Clear terminal command history. Pinned commands and log files are not deleted.",
            "terminal_shell": "Choose the shell used to run terminal commands.",
            "terminal_history": "Pick a saved or pinned terminal command.",
            "terminal_command": "Command to run from the selected working folder.",
            "terminal_cwd": "Terminal working folder. Commands are started from here.",
            "pick_folder": "Choose the terminal working folder with the system dialog.",
            "terminal_run": "Run the entered command in the selected shell and working folder.",
            "latest_report": "Open the latest generated report, if one exists.",
            "command_preview": "Show the command that would run with the current settings, without executing it.",
            "report_view": "Open the built-in reports list without switching to the file explorer.",
            "close": "Close the large terminal window and return to the main panel.",
        }
    return tips.get(key, key.replace("_", " ").strip())


from system_core.core.ansi_terminal import AnsiHtmlRenderer, terminal_html as _render_terminal_html, terminal_lines_html as _terminal_lines_html
from system_core.core.config import load_yaml_or_json
from system_core.core.ffmpeg_escape import ffmpeg_filter_number
from system_core.core.jobs import execute_operation
from system_core.core.lut_cache import LUT_EXTENSIONS, load_lut_cache, save_lut_cache, scan_luts, update_lut_cache
from system_core.core.manifest import CommandNode, Operation, load_manifest
from system_core.core.profile_cache import pinned_profiles, set_profile_pin
from system_core.core.path_cache import cached_output_path, cached_source_path, update_path_cache
from system_core.core.paths import ensure_project_dirs, get_project_paths, open_folder
from system_core.core.script_profiles import script_profile
from system_core.core.trim_contract import format_seconds
from system_core.core.ui_theme_catalog import DEFAULT_THEME_ID, normalize_theme_id
from system_core.core.ui_settings import load_ui_settings
from system_core.ui_nicegui.workbench import (
    WorkbenchAdapter,
    WorkbenchConfig,
    WorkbenchHandlers,
    WorkbenchRenderer,
    WorkbenchRole,
    WORKBENCH_FEEDBACK_CSS,
    WORKBENCH_LAYOUT_CSS,
    WORKBENCH_OVERRIDE_CSS,
    canonical_role,
)


paths = get_project_paths(ROOT)
ensure_project_dirs(paths)
manifest = load_manifest(paths.config / "tool_manifest.yaml")
settings_path = paths.config / "gui_settings.yaml"
settings = load_ui_settings(settings_path)
lut_cache = load_lut_cache(ROOT)
tool_info: dict[str, Any] = manifest.raw.get("tool", {})
ui_info: dict[str, Any] = manifest.raw.get("ui", {})


def _workspace_history_file() -> Path:
    return paths.config / "path_history.json"


def _startup_workspace_path(role: str, configured: str, legacy: str, default_path: Path) -> str:
    return str(default_path)


def load_workspace_route_settings() -> tuple[str, str]:
    return (
        _startup_workspace_path("source", "", "", paths.input),
        _startup_workspace_path("target", "", "", paths.output),
    )


def _yaml_string(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _workspace_setting_for_disk(role: str, path_value: Any, default_path: Path) -> str:
    return ""


def display_path(path_value: Any) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(ROOT)
    except (OSError, ValueError):
        return str(path)
    return str(relative) or "."

def save_app_settings() -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = _workspace_setting_for_disk("source", getattr(settings, "source_path", ""), paths.input)
    destination_path = _workspace_setting_for_disk("target", getattr(settings, "destination_path", ""), paths.output)
    text = (
        "gui:\n"
        "  # Change to \"en\" for public GitHub builds.\n"
        f"  language: \"{settings.language if settings.language in {'en', 'ru'} else 'ru'}\"\n"
        f"  theme: \"{normalize_theme_id(settings.theme)}\"\n"
        f"  emoji: {str(bool(getattr(settings, 'emoji', False))).lower()}\n"
        f"  allow_runtime_switching: {str(bool(getattr(settings, 'allow_runtime_switching', True))).lower()}\n"
        f"  advanced_open: {str(bool(getattr(settings, 'advanced_open', False))).lower()}\n"
        f"  source_path: {_yaml_string(source_path)}\n"
        f"  destination_path: {_yaml_string(destination_path)}\n"
    )
    settings_path.write_text(text, encoding="utf-8", newline="\n")

settings.source_path, settings.destination_path = load_workspace_route_settings()

def _string_map(value: Any) -> dict[str, str]:
    return {str(key).strip(): str(item).strip() for key, item in dict(value).items() if str(key).strip()} if isinstance(value, dict) else {}


def terminal_lines_html(lines: list[str] | tuple[str, ...], leading_newline: bool = False) -> str:
    return _terminal_lines_html(lines, leading_newline=False).replace("\n", "")


def render_terminal_html(lines: list[str] | tuple[str, ...]) -> str:
    return terminal_lines_html(lines) or "&nbsp;"


BUILTIN_THEMES: dict[str, dict[str, Any]] = {
    "code_dark": {
        "label": "Code Dark",
        "label_ru": "Code Темная",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#141413",
            "color-background-secondary": "#1f1e1a",
            "color-background-tertiary": "#0f0f0e",
            "color-text-primary": "#faf9f5",
            "color-text-secondary": "#e8e6dc",
            "color-text-tertiary": "#b0aea5",
            "color-border-tertiary": "rgba(250, 249, 245, 0.15)",
            "color-border-secondary": "rgba(250, 249, 245, 0.3)",
            "color-border-primary": "rgba(250, 249, 245, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "code_graphite": {
        "label": "Code Graphite",
        "label_ru": "Code графит",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#2c2c2a",
            "color-background-secondary": "#34332f",
            "color-background-tertiary": "#141413",
            "color-text-primary": "#faf9f5",
            "color-text-secondary": "#e8e6dc",
            "color-text-tertiary": "#b0aea5",
            "color-border-tertiary": "rgba(250, 249, 245, 0.15)",
            "color-border-secondary": "rgba(250, 249, 245, 0.3)",
            "color-border-primary": "rgba(250, 249, 245, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "code_light": {
        "label": "Code Light",
        "label_ru": "Code светлая",
        "mode": "light",
        "tokens": {
            "color-background-primary": "#faf9f5",
            "color-background-secondary": "#fffdf8",
            "color-background-tertiary": "#f1efe8",
            "color-text-primary": "#141413",
            "color-text-secondary": "#5f5e5a",
            "color-text-tertiary": "#888780",
            "color-border-tertiary": "rgba(20, 20, 19, 0.15)",
            "color-border-secondary": "rgba(20, 20, 19, 0.3)",
            "color-border-primary": "rgba(20, 20, 19, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "code_warm": {
        "label": "Code Warm",
        "label_ru": "Code теплая",
        "mode": "light",
        "tokens": {
            "color-background-primary": "#fffdf8",
            "color-background-secondary": "#faf9f5",
            "color-background-tertiary": "#e8e6dc",
            "color-text-primary": "#141413",
            "color-text-secondary": "#444441",
            "color-text-tertiary": "#888780",
            "color-border-tertiary": "rgba(20, 20, 19, 0.15)",
            "color-border-secondary": "rgba(20, 20, 19, 0.3)",
            "color-border-primary": "rgba(20, 20, 19, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "audion_light": {
        "label": "Audion Light",
        "label_ru": "Audion светлая",
        "mode": "light",
        "tokens": {
            "color-background-primary": "#f7fbff",
            "color-background-secondary": "#ffffff",
            "color-background-tertiary": "#e6f1fb",
            "color-text-primary": "#102033",
            "color-text-secondary": "#36546f",
            "color-text-tertiary": "#6f879c",
            "color-border-tertiary": "rgba(4, 44, 83, 0.15)",
            "color-border-secondary": "rgba(4, 44, 83, 0.3)",
            "color-border-primary": "rgba(4, 44, 83, 0.4)",
            "color-accent-primary": "#378ADD",
            "color-accent-secondary": "#1D9E75",
            "color-accent-tertiary": "#534AB7",
        },
    },
    "audion_dark": {
        "label": "Audion Dark",
        "label_ru": "Audion Темная",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#08131f",
            "color-background-secondary": "#102033",
            "color-background-tertiary": "#050b12",
            "color-text-primary": "#f7fbff",
            "color-text-secondary": "#d7e7f6",
            "color-text-tertiary": "#9bb7cf",
            "color-border-tertiary": "rgba(247, 251, 255, 0.15)",
            "color-border-secondary": "rgba(247, 251, 255, 0.3)",
            "color-border-primary": "rgba(247, 251, 255, 0.4)",
            "color-accent-primary": "#6a9bcc",
            "color-accent-secondary": "#5DCAA5",
            "color-accent-tertiary": "#7F77DD",
        },
    },
    "asar_dark": {
        "label": "Asar Dark",
        "label_ru": "Asar Темная",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#181a1f",
            "color-background-secondary": "#20242b",
            "color-background-tertiary": "#0f1115",
            "color-text-primary": "#f4f7fb",
            "color-text-secondary": "#d6dde7",
            "color-text-tertiary": "#9aa7b8",
            "color-border-tertiary": "rgba(244, 247, 251, 0.15)",
            "color-border-secondary": "rgba(244, 247, 251, 0.3)",
            "color-border-primary": "rgba(244, 247, 251, 0.4)",
            "color-accent-primary": "#85B7EB",
            "color-accent-secondary": "#9FE1CB",
            "color-accent-tertiary": "#CECBF6",
        },
    },
}


def _normalize_theme(theme_id: str, theme_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(theme_data.get("label") or theme_id).strip(),
        "label_ru": str(theme_data.get("label_ru") or theme_data.get("label") or theme_id).strip(),
        "mode": "dark" if str(theme_data.get("mode", "dark")).lower() == "dark" else "light",
        "tokens": _string_map(theme_data.get("tokens", {})),
    }


def builtin_themes() -> dict[str, dict[str, Any]]:
    return {
        theme_id: _normalize_theme(theme_id, theme_data)
        for theme_id, theme_data in BUILTIN_THEMES.items()
    }


def load_ui_colors(path: Path) -> dict[str, Any]:
    data = load_yaml_or_json(path) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    themes: dict[str, dict[str, Any]] = builtin_themes()
    themes_raw = data.get("themes", {})
    if not isinstance(themes_raw, dict):
        themes_raw = {}
    for theme_id, theme_data in themes_raw.items():
        if not isinstance(theme_data, dict):
            continue
        normalized_id = normalize_theme_id(theme_id, default="")
        if not normalized_id:
            continue
        normalized = _normalize_theme(normalized_id, theme_data)
        if normalized_id in themes:
            base = themes[normalized_id]
            normalized["tokens"] = {**_string_map(base.get("tokens", {})), **normalized["tokens"]}
        themes[normalized_id] = normalized
    return {
        "ramps": data.get("ramps", {}) if isinstance(data.get("ramps", {}), dict) else {},
        "tokens": _string_map(data.get("tokens", {})),
        "themes": themes,
    }


ui_colors = load_ui_colors(paths.config / "ui_colors.yaml")


def tolerate_missing_process_pool() -> None:
    """Keep NiceGUI alive when multiprocessing is blocked by the environment.

    NiceGUI initializes a process pool even when the GUI only uses thread/io-bound
    jobs. Some portable, sandboxed, or enterprise Windows environments reject the
    underlying multiprocessing handles, but the shell can still work without CPU
    pool tasks.
    """
    try:
        import nicegui.run as nicegui_run  # type: ignore
    except Exception:
        return

    original_setup = getattr(nicegui_run, "setup", None)
    if not callable(original_setup):
        return

    def safe_setup() -> None:
        try:
            original_setup()
        except (OSError, PermissionError) as exc:
            logging.warning("NiceGUI process pool disabled: %s", exc)
            nicegui_run.process_pool = None

    nicegui_run.setup = safe_setup


tolerate_missing_process_pool()

LABELS = {
    "ru": {
        "workspace": "Рабочие папки",
        "operations": "Операции",
        "maintenance": "Обслуживание",
        "status": "Статус",
        "log": "Журнал операции",
        "idle": "Ожидание",
        "running": "Выполняется",
        "done": "Готово",
        "error": "Ошибка",
        "cancel": "Отменить",
        "another_running": "Другая операция уже выполняется.",
        "confirm_title": "Подтвердите действие",
        "confirm_note": "Действие может изменить управляемую рабочую область.",
        "confirm_target": "Папка: {path}",
        "external_folder_warning": "Внимание: выбранная папка находится вне проекта. Будет очищена именно эта внешняя папка.",
        "run": "Запустить",
        "back": "Назад",
        "selected_operation": "Выбрана команда",
        "open_menu": "Открыть",
        "parameters": "Параметры",
        "advanced": "Дополнительно",
        "trim_no_media": "\u0412 Source \u043d\u0435\u0442 \u0432\u0438\u0434\u0435\u043e",
        "trim_file_previous": "\u041f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0438\u0439 \u0444\u0430\u0439\u043b",
        "trim_file_next": "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0444\u0430\u0439\u043b",
        "trim_probe_hint": "\u0427\u0442\u043e ffprobe \u0437\u043d\u0430\u0435\u0442 \u043e\u0431 \u044d\u0442\u043e\u043c \u0444\u0430\u0439\u043b\u0435",
        "trim_probe_title": "\u0421\u0432\u0435\u0434\u0435\u043d\u0438\u044f \u043e \u0444\u0430\u0439\u043b\u0435",
        "trim_probe_field": "\u041f\u043e\u043b\u0435",
        "trim_probe_value": "\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435",
        "mpv_missing": "Плеер не установлен: install\\Install-Portable-mpv.cmd",
        "mpv_no_file": "Сначала выберите файл выше",
        "mpv_failed": "Плеер не запустился",
        "mpv_opened": "Открыто в плеере",
        "mpv_not_running": "Плеер не открыт",
        "mpv_no_points": "В плеере нет точек A/B: поставьте их клавишей l",
        "mpv_closed": "Плеер закрыт",
        "actions": "Действия",
        "section_audio": "Аудио",
        "section_backend": "Бэкенд кодирования",
        "section_codecs": "Кодеки / цели",
        "section_color": "Цвет",
        "section_decode": "Декодирование",
        "section_encoding": "Кодирование",
        "section_format": "Формат",
        "section_fps": "FPS",
        "section_options": "Опции",
        "section_package": "Упаковка",
        "section_parameters": "Параметры",
        "section_preset": "Профиль",
        "section_run": "Запуск",
        "section_source": "Источник",
        "section_trim": "Обрезка",
        "section_metadata": "Метаданные",
        "section_workflow": "Режим",
        "section_streams": "Потоки",
        "section_mastering": "Мастеринг",
        "section_channels": "Каналы",
        "section_lame": "MP3 / LAME",
        "close": "Закрыть",
        "logs": "Logs",
        "report": "Report",
        "command_preview": "Команда",
        "command_preview_select": "Выберите команду с параметрами для предпросмотра.",
        "command_preview_ready": "Предпросмотр команды построен.",
        "reports": "Отчёты",
        "recent_reports": "Последние операции",
        "open_report_root": "Папка report",
        "open_report": "Report",
        "open_out": "OUT",
        "open_json": "JSON",
        "open_log": "Log",
        "repeat": "Повторить",
        "no_reports": "Отчётов пока нет.",
        "config": "CONFIG",
        "expand": "Развернуть",
        "clear_terminal_window": "Очистить окно терминала",
        "source_path": "Источник",
        "output_path": "Назначение",
        "source_folder": "Источник",
        "target_folder": "Назначение",
        "source_selected": "Источник выбран.",
        "target_selected": "Назначение выбрано.",
        "source_folder_missing": "Источник не найден: {path}",
        "clear_io_short": "Сбросить",
        "delete_io_short": "Удалить",
        "file_list_button": "Список",
        "add_file_short": "Добавить файл...",
        "path_required": "Выберите путь.",
        "path_pinned": "Путь закреплён.",
        "path_unpinned": "Путь откреплён.",
        "path_removed": "Путь удалён из истории.",
        "path_selected": "Путь выбран.",
        "resize_panels": "Изменить ширину панелей",
        "path_cache": "Кэш",
        "pin_path": "Pin",
        "pin_profile": "Pin",
        "choose_path": "Папка...",
        "choose_file": "Выбрать файл",
        "choose_files": "Файлы...",
        "open_path": "Открыть",
        "file_list": "Список файлов",
        "file_list_empty": "В Source нет файлов.",
        "file_list_missing": "Source не найден: {path}",
        "file_list_ready": "Список файлов построен: {count}.",
        "probe_source": "Probe Source",
        "probe_status": "Source probe",
        "probe_not_run": "Probe не выполнен. Нажмите Probe Source.",
        "probe_stale": "Probe устарел после смены Source. Обновите Probe Source.",
        "path_saved": "Путь сохранён.",
        "add_files": "Добавить файлы...",
        "add_folder": "Добавить папку...",
        "stage_files": "Добавление файлов в источник",
        "stage_folder": "Добавление папки в источник",
        "picker_cancelled": "Выбор отменен.",
        "operation_done": "Операция завершена.",
        "operation_failed": "Операция завершилась с кодом {code}.",
        "select_required": "Выберите хотя бы один пункт: {field}",
        "refresh_options": "Обновить список",
        "terminal_command": "Команда",
        "terminal_history": "История команд",
        "terminal_cwd": "CWD",
        "terminal_shell": "Shell",
        "terminal_run": "ВЫПОЛНИТЬ",
        "terminal_file": "Файл",
        "terminal_folder": "Папка",
        "pin_command": "Pin",
        "unpin_command": "Unpin",
        "clear_history": "Очистить",
        "clear_command_cache": "Кэш",
        "terminal_history_empty": "История команд пуста",
        "history_cleared": "История команд очищена; закреплённые команды сохранены.",
        "command_cache_cleared": "Кэш команд очищен.",
        "command_required": "Введите команду.",
        "theme": "Тема",
        "theme_saved": "Тема сохранена. Перезагружаю интерфейс.",
        "lang_switch": "EN",
    },
    "en": {
        "workspace": "Workspace folders",
        "operations": "Operations",
        "maintenance": "Maintenance",
        "status": "Status",
        "log": "Operation log",
        "idle": "Idle",
        "running": "Running",
        "done": "Done",
        "error": "Error",
        "cancel": "Cancel",
        "another_running": "Another operation is already running.",
        "confirm_title": "Confirm action",
        "confirm_note": "This action may change the managed workspace.",
        "confirm_target": "Folder: {path}",
        "external_folder_warning": "Warning: the selected folder is outside the project. This exact external folder will be cleared.",
        "run": "Run",
        "back": "Back",
        "selected_operation": "Selected command",
        "open_menu": "Open",
        "parameters": "Parameters",
        "advanced": "Advanced",
        "trim_no_media": "No video in Source",
        "trim_file_previous": "Previous file",
        "trim_file_next": "Next file",
        "trim_probe_hint": "What ffprobe knows about this file",
        "trim_probe_title": "File details",
        "trim_probe_field": "Field",
        "trim_probe_value": "Value",
        "mpv_missing": "The player is not installed: install\\Install-Portable-mpv.cmd",
        "mpv_no_file": "Choose a file above first",
        "mpv_failed": "The player did not start",
        "mpv_opened": "Opened in the player",
        "mpv_not_running": "The player is not open",
        "mpv_no_points": "No A/B points in the player - set them with the l key",
        "mpv_closed": "The player is closed",
        "actions": "Actions",
        "section_audio": "Audio",
        "section_backend": "Encode backend",
        "section_codecs": "Codecs / targets",
        "section_color": "Color",
        "section_decode": "Decode",
        "section_encoding": "Encoding",
        "section_format": "Format",
        "section_fps": "FPS",
        "section_options": "Options",
        "section_package": "Package",
        "section_parameters": "Parameters",
        "section_preset": "Profile",
        "section_run": "Run",
        "section_source": "Source",
        "section_trim": "Trim",
        "section_metadata": "Metadata",
        "section_workflow": "Workflow",
        "section_streams": "Streams",
        "section_mastering": "Mastering",
        "section_channels": "Channels",
        "section_lame": "MP3 / LAME",
        "close": "Close",
        "logs": "Logs",
        "report": "Report",
        "command_preview": "Command",
        "command_preview_select": "Select a parameterized command to preview.",
        "command_preview_ready": "Command preview generated.",
        "reports": "Reports",
        "recent_reports": "Recent operations",
        "open_report_root": "Report folder",
        "open_report": "Report",
        "open_out": "OUT",
        "open_json": "JSON",
        "open_log": "Log",
        "repeat": "Repeat",
        "no_reports": "No reports yet.",
        "config": "CONFIG",
        "expand": "Expand",
        "clear_terminal_window": "Clear terminal window",
        "source_path": "Source",
        "output_path": "Target",
        "source_folder": "Source",
        "target_folder": "Target",
        "source_selected": "Source selected.",
        "target_selected": "Target selected.",
        "source_folder_missing": "Source was not found: {path}",
        "clear_io_short": "Reset",
        "delete_io_short": "Delete",
        "file_list_button": "List",
        "add_file_short": "Add file...",
        "path_required": "Choose a path.",
        "path_pinned": "Path pinned.",
        "path_unpinned": "Path unpinned.",
        "path_removed": "Path removed from history.",
        "path_selected": "Path selected.",
        "resize_panels": "Resize panels",
        "path_cache": "Cache",
        "pin_path": "Pin",
        "pin_profile": "Pin",
        "choose_path": "Folder...",
        "choose_file": "Choose file",
        "choose_files": "Files...",
        "open_path": "Open",
        "file_list": "File List",
        "file_list_empty": "Source has no files.",
        "file_list_missing": "Source was not found: {path}",
        "file_list_ready": "File list generated: {count}.",
        "probe_source": "Probe Source",
        "probe_status": "Source probe",
        "probe_not_run": "Probe has not been run. Click Probe Source.",
        "probe_stale": "Probe is stale after Source changed. Refresh Probe Source.",
        "path_saved": "Path saved.",
        "add_files": "Add files...",
        "add_folder": "Add folder...",
        "stage_files": "Adding files to source",
        "stage_folder": "Adding folder to source",
        "picker_cancelled": "Selection cancelled.",
        "operation_done": "Operation finished.",
        "operation_failed": "Operation finished with exit code {code}.",
        "select_required": "Select at least one item: {field}",
        "refresh_options": "Refresh list",
        "terminal_command": "Command",
        "terminal_history": "Command history",
        "terminal_cwd": "CWD",
        "terminal_shell": "Shell",
        "terminal_run": "Run",
        "terminal_file": "File",
        "terminal_folder": "Folder",
        "pin_command": "Pin",
        "unpin_command": "Unpin",
        "clear_history": "History",
        "clear_command_cache": "Cache",
        "terminal_history_empty": "Command history is empty",
        "history_cleared": "Command history cleared; pinned commands were kept.",
        "command_cache_cleared": "Command cache cleared.",
        "command_required": "Enter a command.",
        "theme": "Theme",
        "theme_saved": "Theme saved. Reloading UI.",
        "lang_switch": "RU",
    },
}

PICKER_BOOTSTRAP = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AudionDpiAwareness {
  [DllImport("user32.dll")]
  public static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);
  [DllImport("shcore.dll")]
  public static extern int SetProcessDpiAwareness(int value);
}
"@
  try { [AudionDpiAwareness]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null }
  catch { [AudionDpiAwareness]::SetProcessDpiAwareness(2) | Out-Null }
} catch {}
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
"""

TERMINAL_HISTORY_PATH = paths.config / "terminal_commands.json"
TERMINAL_HISTORY_LIMIT = 200
TERMINAL_LINE_LIMIT = 1500


def clean_terminal_commands(items: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(items, list):
        return result
    for item in items:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result[:TERMINAL_HISTORY_LIMIT]


def resolved_terminal_cwd(value: Any) -> str:
    """Absolute terminal CWD, falling back to the project root.

    The project is portable, so a cached folder can outlive the copy that produced it.
    A relative value is read against the current ROOT, and anything that is no longer a
    directory resets to the start state instead of failing on the first command.
    """
    text = str(value or "").strip()
    if not text:
        return str(ROOT)
    candidate = Path(os.path.expandvars(text)).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        return str(ROOT)
    return str(candidate) if candidate.is_dir() else str(ROOT)


def stored_terminal_cwd(value: Any) -> str:
    """Terminal CWD as written to disk: project-local folders stay relative to ROOT."""
    resolved = Path(resolved_terminal_cwd(value))
    try:
        return str(resolved.relative_to(Path(ROOT).resolve()))
    except ValueError:
        return str(resolved)


def load_terminal_cache() -> dict[str, Any]:
    default = {"history": [], "pinned": [], "last": "", "shell": "pwsh" if os.name == "nt" else "sh", "cwd": str(ROOT)}
    if not TERMINAL_HISTORY_PATH.exists():
        return default
    try:
        raw = json.loads(TERMINAL_HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Could not load terminal command history: %s", exc)
        return default
    if not isinstance(raw, dict):
        return default
    shell = str(raw.get("shell") or default["shell"]).strip().lower()
    if os.name == "nt":
        if shell not in {"pwsh", "cmd"}:
            shell = "pwsh"
    else:
        shell = "sh"
    return {
        "history": clean_terminal_commands(raw.get("history", [])),
        "pinned": clean_terminal_commands(raw.get("pinned", [])),
        "last": str(raw.get("last") or "").strip(),
        "shell": shell,
        "cwd": resolved_terminal_cwd(raw.get("cwd")),
    }


initial_terminal_cache = load_terminal_cache()

state: dict[str, Any] = {
    "running": False,
    "cancel": False,
    "progress": 0.0,
    "status": "",
    "lines": [],
    "terminal_base": 0,
    "terminal_seq": 0,
    "terminal_epoch": 0,
    "terminal_scroll_top_seq": 0,
    "log_version": 0,
    "exit_code": None,
    "command_path": [],
    "pending_command": None,
    "field_values": {},
    "applied_profiles": {},
    "source_path": str(cached_source_path(ROOT)),
    "destination_path": str(cached_output_path(ROOT)),
    "lut_cache": lut_cache,
    "probe_summary": "",
    "probe_source_path": "",
    "probe_updated_at": "",
    "last_report_dir": str(paths.report),
    "terminal_cache": initial_terminal_cache,
    "terminal_command": str(initial_terminal_cache.get("last") or ""),
    "terminal_shell": str(initial_terminal_cache.get("shell") or ("pwsh" if os.name == "nt" else "sh")),
    "terminal_cwd": str(initial_terminal_cache.get("cwd") or ROOT),
    "workspace_feedback": {},
}

dynamic_option_cache: dict[str, tuple[float, list[Any]]] = {}
hardware_badge_cache: tuple[float, dict[str, Any]] | None = None
HARDWARE_BADGE_CACHE_SECONDS = 300.0

SOURCE_INFO_OPERATION_ID = "source_info"
SOURCE_INFO_COMMAND_ROOTS = {"audio", "archive", "editing", "storage", "delivery", "remux", "fps", "grading"}
SOURCE_INFO_COMMAND_IDS = SOURCE_INFO_COMMAND_ROOTS | {"audio_run", "archive_run", "editing_run", "storage_run", "delivery_run", "remux_run", "fps_run", "grading_run"}

TOOLTIP_SHOW_DELAY_MS = 1500
TOOLTIP_HIDE_DELAY_MS = 100

VIDEO_REMUX_SOURCE_FORMATS = ("mp4", "mov", "mkv", "mxf", "avi", "webm", "mts", "m2ts")
AUDIO_REMUX_SOURCE_FORMATS = (
    "mp4",
    "mov",
    "mkv",
    "mxf",
    "avi",
    "webm",
    "mts",
    "m2ts",
    "m4a",
    "mka",
    "aac",
    "ac3",
    "eac3",
    "dts",
    "flac",
    "wav",
    "mp3",
    "opus",
    "ogg",
)

VIDEO_REMUX_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "mp4": ("mp4", "mov", "mkv"),
    "mov": ("mov", "mp4", "mkv", "mxf"),
    "mkv": ("mkv", "mp4", "mov"),
    "mxf": ("mxf", "mov", "mkv"),
    "avi": ("avi", "mkv"),
    "webm": ("webm", "mkv"),
    "mts": ("mp4", "mkv"),
    "m2ts": ("mp4", "mkv"),
}

AUDIO_REMUX_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "mp4": ("m4a", "aac", "mka"),
    "mov": ("m4a", "aac", "wav", "mka"),
    "mkv": ("mka",),
    "mxf": ("wav", "mka"),
    "avi": ("wav", "mp3", "mka"),
    "webm": ("opus", "ogg", "mka"),
    "mts": ("aac", "ac3", "eac3", "mka"),
    "m2ts": ("aac", "ac3", "eac3", "mka"),
    "m4a": ("m4a", "alac", "aac", "mka"),
    "mka": ("mka",),
    "aac": ("aac", "m4a", "mka"),
    "ac3": ("ac3", "mka"),
    "eac3": ("eac3", "mka"),
    "dts": ("dts", "mka"),
    "flac": ("flac", "mka"),
    "wav": ("wav", "mka"),
    "mp3": ("mp3", "mka"),
    "opus": ("opus", "ogg", "mka"),
    "ogg": ("ogg", "opus", "mka"),
}


def tr(key: str, **kwargs: Any) -> str:
    lang = settings.language if settings.language in LABELS else "en"
    text = LABELS.get(lang, LABELS["en"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


def add_tooltip(element: Any, text: str) -> Any:
    tooltip_text = str(text or "").strip()
    if not tooltip_text:
        return element
    element.props["data-audion-tooltip"] = tooltip_text
    return element


def em(key: str) -> str:
    if not bool(getattr(settings, "emoji", False)):
        return ""
    return {
        "workspace": "📁 ",
        "operations": "⚙ ",
        "maintenance": "🧰 ",
        "status": "● ",
        "log": "🖥 ",
    }.get(key, "")


def app_title() -> str:
    title = str(ui_info.get("title") or tool_info.get("name") or "Audion GUI Tool")
    return title[:-3] if title.endswith(" UI") else title


def active_theme() -> str:
    theme_id = normalize_theme_id(settings.theme)
    themes = ui_colors["themes"]
    if theme_id in themes:
        return theme_id
    return DEFAULT_THEME_ID if DEFAULT_THEME_ID in themes else next(iter(themes))


def active_theme_data() -> dict[str, Any]:
    return dict(ui_colors["themes"][active_theme()])


def active_theme_mode() -> str:
    return str(active_theme_data().get("mode", "dark"))


def theme_label(theme_id: str) -> str:
    theme_data = ui_colors["themes"].get(theme_id, {})
    label_key = "label_ru" if settings.language == "ru" else "label"
    return str(theme_data.get(label_key) or theme_data.get("label") or theme_id)


def theme_options() -> dict[str, str]:
    return {theme_id: theme_label(theme_id) for theme_id in ui_colors["themes"]}


def set_theme(theme_id: Any) -> None:
    selected = normalize_theme_id(theme_id)
    if selected not in ui_colors["themes"]:
        return
    settings.theme = selected
    save_app_settings()
    safe_notify(tr("theme_saved"), "positive")
    ui.run_javascript("window.location.reload()")


def theme_change_handler(event: Any) -> None:
    set_theme(getattr(event, "value", None))


def theme_variables() -> dict[str, str]:
    variables: dict[str, str] = {}
    for ramp_name, stops in ui_colors["ramps"].items():
        if not isinstance(stops, dict):
            continue
        for stop, color in stops.items():
            variables[f"color-{ramp_name}-{stop}"] = str(color).strip()
    variables.update(ui_colors["tokens"])
    variables.update(_string_map(active_theme_data().get("tokens", {})))
    variables.setdefault("color-background-primary", "#141413")
    variables.setdefault("color-background-secondary", "#1f1e1a")
    variables.setdefault("color-background-tertiary", "#0f0f0e")
    variables.setdefault("color-text-primary", "#faf9f5")
    variables.setdefault("color-text-secondary", "#e8e6dc")
    variables.setdefault("color-text-tertiary", "#b0aea5")
    variables.setdefault("color-border-tertiary", "rgba(250, 249, 245, 0.15)")
    variables.setdefault("color-border-secondary", "rgba(250, 249, 245, 0.3)")
    variables.setdefault("color-border-primary", "rgba(250, 249, 245, 0.4)")
    variables.setdefault("color-accent-primary", "#d97757")
    variables.setdefault("font-sans", "Inter, Segoe UI, Arial, sans-serif")
    variables.setdefault("font-mono", "Cascadia Mono, Consolas, monospace")
    variables.setdefault("border-radius-md", "10px")
    variables.setdefault("border-radius-lg", "14px")
    variables.setdefault(
        "color-active-button-text",
        "#e6e6e6" if active_theme_mode() == "dark" else "#3f3f46",
    )
    return variables


def add_log(message: str) -> None:
    if message is None:
        return
    text = str(message).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    new_lines = text.split("\n") if text else [""]
    state["lines"].extend(new_lines)
    state["terminal_seq"] = int(state.get("terminal_seq", 0)) + len(new_lines)
    state["lines"] = state["lines"][-TERMINAL_LINE_LIMIT:]
    state["terminal_base"] = int(state.get("terminal_seq", 0)) - len(state["lines"])
    state["log_version"] = int(state["log_version"]) + 1


def clear_terminal_log() -> None:
    state["lines"] = []
    state["terminal_base"] = 0
    state["terminal_seq"] = 0
    state["terminal_epoch"] = int(state.get("terminal_epoch", 0)) + 1
    state["log_version"] = int(state["log_version"]) + 1


def terminal_lines_block_html(lines: list[str] | tuple[str, ...], *, renderer: AnsiHtmlRenderer | None = None) -> str:
    active_renderer = renderer or AnsiHtmlRenderer()
    return "".join(
        f'<span class="audion-terminal-line">{active_renderer.render(str(line))}</span>'
        for line in lines
    )


def terminal_html() -> str:
    lines = tuple(str(line) for line in state["lines"][-TERMINAL_LINE_LIMIT:])
    return f'<pre class="audion-terminal-pre">{terminal_lines_block_html(lines)}</pre>'


def terminal_delta_html(start_index: int) -> str:
    lines = tuple(str(line) for line in state["lines"][-TERMINAL_LINE_LIMIT:])
    if start_index < 0:
        start_index = 0
    if start_index > len(lines):
        start_index = len(lines)
    renderer = AnsiHtmlRenderer()
    if start_index:
        renderer.render("\n".join(lines[:start_index]))
    return terminal_lines_block_html(lines[start_index:], renderer=renderer)


def progress_text() -> str:
    return f"{round(max(0.0, min(1.0, float(state['progress']))) * 100):.0f}%"


def probe_status_text() -> str:
    summary = str(state.get("probe_summary") or "").strip()
    source_path = str(role_path("source"))
    probed_source = str(state.get("probe_source_path") or "").strip()
    if summary and probed_source and probed_source != source_path:
        return tr("probe_stale")
    return summary


def safe_notify(message: str, kind: str = "info", **notify_kwargs: Any) -> None:
    notify_type = str(notify_kwargs.pop("type", kind))
    options = {"message": str(message), "type": notify_type, **notify_kwargs}
    delivered = False
    for client in list(nicegui_app.clients()):
        if getattr(client, "_deleted", False) or not client.has_socket_connection:
            continue
        try:
            client.outbox.enqueue_message("notify", options, client.id)
            delivered = True
        except Exception as exc:
            logging.warning("NiceGUI notification delivery failed for client %s: %s", getattr(client, "id", "?"), exc)
    if delivered:
        return

    try:
        ui.notify(message, type=notify_type, **notify_kwargs)
    except RuntimeError as exc:
        message_text = str(exc)
        if "slot belongs to has been deleted" not in message_text and "current slot cannot be determined" not in message_text:
            raise
        logging.warning("NiceGUI notification skipped because no live client slot was available: %s", message)


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def danger_context(operation: Operation) -> tuple[str, bool]:
    if operation.id == "cleanup_source":
        source = role_path("source")
        return tr("confirm_target", path=str(source)), not path_is_inside(source, ROOT)
    if operation.id == "cleanup_transcoded":
        output = role_path("output")
        return tr("confirm_target", path=str(output)), not path_is_inside(output, ROOT)
    return "", False


RUN_STATE_LABELS = {
    "idle": ("idle", "audion-status-idle"),
    "running": ("running", "audion-status-running"),
    "done": ("done", "audion-status-done"),
    "error": ("error", "audion-status-error"),
}


def run_state() -> str:
    """Which of the four states the panel is showing.

    Colour carries this everywhere it appears, so it is decided once.
    """
    if bool(state["running"]):
        return "running"
    exit_code = state.get("exit_code")
    if exit_code is None:
        return "idle"
    return "done" if int(exit_code or 0) == 0 else "error"


def status_row_classes() -> str:
    return f"audion-status-row {RUN_STATE_LABELS[run_state()][1]}"


def status_state_text() -> str:
    return tr(RUN_STATE_LABELS[run_state()][0]).upper()


def elapsed_text(seconds: float | None) -> str:
    """A run's own clock, mm:ss, or an em dash before anything has run.

    The start is noticed by the refresh timer rather than written by the code that
    starts a run: there are several such places, and none of them has to know
    about the panel.
    """
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def status_dot_classes() -> str:
    base = "audion-status-dot text-lg leading-none"
    if bool(state["running"]):
        return f"{base} text-sky-400 animate-pulse"
    if state.get("exit_code") is None:
        return f"{base} text-gray-500"
    if int(state.get("exit_code") or 0) == 0:
        return f"{base} text-green-400"
    return f"{base} text-red-400"


def set_progress(value: float) -> None:
    state["progress"] = max(0.0, min(1.0, float(value)))


def cancel_requested() -> bool:
    return bool(state["cancel"])


def hidden_subprocess_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def resolve_dialog_powershell() -> list[str]:
    candidates = [
        [str(paths.system_core / "powershell" / "pwsh.exe"), "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command"],
    ]
    for candidate in candidates:
        exe = candidate[0]
        if Path(exe).exists() or shutil.which(exe):
            return candidate
    raise RuntimeError("PowerShell was not found for Windows picker.")


def parse_picker_paths(text: str) -> list[Path]:
    import json

    payload = text.strip()
    if not payload:
        return []
    data = json.loads(payload)
    if isinstance(data, str):
        data = [data]
    return [Path(str(item)).resolve() for item in data if str(item).strip()]


def hidden_subprocess_kwargs() -> dict[str, Any]:
    return {
        "creationflags": hidden_subprocess_flags(),
        "startupinfo": hidden_subprocess_startupinfo(),
    }


_PICKER_RUN_LOCK = threading.Lock()
_PICKER_JOB_LOCK = threading.Lock()
_PICKER_SHUTDOWN = threading.Event()
_PICKER_JOB_HANDLE: int | None = None


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def close_picker_job() -> None:
    global _PICKER_JOB_HANDLE
    _PICKER_SHUTDOWN.set()
    with _PICKER_JOB_LOCK:
        handle = _PICKER_JOB_HANDLE
        _PICKER_JOB_HANDLE = None
    if os.name == "nt" and handle:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(wintypes.HANDLE(handle))


def _picker_job_handle() -> int | None:
    global _PICKER_JOB_HANDLE
    if os.name != "nt" or _PICKER_SHUTDOWN.is_set():
        return None
    with _PICKER_JOB_LOCK:
        if _PICKER_SHUTDOWN.is_set():
            return None
        if _PICKER_JOB_HANDLE:
            return _PICKER_JOB_HANDLE
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            logging.warning("Could not create the Windows picker job: %s", ctypes.get_last_error())
            return None
        info = _JobObjectExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(wintypes.HANDLE(job))
            logging.warning("Could not configure the Windows picker job: %s", error)
            return None
        _PICKER_JOB_HANDLE = int(job)
        return _PICKER_JOB_HANDLE


def _assign_picker_to_job(process: subprocess.Popen[str]) -> None:
    handle = _picker_job_handle()
    if os.name != "nt" or not handle:
        if _PICKER_SHUTDOWN.is_set() and process.poll() is None:
            process.kill()
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel32.AssignProcessToJobObject(
        wintypes.HANDLE(handle),
        wintypes.HANDLE(int(process._handle)),  # type: ignore[attr-defined]
    ):
        logging.warning("Could not attach picker PID %s to its Windows job: %s", process.pid, ctypes.get_last_error())


def run_picker_script(script: str, error_message: str) -> list[Path]:
    if not _PICKER_RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("A Windows picker is already open.")
    process: subprocess.Popen[str] | None = None
    try:
        if _PICKER_SHUTDOWN.is_set():
            raise RuntimeError("Windows picker supervisor is shutting down.")
        _picker_job_handle()
        process = subprocess.Popen(
            [*resolve_dialog_powershell(), script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        _assign_picker_to_job(process)
        if _PICKER_SHUTDOWN.is_set():
            if process.poll() is None:
                process.kill()
            raise RuntimeError("Windows picker supervisor is shutting down.")
        try:
            stdout, stderr = process.communicate(timeout=3600)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise RuntimeError("Windows picker timed out.") from exc
        if process.returncode != 0:
            raise RuntimeError(stderr.strip() or error_message)
        return parse_picker_paths(stdout)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        _PICKER_RUN_LOCK.release()


atexit.register(close_picker_job)
nicegui_app.on_shutdown(close_picker_job)


def close_media_player() -> None:
    """A player window that outlives the panel is a leak, like any other."""
    from system_core.services import mpv_service

    mpv_service.close_player()


atexit.register(close_media_player)
nicegui_app.on_shutdown(close_media_player)


def pick_files() -> list[Path]:
    script = PICKER_BOOTSTRAP + r"""
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose source files'
$dialog.Multiselect = $true
$dialog.Filter = 'All supported files|*.*|All files|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  $dialog.FileNames | ConvertTo-Json -Compress
}
"""
    return run_picker_script(script, "File picker failed.")


def pick_lut_files() -> list[Path]:
    title = "Выберите LUT-файлы" if settings.language == "ru" else "Choose LUT files"
    script = PICKER_BOOTSTRAP + f"""
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = {ps_quote(title)}
$dialog.Multiselect = $true
$dialog.CheckFileExists = $true
$dialog.Filter = 'LUT files (*.cube;*.3dl;*.lut)|*.cube;*.3dl;*.lut|All files (*.*)|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  $dialog.FileNames | ConvertTo-Json -Compress
}}
"""
    return run_picker_script(script, "LUT file picker failed.")


def pick_folder() -> list[Path]:
    script = PICKER_BOOTSTRAP + r"""
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Choose source folder'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  @($dialog.SelectedPath) | ConvertTo-Json -Compress
}
"""
    return run_picker_script(script, "Folder picker failed.")


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def pick_one_folder(title: str, initial: str = "") -> Path | None:
    initial_path = Path(initial).expanduser() if initial else None
    selected_path = str(initial_path) if initial_path and initial_path.exists() else ""
    script = PICKER_BOOTSTRAP + f"""
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = {ps_quote(title)}
$dialog.ShowNewFolderButton = $true
if ({ps_quote(selected_path)} -ne '') {{
  $dialog.SelectedPath = {ps_quote(selected_path)}
}}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  @($dialog.SelectedPath) | ConvertTo-Json -Compress
}}
"""
    selected = run_picker_script(script, "Folder picker failed.")
    return selected[0] if selected else None


def pick_one_file(title: str, initial: str = "", file_filter: str = "Text files (*.txt)|*.txt|All files (*.*)|*.*") -> Path | None:
    initial_path = Path(initial).expanduser() if initial else None
    if initial_path and not initial_path.is_absolute():
        initial_path = ROOT / initial_path
    initial_dir = ""
    initial_file = ""
    if initial_path:
        if initial_path.is_file():
            initial_dir = str(initial_path.parent)
            initial_file = initial_path.name
        elif initial_path.parent.exists():
            initial_dir = str(initial_path.parent)
            initial_file = initial_path.name
        elif initial_path.exists():
            initial_dir = str(initial_path)
    script = PICKER_BOOTSTRAP + f"""
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = {ps_quote(title)}
$dialog.Multiselect = $false
$dialog.CheckFileExists = $true
$dialog.Filter = {ps_quote(file_filter)}
if ({ps_quote(initial_dir)} -ne '') {{
  $dialog.InitialDirectory = {ps_quote(initial_dir)}
}}
if ({ps_quote(initial_file)} -ne '') {{
  $dialog.FileName = {ps_quote(initial_file)}
}}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  @($dialog.FileName) | ConvertTo-Json -Compress
}}
"""
    selected = run_picker_script(script, "File picker failed.")
    return selected[0] if selected else None


def file_field_click_handler(field: dict[str, Any], control: Any):
    async def handler() -> None:
        key = field_id(field)
        if not key:
            return
        title = field_label(field) or tr("choose_file")
        initial = str(current_field_value(field) or field_default(field) or "")
        file_filter = str(field.get("file_filter") or "All files (*.*)|*.*")
        try:
            selected = await run.io_bound(pick_one_file, title, initial, file_filter)
        except Exception as exc:
            safe_notify(str(exc), "negative")
            return
        if selected is None:
            safe_notify(tr("picker_cancelled"), "warning")
            return
        value = str(selected)
        set_field_value(key, value)
        control.set_value(value)

    return handler


PATH_HISTORY_LIMIT = 100


def _resolve_workspace_path(value: Any, fallback: Path) -> Path:
    text = str(value or "").strip().strip('"')
    path = Path(text).expanduser() if text else fallback
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def current_source_path() -> Path:
    return _resolve_workspace_path(state.get("source_path") or getattr(settings, "source_path", ""), paths.input)


def current_target_path() -> Path:
    return _resolve_workspace_path(state.get("destination_path") or getattr(settings, "destination_path", ""), paths.output)


def role_path(role: str) -> Path:
    return current_source_path() if role == "source" else current_target_path()


def active_project_paths():
    return replace(paths, input=current_source_path(), output=current_target_path())


def _hardware_capture(command: list[str], timeout: float = 10.0) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=hidden_subprocess_flags(),
            startupinfo=hidden_subprocess_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip()


def _hardware_cpu_name() -> str:
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-Command",
        "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name).Trim()",
    ]
    return _hardware_capture(command) or os.environ.get("PROCESSOR_IDENTIFIER", "CPU")


def _hardware_video_controllers() -> list[str]:
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }",
    ]
    return [line.strip() for line in _hardware_capture(command).splitlines() if line.strip()]


def _hardware_nvidia_info() -> tuple[str, str]:
    output = _hardware_capture(["nvidia-smi.exe", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    if not output:
        return "", ""
    first = output.splitlines()[0]
    parts = [part.strip() for part in first.split(",", 1)]
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _hardware_ffmpeg_version() -> str:
    executable = ROOT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    line = _hardware_capture([str(executable), "-version"]).splitlines()
    if not line:
        return "missing"
    match = re.search(r"ffmpeg version\s+([^\s]+)", line[0], re.IGNORECASE)
    return match.group(1) if match else line[0].strip()


def _hardware_smoke_summary() -> str:
    cache_path = ROOT / "config" / "hardware_capabilities_cache.json"
    if not cache_path.exists():
        return ""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    if not isinstance(summary, dict):
        return ""
    return f"OK {int(summary.get('ok', 0) or 0)}, MISS {int(summary.get('miss', 0) or 0)}, FAIL {int(summary.get('fail', 0) or 0)}"


def hardware_badge_data(force: bool = False) -> dict[str, Any]:
    global hardware_badge_cache
    now = time.monotonic()
    if not force and hardware_badge_cache and now - hardware_badge_cache[0] < HARDWARE_BADGE_CACHE_SECONDS:
        return dict(hardware_badge_cache[1])

    controllers = _hardware_video_controllers()
    nvidia_name, nvidia_driver = _hardware_nvidia_info()
    gpu_name = nvidia_name or next((name for name in controllers if re.search(r"NVIDIA|GeForce|Radeon|AMD|Intel|Iris|Arc", name, re.IGNORECASE)), "")
    cpu_name = _hardware_cpu_name()
    ffmpeg_version = _hardware_ffmpeg_version()
    smoke = _hardware_smoke_summary()
    low = gpu_name.lower()
    is_nvidia = bool(re.search(r"nvidia|geforce|rtx|gtx", low))
    is_amd = bool(re.search(r"amd|radeon", low))
    is_intel = bool(re.search(r"intel|iris|arc", low))
    tone = "nvidia" if is_nvidia else "amd" if is_amd else "intel" if is_intel else "cpu"

    nvidia_driver_version: tuple[int, int] | None = None
    if nvidia_driver:
        match = re.match(r"\s*(\d+)(?:\.(\d+))?", nvidia_driver)
        if match:
            nvidia_driver_version = (int(match.group(1)), int(match.group(2) or 0))

    if settings.language == "ru":
        if is_nvidia:
            headline = "NVIDIA RTX 50xx обнаружена" if re.search(r"RTX\s*50\d{2}", gpu_name, re.IGNORECASE) else "NVIDIA GPU обнаружена"
            if nvidia_driver_version is None:
                short = "Сначала определите версию драйвера NVIDIA"
            elif nvidia_driver_version >= (570, 0):
                short = "Рекомендовано: NVENC + latest BtbN Stable 8.x"
            elif nvidia_driver_version >= (471, 41):
                short = "Рекомендовано: NVENC + BtbN Stable 7.1.x"
            else:
                short = "Обновите драйвер NVIDIA для NVENC"
            driver_text = f"Драйвер {nvidia_driver or 'не определён'}"
        elif is_amd:
            headline, short, driver_text = "AMD GPU обнаружена", "Рекомендовано: AMF после capability smoke", "Драйвер AMD определяет доступные VCN-кодеки"
        elif is_intel:
            headline, short, driver_text = "Intel GPU обнаружена", "Рекомендовано: QSV после capability smoke", "Media SDK/oneVPL выбирается по поколению GPU"
        else:
            headline, short, driver_text = "Аппаратный видеокодер не распознан", "Рекомендовано: CPU-кодирование", "Запустите Hardware capabilities для проверки"
        smoke_text = f"Hardware smoke: {smoke}." if smoke else "Hardware smoke ещё не запускался."
    else:
        if is_nvidia:
            headline = "NVIDIA RTX 50xx detected" if re.search(r"RTX\s*50\d{2}", gpu_name, re.IGNORECASE) else "NVIDIA GPU detected"
            if nvidia_driver_version is None:
                short = "Determine the NVIDIA driver version first"
            elif nvidia_driver_version >= (570, 0):
                short = "Recommended: NVENC + latest BtbN Stable 8.x"
            elif nvidia_driver_version >= (471, 41):
                short = "Recommended: NVENC + BtbN Stable 7.1.x"
            else:
                short = "Update the NVIDIA driver for NVENC"
            driver_text = f"Driver {nvidia_driver or 'unknown'}"
        elif is_amd:
            headline, short, driver_text = "AMD GPU detected", "Recommended: AMF after capability smoke", "AMD driver controls available VCN codecs"
        elif is_intel:
            headline, short, driver_text = "Intel GPU detected", "Recommended: QSV after capability smoke", "Media SDK/oneVPL depends on GPU generation"
        else:
            headline, short, driver_text = "Hardware video encoder not identified", "Recommended: CPU encoding", "Run Hardware capabilities to verify"
        smoke_text = f"Hardware smoke: {smoke}." if smoke else "Hardware smoke has not run yet."

    data = {
        "tone": tone,
        "headline": headline,
        "gpu": gpu_name or ("GPU не найдена" if settings.language == "ru" else "GPU not found"),
        "cpu": cpu_name,
        "short": short,
        "details": f"{driver_text}. FFmpeg {ffmpeg_version}. {smoke_text}",
    }
    hardware_badge_cache = (now, dict(data))
    return data


def refresh_hardware_badge() -> None:
    hardware_badge_data(force=True)
    hardware_badge.refresh()


@ui.refreshable
def hardware_badge() -> None:
    data = hardware_badge_data()
    tone = str(data.get("tone") or "cpu")
    refresh_title = "Обновить GPU/CPU" if settings.language == "ru" else "Refresh GPU/CPU"
    with ui.element("div").props('data-testid="hardware-badge"').classes(f"audion-hardware-badge audion-hardware-badge-{tone}"):
        with ui.element("div").classes("audion-hardware-main"):
            with ui.row().classes("audion-hardware-headline w-full items-center gap-2"):
                ui.icon("memory").classes("audion-hardware-icon")
                ui.label(str(data.get("headline") or "")).classes("audion-hardware-title")
            ui.label(str(data.get("gpu") or "")).classes("audion-hardware-gpu")
            ui.label(str(data.get("short") or "")).classes("audion-hardware-recommendation")
        with ui.element("div").classes("audion-hardware-side"):
            with ui.row().classes("audion-hardware-side-top w-full items-center gap-2"):
                ui.label(str(data.get("cpu") or "")).classes("audion-hardware-cpu")
                ui.space()
                refresh_button = ui.button(icon="refresh", on_click=refresh_hardware_badge).props("dense flat round")
                refresh_button.classes("audion-action audion-hardware-refresh")
                add_tooltip(refresh_button, refresh_title)
            ui.label(str(data.get("details") or "")).classes("audion-hardware-details")


def save_workspace_path(kind: str, value: Any) -> None:
    text = str(value or "").strip()
    if kind == "source":
        selected = str(_resolve_workspace_path(text, paths.input))
        settings.source_path = ""
        state["source_path"] = selected
        update_path_cache(ROOT, "source", selected)
        state["probe_summary"] = ""
        state["probe_source_path"] = selected
        state["probe_updated_at"] = ""
    elif kind == "destination":
        selected = str(_resolve_workspace_path(text, paths.output))
        settings.destination_path = ""
        state["destination_path"] = selected
        update_path_cache(ROOT, "output", selected)
    else:
        raise RuntimeError(f"Unknown workspace path kind: {kind}")
    save_app_settings()


def reload_ui(delay_ms: int = 0) -> None:
    delay = max(0, int(delay_ms))
    ui.run_javascript(f"window.setTimeout(() => window.location.reload(), {delay})")


def toggle_language() -> None:
    settings.language = "en" if settings.language == "ru" else "ru"
    save_app_settings()
    reload_ui()


def open_workspace_folder(role: str) -> None:
    target = current_target_path() if role == "target" else current_source_path()
    if target.is_file():
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", f"/select,{target}"], **hidden_subprocess_kwargs())
        else:
            open_folder(target.parent)
        return
    target.mkdir(parents=True, exist_ok=True)
    open_folder(target)


def mark_workspace_feedback(role: str, action: str) -> None:
    state["workspace_feedback"] = {"role": canonical_role(role), "action": str(action or "path")}


def _save_workspace_adapter_path(role: WorkbenchRole, value: Any) -> None:
    save_workspace_path("destination" if role == "target" else "source", value)


def _workspace_feedback() -> dict[str, str]:
    value = state.get("workspace_feedback")
    return dict(value) if isinstance(value, dict) else {}


def _clear_workspace_feedback() -> None:
    state["workspace_feedback"] = {}


WORKBENCH_CONFIG = WorkbenchConfig(
    root=ROOT,
    input_path=paths.input,
    output_path=paths.output,
    history_path=_workspace_history_file(),
    history_limit=PATH_HISTORY_LIMIT,
)
WORKBENCH_ADAPTER = WorkbenchAdapter(
    config=WORKBENCH_CONFIG,
    current_path_callback=lambda role: current_target_path() if role == "target" else current_source_path(),
    save_path_callback=_save_workspace_adapter_path,
    language_callback=lambda: settings.language,
    translate_callback=tr,
    log_callback=add_log,
    notify_callback=safe_notify,
    reload_callback=reload_ui,
    busy_callback=lambda: bool(state.get("running")),
    feedback_callback=_workspace_feedback,
    set_feedback_callback=mark_workspace_feedback,
    clear_feedback_callback=_clear_workspace_feedback,
)
WORKBENCH_ADAPTER.validate()
WORKBENCH_ADAPTER.ensure_initial_history()


def workspace_pin_click_handler(role: str, pinned: bool):
    async def handler() -> None:
        path_value = str(current_target_path() if role == "target" else current_source_path())
        if not path_value:
            safe_notify(tr("path_required"), "warning")
            return
        try:
            await run.io_bound(WORKBENCH_ADAPTER.set_path_pinned, role, path_value, pinned)
            mark_workspace_feedback(role, "pin" if pinned else "unpin")
            add_log(f"{'Pinned' if pinned else 'Unpinned'} {role} path: {path_value}")
            reload_ui(100)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def workspace_delete_path_click_handler(role: str):
    async def handler() -> None:
        operation_id = "cleanup_transcoded" if role == "target" else "cleanup_source"
        operation = operation_by_id(operation_id)
        if operation is None:
            safe_notify(f"Operation not found: {operation_id}", "negative")
            return
        await start_operation(operation)

    return handler


def workspace_open_click_handler(role: str):
    async def handler() -> None:
        try:
            await run.io_bound(open_workspace_folder, role)
            add_log(f"Opened {'target' if role == 'target' else 'source'}: {current_target_path() if role == 'target' else current_source_path()}")
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def reset_workspace_paths_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        result = await run.io_bound(WORKBENCH_ADAPTER.clear_path_history_cache_keep_pins)
        save_workspace_path("source", "")
        save_workspace_path("destination", "")
        add_log(f"Workspace route reset: SOURCE -> {paths.input}")
        add_log(f"Workspace route reset: TARGET -> {paths.output}")
        add_log(
            "Workspace path cache cleared: "
            f"sources={result.get('removed_sources', 0)}, targets={result.get('removed_targets', 0)}, "
            f"pins kept={result.get('kept_pins', 0)}"
        )
        safe_notify(tr("operation_done"), "positive")
        reload_ui(100)

    return handler


def workspace_path_select_handler(role: str):
    async def handler(event: Any) -> None:
        path_value = str(getattr(event, "value", "") or "").strip()
        if not path_value:
            return
        save_workspace_path("destination" if role == "target" else "source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role, path_value)
        mark_workspace_feedback(role, "path")
        add_log(f"{'TARGET' if role == 'target' else 'SOURCE'} -> {path_value}")
        reload_ui(100)

    return handler


def workspace_pick_click_handler(role: str):
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        try:
            selected = await run.io_bound(pick_folder)
        except Exception as exc:
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        path_value = str(selected[0])
        save_workspace_path("destination" if role == "target" else "source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role, path_value)
        mark_workspace_feedback(role, "path")
        add_log(f"{'TARGET' if role == 'target' else 'SOURCE'} -> {path_value}")
        safe_notify(tr("target_selected") if role == "target" else tr("source_selected"), "positive")
        reload_ui(100)

    return handler


def workspace_single_file_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        try:
            selected = await run.io_bound(
                pick_one_file,
                "Выберите файл-источник" if settings.language == "ru" else "Select source file",
                str(current_source_path()),
                "All files (*.*)|*.*",
            )
        except Exception as exc:
            safe_notify(str(exc), "negative")
            return
        if selected is None:
            add_log(tr("picker_cancelled"))
            return
        path_value = str(selected)
        save_workspace_path("source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, "source", path_value)
        mark_workspace_feedback("source", "path")
        add_log(f"SOURCE FILE -> {path_value}")
        reload_ui(100)

    return handler


def workspace_delete_both_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        source_operation = operation_by_id("cleanup_source")
        target_operation = operation_by_id("cleanup_transcoded")
        if source_operation is None or target_operation is None:
            safe_notify("Cleanup operations are missing.", "negative")
            return
        with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-confirm-card rounded-lg"):
            ui.label("Удалить содержимое Source и OUT?" if settings.language == "ru" else "Delete Source and OUT contents?").classes("text-base font-semibold")
            ui.label(str(current_source_path())).classes("break-all font-mono text-xs text-gray-400")
            ui.label(str(current_target_path())).classes("break-all font-mono text-xs text-gray-400")
            with ui.row().classes("w-full items-center justify-end gap-2"):
                ui.button(tr("cancel"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg")
                ui.button(tr("delete_io_short"), on_click=lambda: dialog.submit(True)).props("dense color=negative")
        if not await dialog:
            return
        await start_operation(source_operation, skip_confirmation=True)
        if int(state.get("exit_code") or 0) == 0:
            await start_operation(target_operation, skip_confirmation=True, append_log=True)

    return handler


async def start_operation(
    operation: Operation,
    *,
    skip_confirmation: bool = False,
    append_log: bool = False,
) -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    if operation.kind == "dangerous" and not skip_confirmation:
        with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-confirm-card rounded-lg"):
            ui.label(tr("confirm_title")).classes("text-base font-semibold")
            ui.label(operation.display_title(settings.language)).classes("text-sm font-semibold")
            description = operation.display_description(settings.language)
            if description:
                ui.label(description).classes("text-sm text-gray-400")
            warning = "Операция изменяет или удаляет файлы." if settings.language == "ru" else "This operation changes or deletes files."
            ui.label(warning).classes("text-sm text-orange-300")
            with ui.row().classes("w-full items-center justify-end gap-2"):
                ui.button(tr("cancel"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg")
                confirm_text = "ПОДТВЕРДИТЬ" if settings.language == "ru" else "CONFIRM"
                ui.button(confirm_text, on_click=lambda: dialog.submit(True)).props("dense flat no-wrap color=negative").classes("audion-action rounded-lg")
        if not await dialog:
            return

    operation_state = {
        "running": True,
        "cancel": False,
        "progress": 0.02,
        "status": f"{tr('running')}: {operation.display_title(settings.language)}",
        "exit_code": None,
    }
    if not append_log:
        operation_state.update(
            {
                "lines": [],
                "terminal_base": 0,
                "terminal_seq": 0,
                "terminal_epoch": int(state.get("terminal_epoch", 0)) + 1,
                "line_offset": 0,
                "log_version": int(state["log_version"]) + 1,
            }
        )
    state.update(operation_state)
    started = time.perf_counter()
    try:
        result = await run.io_bound(
            execute_operation,
            active_project_paths(),
            operation,
            add_log,
            set_progress,
            cancel_requested,
        )
        elapsed = time.perf_counter() - started
        state["exit_code"] = 0 if result.ok else 1
        state["progress"] = 1.0
        report_dir = str(result.data.get("report_dir") or "").strip()
        if report_dir:
            state["last_report_dir"] = report_dir
        if operation.id == "probe_source":
            state["probe_summary"] = str(result.data.get("summary") or "").strip()
            state["probe_source_path"] = str(current_source_path())
            state["probe_updated_at"] = datetime.now().isoformat(timespec="seconds")
        if operation.id == "hardware_capabilities":
            hardware_badge_data(force=True)
            hardware_badge.refresh()
        state["status"] = f"{tr('done') if result.ok else tr('error')}: {operation.display_title(settings.language)} [{state['exit_code']}] {elapsed:.1f}s"
        safe_notify(result.message, "positive" if result.ok else "negative")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {operation.display_title(settings.language)}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False


def operation_button(operation: Operation) -> None:
    description = operation.display_description(settings.language)
    with ui.element("div").classes("audion-operation-row audion-operation-row-leaf"):
        button = ui.button(
            operation.display_title(settings.language),
            on_click=operation_click_handler(operation),
        ).props(f'dense flat no-wrap data-testid="operation-{operation.id}"').classes("audion-action audion-operation-button audion-operation-button-leaf audion-tooltip-align-left rounded-lg")
        add_tooltip(button, description or operation.display_title(settings.language))


def operation_click_handler(operation: Operation):
    async def handler() -> None:
        await start_operation(operation)

    return handler


def maintenance_operation_by_id(operation_id: str) -> Operation | None:
    for operation in manifest.maintenance_operations:
        if operation.id == operation_id:
            return operation
    return None


def source_info_operation() -> Operation | None:
    return maintenance_operation_by_id(SOURCE_INFO_OPERATION_ID)


def source_info_available_for_command(trail: list[CommandNode], pending: CommandNode | None, inline_actions: list[CommandNode] | None) -> bool:
    if not pending and not inline_actions:
        return False
    root_id = trail[0].id if trail else (pending.id if pending is not None else "")
    pending_id = pending.id if pending is not None else ""
    return root_id in SOURCE_INFO_COMMAND_IDS or pending_id in SOURCE_INFO_COMMAND_IDS


def terminal_cache() -> dict[str, Any]:
    cache = state.get("terminal_cache")
    if not isinstance(cache, dict):
        cache = load_terminal_cache()
        state["terminal_cache"] = cache
    cache["history"] = clean_terminal_commands(cache.get("history", []))
    cache["pinned"] = clean_terminal_commands(cache.get("pinned", []))
    return cache


def save_terminal_cache() -> None:
    cache = terminal_cache()
    cache["last"] = str(state.get("terminal_command") or "").strip()
    shell = str(state.get("terminal_shell") or ("pwsh" if os.name == "nt" else "sh")).strip().lower()
    if os.name == "nt":
        cache["shell"] = shell if shell in {"pwsh", "cmd"} else "pwsh"
    else:
        cache["shell"] = "sh"
    cache["cwd"] = stored_terminal_cwd(state.get("terminal_cwd"))
    TERMINAL_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    TERMINAL_HISTORY_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def remember_terminal_command(command: str) -> None:
    command = command.strip()
    if not command:
        return
    cache = terminal_cache()
    history = [command, *[item for item in cache["history"] if item != command]]
    cache["history"] = history[:TERMINAL_HISTORY_LIMIT]
    state["terminal_command"] = command
    save_terminal_cache()


def terminal_command_option_label(command: str, pinned: set[str]) -> str:
    prefix = "PIN " if command in pinned else ""
    text = " ".join(command.split())
    if len(text) > 96:
        text = f"{text[:93]}..."
    return f"{prefix}{text}"


def terminal_command_options() -> dict[str, str]:
    cache = terminal_cache()
    pinned = clean_terminal_commands(cache.get("pinned", []))
    history = [item for item in clean_terminal_commands(cache.get("history", [])) if item not in pinned]
    last = str(cache.get("last") or "").strip()
    current = str(state.get("terminal_command") or "").strip()
    ordered = [*pinned]
    for command in (current, last, *history):
        if command and command not in ordered:
            ordered.append(command)
    options: dict[str, str] = {}
    pinned_set = set(pinned)
    for command in ordered[:TERMINAL_HISTORY_LIMIT]:
        options[command] = terminal_command_option_label(command, pinned_set)
    if not options:
        options[""] = tr("terminal_history_empty")
    return options


def terminal_history_value(options: dict[str, str]) -> str | None:
    current = str(state.get("terminal_command") or "").strip()
    return current if current in options else None


def terminal_command_is_pinned() -> bool:
    command = str(state.get("terminal_command") or "").strip()
    return bool(command and command in terminal_cache().get("pinned", []))


def event_value(event: Any) -> Any:
    if hasattr(event, "value"):
        return event.value
    args = getattr(event, "args", None)
    if isinstance(args, list) and args:
        return args[0]
    if isinstance(args, dict):
        return args.get("value") or args.get("inputValue") or args.get("input")
    return args


def set_terminal_command(value: Any) -> None:
    state["terminal_command"] = str(value or "").strip()
    save_terminal_cache()


def resolve_terminal_history_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    options = terminal_command_options()
    if text in options:
        return text
    for command, label in options.items():
        if text == label:
            return command
    return text


def select_terminal_history(value: Any) -> None:
    set_terminal_command(resolve_terminal_history_value(value))
    terminal_command_bar.refresh()


def set_terminal_shell(value: Any) -> None:
    shell = str(value or ("pwsh" if os.name == "nt" else "sh")).strip().lower()
    if os.name == "nt":
        state["terminal_shell"] = shell if shell in {"pwsh", "cmd"} else "pwsh"
    else:
        state["terminal_shell"] = "sh"
    save_terminal_cache()


def set_terminal_cwd(value: Any) -> None:
    state["terminal_cwd"] = str(value or "").strip() or str(ROOT)
    save_terminal_cache()


def append_terminal_argument(value: Path | str) -> None:
    text = str(value)
    quoted = f'"{text}"' if any(char.isspace() for char in text) else text
    current = str(state.get("terminal_command") or "").rstrip()
    state["terminal_command"] = f"{current} {quoted}".strip() if current else quoted
    save_terminal_cache()
    terminal_command_bar.refresh()


def pin_terminal_command() -> None:
    command = str(state.get("terminal_command") or "").strip()
    if not command:
        safe_notify(tr("command_required"), "warning")
        return
    cache = terminal_cache()
    pinned = [item for item in cache["pinned"] if item != command]
    pinned.insert(0, command)
    cache["pinned"] = pinned[:TERMINAL_HISTORY_LIMIT]
    remember_terminal_command(command)
    terminal_command_bar.refresh()


def unpin_terminal_command() -> None:
    command = str(state.get("terminal_command") or "").strip()
    if not command:
        safe_notify(tr("command_required"), "warning")
        return
    cache = terminal_cache()
    cache["pinned"] = [item for item in cache["pinned"] if item != command]
    remember_terminal_command(command)
    terminal_command_bar.refresh()


def clear_terminal_history() -> None:
    cache = terminal_cache()
    cache["history"] = [item for item in cache["history"] if item in cache["pinned"]]
    cache["last"] = ""
    state["terminal_command"] = ""
    save_terminal_cache()
    safe_notify(tr("history_cleared"), "positive")
    terminal_command_bar.refresh()


def clear_terminal_command_cache() -> None:
    cache = terminal_cache()
    cache["history"] = []
    cache["pinned"] = []
    cache["last"] = ""
    state["terminal_command"] = ""
    save_terminal_cache()
    safe_notify(tr("command_cache_cleared"), "positive")
    terminal_command_bar.refresh()


async def pick_terminal_location(kind: str) -> None:
    try:
        if kind == "file":
            picked = await run.io_bound(pick_files)
            selected = picked[0] if picked else None
        else:
            selected = await run.io_bound(pick_one_folder, tr("choose_path"), str(state.get("terminal_cwd") or ROOT))
    except Exception as exc:
        safe_notify(str(exc), "negative")
        return
    if not selected:
        safe_notify(tr("picker_cancelled"), "warning")
        return
    if selected.is_file():
        set_terminal_cwd(str(selected.parent))
        append_terminal_argument(selected)
    else:
        set_terminal_cwd(str(selected))
    terminal_command_bar.refresh()


def terminal_location_click_handler(kind: str):
    async def handler() -> None:
        await pick_terminal_location(kind)

    return handler


async def start_terminal_command() -> None:
    command = str(state.get("terminal_command") or "").strip()
    if not command:
        safe_notify(tr("command_required"), "warning")
        return
    remember_terminal_command(command)
    terminal_command_bar.refresh()
    shell = str(state.get("terminal_shell") or ("pwsh" if os.name == "nt" else "sh")).strip().lower()
    cwd = str(state.get("terminal_cwd") or ROOT).strip()
    operation = Operation(
        id="terminal_command",
        title="Terminal command",
        title_ru="Команда терминала",
        description=command,
        description_ru=command,
        service="system_core.services.sample_service:terminal_command",
        kind="safe",
        parameters={"command": command, "shell": shell, "cwd": cwd},
    )
    await start_operation(operation)


async def terminal_enter_handler(_event: Any = None) -> None:
    await start_terminal_command()


def preview_operation_from_pending() -> Operation | None:
    node = state.get("pending_command")
    if not isinstance(node, CommandNode):
        return None
    if not validate_pending_fields(node):
        return None
    operation = operation_from_pending_command(node)
    parameters = dict(operation.parameters)
    parameters["dry_run"] = True
    parameters["youtube_dry_run"] = True
    return Operation(
        id=operation.id,
        title="Command preview",
        title_ru="Предпросмотр команды",
        description=operation.display_title("en"),
        description_ru=operation.display_title("ru"),
        service=operation.service,
        kind="safe",
        parameters=parameters,
        fields=operation.fields,
    )


async def start_command_preview() -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return
    operation = preview_operation_from_pending()
    if operation is None:
        safe_notify(tr("command_preview_select"), "warning")
        return

    clear_terminal_log()
    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {tr('command_preview')}",
            "exit_code": None,
        }
    )
    started = time.perf_counter()
    try:
        add_log("[COMMAND PREVIEW]")
        add_log(f"Operation: {operation.description_ru if settings.language == 'ru' else operation.description}")
        result = await run.io_bound(
            execute_operation,
            active_project_paths(),
            operation,
            add_log,
            set_progress,
            cancel_requested,
        )
        elapsed = time.perf_counter() - started
        state["exit_code"] = 0 if result.ok else 1
        state["progress"] = 1.0
        report_dir = str(result.data.get("report_dir") or "").strip()
        if report_dir:
            state["last_report_dir"] = report_dir
        state["status"] = f"{tr('done') if result.ok else tr('error')}: {tr('command_preview')} [{state['exit_code']}] {elapsed:.1f}s"
        safe_notify(tr("command_preview_ready") if result.ok else result.message, "positive" if result.ok else "negative")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {tr('command_preview')}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False


def operation_to_command_node(operation: Operation) -> CommandNode:
    return CommandNode(
        id=operation.id,
        title=operation.title,
        description=operation.description,
        service=operation.service,
        kind=operation.kind,
        title_ru=operation.title_ru,
        description_ru=operation.description_ru,
        parameters=dict(operation.parameters),
        fields=operation.fields,
    )


def root_command_nodes() -> list[CommandNode]:
    if manifest.operation_groups:
        return manifest.operation_groups
    return [operation_to_command_node(operation) for operation in manifest.operations]


def command_level_for_path(command_path: list[str]) -> tuple[list[CommandNode], list[CommandNode]]:
    trail: list[CommandNode] = []
    nodes = root_command_nodes()
    for node_id in command_path:
        node = next((candidate for candidate in nodes if candidate.id == node_id), None)
        if node is None:
            return [], root_command_nodes()
        trail.append(node)
        nodes = list(node.children)
    return trail, nodes


def compact_single_child_command_path(command_path: list[str]) -> list[str]:
    compact_path = list(command_path)
    while True:
        trail, nodes = command_level_for_path(compact_path)
        if trail or len(nodes) != 1 or not nodes[0].children:
            return compact_path
        compact_path.append(nodes[0].id)


def current_command_level() -> tuple[list[CommandNode], list[CommandNode]]:
    command_path = compact_single_child_command_path(list(state.get("command_path", [])))
    state["command_path"] = command_path
    trail, nodes = command_level_for_path(command_path)
    if not trail and command_path:
        state["command_path"] = []
        state["pending_command"] = None
        return [], root_command_nodes()
    return trail, nodes


def enter_command_path(command_path: list[str]) -> None:
    state["pending_command"] = None
    state["command_path"] = compact_single_child_command_path(command_path)
    command_tree.refresh()


def enter_command_node(node: CommandNode) -> None:
    enter_command_path([*state.get("command_path", []), node.id])


def select_command_node(node: CommandNode) -> None:
    state["pending_command"] = node
    command_tree.refresh()


async def activate_command_node(node: CommandNode, path_prefix: list[str] | None = None) -> None:
    prefix = list(path_prefix if path_prefix is not None else state.get("command_path", []))
    if node.children:
        if len(node.children) == 1:
            await activate_command_node(node.children[0], [*prefix, node.id])
            return
        enter_command_path([*prefix, node.id])
        return
    if command_visible_fields(node.fields):
        select_command_node(node)
        return
    state["pending_command"] = None
    await start_operation(operation_from_pending_command(node))


def command_click_handler(node: CommandNode):
    async def handler() -> None:
        await activate_command_node(node)

    return handler


def go_back_command() -> None:
    if state.get("pending_command") is not None:
        state["pending_command"] = None
    else:
        path = list(state.get("command_path", []))
        if path:
            path.pop()
        state["command_path"] = compact_single_child_command_path(path)
    command_tree.refresh()


def field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("name") or "").strip()


def field_kind(field: dict[str, Any]) -> str:
    return str(field.get("type", field.get("kind", "text"))).lower()


def field_label(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("label_ru"):
        return str(field["label_ru"])
    return str(field.get("label") or field.get("title") or field_id(field))


def field_hint(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("hint_ru"):
        return str(field["hint_ru"])
    return str(field.get("hint") or "")


def localized_manifest_text(item: dict[str, Any], *keys: str) -> str:
    language = settings.language
    for key in keys:
        localized_key = f"{key}_{language}"
        if language != "en" and item.get(localized_key):
            return str(item[localized_key])
        if item.get(key):
            return str(item[key])
    return ""


FIELD_TOOLTIP_FALLBACKS: dict[str, dict[str, str]] = {
    "audio_workflow": {
        "en": "Choose what the audio operation changes: extract tracks, update audio in a video copy, or process standalone audio files.",
        "ru": "Выберите сценарий: извлечь дорожки, обновить звук в копии видео или обработать отдельные аудиофайлы.",
    },
    "input_formats": {
        "en": "Limits which Source file extensions are processed. Source is scanned recursively, and OUT keeps the same subfolder structure.",
        "ru": "Ограничивает расширения из Source. Source обходится рекурсивно, а OUT повторяет структуру подпапок.",
    },
    "audio_format": {
        "en": "Output audio codec/container. Copy preserves the selected audio stream without re-encoding; ALAC writes Apple Lossless into M4A.",
        "ru": "Формат результата. Copy сохраняет выбранный аудиопоток без перекодирования; ALAC пишет Apple Lossless в M4A.",
    },
    "audio_copy_container": {
        "en": "Container policy for extracted Copy files: Auto chooses by codec and channel count; MKA/M4A/codec file force a specific wrapping policy.",
        "ru": "Политика контейнера для извлечённых Copy-файлов: Auto выбирает по кодеку и числу каналов; MKA/M4A/файл кодека задают упаковку вручную.",
    },
    "audio_sample_rate": {
        "en": "Target sample rate. Source keeps the original rate.",
        "ru": "Целевая частота дискретизации. Родная оставляет исходную частоту.",
    },
    "audio_bit_depth": {
        "en": "PCM/FLAC bit depth. Source keeps the original depth where the codec supports it.",
        "ru": "Разрядность PCM/FLAC. Родная сохраняет исходную разрядность, если формат это поддерживает.",
    },
    "audio_resampler": {
        "en": "Resampling engine used when changing sample rate.",
        "ru": "Движок ресемплинга при изменении частоты дискретизации.",
    },
    "audio_video_container": {
        "en": "Container for video-copy mode. Some audio codecs are disabled for unsafe container pairs.",
        "ru": "Контейнер для режима обновления звука в видео. Небезопасные пары кодек/контейнер отключаются.",
    },
    "audio_stream_mode": {
        "en": "Which audio stream(s) to process from each source file.",
        "ru": "Какие аудиопотоки брать из каждого исходного файла.",
    },
    "audio_stream_index": {
        "en": "Zero-based audio stream index: a0 is the first audio stream.",
        "ru": "Индекс аудиопотока с нуля: a0 означает первый аудиопоток.",
    },
    "audio_language": {
        "en": "Match streams by container language tag such as eng, rus or ukr.",
        "ru": "Выбор дорожек по языковому тегу контейнера, например eng, rus или ukr.",
    },
    "audio_lufs_mode": {
        "en": "Report analyzes loudness only; one-pass is quick; two-pass is more accurate.",
        "ru": "Отчёт только измеряет громкость; один проход быстрее; два прохода точнее.",
    },
    "audio_lufs": {
        "en": "Target integrated loudness for loudnorm.",
        "ru": "Целевая интегральная громкость для loudnorm.",
    },
    "audio_channel_mode": {
        "en": "Channel layout operation: keep original channels, downmix to stereo/mono, or make dual mono.",
        "ru": "Операция с каналами: сохранить, свести в stereo/mono или сделать dual mono.",
    },
    "mp3_lame_preset": {
        "en": "LAME quality mode for MP3 output.",
        "ru": "Режим качества LAME для MP3.",
    },
    "lut_file": {
        "en": "LUT file applied by the lut3d filter. The selected file is cached; the pin keeps frequently used LUTs at the top.",
        "ru": "LUT-файл для фильтра lut3d. Выбор сохраняется в кэше, а pin закрепляет часто используемый LUT сверху списка.",
    },
    "grading_profile": {
        "en": "The primary mode for the entire Color/LUT window. It selects the transform and production defaults; fields below remain explicit overrides.",
        "ru": "Главный режим всего окна Color/LUT. Кнопка выбирает преобразование и рабочие defaults; поля ниже остаются явными overrides.",
    },
    "pre_gamma": {
        "en": "Gamma applied before the LUT. Values above 1 lift 18% gray; values below 1 lower it. The preview is a pre-LUT technical reference.",
        "ru": "Gamma применяется до LUT. Значения выше 1 поднимают 18% серый, ниже 1 — опускают. Preview показывает технический ориентир до LUT.",
    },
    "audio_mode": {
        "en": "Audio policy for the output: stream copy, lossy/lossless encode, PCM depth, or no audio. MXF permits only compatible PCM modes.",
        "ru": "Политика аудио результата: copy потока, lossy/lossless-кодирование, разрядность PCM или без аудио. Для MXF доступны только совместимые PCM-режимы.",
    },
    "pix_fmt": {
        "en": "Output pixel format and bit depth. Keep it compatible with the selected codec and delivery/editing workflow.",
        "ru": "Pixel format и разрядность результата. Значение должно соответствовать выбранному кодеку и монтажному либо delivery-сценарию.",
    },
    "target_codecs": {
        "en": "One or more output targets. Multiple targets are written separately for each Source file.",
        "ru": "Один или несколько выходных таргетов. Каждый таргет пишется отдельно для каждого файла Source.",
    },
    "decode_backend": {
        "en": "Hardware/software decode preference before encoding.",
        "ru": "Предпочтение аппаратного или программного декодирования перед кодированием.",
    },
    "encode_backend": {
        "en": "Encoder stack used for hardware-capable presets.",
        "ru": "Стек кодирования для пресетов с аппаратным ускорением.",
    },
    "cpu_encoder_preset": {
        "en": "x264/x265 software preset: fast is quicker, slow/slower/veryslow spend more CPU for cleaner compression at the same CRF.",
        "ru": "Software preset x264/x265: fast быстрее, slow/slower/veryslow тратят больше CPU ради более чистого сжатия при том же CRF.",
    },
    "nvenc_preset": {
        "en": "NVIDIA NVENC P-scale. p5 is good quality, p6 is better, p7 is the highest/slowest NVENC tier.",
        "ru": "Шкала NVIDIA NVENC P. p5 good quality, p6 better, p7 самый высокий/медленный уровень NVENC.",
    },
    "qsv_encoder_preset": {
        "en": "Intel QuickSync preset line exposed by FFmpeg, separate from CPU x264/x265 presets.",
        "ru": "Отдельная FFmpeg-линейка Intel QuickSync, не CPU preset x264/x265.",
    },
    "amf_quality": {
        "en": "AMD AMF speed/balanced/quality mode. CQ/QP still controls the quantization level.",
        "ru": "Режим AMD AMF speed/balanced/quality. CQ/QP по-прежнему задаёт уровень квантования.",
    },
    "output_container": {
        "en": "Container for encoded output when the selected codec family allows it.",
        "ru": "Контейнер результата, если выбранное семейство кодеков его допускает.",
    },
    "output_resolution": {
        "en": "Optional scaling target. Source keeps the original frame size.",
        "ru": "Необязательное масштабирование. Исходное сохраняет размер кадра.",
    },
    "crf": {
        "en": "Quality target for software encoders: lower means larger and cleaner.",
        "ru": "Цель качества для software-кодеков: ниже означает крупнее и чище.",
    },
    "cq": {
        "en": "Constant-quality value for hardware encoders.",
        "ru": "Constant Quality для аппаратных кодировщиков.",
    },
    "overwrite": {
        "en": "Allow FFmpeg to replace existing output files.",
        "ru": "Разрешить FFmpeg заменять существующие выходные файлы.",
    },
    "limit_first_file": {
        "en": "Process only the first matching file for a quick preset test.",
        "ru": "Обработать только первый найденный файл для быстрой проверки пресета.",
    },
    "dry_run": {
        "en": "Print commands without processing media.",
        "ru": "Показать команды без обработки медиа.",
    },
}

TOOLTIP_EXCLUDED_FIELD_IDS = {"input_formats"}


def field_tooltip(field: dict[str, Any]) -> str:
    if field_id(field) in TOOLTIP_EXCLUDED_FIELD_IDS:
        return ""
    explicit = localized_manifest_text(field, "tooltip")
    if explicit:
        return explicit
    hint = field_hint(field)
    if hint:
        return hint
    description = localized_manifest_text(field, "description")
    if description:
        return description
    fallback = FIELD_TOOLTIP_FALLBACKS.get(field_id(field), {})
    return fallback.get(settings.language) or fallback.get("en", "")


def field_default(field: dict[str, Any]) -> Any:
    if "default" in field:
        return field["default"]
    kind = field_kind(field)
    options = field.get("options", [])
    if kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        if not isinstance(options, list):
            return []
        selected: list[Any] = []
        for option in options:
            if isinstance(option, dict) and option.get("default", False):
                selected.append(option.get("value", option.get("id", option.get("label"))))
        return selected
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, dict):
            return first.get("value", first.get("id", ""))
        return first
    return ""


def current_field_value(field: dict[str, Any]) -> Any:
    key = field_id(field)
    values = state.setdefault("field_values", {})
    if key not in values:
        values[key] = field_default(field)
    return values[key]


def field_step_is_integer(field: dict[str, Any]) -> bool:
    try:
        return float(field.get("step", 1)).is_integer()
    except (TypeError, ValueError):
        return True


def field_is_integer_number(field: dict[str, Any]) -> bool:
    return field_kind(field) in {"number", "int", "integer"} and field_step_is_integer(field)


def normalize_field_value(field: dict[str, Any], value: Any) -> Any:
    if value is None or value == "" or not field_is_integer_number(field):
        return value
    try:
        numeric = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return value
    return int(numeric) if numeric.is_integer() else value


def set_field_value(key: str, value: Any, *, refresh: bool = False) -> None:
    values = state.setdefault("field_values", {})
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
        ensure_remux_defaults_for_mode()
    if refresh and "command_tree" in globals():
        command_tree.refresh()


def color_profile_gamma(script: str) -> float | str:
    clean_script = str(script or "").strip()
    profile = script_profile(ROOT, clean_script) if clean_script else {}
    filter_kind = str(profile.get("color_filter") or "").strip().lower()
    lowered = clean_script.lower()
    if filter_kind == "preexpose_lut" or "preexpose" in lowered:
        return float(ffmpeg_filter_number(profile.get("pre_gamma") or "1.15", name="pre_gamma"))
    if filter_kind == "pregamma_lut" or "pregamma" in lowered:
        return float(ffmpeg_filter_number(profile.get("pre_gamma") or "0.85", name="pre_gamma"))
    return ""


def set_script_preset_value(value: Any, *, refresh: bool = True) -> None:
    script = str(value or "").strip()
    values = state.setdefault("field_values", {})
    values["script_preset"] = script
    values["pre_gamma"] = color_profile_gamma(script)
    if refresh and "command_tree" in globals():
        command_tree.refresh()


def set_field_value_for_field(field: dict[str, Any], value: Any, *, refresh: bool = False) -> None:
    key = field_id(field)
    if key == "script_preset":
        set_script_preset_value(value, refresh=refresh)
        return
    set_field_value(key, normalize_field_value(field, value), refresh=refresh)


def field_refreshes_layout(field: dict[str, Any]) -> bool:
    return bool(field.get("refresh_on_change") or field.get("refresh_layout") or field.get("affects_layout"))


def _condition_actual_value(key: str) -> Any:
    return state.setdefault("field_values", {}).get(str(key))


def _value_matches_condition(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if "not" in expected:
            return not _value_matches_condition(actual, expected["not"])
        if "neq" in expected:
            return not _value_matches_condition(actual, expected["neq"])
        if "in" in expected:
            return _value_matches_condition(actual, expected["in"])
        if "exists" in expected:
            return (actual not in {None, "", []}) if bool(expected["exists"]) else (actual in {None, "", []})
    if isinstance(expected, (list, tuple, set)):
        if isinstance(actual, (list, tuple, set)):
            actual_values = {str(item).strip().lower() for item in actual}
            expected_values = {str(item).strip().lower() for item in expected}
            return bool(actual_values & expected_values)
        return str(actual).strip().lower() in {str(item).strip().lower() for item in expected}
    if isinstance(expected, bool):
        return bool(actual) is expected
    return str(actual).strip().lower() == str(expected).strip().lower()


def condition_matches(condition: Any) -> bool:
    if not condition:
        return False
    if isinstance(condition, dict):
        if "all" in condition:
            items = condition.get("all") or []
            return all(condition_matches(item) for item in items)
        if "any" in condition:
            items = condition.get("any") or []
            return any(condition_matches(item) for item in items)
        if "not" in condition:
            return not condition_matches(condition["not"])
        for key, expected in condition.items():
            if key in {"all", "any", "not"}:
                continue
            if not _value_matches_condition(_condition_actual_value(str(key)), expected):
                return False
        return True
    if isinstance(condition, (list, tuple, set)):
        return all(condition_matches(item) for item in condition)
    return False


def field_is_visible(field: dict[str, Any]) -> bool:
    if bool(field.get("hidden", field.get("ui_hidden", False))):
        return False
    visible_if = field.get("visible_if", field.get("show_if"))
    if visible_if and not condition_matches(visible_if):
        return False
    hidden_if = field.get("hidden_if", field.get("hide_if"))
    if hidden_if and condition_matches(hidden_if):
        return False
    return True


def adjusted_number_value(field: dict[str, Any], current: Any, direction: int) -> int | float:
    step_raw = field.get("step", 1)
    try:
        step = float(step_raw)
    except (TypeError, ValueError):
        step = 1.0

    seed = current
    if seed is None or seed == "":
        seed = field_default(field) or 0
    try:
        value = float(seed)
    except (TypeError, ValueError):
        value = 0.0

    value += step * (1 if direction > 0 else -1)
    for bound_key, clamp in (("min", max), ("max", min)):
        bound = field.get(bound_key)
        if bound is None or bound == "":
            continue
        try:
            value = clamp(value, float(bound))
        except (TypeError, ValueError):
            continue

    kind = field_kind(field)
    integer_like = kind in {"number", "int", "integer"} and float(step).is_integer()
    return int(round(value)) if integer_like else round(value, 6)


def spin_number_field(key: str, field: dict[str, Any], control: Any, direction: int) -> None:
    value = adjusted_number_value(field, state.setdefault("field_values", {}).get(key), direction)
    set_field_value(key, value)
    control.set_value(value)


def remux_stream_mode_value() -> str:
    value = str(state.setdefault("field_values", {}).get("remux_stream_mode") or "video_audio").strip().lower()
    if value in {"video", "audio", "video_audio"}:
        return value
    return "video_audio"


def remux_source_key_for_target(target_key: str) -> str:
    return "remux_audio_source_format" if target_key == "remux_audio_target_format" else "remux_source_format"


def remux_target_key_for_source(source_key: str) -> str:
    return "remux_audio_target_format" if source_key == "remux_audio_source_format" else "remux_target_format"


def remux_allowed_sources(key: str) -> tuple[str, ...]:
    if key.startswith("remux_audio_"):
        return AUDIO_REMUX_SOURCE_FORMATS
    return VIDEO_REMUX_SOURCE_FORMATS


def remux_compatibility_for_key(key: str) -> dict[str, tuple[str, ...]]:
    return AUDIO_REMUX_COMPATIBILITY if key.startswith("remux_audio_") else VIDEO_REMUX_COMPATIBILITY


def remux_compatible_targets(source_format: str, key: str = "remux_target_format") -> tuple[str, ...]:
    compatibility = remux_compatibility_for_key(key)
    return compatibility.get(source_format.strip().lower(), ())


def ensure_remux_target_for_source(source_format: str, key: str = "remux_source_format") -> None:
    values = state.setdefault("field_values", {})
    target_key = remux_target_key_for_source(key)
    compatible = remux_compatible_targets(source_format, target_key)
    current = str(values.get(target_key) or "").strip().lower()
    if compatible and current not in compatible:
        values[target_key] = compatible[0]


def ensure_remux_defaults_for_mode() -> None:
    values = state.setdefault("field_values", {})
    values.setdefault("remux_stream_mode", "video_audio")
    values.setdefault("remux_target_format", "mp4")
    values.setdefault("remux_audio_target_format", "mka")


def set_remux_format_value(key: str, value: str) -> None:
    values = state.setdefault("field_values", {})
    clean = value.strip().lower()
    if key in {"remux_source_format", "remux_audio_source_format"}:
        values[key] = clean
        ensure_remux_target_for_source(clean, key)
    elif key in {"remux_target_format", "remux_audio_target_format"}:
        values[key] = clean
    else:
        values[key] = clean
    command_tree.refresh()


def dynamic_option_source(field: dict[str, Any]) -> str:
    return str(field.get("options_source") or field.get("source") or "").strip()


def refresh_dynamic_options(field: dict[str, Any]) -> None:
    source = dynamic_option_source(field)
    if source:
        dynamic_option_cache.pop(source, None)
    key = field_id(field)
    if key:
        state.setdefault("field_values", {}).pop(key, None)
    command_tree.refresh()


def refresh_options_click_handler(field: dict[str, Any]):
    def handler() -> None:
        refresh_dynamic_options(field)

    return handler


def apply_preset_values(preset: dict[str, Any], *, skip_checkbox_values: bool = False) -> None:
    values = preset.get("values", {})
    if not isinstance(values, dict):
        return
    field_values = state.setdefault("field_values", {})
    for key, value in values.items():
        if skip_checkbox_values and isinstance(value, (bool, list)):
            continue
        field_values[str(key)] = value


def apply_preset(preset: dict[str, Any], field: dict[str, Any] | None = None) -> None:
    apply_preset_values(preset)
    if field is not None:
        key = field_id(field)
        selected = preset_id(preset)
        if key and selected:
            set_field_value(key, selected)
            state.setdefault("applied_profiles", {})[key] = selected
    command_tree.refresh()


def preset_label(preset: dict[str, Any]) -> str:
    if settings.language == "ru" and preset.get("label_ru"):
        return str(preset["label_ru"])
    return str(preset.get("label") or preset.get("title") or preset.get("id") or "Preset")


def preset_tone(preset: dict[str, Any]) -> str:
    tone = str(preset.get("tone") or preset.get("category") or preset.get("group") or "").strip().lower()
    return "".join(char if char.isalnum() else "-" for char in tone).strip("-") or "default"


def preset_group_key(preset: dict[str, Any]) -> str:
    group = str(preset.get("group") or preset.get("category") or "presets").strip().lower() or "presets"
    return "".join(char if char.isalnum() else "-" for char in group).strip("-") or "presets"


def preset_group_label(preset: dict[str, Any]) -> str:
    if settings.language == "ru":
        return str(preset.get("group_label_ru") or preset.get("category_label_ru") or preset.get("group_label") or preset.get("category_label") or "")
    return str(preset.get("group_label") or preset.get("category_label") or "")


def preset_click_handler(preset: dict[str, Any], field: dict[str, Any] | None = None):
    def handler() -> None:
        apply_preset(preset, field)

    return handler


def preset_id(preset: dict[str, Any]) -> str:
    return str(preset.get("id") or preset.get("value") or preset.get("label") or "").strip()


def profile_presets(field: dict[str, Any]) -> list[dict[str, Any]]:
    raw = field.get("presets", field.get("options", []))
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict) and preset_id(item)]


def profile_options(field: dict[str, Any]) -> dict[str, str]:
    key = field_id(field)
    presets = profile_presets(field)
    pinned = pinned_profiles(ROOT, key)
    by_id = {preset_id(preset): preset for preset in presets}
    ordered_ids = [item for item in pinned if item in by_id]
    ordered_ids.extend(preset_id(preset) for preset in presets if preset_id(preset) not in ordered_ids)
    return {item_id: preset_label(by_id[item_id]) for item_id in ordered_ids}


def current_profile_id(field: dict[str, Any]) -> str:
    value = str(current_field_value(field) or "").strip()
    if value:
        return value
    presets = profile_presets(field)
    return preset_id(presets[0]) if presets else ""


def profile_description(field: dict[str, Any], profile_id: str) -> str:
    preset = next((item for item in profile_presets(field) if preset_id(item) == profile_id), None)
    if not preset:
        return ""
    if settings.language == "ru" and preset.get("description_ru"):
        return str(preset["description_ru"])
    return str(preset.get("description") or "")


def profile_select_change_handler(field: dict[str, Any]):
    def handler(event: Any) -> None:
        selected = str(getattr(event, "value", "") or "")
        if not selected:
            return
        set_field_value(field_id(field), selected)
        preset = next((item for item in profile_presets(field) if preset_id(item) == selected), None)
        if preset:
            apply_preset_values(preset)
            set_field_value(field_id(field), selected)
            state.setdefault("applied_profiles", {})[field_id(field)] = selected
        command_tree.refresh()

    return handler


def profile_pin_change_handler(field: dict[str, Any]):
    def handler(event: Any) -> None:
        selected = current_profile_id(field)
        set_profile_pin(ROOT, field_id(field), selected, bool(getattr(event, "value", False)))
        command_tree.refresh()

    return handler


def _lut_cache_state() -> dict[str, Any]:
    cache = load_lut_cache(ROOT)
    state["lut_cache"] = cache
    return cache


def _lut_path_key(value: Any) -> str:
    return str(Path(str(value or "").strip().strip('"')).expanduser()).casefold()


def current_lut_value(field: dict[str, Any]) -> str:
    key = field_id(field)
    values = state.setdefault("field_values", {})
    selected = str(values.get(key) or "").strip().strip('"')
    if not selected:
        selected = str(_lut_cache_state().get("selected_lut") or "").strip()
    if not selected:
        scanned = scan_luts(ROOT)
        selected = scanned[0] if scanned else ""
    if selected:
        selected = str(Path(selected).expanduser().resolve())
    values[key] = selected
    return selected


def lut_options() -> dict[str, str]:
    cache = _lut_cache_state()
    ordered = [
        *list(cache.get("pinned_luts", [])),
        cache.get("selected_lut", ""),
        *list(cache.get("recent_luts", [])),
        *scan_luts(ROOT),
    ]
    result: dict[str, str] = {}
    seen: set[str] = set()
    lut_root = (ROOT / "LUTs").resolve()
    for item in ordered:
        text = str(item or "").strip().strip('"')
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        path = path.resolve()
        path_key = str(path).casefold()
        if path_key in seen:
            continue
        seen.add(path_key)
        try:
            label = str(path.relative_to(lut_root))
        except ValueError:
            label = str(path)
        result[str(path)] = label
    return result


def lut_pinned(value: Any) -> bool:
    selected_key = _lut_path_key(value)
    if not selected_key:
        return False
    return selected_key in {_lut_path_key(item) for item in _lut_cache_state().get("pinned_luts", [])}


def lut_select_change_handler(field: dict[str, Any]):
    def handler(event: Any) -> None:
        selected = str(getattr(event, "value", "") or "").strip()
        if not selected:
            return
        cache = update_lut_cache(ROOT, selected)
        state["lut_cache"] = cache
        state.setdefault("field_values", {})[field_id(field)] = str(cache.get("selected_lut") or selected)
        command_tree.refresh()

    return handler


def lut_pin_change_handler(field: dict[str, Any]):
    def handler(event: Any) -> None:
        selected = current_lut_value(field)
        if not selected:
            return
        cache = update_lut_cache(ROOT, selected, pinned=bool(getattr(event, "value", False)))
        state["lut_cache"] = cache
        command_tree.refresh()

    return handler


def _copy_lut_file(source: Path, target: Path) -> Path | None:
    source = source.resolve()
    if not source.is_file() or source.suffix.lower() not in LUT_EXTENSIONS:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if source != target.resolve():
        shutil.copy2(source, target)
    return target.resolve()


def _import_luts(kind: str) -> list[Path]:
    lut_root = (ROOT / "LUTs").resolve()
    lut_root.mkdir(parents=True, exist_ok=True)
    imported: list[Path] = []
    if kind == "folder":
        source_root = pick_one_folder(tr("choose_path"), str(lut_root))
        if source_root is None:
            return []
        source_root = source_root.resolve()
        destination_root = lut_root if source_root == lut_root else lut_root / source_root.name
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in LUT_EXTENSIONS:
                continue
            copied = _copy_lut_file(source, destination_root / source.relative_to(source_root))
            if copied is not None:
                imported.append(copied)
    else:
        for source in pick_lut_files():
            copied = _copy_lut_file(source, lut_root / source.name)
            if copied is not None:
                imported.append(copied)
    return imported


def lut_import_click_handler(kind: str):
    async def handler() -> None:
        try:
            imported = await run.io_bound(_import_luts, kind)
        except Exception as exc:
            safe_notify(str(exc), "negative")
            return
        if not imported:
            safe_notify(tr("picker_cancelled"), "warning")
            return
        cache: dict[str, Any] = _lut_cache_state()
        for path in reversed(imported):
            cache = update_lut_cache(ROOT, str(path))
        selected = str(imported[0])
        cache = update_lut_cache(ROOT, selected)
        state["lut_cache"] = cache
        state.setdefault("field_values", {})["lut_file"] = selected
        message = f"Добавлено LUT: {len(imported)}" if settings.language == "ru" else f"LUT files added: {len(imported)}"
        safe_notify(message, "positive")
        command_tree.refresh()

    return handler


def load_dynamic_options(field: dict[str, Any]) -> list[Any]:
    source = dynamic_option_source(field)
    if not source:
        return []

    cache_seconds = float(field.get("cache_seconds", 45) or 0)
    now = time.monotonic()
    cached = dynamic_option_cache.get(source)
    if cached and cache_seconds > 0 and now - cached[0] < cache_seconds:
        return cached[1]

    try:
        if ":" not in source:
            raise RuntimeError(f"Dynamic option source must use module:function syntax: {source}")
        module_name, function_name = source.split(":", 1)
        module = importlib.import_module(module_name)
        provider = getattr(module, function_name)
        try:
            options = provider(ROOT)
        except TypeError:
            options = provider()
        if not isinstance(options, list):
            raise RuntimeError(f"Dynamic option source returned {type(options).__name__}, expected list.")
    except Exception as exc:
        message = f"Option source failed: {exc.__class__.__name__}: {exc}"
        options = [{"value": "", "label": message, "label_ru": message}]

    dynamic_option_cache[source] = (now, options)
    return options


def field_options(field: dict[str, Any]) -> list[Any]:
    dynamic_options = load_dynamic_options(field)
    if dynamic_options:
        return dynamic_options
    options = field.get("options", [])
    return options if isinstance(options, list) else []


def select_options(field: dict[str, Any], current: Any = None) -> dict[Any, str] | list[Any]:
    options = field_options(field)
    if all(isinstance(option, dict) for option in options):
        result: dict[Any, str] = {}
        for option in options:
            value = option.get("value", option.get("id", ""))
            # Radio and checkbox groups already respect these conditions; a
            # dropdown must not keep offering a value the manifest ruled out.
            if value != current and (not option_is_visible(option) or option_is_disabled(option)):
                continue
            if settings.language == "ru" and option.get("label_ru"):
                label = str(option["label_ru"])
            else:
                label = str(option.get("label") or option.get("title") or value)
            result[value] = label
        return result
    return options


def option_value(option: Any) -> Any:
    if isinstance(option, dict):
        return option.get("value", option.get("id", option.get("label", "")))
    return option


def option_label(option: Any) -> str:
    if not isinstance(option, dict):
        return str(option)
    language = settings.language
    if language == "ru" and option.get("label_ru"):
        return str(option["label_ru"])
    return str(option.get("label") or option.get("title") or option_value(option))


def option_tooltip(option: Any) -> str:
    if not isinstance(option, dict):
        return ""
    return localized_manifest_text(option, "tooltip", "hint", "description")


FORMAT_TONE_FIELDS = {
    "audio_mode",
    "audio_format",
    "audio_copy_container",
    "audio_video_container",
    "fps_audio_pcm_depth",
    "input_formats",
    "output_container",
    "remux_target_format",
    "remux_audio_target_format",
    "target_codecs",
    "youtube_audio_format",
    "youtube_container",
    "youtube_video_codec",
}
FORMAT_TONE_HINTS = ("format", "formats", "codec", "codecs", "container")
UNCOMPRESSED_FORMAT_TOKENS = {
    "aif",
    "aiff",
    "au",
    "caf",
    "dff",
    "dsf",
    "f32",
    "pcm",
    "pcm_f32",
    "pcm_s16",
    "pcm_s24",
    "raw",
    "s16",
    "s24",
    "snd",
    "wav",
    "w64",
    "wave",
}
LOSSLESS_FORMAT_TOKENS = {
    "alac",
    "ape",
    "dnx",
    "dnxhr",
    "dnxhr_hq",
    "dnxhr_hqx",
    "ffv1",
    "flac",
    "mka",
    "mov",
    "mxf",
    "prores",
    "prores_422",
    "prores_hq",
    "prores_lt",
    "prores_proxy",
    "tak",
    "tta",
    "wv",
    "x264_lossless",
}
LOSSY_FORMAT_TOKENS = {
    "3gp",
    "aac",
    "aac_320",
    "ac3",
    "amr",
    "av1",
    "avc",
    "avi",
    "awb",
    "dts",
    "eac3",
    "e_ac3",
    "h264",
    "h265",
    "hevc",
    "hevc_x265",
    "m2ts",
    "m4a",
    "m4b",
    "m4v",
    "mkv",
    "mp3",
    "mp4",
    "mpc",
    "mpeg",
    "mpg",
    "mts",
    "ogg",
    "oga",
    "opus",
    "spx",
    "svt_av1",
    "ts",
    "vp9",
    "webm",
    "x264",
    "x265",
}


def choice_tone_slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.strip().lower()).strip("-")


def format_tone_field_enabled(field: dict[str, Any]) -> bool:
    key = field_id(field).lower()
    if key in FORMAT_TONE_FIELDS:
        return True
    group = str(field.get("group") or "").strip().lower()
    if any(hint in key for hint in FORMAT_TONE_HINTS) or any(hint in group for hint in FORMAT_TONE_HINTS):
        return True
    return False


def format_choice_tokens(value: Any, label: str) -> set[str]:
    raw = f"{value} {label}".lower()
    raw = raw.replace("e-ac3", "eac3").replace("h.264", "h264").replace("h.265", "h265").replace("svt-av1", "svt_av1")
    compact = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    tokens = {part for part in re.split(r"[^a-z0-9]+", raw) if part}
    if compact:
        tokens.add(compact)
    if {"svt", "av1"} <= tokens:
        tokens.add("svt_av1")
    if {"x264", "lossless"} <= tokens:
        tokens.add("x264_lossless")
    if {"x265", "hevc"} & tokens:
        tokens.add("hevc_x265")
    if {"prores", "proxy"} <= tokens:
        tokens.add("prores_proxy")
    if {"prores", "lt"} <= tokens:
        tokens.add("prores_lt")
    if {"prores", "hq"} <= tokens:
        tokens.add("prores_hq")
    if {"dnxhr", "hq"} <= tokens:
        tokens.add("dnxhr_hq")
    if {"dnxhr", "hqx"} <= tokens:
        tokens.add("dnxhr_hqx")
    if "pcm" in tokens and "16" in tokens:
        tokens.add("pcm_s16")
    if "pcm" in tokens and "24" in tokens:
        tokens.add("pcm_s24")
    if "pcm" in tokens and ("float" in tokens or "32" in tokens or "32f" in tokens):
        tokens.add("pcm_f32")
    return tokens


def detected_format_tone(field: dict[str, Any], option: Any, value: Any, label: str) -> str:
    if not format_tone_field_enabled(field):
        return ""
    tokens = format_choice_tokens(value, label)
    if tokens & UNCOMPRESSED_FORMAT_TOKENS:
        return "uncompressed"
    if tokens & LOSSLESS_FORMAT_TOKENS:
        return "lossless"
    if tokens & LOSSY_FORMAT_TOKENS:
        return "lossy"
    return ""


def choice_option_tone(field: dict[str, Any], option: Any, value: Any, label: str) -> str:
    detected = detected_format_tone(field, option, value, label)
    if detected:
        return detected
    if isinstance(option, dict) and (option.get("tone") or option.get("category") or option.get("group")):
        return choice_tone_slug(str(option.get("tone") or option.get("category") or option.get("group") or ""))
    return ""


def option_is_disabled(option: Any) -> bool:
    if not isinstance(option, dict):
        return False
    disabled_if = option.get("disabled_if", option.get("disable_if"))
    if disabled_if and condition_matches(disabled_if):
        return True
    enabled_if = option.get("enabled_if", option.get("enable_if"))
    if enabled_if and not condition_matches(enabled_if):
        return True
    return bool(option.get("disabled", option.get("disable", False)))


def option_is_visible(option: Any) -> bool:
    if not isinstance(option, dict):
        return True
    visible_if = option.get("visible_if", option.get("show_if"))
    if visible_if and not condition_matches(visible_if):
        return False
    hidden_if = option.get("hidden_if", option.get("hide_if"))
    if hidden_if and condition_matches(hidden_if):
        return False
    return True


def choice_option_items(field: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for option in field_options(field):
        if not option_is_visible(option):
            continue
        value = option_value(option)
        label = option_label(option)
        items.append(
            {
                "value": value,
                "label": label,
                "tooltip": option_tooltip(option),
                "disabled": option_is_disabled(option),
                "tone": choice_option_tone(field, option, value, label),
            }
        )
    return items


def checkbox_options(field: dict[str, Any]) -> list[tuple[Any, str]]:
    return [(item["value"], item["label"]) for item in choice_option_items(field)]


def is_checkbox_group(field: dict[str, Any]) -> bool:
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    return kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}


def field_choice_layout(field: dict[str, Any]) -> str:
    layout = str(field.get("layout") or field.get("choices_layout") or field.get("option_layout") or "").strip().lower()
    if layout in {"vertical", "column", "stack", "stacked"}:
        return "vertical"
    if layout in {"horizontal", "row", "inline", "two_columns", "three_columns", "four_columns", "five_columns", "six_columns", "seven_columns"}:
        return "horizontal"
    return "horizontal"


def field_choice_columns(field: dict[str, Any]) -> int:
    aliases = {
        "two_columns": 2,
        "three_columns": 3,
        "four_columns": 4,
        "five_columns": 5,
        "six_columns": 6,
        "seven_columns": 7,
    }
    layout = str(field.get("layout") or field.get("choices_layout") or field.get("option_layout") or "").strip().lower()
    raw = field.get("columns", field.get("choice_columns", aliases.get(layout, 0)))
    try:
        columns = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return columns if 2 <= columns <= 7 else 0


def field_choice_style(field: dict[str, Any]) -> str:
    return str(field.get("style") or field.get("choice_style") or field.get("variant") or "").strip().lower()


def field_choice_row_classes(field: dict[str, Any]) -> str:
    if field_choice_layout(field) == "vertical":
        return "audion-choice-row audion-choice-column"
    columns = field_choice_columns(field)
    suffix = f" audion-choice-cols-{columns}" if columns else ""
    return f"audion-choice-row{suffix}"


def trim_source_names() -> list[str]:
    """The takes staged in Source, in the order the badge walks them."""
    try:
        module = importlib.import_module("system_core.services.media_service")
        return list(module.trim_source_file_names(ROOT))
    except Exception:
        return []


def trim_short_name(name: str, limit: int = 34) -> str:
    """A long name with its middle taken out, so the badge stays one line.

    The head and the tail are what identify a take - `M001C008...R00H.mov` reads
    at a glance, while a name cut at the end loses the part that differs.
    """
    text = str(name or "")
    if len(text) <= limit:
        return text
    keep = (limit - 1) // 2
    return f"{text[:keep]}\u2026{text[-(limit - keep - 1):]}"


async def show_trim_probe(name: str) -> None:
    """The ffprobe reading of one file, before anything is cut."""
    try:
        module = importlib.import_module("system_core.services.media_service")
        report = await run.io_bound(module.trim_probe_table, name, ROOT)
    except Exception as exc:
        ui.notify(f"{exc.__class__.__name__}: {exc}", type="negative")
        return
    if not isinstance(report, dict) or not report.get("ok"):
        ui.notify(str((report or {}).get("error") or "ffprobe returned nothing"), type="warning")
        return
    with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-trim-probe rounded-lg"):
        ui.label(f"{tr('trim_probe_title')}: {report.get('file', '')}").classes("audion-trim-probe-title")
        ui.table(
            columns=[
                {"name": "field", "label": tr("trim_probe_field"), "field": "field", "align": "left"},
                {"name": "value", "label": tr("trim_probe_value"), "field": "value", "align": "left"},
            ],
            rows=list(report.get("rows") or []),
            row_key="field",
        ).props("dense flat bordered hide-bottom").classes("audion-trim-probe-table")
        with ui.row().classes("w-full items-center justify-end"):
            ui.button(tr("close"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg")
    dialog.open()


def render_trim_file_field(field: dict[str, Any], key: str, label: str, tooltip: str, hint: str) -> None:
    """The current file as a badge, with an arrow on each side.

    A folder of takes is walked, not searched: the name is on screen and the
    neighbours are one click away, which beats opening a list to find out what
    is even in there.
    """
    names = trim_source_names()
    with ui.element("div").classes("audion-trim-filebar"):
        ui.label(label).classes("audion-trim-group-title")
        if not names:
            ui.label(tr("trim_no_media")).classes("audion-field-hint")
            return

        values = state.setdefault("field_values", {})
        current = str(values.get(key) or "").strip()
        if current not in names:
            current = names[0]
            values[key] = current
        index = names.index(current)

        def step(direction: int) -> None:
            values[key] = names[(index + direction) % len(names)]
            # A new take means the old points describe someone else's material.
            values["trim_start"] = ""
            values["trim_end"] = ""
            command_tree.refresh()

        with ui.row().classes("audion-trim-filerow items-center no-wrap"):
            previous_button = ui.button(icon="chevron_left", on_click=lambda _event=None: step(-1), color=None)
            previous_button.props("dense unelevated").classes("audion-trim-step")
            add_tooltip(previous_button, tr("trim_file_previous"))
            with ui.element("div").classes("audion-trim-badge"):
                ui.icon("movie").classes("audion-trim-badge-icon")
                name_label = ui.label(trim_short_name(current)).classes("audion-trim-filename")
                # The full name lives in the tooltip; the badge keeps one line.
                add_tooltip(name_label, current)
                ui.label(f"{index + 1}/{len(names)}").classes("audion-trim-filecount")
            next_button = ui.button(icon="chevron_right", on_click=lambda _event=None: step(1), color=None)
            next_button.props("dense unelevated").classes("audion-trim-step")
            add_tooltip(next_button, tr("trim_file_next"))
            probe_button = ui.button(icon="table_chart", on_click=lambda _event=None: show_trim_probe(current), color=None)
            probe_button.props("dense unelevated").classes("audion-trim-step")
            add_tooltip(probe_button, tr("trim_probe_hint"))
        if len(names) == 1:
            previous_button.props("disable")
            next_button.props("disable")
    if hint:
        ui.label(hint).classes("audion-field-hint")


def mpv_chosen_media() -> Any:
    """The file the trim section is pointed at, as a path."""
    from system_core.services.media_service import trim_source_path

    return trim_source_path(str(state.get("field_values", {}).get("trim_file") or ""), ROOT)


def mpv_show_selected() -> None:
    """Open the chosen take in the player, or say plainly why not."""
    from system_core.services import mpv_service

    if mpv_service.mpv_binary(ROOT) is None:
        ui.notify(tr("mpv_missing"), type="warning")
        return
    media = mpv_chosen_media()
    if media is None:
        ui.notify(tr("mpv_no_file"), type="warning")
        return
    try:
        player = mpv_service.player(ROOT)
        player.open(media)
        player.wait_until_loaded(timeout=6.0)
    except (OSError, RuntimeError) as error:
        ui.notify(f"{tr('mpv_failed')}: {error}", type="negative")
        return
    ui.notify(f"{tr('mpv_opened')}: {media.name}")


def mpv_points_to_fields(start: float | None, end: float | None) -> list[str]:
    """Write the points the player found into the two timecode fields.

    Nothing but the arithmetic, so it can be checked without a browser: the
    notification and the redraw belong to whoever pressed the button.
    """
    written: list[str] = []
    if start is not None:
        set_field_value("trim_start", format_seconds(start, separator=","))
        written.append(f"IN {format_seconds(start, separator=',')}")
    if end is not None:
        set_field_value("trim_end", format_seconds(end, separator=","))
        written.append(f"OUT {format_seconds(end, separator=',')}")
    return written


def mpv_apply_points(start: float | None, end: float | None) -> None:
    """The same, said out loud and redrawn on screen."""
    written = mpv_points_to_fields(start, end)
    if not written:
        ui.notify(tr("mpv_no_points"), type="warning")
        return
    command_tree.refresh()
    ui.notify("   ".join(written))


def mpv_take_loop(which: str = "both") -> None:
    """A and B out of the player's loop - that loop is the cut itself."""
    from system_core.services import mpv_service

    player = mpv_service.player(ROOT)
    if not player.is_running():
        ui.notify(tr("mpv_not_running"), type="warning")
        return
    start, end = player.ab_loop()
    if which == "in":
        mpv_apply_points(start, None)
    elif which == "out":
        mpv_apply_points(None, end)
    else:
        mpv_apply_points(start, end)


def mpv_mark_here(which: str) -> None:
    """Mark where the player stands: set the loop point there, and take it.

    Two things happen at once on purpose. The point lands in the field, and the
    player's own A/B loop moves with it - so the piece being cut keeps playing
    round and round in the window, and a wrong point is heard immediately.
    """
    from system_core.services import mpv_service

    player = mpv_service.player(ROOT)
    if not player.is_running():
        ui.notify(tr("mpv_not_running"), type="warning")
        return
    position = player.position()
    if position is None:
        ui.notify(tr("mpv_no_points"), type="warning")
        return
    player.send("set_property", "ab-loop-a" if which == "mark_in" else "ab-loop-b", position)
    if which == "mark_in":
        mpv_apply_points(position, None)
    else:
        mpv_apply_points(None, position)


def mpv_close_player() -> None:
    from system_core.services import mpv_service

    mpv_service.close_player()
    ui.notify(tr("mpv_closed"))


def mpv_action_handler(action: str):
    def handler() -> None:
        if action == "open":
            mpv_show_selected()
        elif action == "close":
            mpv_close_player()
        elif action in {"mark_in", "mark_out"}:
            mpv_mark_here(action)
        else:
            mpv_take_loop(action)

    return handler


def render_player_transport(field: dict[str, Any], label: str, tooltip: str, hint: str) -> None:
    """Five buttons: show the take, take the two points, close the player."""
    ui.label(label).classes("audion-field-label")
    items = choice_option_items(field)
    with ui.element("div").classes(f"{field_choice_row_classes(field)} audion-segmented-choice"):
        total_items = len(items)
        for index, item in enumerate(items):
            classes = "audion-action audion-segmented-button rounded-md"
            if item.get("tone"):
                classes += f" audion-segmented-tone-{item['tone']}"
            if index == 0:
                classes += " audion-tooltip-align-left"
            elif index == total_items - 1:
                classes += " audion-tooltip-align-right"
            button = ui.button(
                item["label"],
                on_click=mpv_action_handler(str(item["value"])),
            ).props("dense flat no-wrap").classes(classes)
            add_tooltip(button, item.get("tooltip") or tooltip)
    if hint:
        ui.label(hint).classes("audion-field-hint")


ACTIVE_SEGMENT_CLASS = "audion-segmented-button-active"


def render_segmented_choice(field: dict[str, Any], option_items: list[dict[str, Any]], value: Any) -> None:
    key = field_id(field)
    # The buttons of a row have to know about each other. The active class is
    # decided while drawing, and without this the highlight only moves when
    # something else rebuilds the panel - so a row whose field has no
    # `refresh_on_change` changes its value on click and looks dead.
    row: dict[Any, Any] = {}

    def light(chosen: Any) -> None:
        for option_value, button in row.items():
            if option_value == chosen:
                button.classes(add=ACTIVE_SEGMENT_CLASS)
            else:
                button.classes(remove=ACTIVE_SEGMENT_CLASS)

    def choose(item_value: Any, item_field: dict[str, Any]) -> None:
        light(item_value)
        set_field_value(key, item_value, refresh=field_refreshes_layout(item_field))

    with ui.element("div").classes(f"{field_choice_row_classes(field)} audion-segmented-choice"):
        total_items = len(option_items)
        for index, item in enumerate(option_items):
            selected = item["value"] == value
            classes = "audion-action audion-segmented-button rounded-md"
            if item.get("tone"):
                classes += f" audion-segmented-tone-{item['tone']}"
            if index == 0:
                classes += " audion-tooltip-align-left"
            elif index == total_items - 1:
                classes += " audion-tooltip-align-right"
            if selected:
                classes += f" {ACTIVE_SEGMENT_CLASS}"
            if item["disabled"]:
                classes += " audion-disabled-choice"
            button = ui.button(
                item["label"],
                on_click=lambda item_value=item["value"], item_field=field: choose(item_value, item_field),
            ).props("dense flat no-wrap").classes(classes)
            if item["disabled"]:
                button.props("disable")
            else:
                row[item["value"]] = button
            add_tooltip(button, item.get("tooltip") or field_tooltip(field))


def choice_tone_class(item: dict[str, Any]) -> str:
    tone = str(item.get("tone") or "").strip()
    return f" audion-choice-tone-{tone}" if tone else ""


def render_radio_choice(field: dict[str, Any], option_items: list[dict[str, Any]], value: Any) -> None:
    key = field_id(field)
    tooltip = field_tooltip(field)
    with ui.element("div").classes(field_choice_row_classes(field)):
        for item in option_items:
            item_value = item["value"]
            classes = f"audion-choice-option{choice_tone_class(item)}"
            if item["disabled"]:
                classes += " audion-disabled-choice"
            radio = ui.radio(
                options={item_value: item["label"]},
                value=item_value if item_value == value else None,
                on_change=lambda event, option_value=item_value: set_field_value(key, option_value, refresh=True) if event.value is not None else command_tree.refresh(),
            ).props("dense").classes(classes)
            if item["disabled"]:
                radio.props("disable")
            add_tooltip(radio, item.get("tooltip") or tooltip)


def field_identity_classes(field: dict[str, Any]) -> str:
    key = field_id(field)
    if not key:
        return ""
    safe = "".join(char if char.isalnum() else "-" for char in key.lower()).strip("-")
    return f" audion-field-id-{safe}" if safe else ""


def field_container_classes(field: dict[str, Any], *, flat: bool = False) -> str:
    span = str(field.get("span") or field.get("width") or "").lower()
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    identity = field_identity_classes(field)
    choice_class = ""
    if kind in {"radio", "radiobuttons", "radio-buttons"}:
        choice_class = " audion-field-radio"
    elif kind in {"remux_format", "remux-format"}:
        choice_class = " audion-field-checks audion-field-remux-format"
    elif kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        choice_class = " audion-field-checks"
    if choice_class and field_choice_layout(field) == "vertical":
        choice_class += " audion-choice-vertical"
    flat_class = " audion-field-flat" if flat else ""
    if span in {"full", "wide", "100%", "1/-1"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}"
    if kind in {"select", "choice", "format", "file", "file_path", "path_file"}:
        return f"audion-field{identity}{choice_class}{flat_class}"
    if kind in {"textarea", "multiline", "path", "folder"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}"
    if kind in {"preset_buttons", "presets", "profile_buttons", "profiles"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}"
    if kind in {"profile_select", "profile-select", "preset_select", "preset-select"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}"
    if kind in {"lut_select", "lut-select"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}"
    if kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}"
    return f"audion-field{identity}{choice_class}{flat_class}"


def render_field(field: dict[str, Any], *, flat: bool = False) -> None:
    key = field_id(field)
    if not key:
        return
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    label = field_label(field)
    value = current_field_value(field)
    hint = field_hint(field)
    tooltip = field_tooltip(field)

    with ui.element("div").classes(field_container_classes(field, flat=flat)):
        if kind in {"preset_buttons", "presets", "profile_buttons", "profiles"}:
            presets = [preset for preset in profile_presets(field) if option_is_visible(preset)]
            selected = current_profile_id(field)
            applied_profiles = state.setdefault("applied_profiles", {})
            if selected and applied_profiles.get(key) != selected:
                preset = next((item for item in presets if preset_id(item) == selected), None)
                if preset:
                    apply_preset_values(preset)
                set_field_value(key, selected)
                applied_profiles[key] = selected
            ui.label(label).classes("audion-field-label")
            grouped_presets: list[tuple[str, str, list[dict[str, Any]]]] = []
            group_index: dict[str, int] = {}
            for preset in presets:
                group_key = preset_group_key(preset)
                if group_key not in group_index:
                    group_index[group_key] = len(grouped_presets)
                    grouped_presets.append((group_key, preset_group_label(preset), [preset]))
                else:
                    grouped_presets[group_index[group_key]][2].append(preset)
            with ui.element("div").classes("audion-preset-panel"):
                for group_key, group_label, group_presets in grouped_presets:
                    with ui.element("div").classes(f"audion-preset-group audion-preset-group-{group_key}"):
                        if group_label:
                            ui.label(group_label).classes("audion-preset-group-label")
                        with ui.element("div").classes("audion-preset-grid"):
                            total_items = len(group_presets)
                            for index, preset in enumerate(group_presets):
                                preset_key = preset_id(preset)
                                classes = f"audion-action audion-preset-button audion-preset-tone-{preset_tone(preset)} rounded-lg"
                                if preset_key == selected:
                                    classes += " audion-preset-button-active"
                                if index == 0:
                                    classes += " audion-tooltip-align-left"
                                elif index == total_items - 1:
                                    classes += " audion-tooltip-align-right"
                                preset_button = ui.button(
                                    preset_label(preset),
                                    on_click=preset_click_handler(preset, field),
                                ).props("dense flat no-wrap").classes(classes)
                                add_tooltip(preset_button, localized_manifest_text(preset, "tooltip", "hint", "description") or tooltip)
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"profile_select", "profile-select", "preset_select", "preset-select"}:
            selected = current_profile_id(field)
            options = profile_options(field)
            applied_profiles = state.setdefault("applied_profiles", {})
            if selected and applied_profiles.get(key) != selected:
                preset = next((item for item in profile_presets(field) if preset_id(item) == selected), None)
                if preset:
                    apply_preset_values(preset, skip_checkbox_values=True)
                set_field_value(key, selected)
                applied_profiles[key] = selected
            with ui.row().classes("audion-profile-row w-full items-start gap-2"):
                profile_select = ui.select(
                    options=options,
                    label=label,
                    value=selected,
                    on_change=profile_select_change_handler(field),
                ).props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select min-w-0 flex-1")
                add_tooltip(profile_select, profile_description(field, selected) or tooltip)
                profile_pin = ui.checkbox(
                    tr("pin_profile"),
                    value=selected in pinned_profiles(ROOT, key),
                    on_change=profile_pin_change_handler(field),
                ).props("dense").classes("audion-profile-pin")
                add_tooltip(profile_pin, tr("pin_profile"))
            description = profile_description(field, selected)
            if description:
                ui.label(description).classes("audion-field-hint")
            elif hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"lut_select", "lut-select"}:
            selected = current_lut_value(field)
            options = lut_options()
            if selected and selected not in options:
                options = {selected: selected, **options}
            with ui.row().classes("audion-lut-row w-full items-start gap-2"):
                lut_select = ui.select(
                    options=options,
                    label=label,
                    value=selected,
                    on_change=lut_select_change_handler(field),
                ).props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select min-w-0 flex-1")
                add_tooltip(lut_select, tooltip)
                lut_pin = ui.checkbox(
                    tr("pin_profile"),
                    value=lut_pinned(selected),
                    on_change=lut_pin_change_handler(field),
                ).props("dense").classes("audion-profile-pin")
                add_tooltip(lut_pin, tr("pin_profile"))
                lut_files_button = ui.button(icon="upload_file", on_click=lut_import_click_handler("files")).props("dense flat round")
                lut_files_button.classes("audion-action audion-icon-action audion-path-action rounded-lg")
                add_tooltip(lut_files_button, tr("choose_files"))
                lut_folder_button = ui.button(icon="folder_open", on_click=lut_import_click_handler("folder")).props("dense flat round")
                lut_folder_button.classes("audion-action audion-icon-action audion-path-action rounded-lg")
                add_tooltip(lut_folder_button, tr("choose_path"))
                lut_open_button = ui.button(icon="open_in_new", on_click=lambda: open_folder(ROOT / "LUTs")).props("dense flat round")
                lut_open_button.classes("audion-action audion-icon-action audion-path-action rounded-lg")
                add_tooltip(lut_open_button, tr("open_path"))
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"remux_format", "remux-format"}:
            selected = str(value or field_default(field)).strip().lower()
            ui.label(label).classes("audion-field-label")
            with ui.element("div").classes(f"{field_choice_row_classes(field)} audion-remux-choice-row"):
                for item in choice_option_items(field):
                    option_key = item["value"]
                    option_text = item["label"]
                    option_value_text = str(option_key).strip().lower()
                    is_disabled = item["disabled"]
                    classes = f"audion-choice-option{choice_tone_class(item)}"
                    checkbox = ui.checkbox(
                        option_text,
                        value=option_value_text == selected,
                        on_change=lambda event, item_key=key, item_value=option_value_text: set_remux_format_value(item_key, item_value) if bool(event.value) else command_tree.refresh(),
                    ).props("dense").classes(classes)
                    add_tooltip(checkbox, item.get("tooltip") or tooltip)
                    if is_disabled:
                        checkbox.props("disable").classes("audion-disabled-choice")
            if key in {"remux_target_format", "remux_audio_target_format"}:
                ui.label("Source определяется автоматически; несовместимые файлы будут пропущены с записью в лог.").classes("audion-field-hint")
            elif hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"select", "choice", "format"}:
            options = select_options(field, value)
            # A value the list does not contain makes NiceGUI raise, and the
            # whole section then fails to open rather than showing an empty
            # dropdown. It happens whenever the options are gathered at runtime:
            # an empty Source, a folder emptied between visits, a default of "".
            offered = options.keys() if isinstance(options, dict) else options
            select = ui.select(
                options=options,
                label=label,
                value=value if value in offered else None,
                on_change=lambda event, item_field=field: set_field_value_for_field(item_field, event.value, refresh=field_refreshes_layout(item_field)),
            )
            props = "dense outlined popup-content-class=audion-select-popup"
            if bool(field.get("searchable", field.get("with_input", False))):
                props += " use-input input-debounce=0"
            select.props(props).classes("audion-select w-full")
            add_tooltip(select, tooltip)
            if dynamic_option_source(field):
                refresh_button = ui.button(
                    tr("refresh_options"),
                    on_click=refresh_options_click_handler(field),
                ).props("dense flat no-wrap").classes("audion-action mt-1 rounded-lg")
                add_tooltip(refresh_button, tr("refresh_options"))
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"radio", "radiobuttons", "radio-buttons"}:
            if not flat:
                ui.label(label).classes("audion-field-label")
            option_items = choice_option_items(field)
            enabled_values = [item["value"] for item in option_items if not item["disabled"]]
            option_values = [item["value"] for item in option_items]
            if value not in option_values or any(item["value"] == value and item["disabled"] for item in option_items):
                value = enabled_values[0] if enabled_values else (option_values[0] if option_values else value)
                set_field_value(key, value)
            if field_choice_style(field) in {"segmented", "tabs", "buttons", "button-toggle", "button_toggle"}:
                render_segmented_choice(field, option_items, value)
                if hint:
                    ui.label(hint).classes("audion-field-hint")
                return
            render_radio_choice(field, option_items, value)
            if dynamic_option_source(field):
                refresh_button = ui.button(
                    tr("refresh_options"),
                    on_click=refresh_options_click_handler(field),
                ).props("dense flat no-wrap").classes("audion-action mt-1 rounded-lg")
                add_tooltip(refresh_button, tr("refresh_options"))
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"number", "int", "integer", "float"}:
            number_input = ui.number(
                label=label,
                value=value if value != "" else None,
                min=field.get("min"),
                max=field.get("max"),
                step=field.get("step", 1),
                on_change=lambda event, item_field=field: set_field_value_for_field(item_field, event.value, refresh=field_refreshes_layout(item_field)),
            ).props("dense outlined").classes("audion-number w-full")
            add_tooltip(number_input, tooltip)
            with number_input.add_slot("append"):
                with ui.element("div").classes("audion-number-spinner"):
                    spin_up = ui.button(
                        icon="keyboard_arrow_up",
                        on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, 1),
                    ).props("dense flat round tabindex=-1").classes("audion-number-spin-button")
                    add_tooltip(spin_up, tooltip)
                    spin_down = ui.button(
                        icon="keyboard_arrow_down",
                        on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, -1),
                    ).props("dense flat round tabindex=-1").classes("audion-number-spin-button")
                    add_tooltip(spin_down, tooltip)
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"file", "file_path", "path_file"}:
            with ui.row().classes("audion-file-picker-row w-full items-center gap-2"):
                file_input = ui.input(
                    label=label,
                    value=str(value) if value is not None else "",
                    placeholder=str(field.get("placeholder", "")),
                    on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                ).props("dense outlined").classes("min-w-0 flex-1")
                add_tooltip(file_input, tooltip)
                file_button = ui.button(icon="description", on_click=file_field_click_handler(field, file_input)).props("dense flat round")
                file_button.classes("audion-action audion-icon-action")
                add_tooltip(file_button, tr("choose_file"))
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"checkbox", "bool", "boolean", "toggle"}:
            # The same chip a grouped checkbox gets: one look for one kind of
            # control, whichever block it stands in.
            checkbox = ui.checkbox(
                label,
                value=bool(value),
                on_change=lambda event, item_key=key, item_field=field: set_field_value(item_key, bool(event.value), refresh=field_refreshes_layout(item_field)),
            ).props("dense").classes("audion-single-checkbox audion-choice-option")
            # A hint under one chip of three pushed the row apart; the long
            # version lives in the tooltip, which has room for it.
            add_tooltip(checkbox, " \u00b7 ".join(part for part in (tooltip, hint) if part))
            return

        if is_checkbox_group(field):
            selected = set(value if isinstance(value, list) else [])
            controls: dict[Any, Any] = {}

            def sync_checkboxes(item_key: str = key, item_field: dict[str, Any] = field, *, refresh: bool = False) -> None:
                set_field_value(
                    item_key,
                    [option_key for option_key, checkbox in controls.items() if bool(checkbox.value)],
                    refresh=refresh and field_refreshes_layout(item_field),
                )

            ui.label(label).classes("audion-field-label")
            if dynamic_option_source(field):
                refresh_button = ui.button(
                    tr("refresh_options"),
                    on_click=refresh_options_click_handler(field),
                ).props("dense flat no-wrap").classes("audion-action mb-1 rounded-lg")
                add_tooltip(refresh_button, tr("refresh_options"))
            with ui.row().classes(field_choice_row_classes(field)):
                for item in choice_option_items(field):
                    option_key = item["value"]
                    option_text = item["label"]
                    classes = f"audion-choice-option{choice_tone_class(item)}"
                    checkbox = ui.checkbox(
                        option_text,
                        value=option_key in selected and not item["disabled"],
                        on_change=lambda _event: sync_checkboxes(refresh=True),
                    ).props("dense").classes(classes)
                    add_tooltip(checkbox, item.get("tooltip") or tooltip)
                    if item["disabled"]:
                        checkbox.props("disable").classes("audion-disabled-choice")
                    controls[option_key] = checkbox
            if hint:
                ui.label(hint).classes("audion-field-hint")
            sync_checkboxes()
            return

        if kind in {"trim_file_pick", "file_badge"}:
            render_trim_file_field(field, key, str(label), str(tooltip), str(hint))
            return

        if kind in {"mpv_transport", "player_transport"}:
            render_player_transport(field, str(label), str(tooltip), str(hint))
            return

        text_input = ui.input(
            label=label,
            value=str(value) if value is not None else "",
            placeholder=str(field.get("placeholder", "")),
            on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
        ).props("dense outlined").classes("w-full")
        add_tooltip(text_input, tooltip)
        if hint:
            ui.label(hint).classes("audion-field-hint")


def is_workbench_route_field(field: dict[str, Any]) -> bool:
    key = field_id(field).lower()
    if key in {
        "source",
        "source_dir",
        "source_path",
        "input",
        "input_dir",
        "input_path",
        "input_folder",
        "target",
        "target_dir",
        "target_path",
        "destination",
        "destination_dir",
        "destination_path",
        "output",
        "output_dir",
        "output_path",
        "output_folder",
    }:
        return True
    role = str(field.get("role") or field.get("ui_role") or "").strip().lower()
    return role in {"source", "target", "destination", "output", "input"}


def command_visible_fields(fields: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [field for field in fields if not is_workbench_route_field(field)]


def workbench_value_for_field(field: dict[str, Any]) -> str:
    key = field_id(field).lower()
    role = str(field.get("role") or field.get("ui_role") or "").strip().lower()
    if role in {"target", "destination", "output"} or key.startswith(("target", "destination", "output")):
        return str(current_target_path())
    return str(current_source_path())


def operation_from_pending_command(node: CommandNode) -> Operation:
    parameters = dict(node.parameters)
    values = state.setdefault("field_values", {})
    for field in node.fields:
        key = field_id(field)
        if not key:
            continue
        if is_workbench_route_field(field):
            parameters[key] = workbench_value_for_field(field)
        else:
            parameters[key] = normalize_field_value(field, values.get(key, field_default(field)))
    return node.to_operation(parameters)


def validate_pending_fields(node: CommandNode) -> bool:
    values = state.setdefault("field_values", {})
    for field in command_visible_fields(node.fields):
        if not is_checkbox_group(field):
            continue
        min_selected = int(field.get("min_selected", 0) or 0)
        if min_selected <= 0:
            continue
        key = field_id(field)
        selected = values.get(key, field_default(field))
        if not isinstance(selected, list) or len(selected) < min_selected:
            safe_notify(tr("select_required", field=field_label(field)), "warning")
            return False
    return True


def walk_command_nodes(nodes: tuple[CommandNode, ...] | list[CommandNode] | None = None):
    for node in nodes if nodes is not None else manifest.operation_groups:
        yield node
        if node.children:
            yield from walk_command_nodes(node.children)


def assert_service_callable(service: str) -> None:
    if ":" not in service:
        raise RuntimeError(f"Service must use module:function syntax: {service}")
    module_name, function_name = service.split(":", 1)
    module = importlib.import_module(module_name)
    function = getattr(module, function_name)
    if not callable(function):
        raise RuntimeError(f"Service is not callable: {service}")


def smoke_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == []


def smoke_apply_preset_values(values: dict[str, Any], preset: dict[str, Any]) -> None:
    preset_values = preset.get("values", {})
    if isinstance(preset_values, dict):
        values.update({str(key): value for key, value in preset_values.items()})


def smoke_prepare_node_values(node: CommandNode) -> dict[str, Any]:
    values: dict[str, Any] = dict(node.parameters)
    for field in node.fields:
        key = field_id(field)
        if key:
            values[key] = field_default(field)
    state["field_values"] = dict(values)
    state["applied_profiles"] = {}
    for field in node.fields:
        kind = field_kind(field)
        if kind in {"preset_buttons", "presets", "profile_buttons", "profiles", "profile_select", "profile-select", "preset_select", "preset-select"}:
            key = field_id(field)
            selected = current_profile_id(field)
            preset = next((item for item in profile_presets(field) if preset_id(item) == selected), None)
            if preset:
                smoke_apply_preset_values(values, preset)
            if key and selected:
                values[key] = selected
            state["field_values"] = dict(values)
    return values


def smoke_numeric_value(field: dict[str, Any]) -> Any:
    value = field_default(field)
    if smoke_empty_value(value):
        value = field.get("min", 1)
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def smoke_field_variants(field: dict[str, Any], base: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    key = field_id(field)
    if not key:
        return []
    variants: list[tuple[str, dict[str, Any]]] = []
    state["field_values"] = dict(base)
    kind = field_kind(field)
    if is_checkbox_group(field):
        option_values = [item["value"] for item in choice_option_items(field) if not item["disabled"]]
        if option_values:
            min_selected = max(0, int(field.get("min_selected", 0) or 0))
            if min_selected <= 0:
                variants.append((f"{key}=empty", {**base, key: []}))
            variants.append((f"{key}=all", {**base, key: option_values}))
            if min_selected > 0:
                variants.append((f"{key}=min-selected", {**base, key: option_values[:min_selected]}))
    elif kind in {"checkbox", "bool", "boolean", "toggle"}:
        variants.append((f"{key}=toggle", {**base, key: not bool(base.get(key, field_default(field))) }))
    elif kind in {"radio", "radiobuttons", "radio-buttons", "select", "choice", "format", "remux_format", "remux-format"}:
        for item in choice_option_items(field):
            if not item["disabled"]:
                variants.append((f"{key}={item['value']}", {**base, key: item["value"]}))
    elif kind in {"preset_buttons", "presets", "profile_buttons", "profiles", "profile_select", "profile-select", "preset_select", "preset-select"}:
        for preset in profile_presets(field):
            preset_key = preset_id(preset)
            if not preset_key or not option_is_visible(preset) or option_is_disabled(preset):
                continue
            values = {**base, key: preset_key}
            smoke_apply_preset_values(values, preset)
            variants.append((f"{key}={preset_key}", values))
    elif kind in {"number", "int", "integer", "quality", "quality_percent", "quality-percent"}:
        if field_step_is_integer(field):
            variants.append((f"{key}=float-int", {**base, key: smoke_numeric_value(field)}))
    return variants


def smoke_build_operation(node: CommandNode, values: dict[str, Any]) -> Operation:
    state["field_values"] = dict(values)
    operation = operation_from_pending_command(node)
    assert_integer_number_parameters(operation, node.fields)
    return operation


def assert_integer_number_parameters(operation: Operation, fields: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> None:
    for field in fields:
        key = field_id(field)
        if not key or not field_is_integer_number(field):
            continue
        value = operation.parameters.get(key)
        if isinstance(value, float) and value.is_integer():
            raise RuntimeError(f"Integer GUI field reached Operation.parameters as float: {operation.id}/{key}={value!r}")


def run_gui_smoke() -> dict[str, int]:
    previous_values = dict(state.setdefault("field_values", {}))
    previous_profiles = dict(state.setdefault("applied_profiles", {}))
    try:
        required_handlers = {
            "start_operation": start_operation,
            "file_field_click_handler": file_field_click_handler,
            "save_advanced_open": save_advanced_open,
        }
        for handler_name, handler in required_handlers.items():
            if not callable(handler):
                raise RuntimeError(f"GUI handler is not callable: {handler_name}")
        services: set[str] = set()
        leaf_nodes = [node for node in walk_command_nodes() if not node.children]
        for operation in [*manifest.operations, *manifest.maintenance_operations]:
            if operation.service:
                assert_service_callable(operation.service)
                services.add(operation.service)
        for node in leaf_nodes:
            assert_service_callable(node.service)
            services.add(node.service)

        states = 0
        variants = 0
        for node in leaf_nodes:
            base = smoke_prepare_node_values(node)
            smoke_build_operation(node, base)
            states += 1
            for field in command_visible_fields(node.fields):
                state["field_values"] = dict(base)
                if not field_is_visible(field):
                    continue
                for _label, values in smoke_field_variants(field, base):
                    smoke_build_operation(node, values)
                    states += 1
                    variants += 1

        return {
            "services": len(services),
            "leaf_nodes": len(leaf_nodes),
            "states": states,
            "variants": variants,
        }
    finally:
        state["field_values"] = previous_values
        state["applied_profiles"] = previous_profiles


async def run_pending_command(node: CommandNode) -> None:
    if validate_pending_fields(node):
        await start_operation(operation_from_pending_command(node))


def run_pending_click_handler(node: CommandNode):
    async def handler() -> None:
        await run_pending_command(node)

    return handler


def field_signature(fields: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(field_id(field) for field in command_visible_fields(fields) if field_id(field))


def can_inline_child_actions(parent: CommandNode | None, children: list[CommandNode]) -> bool:
    if parent is None or not parent.fields or not children:
        return False
    parent_signature = field_signature(parent.fields)
    if not parent_signature:
        return False
    return all(not child.children and field_signature(child.fields) == parent_signature for child in children)


def render_inline_child_action(node: CommandNode) -> None:
    button = ui.button(
        node.display_title(settings.language),
        on_click=run_pending_click_handler(node),
    ).props("dense flat no-wrap").classes("audion-action rounded-lg")
    add_tooltip(button, node.display_description(settings.language) or node.display_title(settings.language))


ADVANCED_FIELD_SUFFIXES = (
    "_model_override",
    "_chunk_tokens",
    "_overlap_tokens",
    "_min_chunks",
    "_max_retries",
    "_max_output_tokens",
    "_timeout_sec",
    "_resume",
)


def is_advanced_field(field: dict[str, Any]) -> bool:
    if bool(field.get("advanced", False)):
        return True
    priority = str(field.get("priority") or field.get("section") or "").strip().lower()
    if priority in {"advanced", "expert", "rare"}:
        return True
    key = field_id(field)
    return any(key.endswith(suffix) for suffix in ADVANCED_FIELD_SUFFIXES)


def split_primary_advanced_fields(fields: tuple[dict[str, Any], ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary: list[dict[str, Any]] = []
    advanced: list[dict[str, Any]] = []
    for field in command_visible_fields(fields):
        if is_advanced_field(field):
            advanced.append(field)
        else:
            primary.append(field)
    return primary, advanced


def field_section_id(field: dict[str, Any]) -> str:
    key = field_id(field)
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    explicit = str(field.get("group") or field.get("ui_group") or "").strip().lower()
    if explicit:
        return explicit
    if kind in {"profile_select", "profile-select", "preset_select", "preset-select", "preset_buttons", "presets", "profile_buttons", "profiles"}:
        return "preset"
    if key in {"youtube_url", "batch_file", "youtube_source_mode", "input_formats"}:
        return "source"
    if key in {"target_codecs"}:
        return "codecs"
    if key in {"encode_backend", "backend"}:
        return "backend"
    if key in {"decode_backend", "decode_stack", "decode_hw"}:
        return "decode"
    if key in {
        "audio_mode",
        "audio_bitrate",
        "audio_format",
        "audio_sample_rate",
        "audio_bit_depth",
        "audio_lufs",
        "downmix_stereo",
        "matrix_51",
        "mp3_lame_preset",
    }:
        return "audio"
    if key in {"youtube_profile", "youtube_resolution", "youtube_video_codec", "youtube_audio_format", "youtube_container"}:
        return "format"
    if key in {"youtube_options", "subtitle_options", "parallel_fragments", "download_archive"}:
        return "options"
    if key in {"remux_profile", "remux_task", "remux_source_format", "remux_target_format", "remux_audio_source_format", "remux_audio_target_format"}:
        return "package"
    if key in {"fps_mode", "fps_target", "fps_output_profile"}:
        return "fps"
    if key in {"lut_file", "grading_profile", "script_preset", "pre_gamma"}:
        return "color"
    if key in {
        "output_container",
        "output_resolution",
        "encoder_preset",
        "cpu_encoder_preset",
        "nvenc_preset",
        "qsv_encoder_preset",
        "amf_quality",
        "av1_preset",
        "pix_fmt",
        "crf",
        "cq",
        "encode_tuning",
    }:
        return "encoding"
    if key in {"overwrite", "limit_first_file", "dry_run"}:
        return "run"
    return "parameters"


def field_section_label(section_id: str) -> str:
    return tr(f"section_{section_id}")


def _gray_hex(value: float) -> str:
    channel = max(0, min(255, int(round(value * 255))))
    return f"#{channel:02x}{channel:02x}{channel:02x}"


def color_gamma_preview_state() -> dict[str, Any] | None:
    values = state.setdefault("field_values", {})
    script = str(values.get("script_preset") or "ff-grade-lut-only-x264.cmd").strip()
    if not script:
        return None
    profile = script_profile(ROOT, script)
    filter_kind = str(profile.get("color_filter") or "").strip().lower()
    lowered = script.lower()
    if filter_kind == "hdr2sdr_hable" or "hdr2sdr" in lowered or "hable" in lowered:
        return {"mode": "hdr", "source": _gray_hex(0.18), "target": _gray_hex(0.18), "percent": 18.0}

    default_gamma = str(values.get("pre_gamma") or profile.get("pre_gamma") or "").strip()
    if filter_kind == "preexpose_lut" or "preexpose" in lowered:
        gamma = float(ffmpeg_filter_number(default_gamma or "1.15", name="pre_gamma"))
    elif filter_kind == "pregamma_lut" or "pregamma" in lowered:
        gamma = float(ffmpeg_filter_number(default_gamma or "0.85", name="pre_gamma"))
    else:
        gamma = 1.0

    source = 0.18
    target = source if gamma == 1.0 else max(0.0, min(1.0, source ** (1.0 / gamma)))
    if abs(target - source) < 0.002:
        tone = "same"
    else:
        tone = "lighter" if target > source else "darker"
    return {
        "mode": "gamma",
        "gamma": gamma,
        "source": _gray_hex(source),
        "target": _gray_hex(target),
        "percent": target * 100.0,
        "tone": tone,
    }


def render_color_gamma_preview() -> None:
    try:
        preview = color_gamma_preview_state()
    except ValueError as exc:
        with ui.element("div").classes("audion-gamma-preview audion-gamma-preview-error"):
            ui.label(str(exc)).classes("audion-gamma-preview-status")
        return
    if not preview:
        return

    mode = str(preview.get("mode") or "")
    tone = str(preview.get("tone") or "same")
    if mode == "hdr":
        status = "HDR/Hable" if settings.language == "en" else "HDR/Hable"
        detail = "tonemap" if settings.language == "en" else "tonemap"
    elif tone == "lighter":
        status = "lighter" if settings.language == "en" else "светлее"
        detail = f"{float(preview.get('percent', 18.0)):.1f}%"
    elif tone == "darker":
        status = "darker" if settings.language == "en" else "темнее"
        detail = f"{float(preview.get('percent', 18.0)):.1f}%"
    else:
        status = "neutral" if settings.language == "en" else "нейтрально"
        detail = "18.0%"

    with ui.element("div").classes(f"audion-gamma-preview audion-gamma-preview-{tone}") as preview_element:
        preview_tooltip = (
            "18% gray is a technical reference for the HDR-to-SDR stage; it is not a full image simulation."
            if mode == "hdr" and settings.language == "en"
            else "18% серый — технический ориентир этапа HDR-to-SDR, а не полная симуляция изображения."
            if mode == "hdr"
            else "Shows where pre-LUT gamma moves 18% gray. The LUT itself may change the final image further."
            if settings.language == "en"
            else "Показывает, куда Gamma до LUT переносит 18% серый. Сам LUT может дополнительно изменить итоговое изображение."
        )
        add_tooltip(preview_element, preview_tooltip)
        with ui.element("div").classes("audion-gamma-preview-swatches"):
            ui.element("div").classes("audion-gamma-swatch").style(f"background: {preview['source']}")
            ui.element("div").classes("audion-gamma-arrow")
            ui.element("div").classes("audion-gamma-swatch audion-gamma-swatch-target").style(f"background: {preview['target']}")
        with ui.element("div").classes("audion-gamma-preview-copy"):
            ui.label("18% gray").classes("audion-gamma-preview-title")
            ui.label(f"{status} · {detail}").classes("audion-gamma-preview-status")


def group_fields_by_section(fields: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    group_index: dict[str, int] = {}
    for field in fields:
        section_id = field_section_id(field)
        if section_id not in group_index:
            group_index[section_id] = len(groups)
            groups.append((section_id, [field]))
        else:
            groups[group_index[section_id]][1].append(field)
    if "workflow" in group_index and "preset" in group_index and group_index["workflow"] > group_index["preset"]:
        workflow_group = groups.pop(group_index["workflow"])
        preset_index = next((index for index, (section_id, _fields) in enumerate(groups) if section_id == "preset"), 0)
        groups.insert(preset_index, workflow_group)
    section_ids = [section_id for section_id, _fields in groups]
    if "decode" in section_ids and "backend" in section_ids:
        decode_index = section_ids.index("decode")
        backend_index = section_ids.index("backend")
        if decode_index > backend_index:
            decode_group = groups.pop(decode_index)
            groups.insert(backend_index, decode_group)
    return groups


def should_flatten_single_section_field(section_id: str, fields: list[dict[str, Any]]) -> bool:
    if len(fields) != 1:
        return False
    key = field_id(fields[0])
    return (section_id, key) in {
        ("backend", "encode_backend"),
        ("decode", "decode_backend"),
        ("audio", "audio_mode"),
    }


def render_field_grid(fields: list[dict[str, Any]]) -> None:
    if not fields:
        return
    if any(field_id(field).startswith("remux_") for field in fields):
        ensure_remux_defaults_for_mode()
    with ui.element("div").classes("audion-fields-grid"):
        for section_id, section_fields in group_fields_by_section(fields):
            visible_fields = [field for field in section_fields if field_is_visible(field)]
            if not visible_fields:
                continue
            section_classes = f"audion-field-section audion-field-section-{section_id}"
            if section_id in {"mastering", "channels"}:
                section_classes += " audion-field-section-half"
            flatten_single_field = should_flatten_single_section_field(section_id, visible_fields)
            with ui.element("section").classes(section_classes):
                ui.label(field_section_label(section_id)).classes("audion-section-title")
                with ui.element("div").classes("audion-section-fields"):
                    for field in visible_fields:
                        render_field(field, flat=flatten_single_field)
                    if section_id == "color" and any(field_id(field) == "script_preset" for field in section_fields):
                        render_color_gamma_preview()


def render_advanced_fields(fields: list[dict[str, Any]]) -> None:
    if not fields:
        return
    with ui.expansion(
        tr("advanced"),
        value=bool(getattr(settings, "advanced_open", False)),
        on_value_change=save_advanced_open,
    ).classes("audion-advanced-expansion w-full") as expansion:
        expansion.props("dense switch-toggle-side")
        render_field_grid(fields)


def save_advanced_open(event: Any) -> None:
    settings.advanced_open = bool(getattr(event, "value", False))
    save_app_settings()


def command_node_button(node: CommandNode) -> None:
    has_children = bool(node.children)
    label = node.display_title(settings.language)
    description = node.display_description(settings.language)
    if has_children and not description:
        description = tr("open_menu")

    row_classes = "audion-operation-row"
    button_classes = "audion-action audion-operation-button rounded-lg"
    if not has_children:
        row_classes += " audion-operation-row-leaf"
        button_classes += " audion-operation-button-leaf audion-tooltip-align-left"

    with ui.element("div").classes(row_classes):
        button = ui.button(
            label,
            on_click=command_click_handler(node),
        ).props(f'dense flat no-wrap data-testid="command-{node.id}"').classes(button_classes)
        add_tooltip(button, description or label)
        if has_children:
            ui.label(description).classes("audion-operation-description")


def command_nav_row(
    trail: list[CommandNode],
    pending: CommandNode | None,
    inline_actions: list[CommandNode] | None = None,
) -> None:
    can_go_back = pending is not None or bool(trail)
    if pending is not None:
        title = pending.display_title(settings.language)
    elif trail:
        title = " / ".join(node.display_title(settings.language) for node in trail)
    else:
        title = ""
    source_info = source_info_operation() if source_info_available_for_command(trail, pending, inline_actions) else None

    # At the top level this row holds nothing at all - no Back, no trail, no
    # actions - and an empty row still costs 34 px of min-height plus the
    # column gap on either side. Fifty pixels of nothing directly under the
    # heading, on the screen the operator opens first.
    if not (can_go_back or title or source_info is not None or pending is not None or inline_actions):
        return

    with ui.row().classes("audion-command-nav w-full items-center gap-2"):
        if can_go_back:
            back_button = ui.button(
                tr("back"),
                on_click=go_back_command,
            ).props("dense flat no-wrap").classes("audion-action w-28 rounded-lg")
        ui.label(title).classes("audion-command-title min-w-0 flex-1 truncate text-sm text-gray-400")
        if source_info is not None:
            source_info_button = ui.button(
                source_info.display_title(settings.language),
                on_click=operation_click_handler(source_info),
            ).props("dense flat no-wrap").classes("audion-action audion-nav-info-button rounded-lg")
            add_tooltip(source_info_button, source_info.display_description(settings.language) or source_info.display_title(settings.language))
        if pending is not None:
            run_button = ui.button(
                tr("run"),
                on_click=run_pending_click_handler(pending),
            ).props('dense flat no-wrap data-testid="run-pending"').classes("audion-action audion-nav-run-button rounded-lg")
        elif inline_actions:
            with ui.row().classes("audion-command-nav-actions items-center gap-2"):
                for node in inline_actions:
                    action_button = ui.button(
                        node.display_title(settings.language),
                        on_click=run_pending_click_handler(node),
                    ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg")
                    add_tooltip(action_button, node.display_description(settings.language) or node.display_title(settings.language))


@ui.refreshable
def command_tree() -> None:
    trail, nodes = current_command_level()
    pending = state.get("pending_command")
    parent = trail[-1] if trail else None
    inline_actions = nodes if pending is None and can_inline_child_actions(parent, nodes) else []
    command_nav_row(trail, pending, inline_actions)

    active_nodes = [*trail, *([pending] if pending is not None else [])]
    if any(node.id == "diagnostics" for node in active_nodes):
        hardware_badge()

    if pending is not None:
        if pending.fields:
            primary_fields, advanced_fields = split_primary_advanced_fields(pending.fields)
            ui.label(tr("parameters")).classes("text-sm font-semibold text-gray-300")
            render_field_grid(primary_fields)
        if pending.fields:
            render_advanced_fields(advanced_fields)
        description = pending.display_description(settings.language)
        if description:
            ui.label(description).classes("text-sm text-gray-400")
        return

    if inline_actions:
        primary_fields, advanced_fields = split_primary_advanced_fields(parent.fields)
        ui.label(tr("parameters")).classes("text-sm font-semibold text-gray-300")
        render_field_grid(primary_fields)
        render_advanced_fields(advanced_fields)
        return

    with ui.element("div").classes("audion-operation-list"):
        for node in nodes:
            command_node_button(node)


@ui.refreshable
def terminal_command_bar() -> None:
    shell_options = {"pwsh": "PowerShell", "cmd": "CMD"} if os.name == "nt" else {"sh": "Shell"}
    with ui.column().classes("audion-terminal-command w-full gap-1"):
        history_options = terminal_command_options()
        with ui.row().classes("audion-terminal-command-row w-full items-center gap-2"):
            shell_select = ui.select(
                options=shell_options,
                label=tr("terminal_shell"),
                value=str(state.get("terminal_shell") or next(iter(shell_options))),
                on_change=lambda event: set_terminal_shell(event.value),
            )
            shell_select.props("dense outlined popup-content-class=audion-select-popup").classes("audion-terminal-shell")
            add_tooltip(shell_select, tr("terminal_shell"))

            history_select = ui.select(
                options=history_options,
                label=tr("terminal_history"),
                value=terminal_history_value(history_options),
                on_change=lambda event: select_terminal_history(event_value(event)),
            )
            history_select.props("dense outlined popup-content-class=audion-select-popup").classes("audion-terminal-history min-w-0 flex-1")
            add_tooltip(history_select, tr("terminal_history"))

            pin_button = ui.button(
                icon="push_pin",
                on_click=pin_terminal_command,
            ).props("dense flat round").classes("audion-action audion-terminal-icon-button audion-terminal-pin")
            add_tooltip(pin_button, audion_terminal_action_tooltip("pin_command"))
            unpin_button = ui.button(
                icon="block",
                on_click=unpin_terminal_command,
            ).props("dense flat round").classes("audion-action audion-terminal-icon-button audion-terminal-pin")
            add_tooltip(unpin_button, audion_terminal_action_tooltip("unpin_command"))
            clear_history_button = ui.button(
                icon="delete",
                on_click=clear_terminal_history,
            ).props("dense flat round").classes("audion-action audion-terminal-icon-button audion-terminal-clear")
            add_tooltip(clear_history_button, audion_terminal_action_tooltip("clear_history"))
            terminal_run_button = ui.button(
                tr("terminal_run"),
                on_click=start_terminal_command,
            ).props("dense flat no-wrap").classes("audion-action audion-terminal-run rounded-lg")
            add_tooltip(terminal_run_button, tr("terminal_run"))

        command_area = ui.textarea(
            label=tr("terminal_command"),
            value=str(state.get("terminal_command") or ""),
            on_change=lambda event: set_terminal_command(event.value),
        )
        command_area.props("dense outlined autogrow rows=3").classes("audion-terminal-command-text w-full")
        add_tooltip(command_area, tr("terminal_command"))
        command_area.on("keydown.ctrl.enter", terminal_enter_handler)

        with ui.row().classes("w-full items-center gap-2"):
            cwd_input = ui.input(
                label=tr("terminal_cwd"),
                value=str(state.get("terminal_cwd") or ROOT),
                on_change=lambda event: set_terminal_cwd(event.value),
            ).props("dense outlined").classes("audion-terminal-cwd min-w-0 flex-1")
            add_tooltip(cwd_input, tr("terminal_cwd"))
            folder_button = ui.button(
                tr("terminal_folder"),
                on_click=terminal_location_click_handler("folder"),
            ).props("dense flat no-wrap").classes("audion-action audion-terminal-picker rounded-lg")
            add_tooltip(folder_button, tr("terminal_folder"))
            file_button = ui.button(
                tr("terminal_file"),
                on_click=terminal_location_click_handler("file"),
            ).props("dense flat no-wrap").classes("audion-action audion-terminal-picker rounded-lg")
            add_tooltip(file_button, tr("terminal_file"))


def build_file_list_lines(folder: Path) -> list[str]:
    if not folder.exists():
        return [tr("file_list_missing", path=str(folder))]
    if not folder.is_dir():
        return [tr("file_list_missing", path=str(folder))]

    names = sorted((item.name for item in folder.rglob("*") if item.is_file()), key=str.casefold)
    if not names:
        return [tr("file_list_empty")]

    number_width = max(3, len(str(len(names))))
    lines = [f"{'No.':>{number_width}}  {tr('file_list')}", f"{'-' * number_width}  ----"]
    lines.extend(f"{index:0{number_width}d}. {name}" for index, name in enumerate(names, start=1))
    return lines


async def show_input_file_list() -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    state.update(
        {
            "running": True,
            "cancel": False,
            "status": f"{tr('running')}: {tr('file_list')}",
            "progress": 0.0,
            "exit_code": None,
        }
    )
    clear_terminal_log()
    try:
        lines = await run.io_bound(build_file_list_lines, current_source_path())
        for line in lines:
            add_log(line)
        file_count = max(0, len(lines) - 2) if lines and lines[0].strip().startswith("No.") else 0
        set_progress(1.0)
        state["exit_code"] = 0
        state["status"] = f"{tr('done')}: {tr('file_list')} [{file_count}]"
        safe_notify(tr("file_list_ready", count=file_count), "positive")
    finally:
        state["running"] = False


WORKBENCH_RENDERER = WorkbenchRenderer(
    adapter=WORKBENCH_ADAPTER,
    handlers=WorkbenchHandlers(
        delete_path=workspace_delete_path_click_handler,
        pin_path=workspace_pin_click_handler,
        select_path=workspace_path_select_handler,
        pick_path=workspace_pick_click_handler,
        open_path=workspace_open_click_handler,
        add_file=workspace_single_file_click_handler,
        reset_paths=reset_workspace_paths_click_handler,
        delete_io=workspace_delete_both_click_handler,
        list_files=show_input_file_list,
    ),
    display_path_callback=display_path,
)


def operation_by_id(operation_id: str) -> Operation | None:
    for operation in [*manifest.operations, *manifest.maintenance_operations]:
        if operation.id == operation_id:
            return operation
    return None


_application_css_cache: dict[str, str] = {}


def application_css(name: str) -> str:
    """A stylesheet that lives next to this module rather than inside it."""
    if name not in _application_css_cache:
        path = Path(__file__).resolve().with_name(name)
        _application_css_cache[name] = path.read_text(encoding="utf-8")
    return _application_css_cache[name]


def add_styles() -> None:
    add_audion_canonical_ui_styles()
    variables_css = "\n".join(
        f"            --{key}: {value};"
        for key, value in sorted(theme_variables().items())
    )
    ui.add_head_html(
        "<style>\n"
        ":root {\n"
        f"{variables_css}\n"
        "}\n"
        + application_css("tokens.css")
        + application_css("theme.css")
        + "\n</style>\n"
    )
    ui.add_head_html(
        f"<style>{WORKBENCH_LAYOUT_CSS}\n{WORKBENCH_OVERRIDE_CSS}\n{WORKBENCH_FEEDBACK_CSS}</style>"
    )


@ui.refreshable
def reports_view(dialog: Any | None = None) -> None:
    if state["lines"]:
        ui.html(terminal_html(), sanitize=False).classes("audion-terminal w-full min-h-[70vh]")
        return
    ui.label(tr("recent_reports")).classes("text-sm text-gray-400")


def build_ui() -> None:
    ensure_project_dirs(paths)
    if not state["status"]:
        state["status"] = tr("idle")
    if active_theme_mode() == "dark":
        ui.dark_mode().enable()
    else:
        ui.dark_mode().disable()
    add_styles()

    with ui.header().classes("audion-header h-[42px] items-center justify-between px-4"):
        ui.label(app_title()).classes("audion-header-title text-lg font-bold")
        with ui.row().classes("audion-header-controls items-center gap-2"):
            ui.icon("palette").classes("text-lg")
            theme_select = ui.select(
                options=theme_options(),
                value=active_theme(),
                on_change=theme_change_handler,
            ).props("dense outlined options-dense").classes("audion-theme-select")
            lang_button = ui.button(tr("lang_switch"), on_click=toggle_language).props("dense flat").classes("audion-action rounded-lg")
            cancel_button = ui.button(tr("cancel"), on_click=lambda: state.update({"cancel": True})).props("dense flat color=negative")
            cancel_button.visible = False

    with ui.element("div").classes("audion-shell"):
        with ui.column().classes("audion-pane audion-scroll gap-3"):
            with ui.column().classes("audion-panel audion-workspace-panel w-full gap-2 p-2"):
                WORKBENCH_RENDERER.render_address_rows()
                WORKBENCH_RENDERER.render_action_bar()

            ui.label(f"{em('operations')}{tr('operations')}").classes("text-lg font-bold")
            command_tree()

            if manifest.maintenance_operations:
                ui.label(f"{em('maintenance')}{tr('maintenance')}").classes("text-lg font-bold pt-2")
                with ui.element("div").classes("audion-operation-list"):
                    for operation in manifest.maintenance_operations:
                        if operation.id in {"cleanup_transcoded"}:
                            continue
                        operation_button(operation)

            probe_status_initial = probe_status_text()
            with ui.row().classes("audion-probe-status w-full items-center gap-2") as probe_status_row:
                ui.label(tr("probe_status")).classes("audion-probe-status-title")
                probe_status_label = ui.label(probe_status_initial).classes("min-w-0 flex-1 truncate font-mono text-xs")
            probe_status_row.visible = bool(probe_status_initial)

        ui.element("div").classes("audion-splitter").props(f'title="{tr("resize_panels")}"')

        with ui.element("div").classes("audion-pane audion-right gap-2 pt-3"):
            with ui.column().classes("audion-panel w-full gap-2 p-3"):
                with ui.element("div").classes(status_row_classes()) as status_row:
                    status_dot_main = ui.element("span").classes("audion-status-dot-mark")
                    status_state_label = ui.label(status_state_text()).classes("audion-status-state")
                    status_label = ui.label(str(state["status"])).classes("audion-status-message")
                    status_clock = ui.label(elapsed_text(None)).classes("audion-status-clock")
                    with ui.element("div").classes("audion-status-bar"):
                        status_bar_fill = ui.element("i").style("width: 0%")
                    status_percent = ui.label(progress_text()).classes("audion-status-percent")

            with ui.column().classes("audion-terminal-panel w-full gap-2 p-3"):
                with ui.row().classes("audion-log-toolbar w-full items-center gap-2"):
                    ui.label(f"{em('log')}{tr('log')}").classes("text-base font-semibold")
                    ui.space()
                    preview_button = ui.button(tr("command_preview"), on_click=start_command_preview).props("dense flat").classes("audion-action rounded-lg")
                    add_tooltip(preview_button, audion_terminal_action_tooltip("command_preview"))
                    logs_button = ui.button(tr("logs"), on_click=lambda: open_folder(paths.logs)).props("dense flat").classes("audion-action rounded-lg")
                    add_tooltip(logs_button, audion_folder_button_tooltip("logs", paths.logs))
                    report_button = ui.button(tr("report"), on_click=lambda: (reports_view.refresh(reports_dialog), reports_dialog.open())).props("dense flat").classes("audion-action rounded-lg")
                    add_tooltip(report_button, audion_terminal_action_tooltip("report_view"))
                    config_button = ui.button(tr("config"), on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg")
                    add_tooltip(config_button, audion_folder_button_tooltip("config", paths.config))
                    clear_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                    add_tooltip(clear_log_button, audion_terminal_action_tooltip("clear_terminal_window"))
                    expand_log_button = ui.button(icon="open_in_full", on_click=lambda: log_dialog.open()).props("dense flat round").classes("audion-action audion-log-icon-button")
                    add_tooltip(expand_log_button, audion_terminal_action_tooltip("expand"))
                log_view = ui.html(terminal_html(), sanitize=False).classes("audion-terminal w-full min-h-[66vh]")
                terminal_command_bar()
                with ui.row().classes("audion-terminal-footer w-full items-center gap-2 px-1 pt-1"):
                    status_dot = ui.label("●").classes(status_dot_classes())
                    terminal_status_label = ui.label(str(state["status"])).classes("w-36 truncate text-xs")
                    probe_footer_separator = ui.label("|").classes("text-xs")
                    probe_footer_label = ui.label(probe_status_initial).classes("min-w-0 flex-1 truncate font-mono text-xs")
                    probe_footer_separator.visible = bool(probe_status_initial)
                    probe_footer_label.visible = bool(probe_status_initial)

    with ui.dialog() as log_dialog:
        with ui.card().classes("audion-dialog h-[92vh] w-[92vw] rounded-lg p-3"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(f"{em('log')}{tr('log')}").classes("text-base font-semibold")
                ui.space()
                expanded_config_button = ui.button(tr("config"), on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg")
                add_tooltip(expanded_config_button, audion_folder_button_tooltip("config", paths.config))
                clear_expanded_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                add_tooltip(clear_expanded_log_button, audion_terminal_action_tooltip("clear_terminal_window"))
                close_button = ui.button(tr("close"), on_click=log_dialog.close).props("dense flat").classes("audion-action rounded-lg").tooltip(audion_terminal_action_tooltip("close"))
                add_tooltip(close_button, tr("close"))
            expanded_log_view = ui.html(terminal_html(), sanitize=False).classes("audion-terminal audion-terminal-expanded w-full")

    with ui.dialog() as reports_dialog:
        with ui.card().classes("audion-dialog h-[86vh] w-[88vw] rounded-lg p-3"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(tr("reports")).classes("text-base font-semibold")
                ui.space()
                reports_close_button = ui.button(tr("close"), on_click=reports_dialog.close).props("dense flat").classes("audion-action rounded-lg")
                add_tooltip(reports_close_button, tr("close"))
            with ui.scroll_area().classes("w-full flex-1"):
                reports_view(reports_dialog)

    ui.run_javascript(
        """
        (() => {
          const storageKey = 'audion_gui_terminal_width_px';
          const defaultWidth = 640;
          const minLeft = 520;
          const minRight = 360;

          const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

          const applyWidth = (width) => {
            const shell = document.querySelector('.audion-shell');
            if (!shell) return;
            const rect = shell.getBoundingClientRect();
            const maxRight = Math.max(minRight, rect.width - minLeft - 40);
            const next = clamp(Number(width) || defaultWidth, minRight, maxRight);
            shell.style.setProperty('--audion-terminal-width', `${Math.round(next)}px`);
            localStorage.setItem(storageKey, String(Math.round(next)));
          };

          const setup = () => {
            const shell = document.querySelector('.audion-shell');
            const splitter = document.querySelector('.audion-splitter');
            if (!shell || !splitter) {
              setTimeout(setup, 80);
              return;
            }
            if (splitter.dataset.audionReady === '1') return;
            splitter.dataset.audionReady = '1';

            applyWidth(localStorage.getItem(storageKey) || defaultWidth);

            let dragging = false;
            const updateFromEvent = (event) => {
              if (!dragging) return;
              const rect = shell.getBoundingClientRect();
              const rightWidth = rect.right - event.clientX - 10;
              applyWidth(rightWidth);
            };

            splitter.addEventListener('pointerdown', (event) => {
              dragging = true;
              splitter.setPointerCapture?.(event.pointerId);
              document.body.classList.add('audion-resizing');
              event.preventDefault();
            });
            splitter.addEventListener('pointermove', updateFromEvent);
            splitter.addEventListener('pointerup', (event) => {
              dragging = false;
              splitter.releasePointerCapture?.(event.pointerId);
              document.body.classList.remove('audion-resizing');
            });
            splitter.addEventListener('pointercancel', () => {
              dragging = false;
              document.body.classList.remove('audion-resizing');
            });
            window.addEventListener('resize', () => applyWidth(localStorage.getItem(storageKey) || defaultWidth));
          };

          setup();
        })();
        """
    )
    ui.run_javascript(
        """
        (() => {
          if (window.audionTerminalAppend) return;

          const terminals = () => Array.from(document.querySelectorAll('.audion-terminal'));
          const atBottom = (el) => el.scrollHeight - el.scrollTop - el.clientHeight <= 24;
          const hasSelection = (el) => {
            const selection = window.getSelection();
            if (!selection || selection.isCollapsed) return false;
            return el.contains(selection.anchorNode) || el.contains(selection.focusNode);
          };
          const scrollIfWanted = (el, shouldScroll) => {
            if (shouldScroll) el.scrollTop = el.scrollHeight;
          };
          const scrollTop = () => {
            terminals().forEach((el) => { el.scrollTop = 0; });
          };

          window.audionTerminalSet = (html, forceScroll = false) => {
            terminals().forEach((el) => {
              const shouldScroll = (forceScroll || atBottom(el)) && !hasSelection(el);
              el.innerHTML = html;
              scrollIfWanted(el, shouldScroll);
            });
          };

          window.audionTerminalAppend = (html) => {
            if (!html) return;
            terminals().forEach((el) => {
              const shouldScroll = atBottom(el) && !hasSelection(el);
              let pre = el.querySelector('.audion-terminal-pre');
              if (!pre) {
                el.innerHTML = '<pre class="audion-terminal-pre"></pre>';
                pre = el.querySelector('.audion-terminal-pre');
              }
              pre.insertAdjacentHTML('beforeend', html);
              scrollIfWanted(el, shouldScroll);
            });
          };
          window.audionTerminalScrollTop = () => scrollTop();
        })();
        """
    )

    last_terminal = {
        "epoch": int(state.get("terminal_epoch", 0)),
        "base": int(state.get("terminal_base", 0)),
        "seq": int(state.get("terminal_seq", 0)),
    }

    refresh_timer: Any | None = None

    # Every one of these used to be written twice a second whether or not it had
    # changed, so an idle window still sent ten element updates a second. Holding
    # the last value makes an idle panel cost nothing and pays for the clock.
    shown = {"status": None, "state": None, "row": None, "clock": None, "percent": None, "fill": None}
    run_clock: dict[str, float | None] = {"started": None, "frozen": None}

    def refresh() -> None:
        nonlocal refresh_timer
        try:
            running = bool(state["running"])
            if running and run_clock["started"] is None:
                run_clock["started"] = time.monotonic()
                run_clock["frozen"] = None
            elif not running and run_clock["started"] is not None:
                run_clock["frozen"] = time.monotonic() - run_clock["started"]
                run_clock["started"] = None
            seconds = (
                time.monotonic() - run_clock["started"]
                if run_clock["started"] is not None
                else run_clock["frozen"]
            )

            def show(key: str, value: Any, assign: Any) -> None:
                if shown[key] != value:
                    shown[key] = value
                    assign(value)

            message = str(state["status"])
            show("status", message, lambda value: (
                setattr(status_label, "text", value),
                setattr(terminal_status_label, "text", value),
            ))
            show("state", status_state_text(), lambda value: setattr(status_state_label, "text", value))
            show("row", status_row_classes(), lambda value: (
                status_row.classes(replace=value),
                status_dot.classes(replace=status_dot_classes()),
            ))
            show("clock", elapsed_text(seconds), lambda value: setattr(status_clock, "text", value))
            show("percent", progress_text(), lambda value: setattr(status_percent, "text", value))
            show("fill", f"{float(state['progress']) * 100:.1f}%",
                 lambda value: status_bar_fill.style(f"width: {value}"))
            current_probe_status = probe_status_text()
            probe_status_label.text = current_probe_status
            probe_status_row.visible = bool(current_probe_status)
            probe_footer_label.text = current_probe_status
            probe_footer_separator.visible = bool(current_probe_status)
            probe_footer_label.visible = bool(current_probe_status)
            epoch = int(state.get("terminal_epoch", 0))
            base = int(state.get("terminal_base", 0))
            seq = int(state.get("terminal_seq", 0))
            if epoch != last_terminal["epoch"] or base != last_terminal["base"] or seq < last_terminal["seq"]:
                empty_html = render_terminal_html(())
                append_html = terminal_delta_html(0)
                last_terminal.update({"epoch": epoch, "base": base, "seq": seq})
                scroll_top = int(state.get("terminal_scroll_top_seq", 0)) and int(state.get("terminal_scroll_top_seq", 0)) <= seq
                if scroll_top:
                    state["terminal_scroll_top_seq"] = 0
                ui.run_javascript(
                    "window.audionTerminalSet("
                    f"{json.dumps(empty_html)}, true);"
                    "window.audionTerminalAppend("
                    f"{json.dumps(append_html)});"
                    + ("window.audionTerminalScrollTop();" if scroll_top else "")
                )
            elif seq > last_terminal["seq"]:
                start_index = max(0, last_terminal["seq"] - base)
                append_html = terminal_delta_html(start_index)
                last_terminal["seq"] = seq
                scroll_top = int(state.get("terminal_scroll_top_seq", 0)) and int(state.get("terminal_scroll_top_seq", 0)) <= seq
                if scroll_top:
                    state["terminal_scroll_top_seq"] = 0
                ui.run_javascript(
                    f"window.audionTerminalAppend({json.dumps(append_html)});"
                    + ("window.audionTerminalScrollTop();" if scroll_top else "")
                )
            cancel_button.visible = bool(state["running"])
        except RuntimeError as exc:
            message = str(exc)
            if "slot belongs to has been deleted" not in message and "current slot cannot be determined" not in message:
                raise
            logging.warning("NiceGUI refresh timer stopped because the client slot was deleted.")
            if refresh_timer is not None:
                refresh_timer.deactivate()

    refresh_timer = ui.timer(0.5, refresh)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audion NiceGUI shell.")
    parser.add_argument("--host", default=str(ui_info.get("host", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(ui_info.get("port", 8080)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


def port_is_open(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in str(host or "") else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def assert_gui_host_allowed(host: str) -> None:
    normalized = str(host or "").strip().lower().strip("[]")
    try:
        is_loopback = normalized == "localhost" or ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        is_loopback = normalized == "localhost"
    allow_remote = str(os.environ.get("AUDION_ALLOW_REMOTE_GUI", "")).strip().lower() in {"1", "true", "yes", "on"}
    if not is_loopback and not allow_remote:
        raise SystemExit(
            "Refusing non-loopback host for a GUI with process execution. "
            "Use 127.0.0.1/localhost/::1, or set AUDION_ALLOW_REMOTE_GUI=1 explicitly."
        )


def build_ui_once() -> dict[str, int]:
    """Build the whole page once, headlessly, and report what came of it.

    `--smoke` used to print a line and return, so an app could ship a `build_ui`
    that raised on its first statement and still pass — twice in this fleet it did.
    Here the page is actually built: no browser and no HTTP request, so whatever
    the app defers until a client attaches is skipped, but every widget is
    constructed and the stylesheet has to arrive.
    """
    import asyncio
    import logging
    import re

    from nicegui import core
    from nicegui.client import Client
    from nicegui.page import page as page_definition

    async def build() -> tuple[int, str]:
        core.loop = asyncio.get_running_loop()
        # Work deferred to a connected browser fails here and says nothing about
        # the build. An exception raised by build_ui itself still propagates.
        core.loop.set_exception_handler(lambda _loop, _context: None)
        logging.getLogger("nicegui").setLevel(logging.CRITICAL)
        client = Client(page_definition("/__smoke__"))
        with client:
            build_ui()
        report = len(client.elements), client.shared_head_html + client.head_html
        # The page starts work that waits for a browser to attach. Nothing will
        # attach, so stop it deliberately instead of letting the loop close on it.
        pending = asyncio.all_tasks(core.loop) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return report

    element_count, head = asyncio.run(build())
    if element_count < 2:
        raise RuntimeError("build_ui produced no widgets")
    # Token prefixes differ between apps, so look for any custom property rather
    # than for one project's naming.
    if not re.search(r"--[\w-]+\s*:", head):
        raise RuntimeError("the stylesheet never reached the page")
    return {"elements": element_count, "stylesheet_bytes": len(head)}


def main() -> int:
    args = parse_args()
    assert_gui_host_allowed(args.host)
    ensure_project_dirs(paths)
    if args.smoke:
        try:
            report = build_ui_once()
        except Exception as error:  # noqa: BLE001
            print(f"FAIL nicegui shell: {ROOT}: {error}")
            return 1
        print(
            f"OK nicegui build: {ROOT}"
            f" | widgets={report['elements']}"
            f" | stylesheet={report['stylesheet_bytes']} bytes"
        )
        result = run_gui_smoke()
        print(
            "OK nicegui shell: "
            f"{ROOT} "
            f"({result['services']} service(s), "
            f"{result['leaf_nodes']} command leaf node(s), "
            f"{result['states']} GUI state(s), "
            f"{result['variants']} control override(s))"
        )
        return 0

    if port_is_open(args.host, args.port):
        url = f"http://{args.host}:{args.port}/"
        print(f"GUI already appears to be running: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    ui.run(
        root=build_ui,
        title=app_title(),
        host=args.host,
        port=args.port,
        reload=False,
        native=False,
        show=not args.no_browser,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
