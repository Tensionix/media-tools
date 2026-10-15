"""The outcome of a download names the files it wrote: the files of the download folder, its subfolders too, born during
the run - not what lay there before, not what yt-dlp leaves while it works."""
from __future__ import annotations

import time
from pathlib import Path

from system_core.services import media_service


def test_the_files_born_during_the_run(tmp_path: Path) -> None:
    folder = tmp_path / "Download"
    (folder / "jawed").mkdir(parents=True)
    video = folder / "jawed" / "2005-04-24 - Me at the zoo [jNQXAC9IVRw].mp4"
    video.write_bytes(b"0")
    (folder / "jawed" / "half.mp4.part").write_bytes(b"0")
    assert media_service._files_born_since(folder, time.time() - 30) == [video]
    assert media_service._files_born_since(folder, time.time() + 30) == [], "a file older than the run is not its file"
    assert media_service._files_born_since(tmp_path / "absent", 0.0) == []
