# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""Automated validation tests for stylised Dunkelflaute V4 profiles."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.inre.build_stylised_dunkelflaute_v4 import (  # noqa: E402
    VALIDATION_TOL,
    _scope_masks,
    validate_scope_masks,
)

PROFILE_DIR = REPO_ROOT / "data/inre/profiles/stylised_dunkelflaute_v4"
OUTPUT_DIR = REPO_ROOT / "output/stylised_dunkelflaute_v4"
BASE_NETWORK = REPO_ROOT / "results/base/networks/base_s_10_elec_.nc"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def profiles() -> dict[str, pd.DataFrame]:
    files = {
        "base": "matched_base_p_max_pu.csv",
        "moderate": "moderate_p_max_pu.csv",
        "severe": "severe_p_max_pu.csv",
        "extreme": "extreme_p_max_pu.csv",
    }
    out = {}
    for key, fname in files.items():
        df = pd.read_csv(PROFILE_DIR / fname, parse_dates=["timestamp"], index_col="timestamp")
        out[key] = df.astype(float)
    return out


@pytest.fixture(scope="module")
def metadata() -> dict:
    import yaml

    with open(PROFILE_DIR / "metadata.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def scope_masks(metadata) -> dict[str, pd.Series]:
    idx = pd.read_csv(
        PROFILE_DIR / "matched_base_p_max_pu.csv", parse_dates=["timestamp"], index_col="timestamp"
    ).index
    return _scope_masks(
        idx,
        pd.Timestamp(metadata["core_start"]),
        int(metadata["core_days"]),
        int(metadata["buffer_days_each_side"]),
        float(metadata["transition_hours"]),
        float(metadata["snapshot_hours"]),
    )


def test_all_intervals_equal_snapshot_hours(profiles, metadata):
    idx = profiles["base"].index
    diffs = idx.to_series().diff().dropna()
    expected = pd.Timedelta(hours=float(metadata["snapshot_hours"]))
    assert (diffs == expected).all()


def test_phase_snapshot_counts(scope_masks):
    counts = validate_scope_masks(scope_masks, 3.0)
    assert counts["full-window"] == 224
    assert counts["core"] == 112
    assert counts["pre-buffer"] == 56
    assert counts["transition-in"] == 16
    assert counts["plateau"] == 80
    assert counts["transition-out"] == 16
    assert counts["post-buffer"] == 56
    assert 56 + 16 + 80 + 16 + 56 == 224
    assert 16 + 80 + 16 == 112


def test_no_duplicate_subphase_assignment(scope_masks):
    sub = (
        scope_masks["pre-buffer"].astype(int)
        + scope_masks["transition-in"].astype(int)
        + scope_masks["plateau"].astype(int)
        + scope_masks["transition-out"].astype(int)
        + scope_masks["post-buffer"].astype(int)
    )
    assert (sub <= 1).all()
    assert (sub == 1).all()


def test_no_unclassified_snapshots(scope_masks):
    sub = (
        scope_masks["pre-buffer"]
        | scope_masks["transition-in"]
        | scope_masks["plateau"]
        | scope_masks["transition-out"]
        | scope_masks["post-buffer"]
    )
    assert sub.all()


def test_column_alignment(profiles):
    cols = list(profiles["base"].columns)
    for key in ("moderate", "severe", "extreme"):
        assert list(profiles[key].columns) == cols


def test_no_nan_or_inf(profiles):
    for key, df in profiles.items():
        assert np.isfinite(df.values).all()
        assert not df.isna().any().any()


def test_bounds(profiles):
    for df in profiles.values():
        assert (df.values >= 0).all()
        assert (df.values <= 1).all()


def test_scenario_ordering(profiles):
    b = profiles["base"].values
    assert np.all(profiles["extreme"].values <= profiles["severe"].values + VALIDATION_TOL)
    assert np.all(profiles["severe"].values <= profiles["moderate"].values + VALIDATION_TOL)
    assert np.all(profiles["moderate"].values <= b + VALIDATION_TOL)


def test_buffer_equality(profiles, metadata):
    core_start = pd.Timestamp(metadata["core_start"])
    core_end = pd.Timestamp(metadata["core_end"])
    idx = profiles["base"].index
    core_mask = (idx >= core_start) & (idx <= core_end)
    outside = ~core_mask
    for key in ("moderate", "severe", "extreme"):
        assert np.allclose(profiles[key].loc[outside], profiles["base"].loc[outside], atol=VALIDATION_TOL)


def test_plateau_ratios(profiles, metadata, scope_masks):
    ratios = metadata["severity_assumptions"]["severe"]
    plateau_mask = scope_masks["plateau"]
    onwind_cols = [c for c in profiles["base"].columns if c.endswith(" onwind")]
    for col in onwind_cols[:3]:
        base_v = profiles["base"].loc[plateau_mask, col]
        scen_v = profiles["severe"].loc[plateau_mask, col]
        mask = base_v > 1e-6
        if mask.any():
            assert np.allclose(scen_v[mask] / base_v[mask], ratios["onshore"], rtol=1e-4, atol=1e-4)


def test_solar_night_preservation(profiles):
    solar_cols = [c for c in profiles["base"].columns if "solar" in c]
    for col in solar_cols:
        zero = profiles["base"][col].values == 0
        for key in ("moderate", "severe", "extreme"):
            assert np.allclose(profiles[key][col].values[zero], 0.0, atol=VALIDATION_TOL)


def test_cutout_comparison_exported():
    path = OUTPUT_DIR / "cutout_base_comparison.csv"
    assert path.exists()
    df = pd.read_csv(path)
    assert "pre_overwrite_max_diff" in df.columns
    assert "post_overwrite_max_diff" in df.columns
    assert (df["post_overwrite_max_diff"] < 1e-10).all()


def test_pre_overwrite_diff_not_zero_globally():
    df = pd.read_csv(OUTPUT_DIR / "cutout_base_comparison.csv")
    assert df["pre_overwrite_max_diff"].max() > 0


def test_stitch_diagnostics_exported():
    path = OUTPUT_DIR / "profile_stitch_validation.csv"
    assert path.exists()
    df = pd.read_csv(path)
    assert {"entry_jump", "exit_jump", "maximum_jump"}.issubset(df.columns)


def test_demand_unit_validation():
    path = OUTPUT_DIR / "demand_unit_validation.csv"
    assert path.exists()
    df = pd.read_csv(path)
    row = df.iloc[0]
    assert row["source_unit"] == "MW"
    assert row["converted_unit"] == "GW"
    assert row["status"] == "ok"
    assert row["missing_timestamps"] == 0
    assert row["snapshot_count"] == 224


def test_base_network_immutability(metadata):
    assert BASE_NETWORK.exists()
    assert _sha256(BASE_NETWORK) == metadata["source_base_checksum_sha256"]


def test_v2_v3_paths_untouched():
    assert (REPO_ROOT / "data/inre/profiles/dunkelflaute_wind_factors.csv").exists()
    assert (REPO_ROOT / "data/inre/profiles/historical").exists()


def test_validation_csv_all_passed():
    path = OUTPUT_DIR / "validation_tests.csv"
    assert path.exists()
    df = pd.read_csv(path)
    assert "tolerance" in df.columns
    assert df["passed"].all()


def test_network_audit_exports():
    for name in (
        "network_timeseries_validation.csv",
        "scenario_difference_audit.csv",
        "fixed_capacity_validation.csv",
    ):
        assert (OUTPUT_DIR / name).exists()
