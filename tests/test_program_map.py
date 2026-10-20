"""The map of the program (`media_cli.cmd map`, core\\program_map.py) against its data and against the former window.

The documents of the program are built from the map, never from a memory of the code. So the map must be whole:
every section, mode, group, operation, field, preset and wrapper has its text in both languages; and no text the
former window had is lost on the way - tests\\former_window_map.json holds them, its manifest and the tooltips its
code kept for fields the manifest left without one. What 3.0.0 words otherwise on purpose is named in REWORDED.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from system_core.core import program_map
from system_core.core.manifest import load_manifest
from system_core.core.paths import get_project_paths

PROJECT = Path(__file__).resolve().parent.parent
FORMER = json.loads((Path(__file__).resolve().parent / "former_window_map.json").read_text(encoding="utf-8"))
OWN_TEXT = ("tooltip", "tooltip_ru", "hint", "hint_ru", "description", "description_ru")
TEXTS = (*OWN_TEXT, "label", "label_ru", "title", "title_ru")

# Worded otherwise on purpose: the owner, 15.10.2026, "Source -> Transcoded на input -> output" - the folders are input and
# output, the window calls them the Source and the Target (Источник, Назначение), and the list of links lies in the Source.
REWORDED = {
    "Посчитать Source, Transcoded, Download и LUTs.": "Посчитать файлы в Источнике, Назначении и LUTs.",
    "Read links from Download\\urls.txt.": "Read links from input\\urls.txt.",
    "Читать ссылки из Download\\urls.txt.": "Читать ссылки из input\\urls.txt.",
    "Download\\urls.txt": "input\\urls.txt",
    "Обработать отдельные аудиофайлы из Source: WAV, FLAC, M4A, MP3, AAC или Opus.":
        "Обработать отдельные аудиофайлы из Источника: WAV, FLAC, M4A, MP3, AAC или Opus.",
    "Source is scanned recursively; OUT keeps the same subfolder structure.":
        "The Source is scanned recursively; the Target keeps the same subfolder structure.",
    "Source обходится рекурсивно; OUT сохраняет такую же структуру подпапок.":
        "Источник обходится рекурсивно; Назначение сохраняет такую же структуру подпапок.",
    "Видео- и звуковые файлы из Source по алфавиту. Режется один файл за раз: у дублей редко совпадают ключевые кадры, не говоря о точках реза.":
        "Видео- и звуковые файлы из Источника по алфавиту. Режется один файл за раз: у дублей редко совпадают ключевые кадры, не говоря о точках реза.",
    "Один или несколько выходных таргетов. Каждый таргет пишется отдельно для каждого файла Source.":
        "Один или несколько выходных таргетов. Каждый таргет пишется отдельно для каждого файла Источника.",
    "Один раз запустить ffprobe по Source, вывести таблицу и обновить строку параметров.":
        "Один раз запустить ffprobe по Источнику, вывести таблицу и обновить строку параметров.",
    "Прогнать ffprobe по Source и вывести все аудиопотоки: codec, sample_fmt, sample rate, bits, channels, bitrate, language/title.":
        "Прогнать ffprobe по Источнику и вывести все аудиопотоки: codec, sample_fmt, sample rate, bits, channels, bitrate, language/title.",
    "Удалить файлы из выбранной папки Source, включая внешний выбранный Source после подтверждения.":
        "Удалить файлы из выбранного Источника, включая внешнюю папку или файл после подтверждения.",
    "Очистить Source": "Очистить Источник",
    "Удалить файлы из выбранного назначения/OUT, включая внешнюю выбранную папку после подтверждения.":
        "Удалить файлы из выбранного Назначения, включая внешнюю папку после подтверждения.",
    "Clear OUT": "Clear Target",
    "Очистить OUT": "Очистить Назначение",
    # The audit of 16.10.2026 (F07): a lossless archive keeps the bits or refuses, and the presets say so.
    "Archive master with all streams mapped and FLAC audio.":
        "Archive master with all streams mapped and FLAC audio; float PCM, which FLAC cannot hold, is copied as it is. "
        "A pixel format FFV1 cannot keep is refused.",
    "Архивный мастер со всеми потоками и FLAC аудио.":
        "Архивный мастер со всеми потоками и FLAC аудио; PCM с плавающей точкой, которого FLAC не держит, копируется как есть. "
        "Пиксельный формат, который FFV1 не сохранит, отклоняется.",
    "CRF 0 x264 archive variant, useful when FFV1 is too heavy.":
        "CRF 0 x264 archive variant, useful when FFV1 is too heavy. Keeps YUV of 8 and 10 bits; a 12-bit, RGB or alpha "
        "source is refused - FFV1 keeps it.",
    "CRF 0 x264 как архивный вариант, когда FFV1 слишком тяжелый.":
        "CRF 0 x264 как архивный вариант, когда FFV1 слишком тяжелый. Держит YUV 8 и 10 бит; источник 12 бит, RGB или с "
        "альфой отклоняется — его сохранит FFV1.",
    # The owner, 18.10.2026: FFmpeg by the NVIDIA driver - the newest stable, 9.0.2 at least, from the LTS driver 610.88.
    "Install or refresh portable FFmpeg Gyan GPL payload into Tools/ffmpeg.":
        "Install or refresh the portable FFmpeg of Gyan (GPL) in Tools\\ffmpeg by the NVIDIA driver: the newest stable, "
        "9.0.2 at least, without an NVIDIA card and from the LTS driver 610.88; below it 8.0.1 (570-610.87) or 7.1 so that "
        "NVENC works, and not every operation is possible.",
    "Установить или обновить portable FFmpeg Gyan GPL payload в Tools/ffmpeg.":
        "Установить или обновить переносную FFmpeg от Gyan (GPL) в Tools\\ffmpeg по драйверу NVIDIA: самая новая стабильная, "
        "не ниже 9.0.2, без карты NVIDIA и с LTS-драйвером 610.88 и новее; ниже него 8.0.1 (570-610.87) или 7.1, чтобы "
        "работал NVENC, и доступны не все операции.",
}


# Fields whose words were written anew with the field itself, with why.
REMADE = {
    "trim_exact": "the flag became a choice of two modes - exact and lossless - and its words went to the two choices "
                  "(the owner, 15.10.2026: 'переключатель: lossy-резка (точно) и lossless')",
}


@pytest.fixture(scope="module")
def told() -> dict[str, Any]:
    paths = get_project_paths(PROJECT)
    return program_map.build(paths, load_manifest(paths.config / "tool_manifest.yaml"), version="test")


def strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(strings(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(strings(item) for item in value)) if value else set()
    return set()


def former_texts(node: Any, where: str = "") -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    if isinstance(node, dict):
        ident = str(node.get("id", ""))
        found += [(f"{where}/{ident}", key, node[key]) for key in TEXTS if isinstance(node.get(key), str) and node[key].strip()]
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                found += former_texts(value, f"{where}/{ident or key}")
    elif isinstance(node, list):
        for item in node:
            found += former_texts(item, where)
    return found


def former_fields(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        own = [node] if "id" in node and ("type" in node or "label" in node) and "fields" not in node else []
        return own + [field for value in node.values() for field in former_fields(value)]
    if isinstance(node, list):
        return [field for item in node for field in former_fields(item)]
    return []


def test_the_map_misses_no_text(told: dict[str, Any]) -> None:
    assert told["missing"] == []


def test_the_map_is_whole(told: dict[str, Any]) -> None:
    assert [section["id"] for section in told["sections"]] == ["audio", "encode", "package", "cut", "rate", "color", "download"]
    assert len(told["wrappers"]) == 95
    assert {group["id"] for group in told["groups"]} >= {"youtube", "audio", "archive", "trim", "fps", "grading"}
    for name, wrapper in told["wrappers"].items():
        assert all(run["op"] in told["operations"] for run in wrapper["runs"]), name
        assert len(wrapper["as_runs"]) == len(wrapper["runs"]) and wrapper["call"] == f"media_cli.cmd wrapper {name}"
    assert told["operations"]["remux_run"]["wrappers"][:1] == ["ff-remux-mkv-to-mp4"]


def test_every_text_of_the_former_window_is_in_the_map(told: dict[str, Any]) -> None:
    """Its manifest whole, and of the tooltips its code kept the ones it showed: for a field without its own text."""
    known = strings(told)
    lost = [f"{where} {key}: {text}" for where, key, text in former_texts(FORMER["manifest"])
            if REWORDED.get(text, text) not in known and where.rsplit("/", 1)[-1] not in REMADE]
    bare = {str(field["id"]) for field in former_fields(FORMER["manifest"]["operation_groups"])
            if not any(field.get(key) for key in OWN_TEXT)}
    lost += [f"code tooltip of {field} ({language}): {text}" for field, texts in FORMER["code"]["field_tooltip_fallbacks"].items()
             if field in bare for language, text in texts.items() if REWORDED.get(text, text) not in known]
    assert not lost, "\n".join(lost)


def test_a_reworded_text_is_not_left_as_it_was(told: dict[str, Any]) -> None:
    known = strings(told)
    assert [old for old in REWORDED if old in known] == []


def test_a_condition_is_told_in_words() -> None:
    condition = {"all": [{"audio_channel_mode": "stereo"}, {"matrix_51": False}, {"not": {"audio_format": "copy"}}]}
    assert program_map.condition_words(condition) == "all of (audio_channel_mode is stereo; matrix_51 is off; not (audio_format is copy))"
    assert program_map.condition_words({"audio_format": ["m4a", "opus"]}, "ru") == "audio_format - одно из m4a, opus"
    field = next(item for item in program_map.build(get_project_paths(PROJECT), load_manifest(PROJECT / "config" / "tool_manifest.yaml"))
                 ["operations"]["audio_run"]["fields"] if item["id"] == "downmix_formula")
    assert field["when"].startswith("shown when all of (audio_channel_mode is stereo")


def test_the_console_command_writes_the_map(tmp_path: Path) -> None:
    out = tmp_path / "map.json"
    done = subprocess.run([sys.executable, "-u", str(PROJECT / "system_core" / "cli.py"), "map", "--out", str(out)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=str(PROJECT), timeout=300)
    assert done.returncode == 0, done.stderr[-500:]
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["program"]["name"] == "Audion Media Tools" and written["missing"] == [] and "[MAP]" in done.stdout
