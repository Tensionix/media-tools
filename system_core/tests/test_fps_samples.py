"""The sound of a frame-rate change: within 1 % it keeps its samples, whatever the mode (the owner, 15.10.2026)."""
from __future__ import annotations

import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.fps_contract import fps_audio_filter, fps_audio_mode


class SamplesKeptTests(unittest.TestCase):
    def test_a_conform_within_one_percent_keeps_the_samples(self) -> None:
        speed = (24000 / 1001) / 24  # 24 -> 23.976: 0.1 %
        self.assertEqual(fps_audio_mode("conform", speed), "varispeed")
        chain = fps_audio_filter("conform", 1 / speed, speed, 48000)
        self.assertIn("asetrate=", chain)
        self.assertNotIn("atempo", chain)

    def test_a_conform_past_one_percent_keeps_the_pitch(self) -> None:
        speed = (24000 / 1001) / 25  # 25 -> 23.976: 4.1 %
        self.assertEqual(fps_audio_mode("conform", speed), "conform")
        self.assertIn("atempo=", fps_audio_filter("conform", 1 / speed, speed, 48000))

    def test_varispeed_always_keeps_the_samples(self) -> None:
        self.assertEqual(fps_audio_mode("varispeed", 25 / 23.976), "varispeed")
        self.assertEqual(fps_audio_mode("varispeed", 1.0), "varispeed")

    def test_a_rate_the_file_already_has_moves_nothing(self) -> None:
        self.assertIn("asetrate=48000/1,", fps_audio_filter("conform", 1.0, 1.0, 48000))


if __name__ == "__main__":
    unittest.main()
