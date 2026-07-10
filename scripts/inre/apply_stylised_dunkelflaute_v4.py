# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Apply a stylised Dunkelflaute V4 absolute p_max_pu profile to a Base network.

Replaces only renewable generator availability columns; leaves demand, capacities,
fossil fleet, storage and transmission unchanged. Never overwrites the source network.

Usage::

    python scripts/inre/apply_stylised_dunkelflaute_v4.py \\
        --network results/base/networks/base_s_10_elec_.nc \\
        --profile data/inre/profiles/stylised_dunkelflaute_v4/severe_p_max_pu.csv \\
        --output-network results/stylised-df-severe-v4/networks/base_s_10_elec_.nc
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import pypsa

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.inre.freeze_transmission import freeze_transmission
from scripts.inre.resolve_fixedcap import _fix_component_capacity

logger = logging.getLogger(__name__)

RENEWABLE_CARRIERS = {
    "onwind",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
    "solar",
    "solar-hsat",
}


def load_profile_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    return df.astype(float)


def apply_profile_to_network(
    n: pypsa.Network,
    profile: pd.DataFrame,
    rtol: float = 1e-9,
) -> list[str]:
    snapshots = pd.DatetimeIndex(n.snapshots).tz_localize(None)
    profile_snaps = pd.DatetimeIndex(profile.index).tz_localize(None)
    if not snapshots.equals(profile_snaps):
        raise ValueError(
            "Profile timestamps do not exactly match network snapshots: "
            f"network={snapshots[0]}..{snapshots[-1]} ({len(snapshots)}), "
            f"profile={profile_snaps[0]}..{profile_snaps[-1]} ({len(profile_snaps)})"
        )

    ren_gens = list(n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)].index)
    missing_gens = set(ren_gens) - set(profile.columns)
    if missing_gens:
        raise ValueError(f"Profile missing renewable generators: {sorted(missing_gens)[:5]}")

    non_ren_in_profile = set(profile.columns) - set(ren_gens)
    if non_ren_in_profile:
        raise ValueError(f"Profile contains non-renewable generators: {sorted(non_ren_in_profile)[:5]}")

    for col in ren_gens:
        if col not in n.generators_t.p_max_pu.columns:
            raise ValueError(f"Generator {col} not in network p_max_pu")
        n.generators_t.p_max_pu[col] = profile[col].values

    logger.info("Applied stylised V4 profile to %d renewable generators", len(ren_gens))
    return ren_gens


def _snapshot_hours(profile: pd.DataFrame) -> float:
    diffs = pd.DatetimeIndex(profile.index).to_series().diff().dropna()
    if diffs.empty:
        raise ValueError("Profile has fewer than two timestamps")
    expected = diffs.iloc[0]
    if not (diffs == expected).all():
        raise ValueError("Irregular profile snapshot spacing")
    return expected.total_seconds() / 3600.0


def _infer_demand_unit(series: pd.Series) -> str:
    med = float(series.dropna().median())
    return "MW" if med > 500 else "GW"


def freeze_fixed_capacity_operation(n: pypsa.Network) -> None:
    """Stage-1 operational stress: no capacity expansion on any component."""
    _fix_component_capacity(
        n,
        fix_generator_carriers=set(n.generators.carrier.unique()),
        fix_all_components=True,
    )
    if len(n.stores):
        n.stores["e_nom_extendable"] = False
        if "e_nom_opt" in n.stores.columns:
            n.stores["e_nom_opt"] = n.stores["e_nom"]
    freeze_transmission(n)


def _load_national_demand_mw(
    demand_csv: Path,
    timestamps: pd.DatetimeIndex,
    snapshot_hours: float,
) -> pd.Series:
    """Load ENTSO-E DE demand, resample to snapshot grid, return national total in MW."""
    if not demand_csv.exists():
        raise FileNotFoundError(f"Demand CSV not found: {demand_csv}")

    df = pd.read_csv(demand_csv, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    if df.index.duplicated().any():
        raise ValueError(f"Duplicated timestamps in demand file: {demand_csv}")
    if "DE" not in df.columns:
        raise ValueError(f"Column DE not in {demand_csv}")

    hourly = df["DE"].astype(float)
    unit = _infer_demand_unit(hourly)
    hourly_mw = hourly if unit == "MW" else hourly * 1000.0

    freq = f"{int(snapshot_hours)}h"
    resampled = hourly_mw.resample(freq).mean()
    aligned = resampled.reindex(timestamps)
    missing = aligned.isna()
    if missing.any():
        raise ValueError(
            f"Missing ENTSO-E demand for {int(missing.sum())} snapshots "
            f"(first gap: {timestamps[missing][0]})"
        )
    return aligned


def _cluster_load_shares(loads: pd.DataFrame) -> pd.Series:
    """Normalised spatial shares per load bus (constant across the window)."""
    totals = loads.sum(axis=0).astype(float)
    if float(totals.sum()) <= 0:
        raise ValueError("Cannot derive load shares from zero total demand")
    return totals / float(totals.sum())


def _extend_snapshots_and_demand(n: pypsa.Network, profile: pd.DataFrame, demand_csv: Path | None) -> None:
    profile_snaps = pd.DatetimeIndex(profile.index).tz_localize(None)
    network_snaps = pd.DatetimeIndex(n.snapshots).tz_localize(None)
    if network_snaps.equals(profile_snaps):
        return

    logger.info("Extending network snapshots from %d to %d", len(network_snaps), len(profile_snaps))
    old_p_max = n.generators_t.p_max_pu.copy()
    old_loads = n.loads_t.p_set.copy() if not n.loads_t.p_set.empty else None

    n.set_snapshots(profile_snaps)
    snap_h = _snapshot_hours(profile)
    if hasattr(n, "snapshot_weightings"):
        n.snapshot_weightings["objective"] = snap_h
        if "generators" in n.snapshot_weightings.columns:
            n.snapshot_weightings["generators"] = snap_h
        if "stores" in n.snapshot_weightings.columns:
            n.snapshot_weightings["stores"] = snap_h

    n.generators_t.p_max_pu = pd.DataFrame(index=profile_snaps, columns=old_p_max.columns, dtype=float)
    overlap = profile_snaps.intersection(network_snaps)
    n.generators_t.p_max_pu.loc[overlap] = old_p_max.loc[overlap].values
    for col in old_p_max.columns:
        const = float(n.generators.at[col, "p_max_pu"]) if col in n.generators.index else 1.0
        missing = profile_snaps.difference(network_snaps)
        n.generators_t.p_max_pu.loc[missing, col] = const

    if old_loads is None:
        return

    load_cols = list(old_loads.columns)
    if not demand_csv or not demand_csv.exists():
        raise ValueError(
            "Profile extends beyond Base network snapshots; provide --demand-csv for buffer demand"
        )

    national_mw = _load_national_demand_mw(demand_csv, profile_snaps, snap_h)
    shares = _cluster_load_shares(old_loads.loc[overlap])

    n.loads_t.p_set = pd.DataFrame(index=profile_snaps, columns=load_cols, dtype=float)
    for col in load_cols:
        n.loads_t.p_set[col] = national_mw.values * float(shares[col])

    # Preserve exact Base-network core demand (authoritative 14-day window).
    n.loads_t.p_set.loc[overlap] = old_loads.loc[overlap].values

    if n.loads_t.p_set.isna().any().any():
        raise ValueError("NaN values in loads_t.p_set after buffer demand population")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply stylised Dunkelflaute V4 profile to network")
    parser.add_argument("--network", required=True, help="Source Base network (read-only)")
    parser.add_argument("--profile", required=True, help="Absolute p_max_pu CSV")
    parser.add_argument("--output-network", required=True, help="Output path (must differ from --network)")
    parser.add_argument(
        "--demand-csv",
        default="data/entsoe_electricity_demand/archive/2026-02-02/electricity_demand_entsoe_raw.csv",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    src = Path(args.network)
    if not src.is_absolute():
        src = REPO_ROOT / src
    out = Path(args.output_network)
    if not out.is_absolute():
        out = REPO_ROOT / out
    profile_path = Path(args.profile)
    if not profile_path.is_absolute():
        profile_path = REPO_ROOT / profile_path

    if src.resolve() == out.resolve():
        raise ValueError("Refusing to overwrite source Base network")

    if not src.exists():
        raise FileNotFoundError(src)
    if not profile_path.exists():
        raise FileNotFoundError(profile_path)

    n = pypsa.Network(str(src))
    profile = load_profile_csv(profile_path)
    demand_path = Path(args.demand_csv)
    if not demand_path.is_absolute():
        demand_path = REPO_ROOT / demand_path
    _extend_snapshots_and_demand(n, profile, demand_path)
    apply_profile_to_network(n, profile)
    freeze_fixed_capacity_operation(n)

    out.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(out))
    logger.info("Wrote %s", out)


if __name__ == "__main__":
    main()
