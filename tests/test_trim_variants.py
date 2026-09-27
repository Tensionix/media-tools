"""Rows of the trim panel, and the points of a split, as the engine reads them.

A row is not a piece of one timeline. Each filled row is a run of its own on the
same take - one piece kept, or one piece cut out - and writes a file of its own,
so rows may overlap as freely as two separate runs could. One filled row is the
run the panel always made, with no suffix: that is what keeps the old behaviour.
"""

from __future__ import annotations

import pytest

from system_core.core.trim_contract import TRIM_MAX_VARIANTS
from system_core.services.media_service import _trim_part_suffix, _trim_split_points, _trim_variants


def test_one_row_is_the_old_run_without_a_suffix() -> None:
    params = {"trim_action": "keep", "trim_start": "00:00:05,000", "trim_end": "00:00:09,000"}
    assert _trim_variants(params) == [("", params)]


def test_several_rows_are_named_by_their_number_on_screen() -> None:
    params = {
        "trim_action": "keep",
        "trim_start": "00:00:05,000",
        "trim_end": "00:00:09,000",
        # Row 2 left empty after a `+`: ignored, and row 3 keeps its own number.
        "trim_rows": [{"start": "", "end": ""}, {"start": "00:00:07,000", "end": "00:00:20,000"}],
    }
    variants = _trim_variants(params)
    assert [suffix for suffix, _params in variants] == ["keep01", "keep03"]
    # Overlapping rows stay what they are: two separate runs.
    assert variants[1][1]["trim_start"] == "00:00:07,000"
    assert variants[1][1]["trim_end"] == "00:00:20,000"


def test_a_cut_names_its_variants_as_cuts() -> None:
    params = {
        "trim_action": "cut",
        "trim_start": "00:00:05,000",
        "trim_end": "00:00:09,000",
        "trim_rows": [{"start": "00:00:02,000", "end": "00:00:12,000"}],
    }
    assert [suffix for suffix, _params in _trim_variants(params)] == ["cut01", "cut02"]


def test_a_single_filled_row_further_down_is_still_one_run() -> None:
    params = {"trim_action": "keep", "trim_start": "", "trim_end": "", "trim_rows": [{"start": "00:00:03,000", "end": ""}]}
    [(suffix, variant)] = _trim_variants(params)
    assert suffix == ""
    assert variant["trim_start"] == "00:00:03,000"
    assert variant["trim_end"] == ""


def test_rows_past_the_limit_are_refused_rather_than_dropped() -> None:
    rows = [{"start": f"{second}", "end": f"{second + 1}"} for second in range(1, TRIM_MAX_VARIANTS + 1)]
    params = {"trim_action": "keep", "trim_start": "0.5", "trim_end": "1", "trim_rows": rows}
    with pytest.raises(RuntimeError, match=f"at most {TRIM_MAX_VARIANTS}"):
        _trim_variants(params)


def test_split_points_come_from_the_list_and_fall_back_to_in_and_out() -> None:
    assert _trim_split_points({"trim_points": ["1", "", "5"], "trim_start": "9"}) == ["1", "5"]
    assert _trim_split_points({"trim_points": [""], "trim_start": "9", "trim_end": ""}) == ["9", ""]
    assert _trim_split_points({"trim_start": "9", "trim_end": "12"}) == ["9", "12"]


def test_parts_are_padded_only_when_there_are_ten_or_more() -> None:
    assert _trim_part_suffix(3, 3) == "part3"
    assert _trim_part_suffix(3, 12) == "part03"
    assert _trim_part_suffix(12, 12) == "part12"
