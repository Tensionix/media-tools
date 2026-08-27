from __future__ import annotations

from hashlib import sha256
from fractions import Fraction
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.audio_contract import MP3_PRESETS
from system_core.core.manifest import load_manifest
from system_core.core.encoder_backends import (
    can_keep_frames_on_gpu,
    decode_output_format_args,
    hardware_pix_fmt,
    target_for_backend,
)
from system_core.core.fps_contract import build_fps_command, fps_audio_output_rate, fps_audio_target_rate
from system_core.core.path_cache import cached_output_path, cached_source_path, update_path_cache
from system_core.core.preflight import HARDWARE_DECODERS, HARDWARE_ENCODERS, _required_encoders
from system_core.core.script_profiles import load_script_profiles
from system_core.services.media_service import (
    AUDIO_COPY_CODECS,
    KNOWN_VIDEO_COPY_CODECS,
    VIDEO_COPY_CODECS,
    VIDEO_REMUX_COMPATIBILITY,
    _audio_args,
    _container_audio_mode,
    _copy_codecs_supported,
    _encode_audio_filter_args,
    _fps_audio_output_rate,
    _fps_output_args,
    _media_files,
    _target_video_args,
    hardware_smoke_labels,
)
from Scripts.Common.script_runner import Runner


def _leaf_nodes(manifest):
    def walk(nodes):
        for node in nodes:
            if node.children:
                yield from walk(node.children)
            else:
                yield node

    return walk(manifest.operation_groups)


CANONICAL_WORKBENCH_SHA256 = "81695288ae6c85c53faadce72bd056f4f4f974fe68e0fa561ffcf396e4a31730"
INTERACTIVE_FPS_SOURCES = {"25", "2997", "50", "5994", "100", "11988", "17982"}
BACKENDS = ("cpu", "cuda", "qsv", "amd")
ENCODE_TARGETS = ("x264", "hevc_x265", "svt_av1")
_PIXEL_FORMAT_CACHE: dict[str, set[str]] = {}


def command_encoder(command: list[str]) -> str:
    return command[command.index("-c:v") + 1]


def encoder_pixel_formats(encoder: str) -> set[str]:
    """Pixel formats the installed FFmpeg build reports for an encoder."""
    if encoder in _PIXEL_FORMAT_CACHE:
        return _PIXEL_FORMAT_CACHE[encoder]
    ffmpeg = ROOT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if not ffmpeg.exists():
        raise unittest.SkipTest("Portable FFmpeg is not installed; run install\\Install-Portable-FFmpeg-BtbN.cmd")
    completed = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-h", f"encoder={encoder}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    formats: set[str] = set()
    for line in (completed.stdout or "").splitlines():
        if "Supported pixel formats:" in line:
            formats = set(line.split("Supported pixel formats:", 1)[1].split())
            break
    _PIXEL_FORMAT_CACHE[encoder] = formats
    return formats


class MediaContractsTest(unittest.TestCase):
    def test_workbench_module_is_canonical(self) -> None:
        payload = (ROOT / "system_core" / "ui_nicegui" / "workbench.py").read_bytes()
        self.assertEqual(sha256(payload).hexdigest(), CANONICAL_WORKBENCH_SHA256)

    def test_authoritative_path_cache_drives_backend_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "external source"
            output = root / "external output"
            source.mkdir()
            output.mkdir()
            update_path_cache(root, "source", str(source))
            update_path_cache(root, "output", str(output))
            self.assertEqual(cached_source_path(root), source.resolve())
            self.assertEqual(cached_output_path(root), output.resolve())

    def test_selected_source_file_is_a_valid_backend_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "selected.MOV"
            source.touch()
            self.assertEqual(_media_files(source, {"mov"}), [source])
            self.assertEqual(_media_files(source, {"mp4"}), [])

    def test_mxf_pcm_and_sample_rate_contract(self) -> None:
        for profile in ("prores_mxf", "dnxhr_mxf"):
            with self.subTest(profile=profile, depth="s16"):
                _video, audio, extension, _label = _fps_output_args(profile, {"fps_audio_pcm_depth": "s16"})
                self.assertEqual(extension, "mxf")
                self.assertEqual(audio, ["-c:a", "pcm_s16le"])
            with self.subTest(profile=profile, depth="s24"):
                _video, audio, extension, _label = _fps_output_args(profile, {"fps_audio_pcm_depth": "s24"})
                self.assertEqual(extension, "mxf")
                self.assertEqual(audio, ["-c:a", "pcm_s24le"])
            with self.subTest(profile=profile, depth="f32"):
                _video, audio, extension, _label = _fps_output_args(profile, {"fps_audio_pcm_depth": "f32"})
                self.assertEqual(extension, "mxf")
                self.assertEqual(audio, ["-c:a", "pcm_s24le"])
            self.assertEqual(_fps_audio_output_rate(profile, 192000), 48000)

        self.assertEqual(_fps_audio_output_rate("prores", 192000), 192000)
        self.assertEqual(_fps_audio_output_rate("dnxhr", 96000), 96000)

    def test_interactive_fps_master_is_only_a_shared_profile_frontend(self) -> None:
        launcher = (ROOT / "cli" / "launcher-select-fps-speed.cmd").read_text(encoding="utf-8")
        self.assertNotRegex(launcher, re.compile(r"(?im)^\s*ffmpeg(?:\.exe)?\b"))
        self.assertIn("Scripts\\Common\\script_runner.py", launcher)
        self.assertIn("call \"%TARGET%\"", launcher)
        for profile in ("h264", "hevc", "prores", "prores_mxf", "dnxhr", "dnxhr_mxf"):
            self.assertIn(f"AUDION_FPS_OUTPUT_PROFILE={profile}", launcher)
        for depth in ("s16", "s24", "f32"):
            self.assertIn(f"AUDION_FPS_AUDIO_PCM_DEPTH={depth}", launcher)
        for rate in ("x1", "x2", "x4"):
            self.assertIn(f"AUDION_FPS_AUDIO_OVERSAMPLE={rate}", launcher)

        profiles = load_script_profiles(ROOT)["profiles"]
        for source in INTERACTIVE_FPS_SOURCES:
            for mode in ("varispeed", "conform"):
                profile_id = f"ff-{source}to23976-{mode}"
                with self.subTest(profile=profile_id):
                    self.assertIn(profile_id, profiles)
                    self.assertEqual(profiles[profile_id]["kind"], "fps")
                    wrapper = ROOT / "Scripts" / f"{profile_id}.cmd"
                    self.assertTrue(wrapper.is_file())
                    self.assertIn("Common\\run-profile.cmd", wrapper.read_text(encoding="utf-8"))

    def test_cli_fps_runner_builds_the_same_commands_as_gui_contract(self) -> None:
        cases = [
            ("prores_mxf", "s24", "x4", "mxf", 192000, 48000),
            ("dnxhr", "f32", "x2", "mov", 96000, 96000),
        ]
        for output_profile, depth, oversample, extension, work_rate, output_rate in cases:
            with self.subTest(profile=output_profile, depth=depth, oversample=oversample):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    source_dir = root / "Source"
                    output_dir = root / "OUT"
                    source_dir.mkdir()
                    output_dir.mkdir()
                    source = source_dir / "clip.mov"
                    source.touch()
                    target = output_dir / f"result.{extension}"
                    env = {
                        "AUDION_SOURCE": str(source_dir),
                        "AUDION_OUTPUT": str(output_dir),
                        "AUDION_FPS_OUTPUT_PROFILE": output_profile,
                        "AUDION_FPS_AUDIO_PCM_DEPTH": depth,
                        "AUDION_FPS_AUDIO_OVERSAMPLE": oversample,
                        "AUDION_OVERWRITE": "0",
                    }
                    captured: list[list[str]] = []
                    with patch.dict(os.environ, env, clear=False):
                        runner = Runner("ff-25to23976-conform", [])
                        runner.files = lambda *_args, **_kwargs: [source]  # type: ignore[method-assign]
                        runner.has_audio = lambda _source: True  # type: ignore[method-assign]
                        runner.sample_rate = lambda _source: "48000"  # type: ignore[method-assign]
                        runner.output_path = lambda *_args, **_kwargs: target  # type: ignore[method-assign]
                        runner.run = lambda command, cwd=None: captured.append(command)  # type: ignore[method-assign]
                        runner.run_configured_fps()

                    params = {
                        "fps_audio_pcm_depth": depth,
                        "fps_audio_oversample": oversample,
                        "audio_bitrate": "384k",
                        "encode_backend": "cpu",
                        "cpu_encoder_preset": "medium",
                        "nvenc_preset": "p6",
                        "qsv_encoder_preset": "medium",
                        "amf_quality": "quality",
                        "crf": "14",
                        "cq": "14",
                    }
                    video_args, audio_args, actual_extension, _label = _fps_output_args(output_profile, params)
                    self.assertEqual(actual_extension, extension)
                    self.assertEqual(fps_audio_target_rate(48000, params), work_rate)
                    self.assertEqual(fps_audio_output_rate(output_profile, work_rate), output_rate)
                    source_fps = Fraction(25, 1)
                    target_fps = Fraction(24000, 1001)
                    expected = build_fps_command(
                        ffmpeg=runner.ffmpeg,
                        source=str(source),
                        overwrite=False,
                        mode="conform",
                        k=float(source_fps / target_fps),
                        speed=float(target_fps / source_fps),
                        target_arg="24000/1001",
                        video_args=video_args,
                        audio_args=audio_args,
                        extension=extension,
                        target=str(target),
                        has_audio=True,
                        audio_work_rate=work_rate,
                        audio_output_rate=output_rate,
                    )
                    self.assertEqual(captured, [expected])

    def test_all_catalog_wrappers_delegate_to_the_shared_runner(self) -> None:
        profiles = load_script_profiles(ROOT)["profiles"]
        for profile_id in profiles:
            wrapper = ROOT / "Scripts" / f"{profile_id}.cmd"
            if not wrapper.exists():
                continue
            text = wrapper.read_text(encoding="utf-8")
            with self.subTest(profile=profile_id):
                self.assertIn("Common\\run-profile.cmd", text)
                self.assertNotRegex(text, re.compile(r"(?im)^\s*ffmpeg(?:\.exe)?\b"))

    def test_preflight_requires_the_encoder_the_command_actually_uses(self) -> None:
        """The hardware guard only fires when preflight names the real encoder."""
        encode_cases = [(backend, target) for backend in BACKENDS for target in ENCODE_TARGETS]
        for backend, target in encode_cases:
            with self.subTest(page="encode", backend=backend, target=target):
                params = {"encode_backend": backend, "target_codecs": [target], "pix_fmt": "auto", "crf": 20, "cq": 28}
                command, _extension, _suffix, _family = _target_video_args(target, params)
                self.assertIn(command_encoder(command), _required_encoders("encode_targets", params, ROOT))

        for backend, profile in [(backend, profile) for backend in BACKENDS for profile in ("h264", "hevc")]:
            with self.subTest(page="fps", backend=backend, profile=profile):
                params = {"encode_backend": backend, "fps_output_profile": profile, "crf": 20, "cq": 28}
                video_args, _audio_args, _extension, _label = _fps_output_args(profile, params)
                self.assertIn(command_encoder(video_args), _required_encoders("fps_convert", params, ROOT))

    def test_every_hardware_encoder_has_a_capability_guard(self) -> None:
        """A hardware encoder without a smoke label would run unguarded."""
        smoke_labels = {label for _stack, label in HARDWARE_ENCODERS.values()}
        for backend in BACKENDS[1:]:
            for target in ENCODE_TARGETS:
                encoder = target_for_backend(target, backend)
                with self.subTest(backend=backend, target=target):
                    self.assertIn(encoder, HARDWARE_ENCODERS)
        for label in smoke_labels:
            with self.subTest(smoke=label):
                self.assertIn(label, hardware_smoke_labels())
        for _stack, label in HARDWARE_DECODERS.values():
            with self.subTest(smoke=label):
                self.assertIn(label, hardware_smoke_labels())

    def test_hardware_pixel_formats_are_supported_by_the_encoder(self) -> None:
        """Manifest pixel formats either map to a native format or stop the run."""
        manifest = load_manifest(ROOT / "config" / "tool_manifest.yaml")
        delivery = next(group for group in manifest.operation_groups if group.id == "delivery")
        pix_field = next(field for field in delivery.fields if field.get("id") == "pix_fmt")
        options = [str(option["value"]) for option in pix_field.get("options", [])]
        self.assertIn("yuv420p10le", options)
        for backend in BACKENDS[1:]:
            for target in ENCODE_TARGETS:
                encoder = target_for_backend(target, backend)
                for pix_fmt in options:
                    with self.subTest(encoder=encoder, pix_fmt=pix_fmt):
                        try:
                            native = hardware_pix_fmt(encoder, pix_fmt)
                        except RuntimeError as exc:
                            self.assertIn(encoder, str(exc))
                            continue
                        if pix_fmt == "auto":
                            self.assertEqual(native, "")
                        else:
                            self.assertIn(native, encoder_pixel_formats(encoder))

    def test_cli_and_gui_encode_audio_identically(self) -> None:
        """Same audio mode and sample rate must produce the same FFmpeg arguments."""
        modes = [("aac", "aac_320"), ("pcm_s24", "pcm_s24"), ("pcm_s16", "pcm_s16"), ("flac", "flac"), ("source", "source")]
        rates = ["source", "44100", "48000", "96000", "192000"]
        for cli_mode, gui_mode in modes:
            for rate in rates:
                with self.subTest(mode=cli_mode, rate=rate):
                    with patch.dict(os.environ, {"AUDION_AUDIO_SAMPLE_RATE": rate}, clear=False):
                        runner = Runner("ff-x264-crf14", [])
                        cli_codec = runner.audio_args(cli_mode)
                        cli_filter = runner.audio_filter_args(cli_mode)
                    gui_codec = _audio_args(gui_mode, runner.audio_bitrate)
                    gui_filter = _encode_audio_filter_args({"audio_sample_rate": rate}, gui_mode)
                    self.assertEqual(cli_codec, gui_codec)
                    self.assertEqual(cli_filter, gui_filter)

    def test_cli_and_gui_encode_mp3_with_the_same_lame_preset(self) -> None:
        """MP3 must mean the same LAME preset on every page and in the CLI."""
        for preset in MP3_PRESETS:
            for bitrate in ("192k", "256k", "320k", "384k"):
                with self.subTest(preset=preset, bitrate=bitrate):
                    with patch.dict(
                        os.environ,
                        {"AUDION_MP3_LAME_PRESET": preset, "AUDION_AUDIO_BITRATE": bitrate},
                        clear=False,
                    ):
                        cli_codec = Runner("ff-x264-crf14", []).audio_args("mp3")
                    gui_codec = _audio_args("mp3", bitrate, preset)
                    self.assertEqual(cli_codec, gui_codec)
                    # 384k is offered for AAC only; MPEG-1 Layer III stops at 320.
                    self.assertNotIn("384k", cli_codec)

    def test_mp3_lame_preset_is_offered_wherever_mp3_is(self) -> None:
        """Every page that can encode MP3 exposes the same LAME preset scale."""
        manifest = load_manifest(ROOT / "config" / "tool_manifest.yaml")
        pages = 0
        for node in _leaf_nodes(manifest):
            fields = {str(field.get("id") or ""): field for field in node.fields}
            audio = fields.get("audio_mode") or fields.get("audio_format")
            if not audio:
                continue
            values = {str(option.get("value")) for option in audio.get("options", []) if isinstance(option, dict)}
            if "mp3" not in values:
                continue
            pages += 1
            preset = fields.get("mp3_lame_preset")
            self.assertIsNotNone(preset, f"{node.id} encodes MP3 without a LAME preset field")
            offered = tuple(str(option.get("value")) for option in preset.get("options", []) if isinstance(option, dict))
            self.assertEqual(offered, MP3_PRESETS)
            self.assertEqual(preset.get("default"), "v0")
        self.assertGreaterEqual(pages, 6)

    def test_container_audio_mode_refuses_what_the_muxer_cannot_write(self) -> None:
        """Every audio mode the GUI offers must be writable into the container."""
        modes = ("source", "aac_320", "mp3", "flac", "pcm_s16", "pcm_s24", "pcm_f32", "none")
        for mode in modes:
            for container in ("mp4", "mkv"):
                with self.subTest(container=container, mode=mode):
                    self.assertEqual(_container_audio_mode(container, mode), mode)
            with self.subTest(container="mov", mode=mode):
                # FFmpeg answers "flac only supported in MP4" for the MOV muxer.
                if mode == "flac":
                    with self.assertRaises(RuntimeError):
                        _container_audio_mode("mov", mode)
                else:
                    self.assertEqual(_container_audio_mode("mov", mode), mode)
            with self.subTest(container="mxf", mode=mode):
                if mode in {"pcm_s16", "pcm_s24", "none"}:
                    self.assertEqual(_container_audio_mode("mxf", mode), mode)
                else:
                    with self.assertRaises(RuntimeError):
                        _container_audio_mode("mxf", mode)

    def test_remux_checks_the_codec_and_not_only_the_container(self) -> None:
        """A compatible container pair still cannot carry every codec."""
        targets = {target for pairs in VIDEO_REMUX_COMPATIBILITY.values() for target in pairs}
        for container in sorted(targets):
            with self.subTest(container=container):
                self.assertIn(container, VIDEO_COPY_CODECS)
        # MOV -> MP4 is an offered pair, legal for H.264 and empty for ProRes.
        self.assertIn("mp4", VIDEO_REMUX_COMPATIBILITY["mov"])
        self.assertNotIn("prores", VIDEO_COPY_CODECS["mp4"])
        for container in ("mov", "mxf", "mkv"):
            with self.subTest(prores_into=container):
                self.assertIn("prores", VIDEO_COPY_CODECS[container])
        self.assertNotIn("hevc", VIDEO_COPY_CODECS["mxf"])
        self.assertEqual(VIDEO_COPY_CODECS["webm"], {"av1", "vp8", "vp9"})
        # MKV video+audio into MP4 is an everyday conversion, not a hazard.
        for codec in ("h264", "hevc", "av1", "vp9"):
            with self.subTest(mkv_to_mp4=codec):
                self.assertIn(codec, VIDEO_COPY_CODECS["mkv"])
                self.assertIn(codec, VIDEO_COPY_CODECS["mp4"])
        for codec in ("aac", "ac3", "flac", "opus", "mp3"):
            with self.subTest(mkv_audio_to_mp4=codec):
                self.assertIn(codec, AUDIO_COPY_CODECS["mp4"])
        self.assertEqual(AUDIO_COPY_CODECS["mxf"], {"pcm_s16le", "pcm_s24le"})

    def test_unmeasured_codecs_are_left_to_ffmpeg(self) -> None:
        """A table of known-good pairs must not become a blanket refusal."""
        known_ok, _ = _copy_codecs_supported(["h264"], "mp4", VIDEO_COPY_CODECS, KNOWN_VIDEO_COPY_CODECS)
        known_bad, reason = _copy_codecs_supported(["prores"], "mp4", VIDEO_COPY_CODECS, KNOWN_VIDEO_COPY_CODECS)
        unmeasured, _ = _copy_codecs_supported(["cinepak"], "mp4", VIDEO_COPY_CODECS, KNOWN_VIDEO_COPY_CODECS)
        self.assertTrue(known_ok)
        self.assertFalse(known_bad)
        self.assertIn("prores", reason)
        self.assertTrue(unmeasured, "an unmeasured codec must reach FFmpeg instead of being refused")
        unknown_container, _ = _copy_codecs_supported(["h264"], "ogv", VIDEO_COPY_CODECS, KNOWN_VIDEO_COPY_CODECS)
        self.assertTrue(unknown_container)

    def test_gpu_pipeline_only_when_nothing_needs_system_memory(self) -> None:
        """Frames may stay on the GPU only when nothing in between reads them."""
        for backend in BACKENDS[1:]:
            with self.subTest(backend=backend):
                self.assertTrue(can_keep_frames_on_gpu(backend, backend))
                # A software filter, an explicit pixel format or a CPU encoder
                # all require frames FFmpeg can read back.
                self.assertFalse(can_keep_frames_on_gpu(backend, backend, has_video_filters=True))
                self.assertFalse(can_keep_frames_on_gpu(backend, backend, pix_fmt="yuv420p"))
                self.assertFalse(can_keep_frames_on_gpu(backend, "cpu"))
                self.assertFalse(can_keep_frames_on_gpu("auto", backend))
        self.assertFalse(can_keep_frames_on_gpu("dav1d", "cuda"))
        for other in ("qsv", "amd"):
            with self.subTest(mixed=f"cuda/{other}"):
                self.assertFalse(can_keep_frames_on_gpu("cuda", other))

    def test_qsv_downloads_frames_before_software_filters(self) -> None:
        """QSV defaults to hardware surfaces, which breaks software filters."""
        self.assertEqual(decode_output_format_args("qsv", "qsv"), ["-hwaccel_output_format", "qsv"])
        self.assertEqual(
            decode_output_format_args("qsv", "qsv", has_video_filters=True),
            ["-hwaccel_output_format", "nv12"],
        )
        self.assertEqual(
            decode_output_format_args("qsv", "cpu", source_bit_depth=10),
            ["-hwaccel_output_format", "p010le"],
        )
        # CUDA and D3D11VA already return system memory frames, so forcing a
        # download format would pin a bit depth FFmpeg negotiates on its own.
        for backend in ("cuda", "amd"):
            with self.subTest(backend=backend):
                self.assertEqual(decode_output_format_args(backend, "cpu"), [])
                self.assertEqual(decode_output_format_args(backend, backend, has_video_filters=True), [])
        self.assertEqual(decode_output_format_args("cuda", "cuda"), ["-hwaccel_output_format", "cuda"])
        self.assertEqual(decode_output_format_args("amd", "amd"), ["-hwaccel_output_format", "d3d11"])
        self.assertEqual(decode_output_format_args("auto", "cpu"), [])

    def test_gui_color_presets_reference_the_shared_catalog(self) -> None:
        manifest = load_manifest(ROOT / "config" / "tool_manifest.yaml")
        grading = next(group for group in manifest.operation_groups if group.id == "grading")
        preset_field = next(field for field in grading.fields if field.get("id") == "grading_profile")
        catalog = load_script_profiles(ROOT)["profiles"]
        for preset in preset_field.get("presets", []):
            script_name = str(preset.get("values", {}).get("script_preset", ""))
            profile_id = Path(script_name).stem.lower()
            with self.subTest(preset=preset.get("id")):
                self.assertTrue(script_name)
                self.assertIn(profile_id, catalog)
                self.assertEqual(catalog[profile_id]["kind"], "color")


if __name__ == "__main__":
    unittest.main()
