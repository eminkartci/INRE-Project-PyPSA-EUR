# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""Unit tests for extreme-stress availability clipping (V4)."""

from __future__ import annotations

import pandas as pd
import pypsa

from scripts.inre.apply_historical_dunkelflaute import apply_extreme_sensitivity


def test_extreme_sensitivity_clips_to_unit_interval():
    snapshots = pd.date_range("2021-01-25", periods=4, freq="3h")
    n = pypsa.Network()
    n.set_snapshots(snapshots)
    n.add("Bus", "DE0 0")
    n.add("Carrier", "onwind")
    n.add("Generator", "g1", bus="DE0 0", carrier="onwind", p_nom=100.0)
    n.generators_t.p_max_pu = pd.DataFrame({"g1": [0.8, 0.9, 0.7, 0.6]}, index=snapshots)

    event = pd.Series([0.1, 2.0, -0.1, 0.5], index=snapshots)
    ref = pd.Series([0.2, 0.5, 0.5, 0.5], index=snapshots)
    profiles = {("DE0 0", "onwind"): event}

    import scripts.inre.apply_historical_dunkelflaute as mod

    original_loader = mod.load_cluster_carrier_profiles
    mod.load_cluster_carrier_profiles = lambda _path, _snap: {
        ("DE0 0", "onwind"): ref,
    }
    try:
        apply_extreme_sensitivity(n, profiles, {"solar_denominator_epsilon": 0.02}, None)
    finally:
        mod.load_cluster_carrier_profiles = original_loader

    values = n.generators_t.p_max_pu["g1"].values
    assert values.min() >= 0.0
    assert values.max() <= 1.0
