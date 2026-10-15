"""The frame rate a stream is counted and cut by (trim_contract.stream_rate)."""
from __future__ import annotations

import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.trim_contract import stream_rate


class StreamRateTests(unittest.TestCase):
    def test_a_constant_rate_is_the_exact_nominal_fraction(self) -> None:
        # ProRes LT 4096x2160 of the owner: 599 frames in 24.94 s - the average is 24.016, the file is 23.976.
        self.assertEqual(stream_rate("24000/1001", "7188000/299299"), "24000/1001")
        self.assertEqual(stream_rate("24000/1001", "7188000/299299", variable="average"), "24000/1001")
        self.assertEqual(stream_rate("25/1", "25/1"), "25/1")

    def test_a_variable_rate_keeps_the_field_its_caller_took(self) -> None:
        # A phone: 30 in the nominal field, what it averaged in the other - 3.3 % off, past the line of 1 %.
        self.assertEqual(stream_rate("30/1", "2900/100"), "30/1")
        self.assertEqual(stream_rate("30/1", "2900/100", variable="average"), "2900/100")
        # 0.9 % off is still a constant rate: the nominal fraction.
        self.assertEqual(stream_rate("30/1", "2973/100", variable="average"), "30/1")

    def test_without_a_nominal_rate_the_average(self) -> None:
        self.assertEqual(stream_rate("0/0", "25/1"), "25/1")
        self.assertEqual(stream_rate("", "30000/1001"), "30000/1001")
        self.assertEqual(stream_rate(None, None), "")

    def test_a_nominal_rate_without_an_average_stands(self) -> None:
        self.assertEqual(stream_rate("24/1", "0/0"), "24/1")


if __name__ == "__main__":
    unittest.main()
