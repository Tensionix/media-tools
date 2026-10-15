"""FFmpeg's own line of its work beside the bar of the run (core\\jobs.py: run_process; cli.py: Progress.line).

The owner, 15.10.2026: the native line of FFmpeg - "frame= ... fps= ... size= ... time= ... bitrate= ... speed=" - beside
the bar, not instead of it. FFmpeg prints it every half second; the run says it under each bar and its final line at the
end of the file. The window has the bar as its live line: the native lines of a file not done stay out of its journal.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from system_core import cli
from system_core.core import jobs

PROJECT = Path(__file__).resolve().parent.parent
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
needs_ffmpeg = pytest.mark.skipif(not FFMPEG.is_file(), reason="FFmpeg of the program is not installed")
BAR = re.compile(r"^\[PROGRESS\] ")


class Context:
    def __init__(self, root: Path) -> None:
        self.paths = type("Paths", (), {"root": root})()
        self.commands: list[dict] = []
        self.said: list[str] = []

    def log(self, text: str) -> None:
        self.said.append(text)

    def progress(self, value: float) -> None:
        pass

    def cancelled(self) -> bool:
        return False


@needs_ffmpeg
def test_the_native_line_stands_under_the_bar_and_at_the_end(tmp_path: Path) -> None:
    context = Context(tmp_path)
    command = [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-stats_period", "0.1", "-f", "lavfi", "-i",
               "testsrc2=size=640x360:rate=25:duration=8", "-c:v", "libx264", "-preset", "medium", str(tmp_path / "clip.mp4")]
    jobs.run_process(context, command, ffmpeg_progress=True, progress_total_seconds=8.0, progress_label="clip")
    said = context.said
    native = [index for index, line in enumerate(said) if jobs.FFMPEG_STATS.match(line)]
    bars = [index for index, line in enumerate(said) if BAR.match(line)]
    assert native and bars
    # The final line of FFmpeg closes the file, just before [EXIT].
    assert said[native[-1] + 1].startswith("[EXIT]") and "Lsize=" in said[native[-1]]
    # Every other native line stands under a bar: not every half second, but as often as the bar.
    assert all(BAR.match(said[index - 1]) for index in native[:-1])
    assert len(native) <= len(bars) + 1
    assert "-stats" in context.commands[-1]["command"] and "-nostats" not in context.commands[-1]["command"]


def test_the_window_keeps_only_the_final_native_line_of_a_file() -> None:
    live = cli.Progress(live=True)
    native = "frame=  100 fps= 50 q=28.0 size=     256KiB time=00:00:04.00 bitrate= 524.3kbits/s speed=2.01x"
    final = "frame=  200 fps= 50 q=-1.0 Lsize=     512KiB time=00:00:08.00 bitrate= 524.3kbits/s speed=2.02x"
    assert live.line("[PROGRESS] clip [############------------]  50% 00:00:04/00:00:08 speed=2.01x")
    assert live.line(native) is True
    assert live.line("[PROGRESS] clip [########################] 100% 00:00:08/00:00:08 speed=2.02x")
    assert live.line(final) is False
    # A console gets every line.
    assert cli.Progress(live=False).line(native) is False
