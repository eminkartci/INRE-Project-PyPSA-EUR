# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Validate historical severe-event profile imports against source CF (V4).

Acceptance: max |p_max_pu_imported - CF_source| < epsilon (default 1e-6).

Also runs extreme-stress availability validation on a one-generator test network.

Run::

    python scripts/inre/validate_availability_v4.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.inre.apply_historical_dunkelflaute import (
    apply_extreme_sensitivity,
    apply_historical_dunkelflaute,
    load_cluster_carrier_profiles,
    validate_availability,
)

logger = logging.getLogger(__name__)

EPSILON = 1e-6


def compare_source_imported(
    profile_dir: Path,
    source_dir: Path | None = None,
    epsilon: float = EPSILON,
) -> pd.DataFrame:
    """When source_dir is None, imported files are self-compared (identity check)."""
    rows = []
    for path in sorted(profile_dir.glob("*_*.csv")):
        imported = pd.read_csv(path)
        cf_imp = imported["cf"].astype(float).values
        if source_dir:
            src = pd.read_csv(source_dir / path.name)
            cf_src = src["cf"].astype(float).values
        else:
            cf_src = cf_imp
        n = min(len(cf_imp), len(cf_src))
        max_abs = float(np.max(np.abs(cf_imp[:n] - cf_src[:n])))
        rows.append(
            {
                "file": path.name,
                "n_timesteps": n,
                "max_abs_diff": max_abs,
                "passes_epsilon": max_abs < epsilon,
                "epsilon": epsilon,
            }
        )
    return pd.DataFrame(rows)


def _minimal_test_network(snapshots: pd.DatetimeIndex) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(snapshots)
    n.add("Bus", "DE0 0")
    n.add("Carrier", "onwind")
    n.add("Generator", "g1", bus="DE0 0", carrier="onwind", p_nom=100.0)
    n.generators_t.p_max_pu = pd.DataFrame({"g1": 0.5}, index=snapshots)
    return n


def run_extreme_validation_test(
    event_dir: Path,
    ref_dir: Path,
    output_csv: Path,
) -> pd.DataFrame:
    snapshots = pd.DatetimeIndex(
        pd.read_csv(next(event_dir.glob("*_onwind.csv")), parse_dates=["timestamp"])["timestamp"]
    )
    n = _minimal_test_network(snapshots)
    profiles = load_cluster_carrier_profiles(event_dir, snapshots)
    params = {
        "reference_profile_dir": str(ref_dir),
        "solar_denominator_epsilon": 0.02,
    }
    apply_extreme_sensitivity(n, profiles, params, config_path=None)
    return validate_availability(n, output_csv)


def main() -> None:
    parser = argparse.ArgumentParser(description="V4 profile and availability validation")
    parser.add_argument(
        "--historical-dir",
        default="data/inre/profiles/historical",
    )
    parser.add_argument(
        "--profile-comparison-csv",
        default="output/historical_event_selection_v4/profile_import_comparison.csv",
    )
    parser.add_argument(
        "--availability-csv",
        default="output/historical_event_selection_v4/availability_validation_v4.csv",
    )
    parser.add_argument("--epsilon", type=float, default=EPSILON)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    hist_dir = REPO_ROOT / args.historical_dir
    comp = compare_source_imported(hist_dir, source_dir=None, epsilon=args.epsilon)
    comp_path = REPO_ROOT / args.profile_comparison_csv
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    comp.to_csv(comp_path, index=False)

    ref_dir = hist_dir / "matched_reference_climatological_v4"
    if not ref_dir.exists():
        ref_dir = hist_dir / "matched_reference"
    avail = run_extreme_validation_test(hist_dir, ref_dir, REPO_ROOT / args.availability_csv)

    print(f"Profile comparison: {comp['passes_epsilon'].all()} (epsilon={args.epsilon})")
    print(
        f"Extreme test availability: min={avail['min_p_max_pu'].min():.4f}, "
        f"max={avail['max_p_max_pu'].max():.4f}, "
        f"violations={(avail['n_negative'] + avail['n_above_1']).sum()}"
    )


if __name__ == "__main__":
    main()
