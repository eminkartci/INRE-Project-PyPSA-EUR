# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Apply historical Dunkelflaute profiles by direct p_max_pu assignment.

Modes:
- historical: bar{p}^{Historical}_{n,k,t} = CF^{event}_{n,k,t}
- matched_reference: bar{p}^{Ref}_{n,k,t} = CF^{median}_{n,k,t}
- extreme_sensitivity: baseline × f^{hist} with documented ratio transform

No synthetic edge ramp in historical or matched_reference modes.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa
import yaml

logger = logging.getLogger(__name__)

HISTORICAL_CARRIER_MAP = {
    "onwind": {"onwind"},
    "offwind-ac": {"offwind-ac"},
    "offwind-dc": {"offwind-dc"},
    "offwind-float": {"offwind-float"},
    "offwind": {"offwind-ac", "offwind-dc", "offwind-float"},
    "solar": {"solar"},
    "solar-hsat": {"solar-hsat"},
}


def load_params(config_path: str | Path | None, overrides: dict | None = None) -> dict:
    params: dict = {}
    if config_path:
        with open(config_path) as f:
            params = yaml.safe_load(f) or {}
    if overrides:
        params.update(overrides)
    return params


def _profile_dir(config_path: str | Path | None, params: dict) -> Path:
    raw = params.get("profile_dir", "profiles/historical")
    path = Path(raw)
    if path.is_absolute():
        return path
    if config_path:
        candidate = Path(config_path).parent / path
        if candidate.exists():
            return candidate
    repo = Path(__file__).resolve().parents[2]
    return repo / "data" / "inre" / path


def _load_profile_csv(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=True)
    if "timestamp" in df.columns:
        df = df.set_index("timestamp")
    else:
        df = df.set_index(df.columns[0])
    col = "cf" if "cf" in df.columns else "factor"
    series = df[col].astype(float)
    series.index = pd.DatetimeIndex(series.index).tz_localize(None)
    return series


def _align_to_snapshots(series: pd.Series, snapshots: pd.DatetimeIndex) -> pd.Series:
    snapshots_naive = snapshots.tz_localize(None) if snapshots.tz is not None else snapshots
    aligned = series.reindex(snapshots_naive, method="nearest")
    if aligned.isna().any():
        raise ValueError(
            f"Profile missing {int(aligned.isna().sum())} snapshots; "
            f"first gap: {snapshots_naive[aligned.isna()][0]}"
        )
    return pd.Series(aligned.values, index=snapshots)


def _bus_name_from_stem(stem: str, carrier_key: str) -> str:
    suffix = f"_{carrier_key}"
    if stem.endswith(suffix):
        return stem[: -len(suffix)]
    return stem.rsplit("_", 1)[0]


def load_cluster_carrier_profiles(
    profile_dir: Path, snapshots: pd.DatetimeIndex
) -> dict[tuple[str, str], pd.Series]:
    profiles: dict[tuple[str, str], pd.Series] = {}
    if not profile_dir.exists():
        raise FileNotFoundError(f"Historical profile directory not found: {profile_dir}")

    for path in sorted(profile_dir.glob("*_*.csv")):
        stem = path.stem
        matched_carrier = None
        for key in sorted(HISTORICAL_CARRIER_MAP, key=len, reverse=True):
            if stem.endswith(f"_{key}"):
                matched_carrier = key
                break
        if matched_carrier is None:
            logger.warning("Skipping unrecognized profile file: %s", path.name)
            continue
        bus = _bus_name_from_stem(stem, matched_carrier)
        series = _align_to_snapshots(_load_profile_csv(path), snapshots)
        profiles[(bus, matched_carrier)] = series
    if not profiles:
        raise FileNotFoundError(f"No cluster×carrier profiles in {profile_dir}")
    return profiles


def _generators_for_profile(
    n: pypsa.Network, bus: str, carrier_key: str
) -> list[str]:
    carriers = HISTORICAL_CARRIER_MAP[carrier_key]
    gens = n.generators.query("bus == @bus and carrier in @carriers")
    return [g for g in gens.index if g in n.generators_t.p_max_pu.columns]


def apply_direct_profiles(
    n: pypsa.Network,
    profiles: dict[tuple[str, str], pd.Series],
) -> None:
    """Overwrite p_max_pu with historical or matched-reference CF values."""
    applied = 0
    for (bus, carrier_key), series in profiles.items():
        cols = _generators_for_profile(n, bus, carrier_key)
        for col in cols:
            n.generators_t.p_max_pu[col] = series.values
            applied += 1
    logger.info("Applied direct CF profiles to %d generator columns", applied)


def apply_extreme_sensitivity(
    n: pypsa.Network,
    profiles: dict[tuple[str, str], pd.Series],
    params: dict,
    config_path: str | Path | None,
) -> None:
    """Anomaly-transfer: bar{p}_{g,t}^{new} = min(bar{p}_{g,t}^{base} * f_{g,t}, 1), clipped to [0, 1]."""
    ref_dir = params.get("reference_profile_dir", "profiles/historical/matched_reference")
    ref_path = Path(ref_dir)
    if not ref_path.is_absolute() and config_path:
        ref_path = Path(config_path).parent / ref_path
    if not ref_path.is_absolute():
        ref_path = Path(__file__).resolve().parents[2] / "data" / "inre" / ref_path

    epsilon = float(params.get("solar_denominator_epsilon", 0.02))
    ref_profiles = load_cluster_carrier_profiles(ref_path, pd.DatetimeIndex(n.snapshots))

    applied = 0
    for (bus, carrier_key), event_cf in profiles.items():
        ref_cf = ref_profiles.get((bus, carrier_key))
        if ref_cf is None:
            logger.warning("No reference profile for %s %s", bus, carrier_key)
            continue
        ratio = np.ones(len(event_cf))
        denom = ref_cf.values
        numer = event_cf.values
        valid = denom > epsilon
        ratio[valid] = numer[valid] / denom[valid]
        if carrier_key in ("solar", "solar-hsat"):
            ratio[~valid] = 1.0

        cols = _generators_for_profile(n, bus, carrier_key)
        for col in cols:
            base = n.generators_t.p_max_pu[col].values
            updated = np.clip(base * ratio, 0.0, 1.0)
            n.generators_t.p_max_pu[col] = updated
            applied += 1
    logger.info("Applied extreme sensitivity ratios to %d generator columns (clipped [0,1])", applied)


def validate_availability(
    n: pypsa.Network,
    output_path: str | Path | None = None,
) -> pd.DataFrame:
    """Export per-generator availability checks for V4 acceptance."""
    rows = []
    p_max = n.generators_t.p_max_pu
    snapshots = pd.DatetimeIndex(n.snapshots)
    for col in p_max.columns:
        gen = n.generators.loc[col]
        series = p_max[col]
        rows.append(
            {
                "generator": col,
                "bus": gen.bus,
                "carrier": gen.carrier,
                "n_snapshots": len(series),
                "min_p_max_pu": float(series.min()),
                "max_p_max_pu": float(series.max()),
                "n_negative": int((series < 0).sum()),
                "n_above_1": int((series > 1).sum()),
                "n_missing": int(series.isna().sum()),
                "night_mean_solar": (
                    float(series[snapshots.hour.isin(range(0, 6)) | snapshots.hour.isin(range(20, 24))].mean())
                    if "solar" in str(gen.carrier)
                    else float("nan")
                ),
            }
        )
    df = pd.DataFrame(rows)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        logger.info("Wrote availability validation to %s", path)
    return df


def apply_historical_dunkelflaute(
    n: pypsa.Network,
    params: dict | None = None,
    config_path: str | Path | None = None,
) -> pypsa.Network:
    params = params or load_params(config_path)
    if not params.get("enabled", True):
        return n

    mode = params.get("mode", "historical")
    snapshots = pd.DatetimeIndex(pd.to_datetime(n.snapshots))
    profile_dir = _profile_dir(config_path, params)
    profiles = load_cluster_carrier_profiles(profile_dir, snapshots)

    if mode in ("historical", "matched_reference", "historical_normal"):
        apply_direct_profiles(n, profiles)
    elif mode == "extreme_sensitivity":
        apply_extreme_sensitivity(n, profiles, params, config_path)
    else:
        raise ValueError(f"Unknown historical dunkelflaute mode: {mode}")

    validation_csv = params.get("availability_validation_csv")
    if validation_csv:
        validate_availability(n, validation_csv)

    logger.info("Historical Dunkelflaute mode=%s from %s", mode, profile_dir)
    return n
