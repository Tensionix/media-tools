from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.ffmpeg_escape import ffmpeg_filter_number, ffmpeg_filter_path
from system_core.services.media_service import _color_filter


class FfmpegFilterPathTest(unittest.TestCase):
    def test_lut_path_filtergraph_escaping(self) -> None:
        cases = {
            r"C:\LUTs\normal.cube": r"C\\:/LUTs/normal.cube",
            r"C:\LUTs\space name.cube": r"C\\:/LUTs/space name.cube",
            r"C:\LUTs\Kodak's K1S1.cube": r"C\\:/LUTs/Kodak\\\'s K1S1.cube",
            r"C:\LUTs\comma,name.cube": r"C\\:/LUTs/comma\,name.cube",
            r"C:\LUTs\semi;name.cube": r"C\\:/LUTs/semi\;name.cube",
            r"C:\LUTs\[ARRI] LogC.cube": r"C\\:/LUTs/\[ARRI\] LogC.cube",
            r"C:\LUTs\percent%name.cube": r"C\\:/LUTs/percent%name.cube",
            r"C:\LUTs\amp&name.cube": r"C\\:/LUTs/amp&name.cube",
        }

        for raw_path, expected_path in cases.items():
            with self.subTest(raw_path=raw_path):
                path = Path(raw_path)
                self.assertEqual(ffmpeg_filter_path(path), expected_path)
                filter_expr, suffix = _color_filter("ff-grade-lut-only-x264.cmd", path, {})
                self.assertEqual(suffix, "lut")
                self.assertEqual(filter_expr, f"lut3d=file={expected_path}:interp=tetrahedral")

    def test_filter_number_accepts_finite_values(self) -> None:
        cases = {
            "1": "1",
            "1.1500": "1.15",
            "0.85": "0.85",
            2: "2",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(ffmpeg_filter_number(value, name="pre_gamma"), expected)

    def test_filter_number_rejects_invalid_values(self) -> None:
        for value in ["not-a-number", "nan", "inf", "", True]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Expected a finite number"):
                    ffmpeg_filter_number(value, name="pre_gamma")

    def test_color_filter_rejects_invalid_gamma(self) -> None:
        with self.assertRaisesRegex(ValueError, "pre_gamma"):
            _color_filter(
                "ff-grade-pregamma-lut-x264.cmd",
                Path(r"C:\LUTs\ok.cube"),
                {},
                {"color_filter": "pregamma_lut", "pre_gamma": "not-a-number"},
            )

    def test_color_filter_uses_gamma_parameter_override(self) -> None:
        filter_expr, suffix = _color_filter(
            "ff-grade-pregamma-lut-x264.cmd",
            Path(r"C:\LUTs\ok.cube"),
            {"pre_gamma": "1.2"},
            {"color_filter": "pregamma_lut", "pre_gamma": "0.85"},
        )
        self.assertEqual(suffix, "pregamma_lut")
        self.assertTrue(filter_expr.startswith(r"eq=gamma=1.2,lut3d=file=C\\:/LUTs/ok.cube"))


if __name__ == "__main__":
    unittest.main()
