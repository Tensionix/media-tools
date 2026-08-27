from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any
import json
import os
import re
import shutil
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from system_core.core.audio_contract import mp3_encoder_args, normalize_mp3_preset, resample_filter_args
from system_core.core.encoder_backends import (
    AMF_QUALITY_PRESETS,
    CPU_ENCODER_PRESETS,
    NVENC_PRESETS,
    QSV_ENCODER_PRESETS,
    decode_args as backend_decode_args,
    decode_output_format_args,
    hardware_pix_fmt,
    normalize_amf_quality,
    normalize_cpu_preset,
    normalize_encode_backend,
    normalize_decode_backend,
    normalize_nvenc_preset,
    normalize_qsv_preset,
)
from system_core.core.ffmpeg_escape import ffmpeg_filter_number, ffmpeg_filter_path
from system_core.core.trim_contract import (
    audio_channel_complaint,
    audio_channel_filter,
    audio_reencode_args,
    build_trim_command,
    format_offset,
    format_seconds,
    is_variable_rate,
    keyframe_probe_command,
    parse_keyframe_times,
    parse_rate,
    parse_seconds,
    extra_stream_plan,
    plan_cut,
    plan_gap,
    rate_label,
    shift_timecode,
    timecode_is_drop_frame,
    zero_timecode,
)

# Muxers that will refuse a codec outright. FFmpeg answers with "Could not find
# tag for codec" and leaves a zero-byte file, which is a poor way to learn that
# MP4 cannot hold ProRes.
# Measured; see Docs/TRIM_MATRIX_RU.md.
TRIM_CONTAINER_REFUSALS = {
    "mp4": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "huffyuv", "utvideo", "cineform"},
    "m4v": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "huffyuv", "utvideo", "cineform"},
    "mov": {"av1", "vp9"},
    "m2ts": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "vp9", "av1"},
    "ts": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "vp9", "av1"},
    "mxf": {"vp9", "av1", "hevc"},
}

TRIM_AUDIO_REFUSALS = {
    "mov": {"flac", "opus", "vorbis"},
    "m2ts": {"flac", "alac", "vorbis"},
    "ts": {"flac", "alac", "vorbis"},
}

# HEVC with a B-pyramid writes a few frames fewer than `-frames:v` asks for.
TRIM_TOP_UP_LIMIT = 16
from system_core.core.fps_contract import (
    build_fps_command,
    fps_audio_output_rate,
    fps_audio_target_rate,
)
from system_core.core.video_contract import scale_filter
from system_core.services.media_service import _fps_output_args


VIDEO_EXTS = {"mp4", "m4v", "mov", "mkv", "mxf", "avi", "webm", "mpg", "mpeg", "mts", "m2ts", "ts", "3gp"}
AUDIO_EXTS = {
    "wav",
    "w64",
    "flac",
    "m4a",
    "m4b",
    "aac",
    "mp3",
    "opus",
    "oga",
    "ogg",
    "aif",
    "aiff",
    "caf",
    "au",
    "snd",
    "ac3",
    "eac3",
    "dts",
    "mka",
    "ape",
    "wv",
    "tak",
    "tta",
    "mpc",
    "mpc8",
    "amr",
    "awb",
    "spx",
    "dsf",
    "dff",
}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS

FPS_RATES = {
    "100": Fraction(100, 1),
    "11988": Fraction(12000, 1001),
    "17982": Fraction(18000, 1001),
    "24": Fraction(24, 1),
    "25": Fraction(25, 1),
    "2997": Fraction(30000, 1001),
    "50": Fraction(50, 1),
    "5994": Fraction(60000, 1001),
    "23976": Fraction(24000, 1001),
}


def truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def split_values(value: str) -> list[str]:
    return [item.strip().strip(".").lower() for item in re.split(r"[,; ]+", value) if item.strip()]


def normalize_bitrate(value: str, default: str = "384k") -> str:
    clean = (value or default).strip().lower().replace("kbps", "k").replace(" ", "")
    if clean in {"192", "256", "320", "384"}:
        clean += "k"
    return clean if clean in {"192k", "256k", "320k", "384k"} else default


def list2cmdline(command: list[str]) -> str:
    return subprocess.list2cmdline([str(item) for item in command])


def atempo_chain(speed: float) -> str:
    parts: list[float] = []
    value = float(speed)
    while value < 0.5:
        parts.append(0.5)
        value /= 0.5
    while value > 2.0:
        parts.append(2.0)
        value /= 2.0
    parts.append(value)
    return ",".join(f"atempo={part:.8g}" for part in parts)


def load_catalog(root: Path) -> dict[str, Any]:
    try:
        from system_core.core.script_profiles import load_script_profiles

        return load_script_profiles(root)
    except Exception as exc:
        print(f"[WARN] Script profile catalog is unavailable: {exc}", file=sys.stderr)
        return {"defaults": {}, "profiles": {}}


def profile_id(value: str) -> str:
    return Path(str(value).strip().strip('"')).stem.lower()


class Runner:
    def __init__(self, profile: str, args: list[str]) -> None:
        self.profile = profile_id(profile)
        self.args = args
        self.root = Path(__file__).resolve().parents[2]
        self.catalog = load_catalog(self.root)
        profiles = self.catalog.get("profiles", {})
        self.profile_config = profiles.get(self.profile, {}) if isinstance(profiles, dict) else {}
        if not isinstance(self.profile_config, dict):
            self.profile_config = {}
        defaults = self.catalog.get("defaults", {})
        self.defaults = defaults if isinstance(defaults, dict) else {}
        self.source_dir = self.resolve_path(first_env("AUDION_SOURCE", "AUDION_SRC", "SOURCE", "SRC"), self.root / "Source")
        self.output_dir = self.resolve_path(first_env("AUDION_OUTPUT", "AUDION_OUT", "AUDION_DESTINATION", "OUT"), self.root / "Transcoded")
        self.download_dir = self.resolve_path(first_env("AUDION_DOWNLOAD", "AUDION_DOWNLOAD_DIR", "DL"), self.root / "Download")
        self.luts_dir = self.resolve_path(first_env("AUDION_LUTS", "LUTS"), self.root / "LUTs")
        self.dry_run = truthy(first_env("AUDION_DRY_RUN", "DRY_RUN"), False)
        self.overwrite = truthy(first_env("AUDION_OVERWRITE", "OVERWRITE"), True)
        self.limit_first = truthy(first_env("AUDION_LIMIT_FIRST_FILE", "AUDION_FIRST_FILE", "FIRST_FILE"), False)
        self.recursive = truthy(first_env("AUDION_RECURSIVE", "RECURSIVE"), True)
        default_bitrate = str(self.cfg("audio_bitrate", self.defaults.get("audio_bitrate", "384k")))
        self.audio_bitrate = normalize_bitrate(first_env("AUDION_AUDIO_BITRATE", "AUDIO_BITRATE"), default_bitrate)
        self.mp3_lame_preset = normalize_mp3_preset(
            first_env("AUDION_MP3_LAME_PRESET", "MP3_LAME_PRESET", default=str(self.cfg("mp3_lame_preset", "v0")))
        )
        self.crf = first_env("AUDION_CRF", "CRF", default=str(self.cfg("crf", "")))
        self.cq = first_env("AUDION_CQ", "AUDION_QP", "CQ", "QP", default=str(self.cfg("cq", self.defaults.get("cq", "14"))))
        self.encode_backend = normalize_encode_backend(first_env("AUDION_ENCODE_BACKEND", "AUDION_BACKEND", "ENCODE_BACKEND", default="cpu"))
        self.cpu_encoder_preset = normalize_cpu_preset(
            first_env(
                "AUDION_CPU_ENCODER_PRESET",
                default=str(self.cfg("cpu_encoder_preset", self.defaults.get("cpu_encoder_preset", self.defaults.get("encoder_preset", "medium")))),
            )
        )
        self.nvenc_preset = normalize_nvenc_preset(
            first_env("AUDION_NVENC_PRESET", default=str(self.cfg("nvenc_preset", self.defaults.get("nvenc_preset", "p6"))))
        )
        self.qsv_encoder_preset = normalize_qsv_preset(
            first_env("AUDION_QSV_ENCODER_PRESET", default=str(self.cfg("qsv_encoder_preset", self.defaults.get("qsv_encoder_preset", "medium"))))
        )
        self.amf_quality = normalize_amf_quality(first_env("AUDION_AMF_QUALITY", default=str(self.cfg("amf_quality", self.defaults.get("amf_quality", "quality")))))
        legacy_preset = first_env("AUDION_ENCODER_PRESET", "ENCODER_PRESET", "PRESET", default="")
        if legacy_preset:
            if self.encode_backend == "cuda":
                self.nvenc_preset = normalize_nvenc_preset(legacy_preset)
            elif self.encode_backend == "qsv":
                self.qsv_encoder_preset = normalize_qsv_preset(legacy_preset)
            elif self.encode_backend == "amd":
                self.amf_quality = normalize_amf_quality(legacy_preset)
            else:
                self.cpu_encoder_preset = normalize_cpu_preset(legacy_preset)
        self.encoder_preset = {
            "cuda": self.nvenc_preset,
            "qsv": self.qsv_encoder_preset,
            "amd": self.amf_quality,
        }.get(self.encode_backend, self.cpu_encoder_preset)
        self.pix_fmt = first_env("AUDION_PIX_FMT", "PIX_FMT", default=str(self.cfg("pix_fmt", self.defaults.get("pix_fmt", "yuv420p"))))
        self.audio_sample_rate = first_env("AUDION_AUDIO_SAMPLE_RATE", "AUDIO_SAMPLE_RATE", default=str(self.cfg("audio_sample_rate", "source")))
        self.decode_backend = normalize_decode_backend(first_env("AUDION_DECODE_BACKEND", "DECODE_BACKEND", default="auto"))
        self.input_formats = set(split_values(first_env("AUDION_INPUT_FORMATS", "INPUT_FORMATS")))
        self.env = os.environ.copy()
        self.env["PYTHONIOENCODING"] = "utf-8"
        self.env["PYTHONUTF8"] = "1"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def cfg(self, key: str, default: Any = None) -> Any:
        return self.profile_config.get(key, default)

    def cfg_list(self, key: str) -> list[str]:
        value = self.profile_config.get(key, [])
        if isinstance(value, list):
            return [str(item) for item in value]
        if value is None or value == "":
            return []
        return [str(value)]

    def resolve_path(self, raw: str, default: Path) -> Path:
        if not raw:
            return default
        text = os.path.expandvars(raw.strip().strip('"'))
        path = Path(text).expanduser()
        return path if path.is_absolute() else self.root / path

    def tool_path(self, name: str, candidates: list[Path]) -> str:
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        resolved = shutil.which(name)
        if resolved:
            return resolved
        raise RuntimeError(f"{name} was not found in portable Tools or PATH.")

    @property
    def ffmpeg(self) -> str:
        return self.tool_path("ffmpeg", [self.root / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"])

    @property
    def ffprobe(self) -> str:
        return self.tool_path("ffprobe", [self.root / "Tools" / "ffmpeg" / "bin" / "ffprobe.exe"])

    @property
    def ytdlp(self) -> str:
        return self.tool_path(
            "yt-dlp",
            [
                self.root / "Tools" / "yt-dlp" / "bin" / "yt-dlp.exe",
                self.root / "Tools" / "yt-dlp" / "yt-dlp.exe",
            ],
        )

    @property
    def deno(self) -> str | None:
        candidates = [
            self.root / "Tools" / "deno" / "deno.exe",
            self.root / "Tools" / "deno" / "bin" / "deno.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return shutil.which("deno")

    def tool_env(self) -> dict[str, str]:
        paths = [
            self.root / "Tools" / "ffmpeg" / "bin",
            self.root / "Tools" / "yt-dlp" / "bin",
            self.root / "Tools" / "deno",
            self.root / "Tools" / "deno" / "bin",
            self.root / "Tools" / "7zip" / "bin",
        ]
        existing = [str(path) for path in paths if path.exists()]
        env = self.env.copy()
        env["PATH"] = os.pathsep.join([*existing, env.get("PATH", "")])
        return env

    def run(self, command: list[str], cwd: Path | None = None) -> None:
        print("[CMD] " + list2cmdline(command), flush=True)
        if self.dry_run:
            return
        result = subprocess.run(command, cwd=str(cwd or self.root), env=self.tool_env())
        if result.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {result.returncode}.")

    def probe_one(self, command: list[str]) -> str:
        result = subprocess.run(
            command,
            cwd=str(self.root),
            env=self.tool_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""

    def yt_base_command(self) -> list[str]:
        command = [self.ytdlp]
        deno = self.deno
        if deno:
            command.extend(["--js-runtimes", f"deno:{deno}"])
            return command
        override = first_env("AUDION_YTDLP_JS_RUNTIMES", "YTDLP_JS_RUNTIMES")
        if override:
            command.extend(["--js-runtimes", override])
            return command
        print(
            "[WARN] No Deno JS runtime found. YouTube formats may be limited.",
            file=sys.stderr,
        )
        return command

    def yt_cookies_args(self) -> list[str]:
        browser = first_env("AUDION_YTDLP_COOKIES_BROWSER", "YTDLP_COOKIES_BROWSER")
        if browser:
            return ["--cookies-from-browser", browser]
        cookie_file = first_env("AUDION_YTDLP_COOKIES", "YTDLP_COOKIES", "COOKIES")
        if cookie_file:
            return ["--cookies", cookie_file]
        cookies_env = str(self.cfg("cookies_env", ""))
        if cookies_env and os.environ.get(cookies_env):
            return ["--cookies", os.environ[cookies_env]]
        return []

    def yt_sponsorblock_args(self) -> list[str]:
        cats = first_env("AUDION_YTDLP_SPONSORBLOCK", "YTDLP_SPONSORBLOCK")
        return ["--sponsorblock-remove", cats] if cats else []

    def yt_video_extra_args(self) -> list[str]:
        profile = self.profile
        args = set(self.cfg_list("args"))
        audio_or_subs = profile in {"yt-best-m4a", "yt-opus", "yt-mp3", "yt-subs-only"} or "-x" in args or "--audio-format" in args or "--skip-download" in args
        return [] if audio_or_subs else self.yt_sponsorblock_args()

    def files(self, extensions: set[str], *, recursive: bool | None = None, source: Path | None = None) -> list[Path]:
        exts = self.input_formats or {item.lower().strip(".") for item in extensions}
        folder = source or self.source_dir
        if not folder.exists():
            print(f"[!] Source folder was not found: {folder}")
            return []
        iterator = folder.rglob("*") if (self.recursive if recursive is None else recursive) else folder.iterdir()
        found = sorted(path for path in iterator if path.is_file() and path.suffix.lower().lstrip(".") in exts)
        return found[:1] if self.limit_first else found

    def source_relative_parent(self, source: Path) -> Path:
        try:
            return source.resolve().parent.relative_to(self.source_dir.resolve())
        except (OSError, ValueError):
            return Path()

    def source_label(self, source: Path) -> str:
        try:
            return source.resolve().relative_to(self.source_dir.resolve()).as_posix()
        except (OSError, ValueError):
            return source.name

    def output_path(self, source: Path, suffix: str, extension: str, *, subdir: str = "") -> Path:
        base = self.output_dir / subdir if subdir else self.output_dir
        folder = base / self.source_relative_parent(source)
        folder.mkdir(parents=True, exist_ok=True)
        suffix = suffix.strip("_")
        name = f"{source.stem}_{suffix}.{extension}" if suffix else f"{source.stem}.{extension}"
        return folder / name

    def overwrite_arg(self) -> str:
        return "-y" if self.overwrite else "-n"

    def source_bit_depth(self, source: Path | None) -> int:
        if source is None:
            return 8
        raw = self.probe_one(
            [self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt", "-of", "default=nw=1:nk=1", str(source)]
        )
        return 10 if any(token in raw for token in ("10", "12", "16")) else 8

    def decode_args(self, *, has_video_filters: bool = False, source: Path | None = None) -> list[str]:
        return [
            *backend_decode_args(self.decode_backend),
            *decode_output_format_args(
                self.decode_backend,
                self.encode_backend,
                pix_fmt=self.pix_fmt,
                has_video_filters=has_video_filters,
                source_bit_depth=self.source_bit_depth(source),
            ),
        ]

    def tuning_args(self, codec: str) -> list[str]:
        tuning = split_values(first_env("AUDION_ENCODE_TUNING", "ENCODE_TUNING"))
        allowed = ["grain", "film", "animation", "fastdecode", "zerolatency"] if codec == "x264" else ["grain", "fastdecode", "zerolatency"]
        for item in allowed:
            if item in tuning:
                return ["-tune", item]
        return []

    def audio_args(self, default_mode: str = "aac") -> list[str]:
        mode = first_env("AUDION_AUDIO_MODE", "AUDIO_MODE", default=default_mode).lower()
        bitrate = self.audio_bitrate
        if mode.startswith("aac_"):
            bitrate = normalize_bitrate(mode.removeprefix("aac_"), bitrate)
            mode = "aac"
        if mode in {"none", "off"}:
            return ["-an"]
        if mode in {"source", "native", "copy", "original"}:
            return ["-c:a", "copy"]
        if mode == "mp3":
            return mp3_encoder_args(self.mp3_lame_preset, bitrate)
        if mode == "flac":
            return ["-c:a", "flac", "-compression_level", "8"]
        if mode in {"pcm_s16", "pcm16"}:
            return ["-c:a", "pcm_s16le"]
        if mode in {"pcm_f32", "pcm32f", "float"}:
            return ["-c:a", "pcm_f32le"]
        if mode in {"pcm_s24", "pcm24", "pcm"}:
            return ["-c:a", "pcm_s24le"]
        return ["-c:a", "aac", "-b:a", bitrate]

    def audio_mode(self, default_mode: str = "aac") -> str:
        mode = first_env("AUDION_AUDIO_MODE", "AUDIO_MODE", default=default_mode).lower()
        return "aac" if mode.startswith("aac_") else mode

    def audio_filter_args(self, default_mode: str = "aac") -> list[str]:
        """SoX resample arguments, matching the GUI `audio_sample_rate` field.

        Unset means the source rate is preserved, exactly like the GUI default.
        """
        return resample_filter_args(self.audio_sample_rate, self.audio_mode(default_mode), default="source")

    def hardware_pix_fmt_args(self, encoder: str, requested: str = "") -> list[str]:
        native = hardware_pix_fmt(encoder, requested or self.pix_fmt or "yuv420p")
        return ["-pix_fmt", native] if native else []

    def video_h264_args(self, crf_default: str = "14") -> tuple[list[str], str]:
        crf = self.crf or crf_default
        backend = self.encode_backend
        if backend == "cuda":
            return ["-c:v", "h264_nvenc", "-preset", self.nvenc_preset, "-tune", "hq", "-cq:v", self.cq, "-b:v", "0", *self.hardware_pix_fmt_args("h264_nvenc")], f"h264_nvenc_{self.nvenc_preset}_cq{self.cq}"
        if backend == "qsv":
            return ["-c:v", "h264_qsv", "-preset", self.qsv_encoder_preset, "-global_quality", self.cq, *self.hardware_pix_fmt_args("h264_qsv")], f"h264_qsv_{self.qsv_encoder_preset}_gq{self.cq}"
        if backend == "amd":
            return ["-c:v", "h264_amf", "-quality", self.amf_quality, "-rc", "cqp", "-qp_i", self.cq, "-qp_p", self.cq, "-qp_b", self.cq, *self.hardware_pix_fmt_args("h264_amf")], f"h264_amf_{self.amf_quality}_qp{self.cq}"
        pix_fmt = self.pix_fmt or "yuv420p"
        return ["-c:v", "libx264", "-preset", self.cpu_encoder_preset, "-crf", crf, *self.tuning_args("x264"), "-pix_fmt", pix_fmt], f"x264_crf{crf}_{self.cpu_encoder_preset}"

    def video_hevc_args(self, crf_default: str = "14") -> tuple[list[str], str]:
        crf = self.crf or crf_default
        backend = self.encode_backend
        # The pixel format comes from the profile or AUDION_PIX_FMT, exactly like
        # the GUI. 10-bit HEVC profiles declare pix_fmt in config/script_profiles.yaml
        # instead of the encoder silently overriding an explicit 8-bit request.
        hevc_pix_fmt = self.pix_fmt or "yuv420p10le"
        if backend == "cuda":
            return ["-c:v", "hevc_nvenc", "-preset", self.nvenc_preset, "-tune", "hq", "-cq:v", self.cq, "-b:v", "0", *self.hardware_pix_fmt_args("hevc_nvenc", hevc_pix_fmt)], f"hevc_nvenc_{self.nvenc_preset}_cq{self.cq}"
        if backend == "qsv":
            return ["-c:v", "hevc_qsv", "-preset", self.qsv_encoder_preset, "-global_quality", self.cq, *self.hardware_pix_fmt_args("hevc_qsv", hevc_pix_fmt)], f"hevc_qsv_{self.qsv_encoder_preset}_gq{self.cq}"
        if backend == "amd":
            return ["-c:v", "hevc_amf", "-quality", self.amf_quality, "-rc", "cqp", "-qp_i", self.cq, "-qp_p", self.cq, *self.hardware_pix_fmt_args("hevc_amf", hevc_pix_fmt)], f"hevc_amf_{self.amf_quality}_qp{self.cq}"
        return ["-c:v", "libx265", "-preset", self.cpu_encoder_preset, "-x265-params", f"crf={crf}", *self.tuning_args("x265"), "-pix_fmt", hevc_pix_fmt], f"hevc10_crf{crf}_{self.cpu_encoder_preset}"

    def video_av1_args(self, crf_default: str = "14") -> tuple[list[str], str]:
        """AV1 through SVT-AV1 on CPU, or the matching hardware AV1 encoder.

        Mirrors the GUI AV1 target: the software preset applies to libsvtav1
        only, hardware backends use their own preset/quality scales.
        """
        crf = self.crf or crf_default
        backend = self.encode_backend
        av1_pix_fmt = self.pix_fmt if self.pix_fmt and self.pix_fmt != "yuv420p" else "yuv420p10le"
        if backend == "cuda":
            return ["-c:v", "av1_nvenc", "-preset", self.nvenc_preset, "-tune", "hq", "-cq:v", self.cq, "-b:v", "0", *self.hardware_pix_fmt_args("av1_nvenc", av1_pix_fmt)], f"av1_nvenc_{self.nvenc_preset}_cq{self.cq}"
        if backend == "qsv":
            return ["-c:v", "av1_qsv", "-preset", self.qsv_encoder_preset, "-global_quality", self.cq, *self.hardware_pix_fmt_args("av1_qsv", av1_pix_fmt)], f"av1_qsv_{self.qsv_encoder_preset}_gq{self.cq}"
        if backend == "amd":
            return ["-c:v", "av1_amf", "-quality", self.amf_quality, "-rc", "cqp", "-qp_i", self.cq, "-qp_p", self.cq, *self.hardware_pix_fmt_args("av1_amf", av1_pix_fmt)], f"av1_amf_{self.amf_quality}_qp{self.cq}"
        av1_preset = str(first_env("AUDION_AV1_PRESET", "AV1_PRESET", default=str(self.cfg("av1_preset", self.defaults.get("av1_preset", "6")))))
        return ["-c:v", "libsvtav1", "-preset", av1_preset, "-crf", crf, "-pix_fmt", av1_pix_fmt], f"svtav1_crf{crf}"

    def video_target_args(self, target: str) -> tuple[list[str], str, str]:
        if target == "hevc10":
            args, label = self.video_hevc_args("14")
            return args, "mp4", label
        if target == "prores_lt":
            return ["-c:v", "prores_ks", "-profile:v", "1", "-pix_fmt", "yuv422p10le"], "mov", "proresLT"
        if target == "prores422":
            return ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le"], "mov", "prores422"
        args, label = self.video_h264_args("14")
        return args, "mp4", label

    def run_batch_encode(self, *, target: str, suffix: str, extension: str, video_args: list[str], audio_args: list[str], vf: str = "", af: list[str] | None = None) -> None:
        files = self.files(VIDEO_EXTS)
        if not files:
            print(f"[!] No input files in {self.source_dir}")
            return
        drops_audio = "-an" in audio_args
        for source in files:
            output = self.output_path(source, suffix, extension)
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", self.overwrite_arg(), "-nostdin", *self.decode_args(has_video_filters=bool(vf), source=source), "-i", str(source)]
            # Same stream selection as the GUI: first video track, audio when kept,
            # no subtitle or data streams carried into an encode.
            command.extend(["-map", "0:v:0"])
            if not drops_audio:
                command.extend(["-map", "0:a?"])
            command.extend(["-sn", "-dn"])
            if vf:
                command.extend(["-vf", vf])
            command.extend([*video_args, *audio_args, *(af or []), "-map_metadata", "0"])
            if extension in {"mp4", "mov"}:
                command.extend(["-movflags", "+faststart"])
            if extension == "mxf":
                command.extend(["-f", "mxf"])
            command.append(str(output))
            print(f"[PROCESS] {source.name} -> {target}")
            self.run(command)

    def run_x264_hevc(self) -> None:
        profile = self.profile
        if profile == "ff-extract-audio":
            self.run_audio_extract_copy(container_suffix="audio")
            return
        if profile == "ff-extract-subs":
            self.run_subtitle_extract()
            return
        if profile == "ff-selftest":
            self.run_ff_selftest()
            return

        scale = ""
        crf_default = "14"
        if match := re.search(r"crf(\d+)", profile):
            crf_default = match.group(1)
        if "4k-to-1080" in profile:
            # Height-driven like the GUI, so non-16:9 sources keep their aspect ratio.
            scale = scale_filter("1080")
        if "hevc10" in profile:
            video_args, label = self.video_hevc_args(crf_default)
            self.run_batch_encode(target=label, suffix=label, extension="mp4", video_args=video_args, audio_args=self.audio_args("aac"), af=self.audio_filter_args("aac"), vf=scale)
            return
        if "hdr2sdr-hable" in profile:
            vf = (
                "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv,"
                "zscale=t=linear:npl=100,format=gbrpf32le,tonemap=hable:desat=0.5,"
                "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p"
            )
            if "hevc10" in profile:
                video_args, label = self.video_hevc_args(crf_default)
            else:
                video_args, label = self.video_h264_args(crf_default)
            self.run_batch_encode(target=label, suffix=f"sdr709_hable_{label}", extension="mp4", video_args=video_args, audio_args=self.audio_args("aac"), af=self.audio_filter_args("aac"), vf=vf)
            return
        video_args, label = self.video_h264_args(crf_default)
        suffix = f"1080_{label}" if scale else label
        self.run_batch_encode(target=label, suffix=suffix, extension="mp4", video_args=video_args, audio_args=self.audio_args("aac"), af=self.audio_filter_args("aac"), vf=scale)

    def run_editing(self) -> None:
        profile = self.profile
        extension = "mxf" if profile.endswith("-mxf") else "mov"
        if "dnxhr" in profile:
            dnx_profile = "dnxhr_hqx" if "hqx" in profile else "dnxhr_hq"
            pixel_format = "yuv422p10le" if dnx_profile == "dnxhr_hqx" else "yuv422p"
            video_args = ["-c:v", "dnxhd", "-profile:v", dnx_profile, "-pix_fmt", pixel_format]
            label = dnx_profile
        else:
            prores_profile = "0" if "proxy" in profile else "1" if "lt" in profile else "2"
            label = "prores_proxy" if "proxy" in profile else "proresLT" if "lt" in profile else "prores422"
            video_args = ["-c:v", "prores_ks", "-profile:v", prores_profile, "-pix_fmt", "yuv422p10le"]
        self.run_batch_encode(target=label, suffix=label, extension=extension, video_args=video_args, audio_args=self.audio_args("pcm_s24"), af=self.audio_filter_args("pcm_s24"))

    def select_lut(self) -> Path:
        raw = first_env("AUDION_LUT_FILE", "LUT_FILE", "ACTIVE_LUT")
        candidates: list[Path] = []
        if raw:
            candidates.append(self.resolve_path(raw, self.luts_dir / raw))
        candidates.append(self.luts_dir / "active.cube")
        candidates.extend(sorted(self.luts_dir.glob("*.cube")) if self.luts_dir.exists() else [])
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise RuntimeError(f"No LUT .cube files were found in {self.luts_dir}.")

    def run_color(self) -> None:
        profile = self.profile
        filters: list[str] = []
        suffix = "lut"
        if "hdr2sdr" in profile:
            filters.append(
                "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv,"
                "zscale=t=linear:npl=100,format=gbrpf32le,tonemap=hable:desat=0.5,"
                "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p"
            )
            suffix = "sdr709_hable"
        else:
            gamma = first_env("AUDION_PRE_GAMMA", "PRE_GAMMA", default="")
            if "preexpose" in profile:
                gamma = gamma or "1.15"
                gamma = ffmpeg_filter_number(gamma, name="AUDION_PRE_GAMMA")
                filters.append(f"eq=gamma={gamma}")
                suffix = f"preLUTgamma{gamma}"
            elif "pregamma" in profile:
                gamma = gamma or "0.85"
                gamma = ffmpeg_filter_number(gamma, name="AUDION_PRE_GAMMA")
                filters.append(f"eq=gamma={gamma}")
                suffix = f"preG{gamma}_lut"
            lut = self.select_lut()
            print(f"[LUT] {lut}")
            filters.append(f"lut3d=file={ffmpeg_filter_path(lut)}:interp=tetrahedral")
        scale = first_env("AUDION_SCALE_FILTER", "SCALE_FILTER")
        if scale:
            filters.append(scale)
        targets = split_values(first_env("AUDION_TARGET_CODECS", "TARGET_CODECS"))
        if not targets:
            if "hevc" in profile:
                targets = ["hevc10"]
            elif "proreslt" in profile.lower() or "prores-lt" in profile:
                targets = ["prores_lt"]
            elif "prores" in profile:
                targets = ["prores422"]
            else:
                targets = ["x264"]
        vf = ",".join(filters)
        for target in targets:
            target = {"hevc_x265": "hevc10", "prores_422": "prores422", "prores_lt": "prores_lt"}.get(target, target)
            video_args, extension, label = self.video_target_args(target)
            self.run_batch_encode(target=label, suffix=f"{suffix}_{label}", extension=extension, video_args=video_args, audio_args=self.audio_args("aac"), af=self.audio_filter_args("aac"), vf=vf)

    def run_remux(self) -> None:
        profile = self.profile
        pairs = {
            "ff-remux-mkv-to-mp4": ("mkv", "mp4"),
            "ff-remux-mkv-to-mp4-faststart": ("mkv", "mp4"),
            "ff-remux-mp4-to-mkv": ("mp4", "mkv"),
            "ff-remux-mp4-to-mkv-copy": ("mp4", "mkv"),
            "ff-remux-mov-to-mxf-copy": ("mov", "mxf"),
            "ff-remux-mxf-to-mov-copy": ("mxf", "mov"),
        }
        source_ext, target_ext = pairs.get(profile, ("mkv", "mp4"))
        files = self.files({source_ext})
        if not files:
            print(f"[!] No .{source_ext} files in {self.source_dir}")
            return
        for source in files:
            output = self.output_path(source, "", target_ext)
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", self.overwrite_arg(), "-nostdin", "-i", str(source)]
            if target_ext == "mp4":
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-map_chapters", "0", "-map_metadata", "0", "-c", "copy", "-movflags", "+faststart"])
            elif target_ext == "mxf":
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-c", "copy", "-f", "mxf"])
            elif target_ext == "mov":
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-c", "copy", "-movflags", "+faststart"])
            else:
                command.extend(["-map", "0", "-c", "copy"])
            command.append(str(output))
            print(f"[REMUX] {source.name}: {source_ext.upper()} -> {target_ext.upper()}")
            self.run(command)

    def run_fps(self) -> None:
        match = re.match(r"ff-(\d+)to(\d+)-(varispeed|conform)", self.profile)
        if not match:
            raise RuntimeError(f"Unsupported FPS profile: {self.profile}")
        source_rate = FPS_RATES.get(match.group(1))
        target_rate = FPS_RATES.get(match.group(2), Fraction(24000, 1001))
        mode = match.group(3)
        if source_rate is None:
            raise RuntimeError(f"Unsupported source FPS in profile: {self.profile}")
        output_mode = first_env("AUDION_FPS_OUTPUT_PROFILE", "OUT_MODE", default="h264").lower()
        if output_mode == "prores":
            video_args = ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le"]
            audio_args = self.audio_args("pcm_s24")
            extension = "mov"
            label = "prores422"
        elif output_mode == "dnxhr":
            video_args = ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx", "-pix_fmt", "yuv422p10le"]
            audio_args = self.audio_args("pcm_s24")
            extension = "mov"
            label = "dnxhr_hqx"
        else:
            video_args, label = self.video_h264_args("14")
            audio_args = self.audio_args("aac")
            extension = "mp4"
        k = float(source_rate / target_rate)
        speed = float(target_rate / source_rate)
        target_arg = "24000/1001" if target_rate == Fraction(24000, 1001) else f"{target_rate.numerator}/{target_rate.denominator}"
        files = self.files(VIDEO_EXTS)
        if not files:
            print(f"[!] No input files in {self.source_dir}")
            return
        for source in files:
            has_audio = self.has_audio(source)
            suffix = f"{match.group(1)}to{match.group(2)}_{mode}_{label}"
            output = self.output_path(source, suffix, extension)
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", self.overwrite_arg(), "-nostdin", *self.decode_args(has_video_filters=True, source=source), "-i", str(source)]
            if has_audio:
                if mode == "conform":
                    audio_filter = f"{atempo_chain(speed)},aresample=48000,aresample=async=1:first_pts=0"
                else:
                    audio_filter = f"aresample=48000,asetrate=48000/{k:.12g},aresample=48000,aresample=async=1:first_pts=0"
                command.extend(["-filter_complex", f"[0:v]setpts={k:.12g}*PTS[v];[0:a]{audio_filter}[a]", "-map", "[v]", "-map", "[a]"])
            else:
                command.extend(["-filter_complex", f"[0:v]setpts={k:.12g}*PTS[v]", "-map", "[v]", "-an"])
            command.extend(["-r", target_arg, "-map_metadata", "-1", "-metadata:s:v:0", "timecode=00:00:00:00", "-timecode", "00:00:00:00", *video_args])
            if has_audio:
                command.extend(audio_args)
            if extension in {"mp4", "mov"}:
                command.extend(["-movflags", "+faststart"])
            command.append(str(output))
            print(f"[FPS] {source.name}: {float(source_rate):.6g} -> {target_arg} {mode}")
            self.run(command)

    def has_audio(self, source: Path) -> bool:
        raw = self.probe_one(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(source),
            ]
        )
        return bool(raw)

    def audio_codec(self, source: Path) -> str:
        return self.probe_one(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "csv=p=0",
                str(source),
            ]
        )

    def audio_stream_info(self, source: Path) -> dict[str, Any]:
        result = subprocess.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index,codec_name,sample_rate,sample_fmt,channels,channel_layout,bits_per_sample,bit_rate:stream_tags=language,title",
                "-of",
                "json",
                str(source),
            ],
            cwd=str(self.root),
            env=self.tool_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}
        streams = data.get("streams", [])
        if not isinstance(streams, list) or not streams:
            return {}
        stream = streams[0]
        if not isinstance(stream, dict):
            return {}
        return {
            "codec": str(stream.get("codec_name") or ""),
            # Both spellings, because callers reach for either and a missing
            # codec silently means "this file has no audio" downstream.
            "codec_name": str(stream.get("codec_name") or ""),
            "channels": str(stream.get("channels") or ""),
            "channel_layout": str(stream.get("channel_layout") or ""),
            "sample_fmt": str(stream.get("sample_fmt") or ""),
        }

    def audio_stream_channels(self, stream: dict[str, Any]) -> int:
        try:
            return int(float(str(stream.get("channels", "")).strip()))
        except (TypeError, ValueError):
            pass
        layout = str(stream.get("channel_layout") or "").strip().lower()
        if layout in {"mono", "1.0"}:
            return 1
        if layout in {"stereo", "2.0"}:
            return 2
        match = re.search(r"(\d+)\.(\d+)", layout)
        if match:
            return int(match.group(1)) + int(match.group(2))
        return 0

    def audio_copy_extension(self, stream: dict[str, Any], *, policy: str = "auto") -> str:
        codec = str(stream.get("codec") or "").strip().lower()
        channels = self.audio_stream_channels(stream)
        policy = (policy or "auto").strip().lower()
        policy = {"source": "auto", "raw": "elementary", "codec": "elementary", "native": "elementary", "matroska": "mka"}.get(policy, policy)
        if policy == "mka":
            return "mka"
        if policy == "m4a":
            return "m4a" if codec in {"aac", "alac"} else "mka"
        elementary_by_codec = {
            "aac": "aac",
            "aac_latm": "mka",
            "ac3": "ac3",
            "eac3": "eac3",
            "dts": "dts",
            "truehd": "thd",
            "mlp": "mlp",
            "mp3": "mp3",
            "flac": "flac",
            "opus": "opus",
            "vorbis": "ogg",
            "alac": "m4a",
        }
        if policy == "elementary":
            return elementary_by_codec.get(codec, "mka")
        if codec == "aac":
            return "mka" if channels > 2 else "m4a"
        if codec == "aac_latm":
            return "mka"
        if codec == "alac":
            return "m4a"
        if codec in {"ac3", "eac3", "dts", "truehd", "mlp", "mp3", "flac", "opus", "vorbis"}:
            return elementary_by_codec[codec]
        if codec.startswith("pcm_"):
            return "wav"
        if codec.startswith("dsd_"):
            return "mka"
        return "mka"

    def sample_rate(self, source: Path) -> str:
        return self.probe_one(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(source),
            ]
        )

    def run_audio(self) -> None:
        profile = self.profile
        if profile == "audio-extract-audio-copy":
            self.run_audio_extract_copy()
            return
        if profile in {"audio-extract-audio-wav", "audio-extract-audio-wav-32"}:
            codec = "pcm_f32le" if profile.endswith("-32") else "pcm_s24le"
            label = "wav32f" if profile.endswith("-32") else "wav24"
            self.run_audio_batch(codec_args=["-c:a", codec], suffix=label, extension="wav")
            return
        if profile.startswith("audio-to-m4a"):
            default_bitrate = "256k" if profile.endswith("256") else "384k"
            bitrate = normalize_bitrate(first_env("AUDION_AUDIO_BITRATE", "AUDIO_BITRATE", default=default_bitrate), default_bitrate)
            self.run_audio_batch(codec_args=["-c:a", "aac", "-b:a", bitrate], suffix=f"m4a_{bitrate}", extension="m4a")
            return
        if profile.startswith("audio-to-flac"):
            ar: list[str] = []
            label = "flac"
            if profile.endswith("48k"):
                ar = ["-ar", "48000"]
                label = "flac_48k"
            elif profile.endswith("96k"):
                ar = ["-ar", "96000"]
                label = "flac_96k"
            self.run_audio_batch(codec_args=["-c:a", "flac", "-compression_level", "8", *ar], suffix=label, extension="flac")
            return
        if profile.startswith("audio-resample-to-"):
            match = re.search(r"to-(44100|48000)", profile)
            rate = match.group(1) if match else "48000"
            codec = "pcm_f32le" if "32f" in profile else "pcm_s24le"
            depth = "32f" if "32f" in profile else "24b"
            filter_expr = f"aresample={rate}:resampler=soxr:cutoff=0.95:precision=28:dither_method=triangular"
            if profile.endswith("_sync"):
                filter_expr += ",aresample=async=1:first_pts=0"
            self.run_audio_batch(
                codec_args=["-c:a", codec, "-af", filter_expr],
                suffix=f"audio_{rate}Hz_{depth}",
                extension="wav",
                recursive=True,
                skip_same_rate=rate,
            )
            return
        if profile.startswith("audio-lufs-"):
            target = "-14" if profile.endswith("14") else "-23"
            true_peak = "-1.0" if target == "-14" else "-2.0"
            self.run_audio_batch(
                codec_args=["-af", f"loudnorm=I={target}:TP={true_peak}:LRA=11:print_format=summary", "-c:a", "pcm_s24le"],
                suffix=f"lufs{target.replace('-', '')}db",
                extension="wav",
            )
            return
        if profile == "audio-downmix-51-to-20":
            pan = "pan=stereo|FL=1.0*FL+0.707*FC+0.5*BL+0.5*SL+0.0*LFE|FR=1.0*FR+0.707*FC+0.5*BR+0.5*SR+0.0*LFE"
            self.run_audio_batch(codec_args=["-af", pan, "-c:a", "pcm_s24le"], suffix="dmix2ch_24bit", extension="wav")
            return
        raise RuntimeError(f"Unsupported audio profile: {profile}")

    def run_audio_batch(
        self,
        *,
        codec_args: list[str],
        suffix: str,
        extension: str,
        recursive: bool | None = None,
        skip_same_rate: str = "",
    ) -> None:
        files = self.files(MEDIA_EXTS, recursive=recursive)
        if not files:
            print(f"[!] No audio/video files in {self.source_dir}")
            return
        for source in files:
            if skip_same_rate and self.sample_rate(source) == skip_same_rate:
                print(f"[SKIP] {source.name}: already {skip_same_rate} Hz")
                continue
            output = self.output_path(source, suffix, extension, subdir="Audio")
            command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-stats",
                self.overwrite_arg(),
                "-nostdin",
                "-i",
                str(source),
                "-vn",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "0",
                *codec_args,
                str(output),
            ]
            print(f"[AUDIO] {source.name} -> {output.name}")
            self.run(command)

    def run_audio_extract_copy(self, *, container_suffix: str = "audio_copy", extension: str = "") -> None:
        files = self.files(MEDIA_EXTS)
        if not files:
            print(f"[!] No audio/video files in {self.source_dir}")
            return
        configured_policy = first_env(
            "AUDION_AUDIO_COPY_CONTAINER",
            "AUDIO_COPY_CONTAINER",
            default=str(self.cfg("audio_copy_container", "auto")),
        )
        forced_extension = (extension or "").strip().lower().lstrip(".")
        for source in files:
            stream = self.audio_stream_info(source)
            codec = str(stream.get("codec") or "")
            if not codec:
                print(f"[SKIP] {source.name}: no audio stream")
                continue
            if forced_extension in {"", "auto", "source"}:
                out_ext = self.audio_copy_extension(stream, policy=configured_policy)
            elif forced_extension in {"elementary", "codec", "native", "raw"}:
                out_ext = self.audio_copy_extension(stream, policy="elementary")
            else:
                out_ext = forced_extension
            output = self.output_path(source, container_suffix, out_ext, subdir="Audio")
            command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-stats",
                self.overwrite_arg(),
                "-nostdin",
                "-i",
                str(source),
                "-map",
                "0:a:0?",
                "-vn",
                "-sn",
                "-dn",
                "-map_metadata",
                "0",
                "-c",
                "copy",
                str(output),
            ]
            print(f"[AUDIO COPY] {source.name} [{codec}] -> {output.name}")
            self.run(command)

    def run_subtitle_extract(self) -> None:
        files = self.files(VIDEO_EXTS)
        if not files:
            print(f"[!] No input files in {self.source_dir}")
            return
        for source in files:
            output = self.output_path(source, "subs", "mks")
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", self.overwrite_arg(), "-nostdin", "-i", str(source), "-map", "0:s?", "-c", "copy", "-f", "matroska", str(output)]
            print(f"[SUBS] {source.name} -> {output.name}")
            self.run(command)

    def run_ff_selftest(self) -> None:
        self.run([self.ffmpeg, "-hide_banner", "-version"])
        self.run([self.ffmpeg, "-hide_banner", "-filters"])

    def yt_common_output(self) -> str:
        return "%(uploader)s/%(upload_date>%Y-%m-%d)s - %(title).180B [%(id)s].%(ext)s"

    def yt_urls(self) -> list[str]:
        if self.args:
            return self.args
        raw = first_env("AUDION_YOUTUBE_URL", "YOUTUBE_URL", "URL")
        return [raw] if raw else []

    def yt_urls_file(self) -> Path:
        raw = first_env("AUDION_URLS_FILE", "URLS_FILE", "LIST")
        return self.resolve_path(raw, self.download_dir / "urls.txt") if raw else self.download_dir / "urls.txt"

    def run_youtube(self) -> None:
        profile = self.profile
        if profile == "yt-selftest":
            self.run([self.ytdlp, "--version"])
            return
        if profile == "yt-update":
            installer = self.root / "install" / "Install-Portable-yt-dlp.cmd"
            if not installer.exists():
                raise RuntimeError(f"Installer was not found: {installer}")
            self.run(["cmd.exe", "/d", "/c", str(installer), "/NOPAUSE"])
            return
        if profile == "yt-clip-sections":
            if len(self.args) < 2:
                raise RuntimeError('Usage: yt-clip-sections.cmd "*HH:MM:SS-HH:MM:SS,*..." <URL>')
            sections = self.args[0]
            urls = self.args[1:]
            command = [
                *self.yt_base_command(),
                "-P",
                str(self.download_dir),
                "--download-sections",
                sections,
                "-N",
                "8",
                "-S",
                "res,ext:mp4:m4a",
                "--merge-output-format",
                "mp4",
                "-o",
                self.yt_common_output(),
                *urls,
            ]
            self.run(command)
            return

        urls = self.yt_urls()
        output_template = self.yt_common_output()
        command = self.yt_base_command() + ["-P", str(self.download_dir)]
        if profile == "yt-best-mp4-safe":
            command.extend(["-N", "1", "--retries", "10", "--fragment-retries", "10", "--retry-sleep", "2", "--sleep-requests", "1", "--http-chunk-size", "10M", "--force-ipv4", "--extractor-args", "youtube:player-client=web_safari,default"])
            command.extend(["-S", "res,ext:mp4:m4a", "--merge-output-format", "mp4"])
        elif profile == "yt-best-mp4-safari":
            command.extend(["--extractor-args", "youtube:player-client=web_safari,default", "-N", "8", "-S", "res,ext:mp4:m4a", "--merge-output-format", "mp4"])
        elif profile == "yt-1080p-avc-mp4":
            command.extend(["-N", "8", "-S", "res:1080,codec:avc:m4a", "--merge-output-format", "mp4"])
        elif profile == "yt-480p-aac":
            command.extend(["-N", "8", "-S", "res:480,ext:mp4:m4a", "--merge-output-format", "mp4"])
        elif profile == "yt-best-av1":
            command.extend(["-N", "8", "-S", "codec:av01,res,ext:mp4:m4a", "--merge-output-format", "mp4"])
        elif profile == "yt-webm-vp9":
            command.extend(["-N", "8", "-f", "bv*[vcodec^=vp9]+ba/best", "--merge-output-format", "webm"])
        elif profile == "yt-embed-subs":
            command.extend(["-N", "8", "--write-subs", "--sub-langs", "ru,en.*", "--embed-subs", "-S", "res,ext:mp4:m4a", "--merge-output-format", "mp4"])
        elif profile == "yt-subs-only":
            command.extend(["-N", "8", "--skip-download", "--write-subs", "--sub-langs", "ru,en.*"])
        elif profile == "yt-best-m4a":
            command.extend(["-N", "8", "-f", "bestaudio[acodec^=mp4a]/bestaudio", "-x", "--audio-format", "m4a", "--embed-thumbnail", "--embed-metadata"])
        elif profile == "yt-opus":
            command.extend(["-N", "8", "-x", "--audio-format", "opus", "--embed-thumbnail", "--embed-metadata"])
        elif profile == "yt-mp3":
            command.extend(["-N", "8", "-x", "--audio-format", "mp3", "--audio-quality", "0", "--embed-thumbnail", "--embed-metadata"])
        elif profile == "yt-playlist-best":
            output_template = "%(playlist_index)03d - %(title).200B [%(id)s].%(ext)s"
            command.extend(["--ignore-errors", "--continue", "-N", "8", "-S", "res,ext:mp4:m4a", "--merge-output-format", "mp4"])
        elif profile == "yt-playlist-1080p-avc":
            output_template = "%(playlist_index)03d - %(title).200B [%(id)s].%(ext)s"
            command.extend(["--ignore-errors", "--continue", "-N", "8", "-S", "res:1080,codec:avc:m4a", "--merge-output-format", "mp4"])
        elif profile in {"yt-batch-best-mp4", "yt-batch-480p-aac"}:
            list_file = self.yt_urls_file()
            if not list_file.exists():
                raise RuntimeError(f"URL list file was not found: {list_file}")
            selector = "res:480,ext:mp4:m4a" if profile == "yt-batch-480p-aac" else "res,ext:mp4:m4a"
            command.extend(["-N", "8", "-S", selector, "--merge-output-format", "mp4", "-a", str(list_file)])
            command.extend(self.yt_cookies_args())
            command.extend(self.yt_video_extra_args())
            self.run(command)
            return
        else:
            command.extend(["-N", "8", "-S", "res,ext:mp4:m4a", "--merge-output-format", "mp4"])

        command.extend(self.yt_cookies_args())
        command.extend(self.yt_video_extra_args())
        command.extend(["-o", output_template, *urls])
        self.run(command)

    def run_configured_encode(self) -> None:
        target = str(self.cfg("target", "x264")).lower()
        crf_default = str(self.cfg("crf", "14"))
        extension = str(self.cfg("extension", "mp4"))
        video_filter = str(self.cfg("video_filter", ""))
        if target in {"hevc", "hevc10", "hevc_x265", "x265"}:
            video_args, label = self.video_hevc_args(crf_default)
        elif target in {"av1", "svt_av1", "svtav1"}:
            video_args, label = self.video_av1_args(crf_default)
        else:
            video_args, label = self.video_h264_args(crf_default)
        suffix = str(self.cfg("suffix", label))
        prefix = str(self.cfg("suffix_prefix", "")).strip()
        if prefix:
            suffix = f"{prefix}_{suffix}"
        self.run_batch_encode(target=label, suffix=suffix, extension=extension, video_args=video_args, audio_args=self.audio_args("aac"), af=self.audio_filter_args("aac"), vf=video_filter)

    def run_configured_editing(self) -> None:
        target = str(self.cfg("target", "prores")).lower()
        extension = str(self.cfg("extension", "mov"))
        suffix = str(self.cfg("suffix", "editing"))
        if target == "dnxhr":
            dnx_profile = str(self.cfg("dnx_profile", "dnxhr_hq"))
            pixel_format = "yuv422p10le" if dnx_profile == "dnxhr_hqx" else "yuv422p"
            video_args = ["-c:v", "dnxhd", "-profile:v", dnx_profile, "-pix_fmt", pixel_format]
            label = suffix or dnx_profile
        else:
            prores_profile = str(self.cfg("prores_profile", "2"))
            video_args = ["-c:v", "prores_ks", "-profile:v", prores_profile, "-pix_fmt", "yuv422p10le"]
            label = suffix or "prores422"
        self.run_batch_encode(target=label, suffix=label, extension=extension, video_args=video_args, audio_args=self.audio_args("pcm_s24"), af=self.audio_filter_args("pcm_s24"))

    def run_configured_color(self) -> None:
        filter_kind = str(self.cfg("color_filter", "lut")).lower()
        filters: list[str] = []
        suffix = "lut"
        if filter_kind == "hdr2sdr_hable":
            filters.append(
                "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv,"
                "zscale=t=linear:npl=100,format=gbrpf32le,tonemap=hable:desat=0.5,"
                "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p"
            )
            suffix = "sdr709_hable"
        else:
            gamma = first_env("AUDION_PRE_GAMMA", "PRE_GAMMA", default=str(self.cfg("pre_gamma", "")))
            if filter_kind == "preexpose_lut":
                gamma = gamma or "1.15"
                gamma = ffmpeg_filter_number(gamma, name="AUDION_PRE_GAMMA")
                filters.append(f"eq=gamma={gamma}")
                suffix = f"preLUTgamma{gamma}"
            elif filter_kind == "pregamma_lut":
                gamma = gamma or "0.85"
                gamma = ffmpeg_filter_number(gamma, name="AUDION_PRE_GAMMA")
                filters.append(f"eq=gamma={gamma}")
                suffix = f"preG{gamma}_lut"
            lut = self.select_lut()
            print(f"[LUT] {lut}")
            filters.append(f"lut3d=file={ffmpeg_filter_path(lut)}:interp=tetrahedral")
        scale = first_env("AUDION_SCALE_FILTER", "SCALE_FILTER")
        if scale:
            filters.append(scale)
        targets = split_values(first_env("AUDION_TARGET_CODECS", "TARGET_CODECS")) or self.cfg_list("targets") or ["x264"]
        vf = ",".join(filters)
        for target in targets:
            mapped = {"hevc_x265": "hevc10", "prores_422": "prores422", "prores_lt": "prores_lt"}.get(str(target), str(target))
            video_args, extension, label = self.video_target_args(mapped)
            self.run_batch_encode(target=label, suffix=f"{suffix}_{label}", extension=extension, video_args=video_args, audio_args=self.audio_args("aac"), af=self.audio_filter_args("aac"), vf=vf)

    def run_configured_remux(self) -> None:
        source_ext = str(self.cfg("source", "mkv")).lower()
        target_ext = str(self.cfg("target", "mp4")).lower()
        files = self.files({source_ext})
        if not files:
            print(f"[!] No .{source_ext} files in {self.source_dir}")
            return
        for source in files:
            output = self.output_path(source, "", target_ext)
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", self.overwrite_arg(), "-nostdin", "-i", str(source)]
            if target_ext == "mp4":
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-map_chapters", "0", "-map_metadata", "0", "-c", "copy", "-movflags", "+faststart"])
            elif target_ext == "mxf":
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-c", "copy", "-f", "mxf"])
            elif target_ext == "mov":
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-c", "copy", "-movflags", "+faststart"])
            else:
                command.extend(["-map", "0", "-c", "copy"])
            command.append(str(output))
            print(f"[REMUX] {source.name}: {source_ext.upper()} -> {target_ext.upper()}")
            self.run(command)

    def rate(self, value: str) -> Fraction:
        if value in FPS_RATES:
            return FPS_RATES[value]
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return Fraction(int(numerator), int(denominator))
        return Fraction(value)

    def run_configured_fps(self) -> None:
        source_key = str(self.cfg("source_fps", "24"))
        target_key = str(self.cfg("target_fps", "23976"))
        mode = str(self.cfg("mode", "varispeed"))
        source_rate = self.rate(source_key)
        target_rate = self.rate(target_key)
        output_mode = first_env("AUDION_FPS_OUTPUT_PROFILE", "OUT_MODE", default="h264").lower()
        params = {
            "fps_audio_pcm_depth": first_env("AUDION_FPS_AUDIO_PCM_DEPTH", default="s24"),
            "fps_audio_oversample": first_env("AUDION_FPS_AUDIO_OVERSAMPLE", default="x1"),
            "audio_bitrate": self.audio_bitrate,
            "encode_backend": self.encode_backend,
            "cpu_encoder_preset": self.cpu_encoder_preset,
            "nvenc_preset": self.nvenc_preset,
            "qsv_encoder_preset": self.qsv_encoder_preset,
            "amf_quality": self.amf_quality,
            "crf": self.crf or ("16" if output_mode == "hevc" else "14"),
            "cq": self.cq,
        }
        video_args, audio_args, extension, label = _fps_output_args(output_mode, params)
        k = float(source_rate / target_rate)
        speed = float(target_rate / source_rate)
        target_arg = "24000/1001" if target_rate == Fraction(24000, 1001) else f"{target_rate.numerator}/{target_rate.denominator}"
        files = self.files(VIDEO_EXTS)
        if not files:
            print(f"[!] No input files in {self.source_dir}")
            return
        for source in files:
            has_audio = self.has_audio(source)
            output = self.output_path(source, f"{source_key}to{target_key}_{mode}_{label}", extension)
            source_sample_rate = 48000
            if has_audio:
                try:
                    source_sample_rate = int(self.sample_rate(source) or "48000")
                except ValueError:
                    source_sample_rate = 48000
            work_rate = fps_audio_target_rate(source_sample_rate, params) if has_audio else 0
            output_rate = fps_audio_output_rate(output_mode, work_rate) if has_audio else 0
            if has_audio and output_rate != work_rate:
                print(f"[AUDIO] Work rate {work_rate} Hz -> MXF output rate {output_rate} Hz")
            command = build_fps_command(
                ffmpeg=self.ffmpeg,
                source=str(source),
                overwrite=self.overwrite,
                mode=mode,
                k=k,
                speed=speed,
                target_arg=target_arg,
                video_args=video_args,
                audio_args=audio_args,
                extension=extension,
                target=str(output),
                has_audio=has_audio,
                audio_work_rate=work_rate,
                audio_output_rate=output_rate,
                decode_args=self.decode_args(has_video_filters=True, source=source),
            )
            print(f"[FPS] {source.name}: {float(source_rate):.6g} -> {target_arg} {mode}")
            self.run(command)

    def run_configured_audio(self) -> None:
        action = str(self.cfg("action", "")).lower()
        if action == "extract_copy":
            self.run_audio_extract_copy(container_suffix=str(self.cfg("suffix", "audio_copy")), extension=str(self.cfg("extension", "")))
            return
        if action == "extract_wav":
            self.run_audio_batch(codec_args=["-c:a", str(self.cfg("codec", "pcm_s24le"))], suffix=str(self.cfg("suffix", "wav24")), extension=str(self.cfg("extension", "wav")))
            return
        if action == "m4a":
            bitrate = normalize_bitrate(first_env("AUDION_AUDIO_BITRATE", "AUDIO_BITRATE"), str(self.cfg("audio_bitrate", self.audio_bitrate)))
            suffix = str(self.cfg("suffix", f"m4a_{bitrate}"))
            if "m4a_" in suffix and suffix != f"m4a_{bitrate}":
                suffix = f"m4a_{bitrate}"
            self.run_audio_batch(codec_args=["-c:a", "aac", "-b:a", bitrate], suffix=suffix, extension=str(self.cfg("extension", "m4a")))
            return
        if action == "flac":
            args = ["-c:a", "flac", "-compression_level", "8"]
            sample_rate = str(self.cfg("sample_rate", ""))
            if sample_rate:
                args.extend(["-ar", sample_rate])
            self.run_audio_batch(codec_args=args, suffix=str(self.cfg("suffix", "flac")), extension=str(self.cfg("extension", "flac")))
            return
        if action == "resample":
            rate = str(self.cfg("sample_rate", "48000"))
            codec = str(self.cfg("codec", "pcm_s24le"))
            depth = str(self.cfg("bit_depth_label", "24b"))
            filter_expr = f"aresample={rate}:resampler=soxr:cutoff=0.95:precision=28:dither_method=triangular"
            if truthy(str(self.cfg("sync", "")), False):
                filter_expr += ",aresample=async=1:first_pts=0"
            self.run_audio_batch(codec_args=["-c:a", codec, "-af", filter_expr], suffix=f"audio_{rate}Hz_{depth}", extension="wav", recursive=True, skip_same_rate=rate)
            return
        if action == "lufs":
            target = str(self.cfg("target_lufs", "-14"))
            true_peak = str(self.cfg("true_peak", "-1.0"))
            self.run_audio_batch(codec_args=["-af", f"loudnorm=I={target}:TP={true_peak}:LRA=11:print_format=summary", "-c:a", "pcm_s24le"], suffix=str(self.cfg("suffix", f"lufs{target.replace('-', '')}db")), extension=str(self.cfg("extension", "wav")))
            return
        if action == "downmix":
            pan = "pan=stereo|FL=1.0*FL+0.707*FC+0.5*BL+0.5*SL+0.0*LFE|FR=1.0*FR+0.707*FC+0.5*BR+0.5*SR+0.0*LFE"
            self.run_audio_batch(codec_args=["-af", pan, "-c:a", "pcm_s24le"], suffix=str(self.cfg("suffix", "dmix2ch_24bit")), extension=str(self.cfg("extension", "wav")))
            return
        raise RuntimeError(f"Unsupported configured audio action: {action}")

    def run_configured_youtube(self) -> None:
        mode = str(self.cfg("mode", "download")).lower()
        if mode == "selftest":
            self.run([self.ytdlp, "--version"])
            return
        if mode == "update":
            installer = self.root / "install" / "Install-Portable-yt-dlp.cmd"
            if not installer.exists():
                raise RuntimeError(f"Installer was not found: {installer}")
            self.run(["cmd.exe", "/d", "/c", str(installer), "/NOPAUSE"])
            return
        if mode == "clip":
            if len(self.args) < 2:
                raise RuntimeError('Usage: yt-clip-sections.cmd "*HH:MM:SS-HH:MM:SS,*..." <URL>')
            sections = self.args[0]
            urls = self.args[1:]
            command = self.yt_base_command() + ["-P", str(self.download_dir), "--download-sections", sections, *self.cfg_list("args"), "-o", self.yt_common_output(), *urls]
            self.run(command)
            return
        command = self.yt_base_command() + ["-P", str(self.download_dir), *self.cfg_list("args")]
        command.extend(self.yt_cookies_args())
        command.extend(self.yt_video_extra_args())
        if mode == "batch":
            list_file = self.yt_urls_file()
            if not list_file.exists():
                raise RuntimeError(f"URL list file was not found: {list_file}")
            command.extend(["-a", str(list_file)])
            self.run(command)
            return
        output_template = str(self.cfg("output_template", self.yt_common_output()))
        command.extend(["-o", output_template, *self.yt_urls()])
        self.run(command)

    def probe_lines(self, command: list[str]) -> str:
        result = subprocess.run(
            command,
            cwd=str(self.root),
            env=self.tool_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return (result.stdout or "") if result.returncode == 0 else ""

    def source_timecode(self, source: Path) -> str:
        raw = self.probe_lines(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream_tags=timecode:format_tags=timecode",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(source),
            ]
        )
        for line in raw.splitlines():
            text = line.strip()
            if re.match(r"^\d{1,2}[:;.]\d{2}[:;.]\d{2}[:;.]\d{2}$", text):
                return text
        return ""

    def trim_keyframes(self, source: Path, around: float) -> list[float]:
        windowed = self.probe_lines(keyframe_probe_command(self.ffprobe, str(source), start=around, window=15.0))
        times = parse_keyframe_times(windowed)
        if times:
            return times
        return parse_keyframe_times(self.probe_lines(keyframe_probe_command(self.ffprobe, str(source))))

    def run_configured_trim(self) -> None:
        """Cut the head, the tail, or both off camera footage without re-encoding.

        The arithmetic lives in `system_core.core.trim_contract`, so a trim run
        from a CMD wrapper lands on exactly the same frame as one run from the
        GUI.
        """
        pattern = first_env("AUDION_TRIM_PATTERN", default=str(self.cfg("pattern", "start"))).strip().lower()
        head = first_env("AUDION_TRIM_START", "TRIM_START", default=str(self.cfg("start", "")))
        tail = first_env("AUDION_TRIM_END", "TRIM_END", default=str(self.cfg("end", "")))
        container_choice = first_env("AUDION_TRIM_CONTAINER", default=str(self.cfg("container", "source"))).strip().lower()
        audio_mode = first_env("AUDION_TRIM_AUDIO", default="copy").strip().lower()
        channel_mode = first_env("AUDION_TRIM_AUDIO_CHANNEL", default="both").strip().lower()
        timecode_mode = first_env("AUDION_TRIM_TIMECODE", default="shift").strip().lower()
        faststart = truthy(first_env("AUDION_TRIM_FASTSTART"), True)

        # One file per run: cut points belong to a take, not to a folder.
        wanted = first_env("AUDION_TRIM_FILE", "TRIM_FILE").strip().strip('"')
        files = self.files(VIDEO_EXTS)
        if wanted:
            candidate = Path(wanted)
            if not candidate.is_absolute():
                candidate = self.source_dir / wanted
            if not candidate.is_file():
                print(f"[!] File was not found: {candidate}")
                return
            source = candidate
        else:
            if not files:
                print(f"[!] No video files in {self.source_dir}")
                return
            source = files[0]
            if len(files) > 1:
                print(f"[i] {len(files)} files staged; trimming {self.source_label(source)}.")
                print("[i] Point AUDION_TRIM_FILE at another one, or trim the rest from the GUI.")
        try:
            if pattern == "middle":
                self.trim_middle(
                    source,
                    head=head,
                    tail=tail,
                    container_choice=container_choice,
                    audio_mode=audio_mode,
                    channel_mode=channel_mode,
                    timecode_mode=timecode_mode,
                    faststart=faststart,
                )
                return
            self.trim_one(
                source,
                pattern=pattern,
                head=head,
                tail=tail,
                container_choice=container_choice,
                audio_mode=audio_mode,
                channel_mode=channel_mode,
                timecode_mode=timecode_mode,
                faststart=faststart,
            )
        except Exception as exc:
            print(f"[SKIP] {self.source_label(source)}: {exc}")

    def trim_one(
        self,
        source: Path,
        *,
        pattern: str,
        head: str,
        tail: str,
        container_choice: str,
        audio_mode: str,
        channel_mode: str,
        timecode_mode: str,
        faststart: bool,
        target: Path | None = None,
        sample_exact: bool = False,
    ) -> Path:
        """Cut one piece. Returns where it landed, so a caller can join pieces.

        `sample_exact` is for a piece about to be joined: PCM is rewritten
        rather than copied, and the sound is given the length of the piece so
        it does not stop with the last frame. Both surpluses would otherwise
        land on the joint.
        """
        facts = self.trim_stream_facts(source)
        variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
        # On a variable rate the average is not the rate of any given second, so
        # the nominal one is the honest basis for timecode and for display.
        rate_raw = facts.get("r_frame_rate") if variable_rate else facts.get("avg_frame_rate")
        # The file's own rate, exactly as ffprobe reports it.
        rate = parse_rate(rate_raw)
        duration = float(facts.get("duration") or 0.0)
        # Positions are counted from the first picture; MPEG-TS starts at 1.44 s
        # and FFmpeg counts in that timeline, so the origin comes back at seek.
        origin = float(facts.get("origin") or 0.0)
        requested_head = parse_seconds(head or 0) if pattern in {"start", "both"} else 0.0
        keyframes = (
            [item - origin for item in self.trim_keyframes(source, requested_head + origin)]
            if requested_head > 0
            else []
        )
        cut = plan_cut(
            pattern=pattern,
            start=head,
            end=tail,
            duration=duration,
            rate=rate,
            keyframes=keyframes,
            frame_exact=not variable_rate,
        )

        container = source.suffix.lower().lstrip(".") if container_choice in {"", "source", "same", "keep"} else container_choice
        stream = self.audio_stream_info(source)
        audio_codec = str(stream.get("codec") or stream.get("codec_name") or "")
        video_codec = self.probe_one(
            [self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=nokey=1:noprint_wrappers=1", str(source)]
        )
        if video_codec.strip().lower() in TRIM_CONTAINER_REFUSALS.get(container, set()):
            raise RuntimeError(f"{container.upper()} cannot hold {video_codec.upper()} video. MOV or MKV can.")
        # Measured: the MXF muxer takes PCM and refuses aac, ac3, mp3, alac and flac.
        if container == "mxf" and audio_codec and not audio_codec.lower().startswith("pcm_"):
            raise RuntimeError(f"MXF takes PCM audio only, and this file carries {audio_codec.upper()}. MOV keeps it as it is.")
        if audio_codec.lower() in TRIM_AUDIO_REFUSALS.get(container, set()):
            raise RuntimeError(f"{container.upper()} cannot hold {audio_codec.upper()} audio. MKV or MP4 can.")
        if not audio_codec:
            audio_mode = "none"
        if audio_mode not in {"none", "off"}:
            complaint = audio_channel_complaint(channel_mode, int(stream.get("channels") or 0))
            if complaint:
                raise RuntimeError(complaint)
        audio_filter = "" if audio_mode in {"none", "off"} else audio_channel_filter(channel_mode)
        audio_args: list[str] = []
        lossless = True
        rewrite_pcm = False
        if audio_filter:
            audio_args, lossless = audio_reencode_args(audio_codec, sample_fmt=str(stream.get("sample_fmt") or ""), bitrate=self.audio_bitrate)
        elif (
            audio_mode not in {"none", "off"}
            and audio_codec.lower().startswith("pcm_")
            and (container == "mxf" or sample_exact)
        ):
            # See the service: copying PCM into MXF drags in the samples before
            # the cut; rewriting the same PCM lands on the sample.
            # Little-endian for MXF: it refuses pcm_s16be, which is what Canon writes.
            audio_args, lossless = audio_reencode_args(
                audio_codec.replace("be", "le"), sample_fmt=str(stream.get("sample_fmt") or ""), bitrate=self.audio_bitrate
            )
            rewrite_pcm = True

        source_timecode = self.source_timecode(source)
        if timecode_mode in {"zero", "reset"}:
            timecode = zero_timecode(rate, drop=timecode_is_drop_frame(source_timecode))
        elif source_timecode:
            timecode = shift_timecode(source_timecode, cut.start, rate)
        else:
            timecode = ""

        # Telemetry and subtitles ride along by default, exactly as in the panel.
        keep_data, keep_subtitles, extra_warnings = extra_stream_plan(
            self.trim_all_streams(source),
            container,
            want_data=truthy(first_env("AUDION_TRIM_DATA"), True),
            want_subtitles=truthy(first_env("AUDION_TRIM_SUBTITLES"), True),
            source_container=source.suffix,
        )

        output = Path(target) if target is not None else self.output_path(source, "", container, subdir="Trim")
        output.parent.mkdir(parents=True, exist_ok=True)
        command = build_trim_command(
            ffmpeg=self.ffmpeg,
            source=str(source),
            target=str(output),
            overwrite=self.overwrite,
            start_seconds=cut.start + origin,
            frame_count=cut.frames,
            duration_seconds=cut.tail_seconds,
            sound_to_seconds=(cut.kept if cut.frames and sample_exact else None),
            extension=container,
            audio_mode=audio_mode,
            audio_args=audio_args,
            audio_filter=audio_filter,
            rewrite_audio=rewrite_pcm,
            timecode=timecode,
            faststart=faststart,
            keep_data=keep_data,
            keep_subtitles=keep_subtitles,
        )
        print(f"[TRIM] {source.name} | {rate_label(rate)} | {format_seconds(duration)} -> {container.upper()}")
        if cut.keyframe_offset:
            print(f"       in  {format_seconds(cut.requested_start)} -> keyframe {format_seconds(cut.start)} ({format_offset(cut.keyframe_offset)})")
        else:
            print(f"       in  {format_seconds(cut.start)}")
        if cut.frames:
            tail_text = f" -> {cut.frames} frames"
        elif variable_rate:
            tail_text = " (by time: variable frame rate)"
        else:
            tail_text = " (end of file)"
        print(f"       out {format_seconds(cut.requested_end)}{tail_text}")
        print(f"       keeping {format_seconds(cut.kept)}")
        if timecode:
            print(f"       timecode {source_timecode or 'none'} -> {timecode}")
        if container == "mkv" and timecode:
            print("       [WARNING] MKV keeps a timecode as a text tag, not a tmcd track.")
        if (
            container in {"mp4", "m4v"}
            and audio_codec.lower().startswith("pcm_")
            and source.suffix.lower().lstrip(".") not in {"mp4", "m4v"}
        ):
            print("       [WARNING] PCM audio in MP4 uses the non-standard ipcm tag. MOV is the safe home for camera PCM.")
        carried = [name for name, flag in (("telemetry", keep_data), ("subtitles", keep_subtitles)) if flag]
        if carried:
            print(f"       carried over: {', '.join(carried)}")
        for warning in extra_warnings:
            print(f"       [WARNING] {warning}")
        if rewrite_pcm:
            print("       audio: PCM rewritten sample-accurately for MXF (same depth, no generation lost)")
        if audio_filter and not lossless:
            print(f"       [WARNING] Picking a channel rebuilds {audio_codec.upper()} audio and costs a generation.")
        if variable_rate:
            print("       [WARNING] Variable frame rate: the cut is made by time, so the tail lands within a packet.")
        self.run(command)
        self.trim_top_up(command, cut.frames, output)
        return output

    def trim_middle(
        self,
        source: Path,
        *,
        head: str,
        tail: str,
        container_choice: str,
        audio_mode: str,
        channel_mode: str,
        timecode_mode: str,
        faststart: bool,
    ) -> None:
        """Remove the piece between the points and join what is left.

        The tail starts at the first keyframe at or after the end point - never
        before it, or part of the removed piece would survive into the result.
        """
        facts = self.trim_stream_facts(source)
        variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
        rate = parse_rate(facts.get("r_frame_rate") if variable_rate else facts.get("avg_frame_rate"))
        duration = float(facts.get("duration") or 0.0)
        origin = float(facts.get("origin") or 0.0)

        gap_end = parse_seconds(tail or 0)
        keyframes = [item - origin for item in self.trim_keyframes(source, gap_end + origin)]
        gap = plan_gap(
            start=head,
            end=tail,
            duration=duration,
            rate=rate,
            keyframes=keyframes,
            frame_exact=not variable_rate,
        )

        container = source.suffix.lower().lstrip(".") if container_choice in {"", "source", "same", "keep"} else container_choice
        stage = self.output_dir / "Trim" / "_parts"
        stage.mkdir(parents=True, exist_ok=True)
        final = self.output_path(source, "", container, subdir="Trim")

        print(f"[GAP ] {source.name} | {rate_label(rate)} | {format_seconds(duration)} -> {container.upper()}")
        print(f"       remove  {format_seconds(gap.requested_start)} .. {format_seconds(gap.requested_end)}")
        if gap.keyframe_offset > 0:
            print(f"       tail at {format_seconds(gap.tail_start)} (first keyframe past the piece, {format_offset(gap.keyframe_offset)})")
            print(f"       [WARNING] {format_offset(gap.keyframe_offset).lstrip('+')} more than asked for is removed; starting earlier would leave part of the piece in.")
        else:
            print(f"       tail at {format_seconds(gap.tail_start)} (a keyframe sits exactly there)")
        print(f"       removed {format_seconds(gap.removed)}, keeping {format_seconds(gap.kept)}")

        pieces: list[Path] = []
        list_file = stage / f"{final.stem}_parts.txt"
        try:
            for name, piece_pattern, piece_head, piece_tail in (
                ("gap_head", "end", "", format_seconds(gap.requested_start)),
                ("gap_tail", "start", format_seconds(gap.tail_start), ""),
            ):
                pieces.append(
                    self.trim_one(
                        source,
                        pattern=piece_pattern,
                        head=piece_head,
                        tail=piece_tail,
                        container_choice=container,
                        audio_mode=audio_mode,
                        channel_mode=channel_mode,
                        # The head keeps the file's own timecode; shifting it on
                        # a piece that is about to become the middle of another
                        # file would describe a take that does not exist.
                        timecode_mode=timecode_mode if name == "gap_head" else "keep",
                        faststart=False,
                        target=stage / f"{final.stem}_{name}.{container}",
                        sample_exact=True,
                    )
                )
            lines = ["file '" + str(item).replace("'", "'\\''") + "'" for item in pieces]
            list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

            join = [
                self.ffmpeg,
                "-hide_banner",
                "-stats",
                "-y" if self.overwrite else "-n",
                "-nostdin",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                # By name, not `-map 0`: the timecode track cannot travel through
                # a concat into MOV, and the run would fail outright.
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-sn",
                "-dn",
                "-c",
                "copy",
                "-map_metadata",
                "0",
            ]
            source_timecode = self.source_timecode(source)
            if source_timecode and timecode_mode not in {"zero", "reset"}:
                join += ["-timecode", source_timecode]
            elif timecode_mode in {"zero", "reset"}:
                join += ["-timecode", zero_timecode(rate, drop=timecode_is_drop_frame(source_timecode))]
            if container in {"mp4", "m4v", "mov"}:
                flags = "use_metadata_tags"
                if faststart:
                    flags += "+faststart"
                join += ["-movflags", flags]
            join.append(str(final))
            print(f"[JOIN] {final.name}")
            self.run(join)
        finally:
            for item in pieces:
                item.unlink(missing_ok=True)
            list_file.unlink(missing_ok=True)
            # The staging folder goes too, unless something else is using it.
            try:
                stage.rmdir()
            except OSError:
                pass

    def trim_all_streams(self, source: Path) -> list[dict[str, Any]]:
        """Every stream in the file, as the shared rule wants to see them."""
        raw = self.probe_lines(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,codec_tag_string",
                "-of",
                "json",
                str(source),
            ]
        )
        try:
            # probe_lines hands back one string, not a list: joining it would splice
            # a newline between every character, the parse would fail silently, and
            # every file would look as though it had no extra streams at all.
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        streams = data.get("streams")
        return [item for item in streams if isinstance(item, dict)] if isinstance(streams, list) else []

    def trim_stream_facts(self, source: Path) -> dict[str, Any]:
        """Rate fields, timeline origin and duration, straight from the stream."""
        raw = self.probe_lines(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate,r_frame_rate,start_time:format=duration,start_time",
                "-of",
                "json",
                str(source),
            ]
        )
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        streams = data.get("streams") or [{}]
        stream = streams[0] if isinstance(streams[0], dict) else {}
        fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
        fmt = fmt or {}

        def number(value: Any) -> float:
            try:
                result = float(value)
            except (TypeError, ValueError):
                return 0.0
            return result if result > 0 else 0.0

        return {
            "avg_frame_rate": stream.get("avg_frame_rate"),
            "r_frame_rate": stream.get("r_frame_rate"),
            "origin": number(stream.get("start_time")) or number(fmt.get("start_time")),
            "duration": number(fmt.get("duration")),
        }

    def counted_frames(self, target: Path) -> int:
        raw = self.probe_one(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_packets",
                "-show_entries",
                "stream=nb_read_packets",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(target),
            ]
        )
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return 0

    def trim_top_up(self, command: list[str], planned: int | None, target: Path) -> None:
        """Redo the cut when the muxer held frames back, raised by the shortfall."""
        if not planned or self.dry_run:
            return
        written = self.counted_frames(target)
        shortfall = int(planned) - written
        if written <= 0 or shortfall <= 0 or shortfall > TRIM_TOP_UP_LIMIT:
            return
        retry = list(command)
        try:
            position = retry.index("-frames:v")
        except ValueError:
            return
        retry[position + 1] = str(int(planned) + shortfall)
        print(f"       [RETRY] Muxer wrote {written} of {planned} frames; asking for {retry[position + 1]}.")
        self.run(retry)

    def dispatch(self) -> None:
        profile = self.profile
        print(f"[PROFILE] {profile}")
        print(f"[SOURCE] {self.source_dir}")
        print(f"[OUTPUT] {self.output_dir}")
        kind = str(self.cfg("kind", "")).lower()
        if kind == "encode":
            self.run_configured_encode()
        elif kind == "editing":
            self.run_configured_editing()
        elif kind == "color":
            self.run_configured_color()
        elif kind == "remux":
            self.run_configured_remux()
        elif kind == "fps":
            self.run_configured_fps()
        elif kind == "audio":
            self.run_configured_audio()
        elif kind == "youtube":
            self.run_configured_youtube()
        elif kind == "trim":
            self.run_configured_trim()
        elif kind == "subtitles":
            self.run_subtitle_extract()
        elif kind == "ff_selftest":
            self.run_ff_selftest()
        elif kind:
            raise RuntimeError(f"Unsupported configured profile kind: {kind}")
        elif profile.startswith("yt-"):
            self.run_youtube()
        elif profile.startswith("audio-"):
            self.run_audio()
        elif profile.startswith("ff-remux-"):
            self.run_remux()
        elif re.match(r"ff-\d+to\d+-(varispeed|conform)", profile):
            self.run_fps()
        elif profile.startswith("ff-grade-") or profile.startswith("ff-hdr2sdr-"):
            self.run_color()
        elif profile.startswith("ff-prores-") or profile.startswith("ff-dnxhr-"):
            self.run_editing()
        elif profile.startswith("ff-"):
            self.run_x264_hevc()
        else:
            raise RuntimeError(f"Unsupported profile: {profile}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: script_runner.py <profile> [args...]", file=sys.stderr)
        return 2
    try:
        Runner(argv[1], argv[2:]).dispatch()
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
