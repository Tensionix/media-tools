"""The player, run as a separate program and spoken to over a pipe.

Why mpv and not something built in the browser: a cut has to be found by eye and
by ear, frame by frame, and a browser plays what the browser feels like playing.
mpv steps exactly one frame forwards or backwards, seeks to an exact time rather
than to the nearest keyframe, plays backwards, and opens camera formats that no
`<video>` tag will ever touch - because it carries the same FFmpeg this program
already uses for cutting.

How it is attached matters legally as well as technically. mpv is GPLv2+; this
project is GPL-3.0-or-later, so either way would be allowed, but running it as
its own program - one process, one pipe, JSON lines in and out - keeps the two
cleanly separate and is exactly how `ffmpeg.exe` is already used here.

One rule shapes the whole file: **a Windows pipe is a single-file handle, and it
cannot be read and written at the same time.** A background reader thread and a
writing panel deadlocked on the first question asked. So every exchange is
strictly one command, one answer, under one lock - the way the pipe actually
works, rather than the way an event-driven design would prefer.

That leaves no channel for the player to push anything back, which turns out not
to matter, because mpv already holds the two numbers the section needs. Its A/B
loop - `l` for A, `l` again for B - is exactly a cut: the piece between them
plays round and round, so the choice is heard before anything is written. The
panel reads `ab-loop-a` and `ab-loop-b` the same way it reads the position. One
mechanism, no events, and nothing invented on top of a feature the player has
had for years.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

MPV_RELATIVE = Path("Tools") / "mpv" / "bin" / "mpv.exe"
CONFIG_RELATIVE = Path("config") / "mpv"

# A pipe name is global to the machine; the process id keeps two copies of the
# program from talking into each other's player.
PIPE_NAME = rf"\\.\pipe\audion-media-tools-mpv-{os.getpid()}"

ANSWER_TIMEOUT = 4.0
START_TIMEOUT = 12.0


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def mpv_binary(root: Path | str | None = None) -> Path | None:
    """The player, or nothing if it was never installed."""
    base = Path(root) if root else project_root()
    candidate = base / MPV_RELATIVE
    return candidate if candidate.exists() else None


class MpvPlayer:
    """One mpv, kept alive between files.

    Reopening a file is a command, not a restart: the window stays where the
    operator put it - second monitor, usually - and does not jump back to the
    middle of the screen on every take.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or project_root()
        self.process: subprocess.Popen[bytes] | None = None
        self.handle: Any = None
        self.media: Path | None = None
        self.lock = threading.RLock()
        self.request = 0

    # -- lifetime ---------------------------------------------------------

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, media: Path) -> None:
        binary = mpv_binary(self.root)
        if binary is None:
            raise FileNotFoundError("mpv is not installed")
        arguments = [
            str(binary),
            f"--input-ipc-server={PIPE_NAME}",
            # The panel's own config directory, so a personal mpv.conf on the
            # machine cannot change what the operator sees here.
            f"--config-dir={self.root / CONFIG_RELATIVE}",
            "--force-window=yes",
            "--keep-open=yes",
            "--pause",
            # Always land on the frame asked for, never on the nearest keyframe.
            "--hr-seek=yes",
            "--no-resume-playback",
            "--osd-fractions",
            "--title=Audion Media Tools - ${filename}",
            str(media),
        ]
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        self.process = subprocess.Popen(
            arguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
        )
        self.media = media
        self._connect()

    def _connect(self, timeout: float = START_TIMEOUT) -> None:
        deadline = time.monotonic() + timeout
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError("mpv exited before it opened its pipe")
            try:
                self.handle = open(PIPE_NAME, "r+b", buffering=0)
                return
            except OSError as error:
                last_error = error
                time.sleep(0.05)
        raise RuntimeError(f"mpv did not open its pipe: {last_error}")

    def close(self) -> None:
        """Leave nothing running. A player that survives the panel is a leak."""
        with self.lock:
            process, handle = self.process, self.handle
            self.process, self.handle, self.media = None, None, None
            if handle is not None:
                try:
                    handle.write(b'{"command":["quit"]}\n')
                except (OSError, ValueError):
                    pass
                try:
                    handle.close()
                except (OSError, ValueError):
                    pass
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()

    # -- the pipe ---------------------------------------------------------

    def send(self, *command: object) -> Any:
        """One command, one answer, nothing in between.

        Returns None when the player is not there, when mpv refuses, or when it
        does not answer in time - the panel treats all three the same way, by
        leaving the field alone.
        """
        with self.lock:
            if not self.is_running() or self.handle is None:
                return None
            self.request += 1
            request_id = self.request
            payload = json.dumps({"command": list(command), "request_id": request_id}) + "\n"
            try:
                self.handle.write(payload.encode("utf-8"))
            except (OSError, ValueError):
                return None

            deadline = time.monotonic() + ANSWER_TIMEOUT
            buffer = b""
            while time.monotonic() < deadline:
                try:
                    chunk = self.handle.read(4096)
                except (OSError, ValueError):
                    return None
                if not chunk:
                    return None
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    # Events arrive on the same pipe and are simply passed over:
                    # everything the panel needs is asked for, never pushed.
                    if message.get("request_id") != request_id:
                        continue
                    if message.get("error") != "success":
                        return None
                    return message.get("data")
            return None

    # -- what the panel asks for -----------------------------------------

    def open(self, media: Path) -> None:
        """Show this file, starting the player only if it is not up."""
        media = Path(media)
        if not self.is_running():
            self.start(media)
            return
        if self.media is not None and Path(self.media) == media:
            return
        self.send("loadfile", str(media), "replace")
        self.media = media

    def wait_until_loaded(self, timeout: float = 10.0) -> bool:
        """True once mpv knows the file's length - and can be asked about it."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.send("get_property", "duration") is not None:
                return True
            time.sleep(0.1)
        return False

    def position(self) -> float | None:
        value = self.send("get_property", "time-pos")
        return float(value) if isinstance(value, (int, float)) else None

    def seek(self, seconds: float) -> None:
        self.send("seek", float(seconds), "absolute+exact")

    def ab_loop(self) -> tuple[float | None, float | None]:
        """The A and B points set in the player, in seconds.

        mpv answers `False` for a point that is not set, which is why the type
        is checked rather than trusted: a loop with only A set is a normal state
        - the operator has found the beginning and is still looking for the end.
        """
        points: list[float | None] = []
        for name in ("ab-loop-a", "ab-loop-b"):
            value = self.send("get_property", name)
            points.append(float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
        return points[0], points[1]

    def clear_ab_loop(self) -> None:
        for name in ("ab-loop-a", "ab-loop-b"):
            self.send("set_property", name, "no")


_player: MpvPlayer | None = None
_player_lock = threading.Lock()


def player(root: Path | None = None) -> MpvPlayer:
    """The one player this process owns."""
    global _player
    with _player_lock:
        if _player is None:
            _player = MpvPlayer(root)
        return _player


def close_player() -> None:
    global _player
    with _player_lock:
        if _player is not None:
            _player.close()
            _player = None
