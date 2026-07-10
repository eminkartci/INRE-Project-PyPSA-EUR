# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""Unit tests for historical event overlap grouping (V4)."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.inre.historical_event_selection import (
    HOURS_EVENT,
    OVERLAP_THRESHOLD,
    flag_overlaps,
    select_top_independent,
)


def _window(start: str, i_tau: float) -> dict:
    start_ts = pd.Timestamp(start)
    end_ts = start_ts + pd.Timedelta(hours=HOURS_EVENT - 1)
    return {
        "start": start_ts,
        "end": end_ts,
        "i_tau": i_tau,
        "year": start_ts.year,
    }


def test_flag_overlaps_marks_one_primary_per_group():
    # Three windows: A and B overlap strongly; C is independent
    rows = [
        _window("2020-01-10 00:00:00", 0.90),
        _window("2020-01-10 12:00:00", 0.85),
        _window("2020-03-01 00:00:00", 0.80),
    ]
    df = pd.DataFrame(rows)
    flagged = flag_overlaps(df, threshold=OVERLAP_THRESHOLD)

    assert flagged["is_primary_independent"].sum() == 2
    group_ab = flagged.loc[flagged["start"] == pd.Timestamp("2020-01-10 00:00:00"), "overlap_group"].iloc[0]
    assert (
        flagged.loc[flagged["overlap_group"] == group_ab, "is_primary_independent"].sum() == 1
    )
    best_ab = flagged[flagged["overlap_group"] == group_ab].sort_values("i_tau", ascending=False).iloc[0]
    assert best_ab["start"] == pd.Timestamp("2020-01-10 00:00:00")


def test_select_top_independent_returns_non_overlapping_set():
    rows = [
        _window("2020-01-10 00:00:00", 0.92),
        _window("2020-01-10 06:00:00", 0.91),
        _window("2020-02-01 00:00:00", 0.88),
        _window("2020-03-15 00:00:00", 0.86),
        _window("2020-04-20 00:00:00", 0.84),
    ]
    df = pd.DataFrame(rows)
    top = select_top_independent(df, top_n=3)

    assert len(top) == 3
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            overlap = min(top.iloc[i]["end"], top.iloc[j]["end"]) - max(
                top.iloc[i]["start"], top.iloc[j]["start"]
            )
            frac = overlap / pd.Timedelta(hours=HOURS_EVENT) if overlap.total_seconds() > 0 else 0.0
            assert frac < OVERLAP_THRESHOLD


def test_all_shifted_windows_share_one_group_with_single_primary():
    rows = [_window(f"2021-01-25 {h:02d}:00:00", 0.9 - h * 0.001) for h in range(6)]
    flagged = flag_overlaps(pd.DataFrame(rows))
    assert flagged["overlap_group"].nunique() == 1
    assert flagged["is_primary_independent"].sum() == 1
