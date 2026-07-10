# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Build deterministic stylised Dunkelflaute V4 renewable availability profiles.

Uses Base network p_max_pu for the 14-day core and local Atlite cutout (buffer days)
to assemble a 28-day matched Base profile, then applies raised-cosine stress envelopes.

Run with the pypsa-eur environment (atlite required)::

    python scripts/inre/build_stylised_dunkelflaute_v4.py
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa
import xarray as xr
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._helpers import load_cutout

logger = logging.getLogger(__name__)

RENEWABLE_CARRIERS = [
    "onwind",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
    "solar",
    "solar-hsat",
]

CARRIER_TO_GROUP = {
    "onwind": "onshore",
    "offwind-ac": "offshore",
    "offwind-dc": "offshore",
    "offwind-float": "offshore",
    "solar": "solar",
    "solar-hsat": "solar",
}

SEVERITY_ASSUMPTIONS = {
    "moderate": {"onshore": 0.35, "offshore": 0.40, "solar": 0.30},
    "severe": {"onshore": 0.20, "offshore": 0.25, "solar": 0.15},
    "extreme": {"onshore": 0.10, "offshore": 0.15, "solar": 0.10},
}

OVERLAP_EPSILON = 1e-4
VALIDATION_TOL = 1e-10
PLATEAU_RATIO_THRESHOLD = 1e-6


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_base_network(network_path: Path) -> tuple[pypsa.Network, str]:
    if not network_path.exists():
        raise FileNotFoundError(f"Base network not found: {network_path}")
    checksum = sha256_file(network_path)
    n = pypsa.Network(str(network_path))
    return n, checksum


def renewable_generators(n: pypsa.Network) -> pd.DataFrame:
    gens = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)].copy()
    if gens.empty:
        raise ValueError("No renewable generators found in Base network")
    missing = set(gens.index) - set(n.generators_t.p_max_pu.columns)
    if missing:
        raise ValueError(f"Missing p_max_pu columns for generators: {sorted(missing)[:5]}")
    return gens


def build_full_window_timestamps(
    core_start: pd.Timestamp,
    core_days: int,
    buffer_days: int,
    snapshot_hours: float,
) -> pd.DatetimeIndex:
    sim_start = core_start - pd.Timedelta(days=buffer_days)
    total_days = 2 * buffer_days + core_days
    n_snaps = int(total_days * 24 / snapshot_hours)
    freq = f"{int(snapshot_hours)}h"
    snaps = pd.date_range(sim_start, periods=n_snaps, freq=freq)
    return pd.DatetimeIndex(snaps)


def validate_time_index(
    timestamps: pd.DatetimeIndex,
    snapshot_hours: float,
    expected_count: int | None = None,
    expected_start: pd.Timestamp | None = None,
    expected_end: pd.Timestamp | None = None,
) -> None:
    if timestamps.duplicated().any():
        raise ValueError("Timestamps are not unique")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("Timestamps are not sorted")
    if len(timestamps) < 2:
        raise ValueError("Need at least two timestamps")
    diffs = timestamps.to_series().diff().dropna()
    expected_delta = pd.Timedelta(hours=snapshot_hours)
    if not (diffs == expected_delta).all():
        bad = diffs[diffs != expected_delta]
        raise ValueError(
            f"Irregular or missing timestamps detected; first bad interval at {bad.index[0]}: {bad.iloc[0]}"
        )
    if expected_count is not None and len(timestamps) != expected_count:
        raise ValueError(f"Expected {expected_count} snapshots, got {len(timestamps)}")
    if expected_start is not None and timestamps[0] != expected_start:
        raise ValueError(f"Expected start {expected_start}, got {timestamps[0]}")
    if expected_end is not None and timestamps[-1] != expected_end:
        raise ValueError(f"Expected end {expected_end}, got {timestamps[-1]}")


def extract_renewable_profiles(n: pypsa.Network) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (p_base DataFrame indexed by snapshots, generator metadata)."""
    gens = renewable_generators(n)
    cols = list(gens.index)
    p_base = n.generators_t.p_max_pu[cols].copy()
    meta = gens[["bus", "carrier", "p_nom"]].copy()
    meta["carrier_group"] = meta["carrier"].map(CARRIER_TO_GROUP)
    return p_base, meta


def _renewable_resource(tech: str, config_path: Path) -> tuple[dict, str, float, float]:
    cfg = yaml.safe_load(config_path.read_text())
    params = cfg["renewable"][tech]
    resource = dict(params["resource"])
    for key in ("turbine", "panel"):
        if key in resource and isinstance(resource[key], dict):
            resource[key] = list(resource[key].values())[0]
    method = resource.pop("method")
    return resource, method, float(params["capacity_per_sqkm"]), float(params.get("correction_factor", 1.0))


def _compute_cutout_profiles(
    tech: str,
    hourly_index: pd.DatetimeIndex,
    cutout_path: Path,
    clusters: int = 10,
) -> xr.DataArray:
    config_path = REPO_ROOT / "config/config.default.yaml"
    resource, method, capacity_per_sqkm, correction_factor = _renewable_resource(tech, config_path)
    availability_path = REPO_ROOT / f"resources/availability_matrix_{clusters}_{tech}.nc"
    if not availability_path.exists():
        raise FileNotFoundError(f"Missing availability matrix: {availability_path}")
    if not cutout_path.exists():
        raise FileNotFoundError(f"Missing cutout: {cutout_path}")

    cutout = load_cutout(str(cutout_path), time=hourly_index)
    availability = xr.open_dataarray(availability_path)
    if "bin" not in availability.dims:
        availability = availability.expand_dims(bin=[0])

    area = cutout.grid.to_crs(3035).area / 1e6
    area = xr.DataArray(area.values.reshape(cutout.shape), [cutout.coords["y"], cutout.coords["x"]])
    func = getattr(cutout, method)
    capacity_factor = correction_factor * func(capacity_factor=True, **resource)
    layout = capacity_factor * area * capacity_per_sqkm
    class_masks = xr.ones_like(availability).astype(bool)
    matrix = (availability * class_masks).stack(bus_bin=["bus", "bin"], spatial=["y", "x"])
    profile = func(
        matrix=matrix,
        layout=layout,
        index=matrix.indexes["bus_bin"],
        per_unit=True,
        return_capacity=False,
        **resource,
    )
    return profile.unstack("bus_bin").clip(min=0.0, max=1.0)


def _parse_generator_name(name: str) -> tuple[str, int, str]:
    for carrier in sorted(RENEWABLE_CARRIERS, key=len, reverse=True):
        suffix = f" {carrier}"
        if name.endswith(suffix):
            rest = name[: -len(suffix)]
            bus, bin_str = rest.rsplit(" ", 1)
            return bus, int(bin_str), carrier
    raise ValueError(f"Cannot parse generator name: {name}")


def extend_profiles_to_28day(
    n: pypsa.Network,
    p_base_core: pd.DataFrame,
    full_timestamps: pd.DatetimeIndex,
    core_timestamps: pd.DatetimeIndex,
    cutout_path: Path,
    snapshot_hours: float,
    meta: pd.DataFrame,
    summary_dir: Path,
) -> tuple[pd.DataFrame, dict]:
    """
    Assemble matched 28-day profiles: cutout for full window at 3h, overwrite core with Base.
    """
    gens = renewable_generators(n)
    hourly_index = pd.date_range(
        full_timestamps[0],
        full_timestamps[-1] + pd.Timedelta(hours=snapshot_hours - 0.001),
        freq="h",
    )

    frames: dict[str, pd.Series] = {}
    for carrier in RENEWABLE_CARRIERS:
        carrier_gens = gens[gens.carrier == carrier]
        if carrier_gens.empty:
            continue
        logger.info("Computing cutout profiles for %s (%d generators)", carrier, len(carrier_gens))
        prof = _compute_cutout_profiles(carrier, hourly_index, cutout_path)
        for gen in carrier_gens.index:
            bus, bin_id, _ = _parse_generator_name(gen)
            try:
                hourly = prof.sel(bus=bus, bin=bin_id).to_series()
            except Exception as exc:
                raise ValueError(f"Cannot locate cutout profile for generator {gen}") from exc
            series_3h = hourly.resample(f"{int(snapshot_hours)}h").mean()
            aligned = series_3h.reindex(full_timestamps)
            if aligned.isna().any():
                raise ValueError(f"Missing cutout timestamps for generator {gen}")
            frames[gen] = aligned.astype(float)

    generated_columns = set(frames.keys())
    required_columns = set(p_base_core.columns)
    missing = required_columns - generated_columns
    unexpected = generated_columns - required_columns
    if missing:
        raise ValueError(f"Cutout assembly missing generators: {sorted(missing)}")
    if unexpected:
        logger.warning("Cutout assembly produced unexpected generators: %s", sorted(unexpected)[:5])

    p_full = pd.DataFrame(frames)
    p_full = p_full.reindex(columns=list(p_base_core.columns))

    if p_full.isna().any().any():
        raise ValueError("NaN values in cutout-assembled profiles before core overwrite")
    if not np.isfinite(p_full.values).all():
        raise ValueError("Non-finite values in cutout-assembled profiles before core overwrite")
    if p_full.columns.duplicated().any():
        raise ValueError("Duplicated generator columns in cutout assembly")

    core_mask = full_timestamps.isin(core_timestamps)
    comparison_rows = []
    pre_max_vals: list[float] = []
    pre_mean_vals: list[float] = []

    for col in p_base_core.columns:
        cutout_core = p_full.loc[core_mask, col].copy()
        base_core = p_base_core.loc[core_timestamps, col].copy()
        pre_diff = np.abs(cutout_core.values - base_core.values)
        pre_max = float(np.max(pre_diff))
        pre_mean = float(np.mean(pre_diff))
        pre_max_vals.append(pre_max)
        pre_mean_vals.append(pre_mean)

        p_full.loc[core_mask, col] = base_core.values

        post_diff = np.abs(p_full.loc[core_mask, col].values - base_core.values)
        post_max = float(np.max(post_diff))

        warn = ""
        if pre_max > OVERLAP_EPSILON:
            warn = "cutout_core_differs_from_base"
        if post_max >= VALIDATION_TOL:
            raise ValueError(
                f"Post-overwrite core mismatch for {col}: max diff {post_max:.2e} >= {VALIDATION_TOL}"
            )

        comparison_rows.append(
            {
                "generator": col,
                "carrier": meta.at[col, "carrier"],
                "bus": meta.at[col, "bus"],
                "pre_overwrite_max_diff": pre_max,
                "pre_overwrite_mean_abs_diff": pre_mean,
                "post_overwrite_max_diff": post_max,
                "warning": warn,
            }
        )

    summary_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(comparison_rows).to_csv(summary_dir / "cutout_base_comparison.csv", index=False)

    overlap_info = {
        "pre_overwrite_global_max_diff": max(pre_max_vals) if pre_max_vals else 0.0,
        "pre_overwrite_global_mean_abs_diff": float(np.mean(pre_mean_vals)) if pre_mean_vals else 0.0,
        "post_overwrite_global_max_diff": 0.0,
        "per_generator": comparison_rows,
    }
    logger.info(
        "Cutout/Base core comparison: pre max=%.4f, pre mean=%.4f, post max=%.2e",
        overlap_info["pre_overwrite_global_max_diff"],
        overlap_info["pre_overwrite_global_mean_abs_diff"],
        overlap_info["post_overwrite_global_max_diff"],
    )
    return p_full, overlap_info


def build_stress_envelope(
    timestamps: pd.DatetimeIndex,
    core_start: pd.Timestamp,
    core_days: int,
    transition_hours: float,
    snapshot_hours: float,
) -> pd.Series:
    core_end = core_start + pd.Timedelta(days=core_days) - pd.Timedelta(hours=snapshot_hours)
    core_hours = core_days * 24.0
    plateau_hours = core_hours - 2 * transition_hours
    if plateau_hours <= 0:
        raise ValueError("Core too short for transition periods")

    s_values = []
    for ts in timestamps:
        if ts < core_start or ts > core_end:
            s_values.append(0.0)
            continue
        elapsed_h = (ts - core_start).total_seconds() / 3600.0
        if elapsed_h < transition_hours:
            s = 0.5 * (1.0 - np.cos(np.pi * elapsed_h / transition_hours))
        elif elapsed_h >= core_hours - transition_hours:
            t0 = core_hours - transition_hours
            s = 0.5 * (1.0 + np.cos(np.pi * (elapsed_h - t0) / transition_hours))
        else:
            s = 1.0
        s_values.append(float(np.clip(s, 0.0, 1.0)))
    return pd.Series(s_values, index=timestamps, name="stress_intensity")


def map_carrier_group(carrier: str) -> str:
    if carrier not in CARRIER_TO_GROUP:
        raise ValueError(f"Unknown carrier: {carrier}")
    return CARRIER_TO_GROUP[carrier]


def apply_derating(
    p_base: pd.DataFrame,
    meta: pd.DataFrame,
    stress: pd.Series,
    remaining_ratios: dict[str, float],
) -> pd.DataFrame:
    out = p_base.copy()
    for gen in out.columns:
        group = map_carrier_group(meta.at[gen, "carrier"])
        r_k = remaining_ratios[group]
        m = 1.0 - stress * (1.0 - r_k)
        out[gen] = (p_base[gen] * m).clip(lower=0.0)
        out[gen] = np.minimum(out[gen], p_base[gen])
    return out


def aggregate_capacity_weighted_profiles(
    profiles: pd.DataFrame,
    meta: pd.DataFrame,
    carrier: str | None = None,
    carrier_group: str | None = None,
) -> pd.Series:
    if carrier is not None:
        gens = meta.index[meta["carrier"] == carrier]
    elif carrier_group is not None:
        gens = meta.index[meta["carrier_group"] == carrier_group]
    else:
        raise ValueError("Specify carrier or carrier_group")
    gens = [g for g in gens if g in profiles.columns]
    if not gens:
        raise ValueError(f"No generators for aggregation: carrier={carrier}, group={carrier_group}")
    caps = meta.loc[gens, "p_nom"].astype(float)
    weighted = profiles[gens].multiply(caps, axis=1).sum(axis=1) / caps.sum()
    return weighted


def _scope_masks(
    timestamps: pd.DatetimeIndex,
    core_start: pd.Timestamp,
    core_days: int,
    buffer_days: int,
    transition_hours: float,
    snapshot_hours: float,
) -> dict[str, pd.Series]:
    sim_start = timestamps[0]
    pre_end = core_start - pd.Timedelta(hours=snapshot_hours)
    core_end = core_start + pd.Timedelta(days=core_days) - pd.Timedelta(hours=snapshot_hours)
    post_start = core_end + pd.Timedelta(hours=snapshot_hours)
    core_hours = core_days * 24.0

    transition_in_end = core_start + pd.Timedelta(hours=transition_hours - snapshot_hours)
    plateau_start = core_start + pd.Timedelta(hours=transition_hours)
    trans_out_start = core_start + pd.Timedelta(hours=core_hours - transition_hours)
    plateau_end = trans_out_start - pd.Timedelta(hours=snapshot_hours)

    return {
        "pre-buffer": (timestamps >= sim_start) & (timestamps <= pre_end),
        "transition-in": (timestamps >= core_start) & (timestamps <= transition_in_end),
        "plateau": (timestamps >= plateau_start) & (timestamps <= plateau_end),
        "transition-out": (timestamps >= trans_out_start) & (timestamps <= core_end),
        "core": (timestamps >= core_start) & (timestamps <= core_end),
        "post-buffer": (timestamps >= post_start) & (timestamps <= timestamps[-1]),
        "full-window": pd.Series(True, index=timestamps),
    }


def validate_scope_masks(
    scopes: dict[str, pd.Series],
    snapshot_hours: float,
) -> dict[str, int]:
    """Return phase snapshot counts; mutually exclusive sub-phases must partition the window."""
    sub_phases = ("pre-buffer", "transition-in", "plateau", "transition-out", "post-buffer")
    counts = {name: int(scopes[name].sum()) for name in scopes}
    sub = scopes["transition-in"].astype(int) + scopes["plateau"].astype(int) + scopes["transition-out"].astype(int)
    if not (sub == scopes["core"].astype(int)).all():
        raise ValueError("Core sub-phases do not sum to core mask")
    overlap = sum(scopes[p].astype(int) for p in sub_phases)
    if (overlap > 1).any():
        raise ValueError("Snapshot assigned to more than one sub-phase")
    unclassified = overlap == 0
    if unclassified.any():
        raise ValueError(f"{int(unclassified.sum())} snapshots unclassified in sub-phases")
    expected = {
        "pre-buffer": 56,
        "transition-in": 16,
        "plateau": 80,
        "transition-out": 16,
        "post-buffer": 56,
        "core": 112,
        "full-window": 224,
    }
    if abs(snapshot_hours - 3.0) < 1e-9:
        for key, exp in expected.items():
            if counts[key] != exp:
                raise ValueError(f"Scope {key}: expected {exp} snapshots, got {counts[key]}")
        if sum(counts[p] for p in sub_phases) != 224:
            raise ValueError("Sub-phase snapshot counts do not sum to 224")
    return counts


def validate_profiles(
    p_base: pd.DataFrame,
    scenarios: dict[str, pd.DataFrame],
    meta: pd.DataFrame,
    stress: pd.Series,
    core_start: pd.Timestamp,
    core_days: int,
    buffer_days: int,
    transition_hours: float,
    snapshot_hours: float,
    severity: dict[str, dict[str, float]],
) -> pd.DataFrame:
    rows = []
    timestamps = p_base.index
    scopes = _scope_masks(timestamps, core_start, core_days, buffer_days, transition_hours, snapshot_hours)
    core_mask = scopes["core"]

    def add(test: str, passed: bool, detail: str = "", tolerance: str = ""):
        rows.append({"test": test, "passed": passed, "tolerance": tolerance, "detail": detail})

    phase_counts = validate_scope_masks(scopes, snapshot_hours)
    add("phase_counts_224", phase_counts["full-window"] == 224, f"counts={phase_counts}")
    add(
        "phase_partition",
        sum(phase_counts[p] for p in ("pre-buffer", "transition-in", "plateau", "transition-out", "post-buffer")) == 224,
        "",
    )
    add("dimensions_full_window", len(timestamps) == 224, f"n={len(timestamps)}")
    add("time_unique", not timestamps.duplicated().any(), "")
    add("time_sorted", timestamps.is_monotonic_increasing, "")
    add("columns_match_base", list(p_base.columns) == list(next(iter(scenarios.values())).columns), "")

    for scen_name, p_scen in scenarios.items():
        if not np.all((p_scen.values >= 0) & (p_scen.values <= 1)):
            add(f"bounds_{scen_name}", False, "values outside [0,1]")
        else:
            add(f"bounds_{scen_name}", True, "")

    ordering_ok = True
    for gen in p_base.columns:
        b = p_base[gen].values
        if not np.all(scenarios["extreme"][gen].values <= scenarios["severe"][gen].values + VALIDATION_TOL):
            ordering_ok = False
        if not np.all(scenarios["severe"][gen].values <= scenarios["moderate"][gen].values + VALIDATION_TOL):
            ordering_ok = False
        if not np.all(scenarios["moderate"][gen].values <= b + VALIDATION_TOL):
            ordering_ok = False
    add("scenario_ordering", ordering_ok, "")

    buffer_ok = True
    for scen_name, p_scen in scenarios.items():
        outside = ~core_mask
        if not np.allclose(p_scen.loc[outside].values, p_base.loc[outside].values, atol=VALIDATION_TOL):
            buffer_ok = False
    add("buffer_equality", buffer_ok, f"tol={VALIDATION_TOL}")

    plateau_mask = scopes["plateau"]
    plateau_ok = True
    for scen_name in ("moderate", "severe", "extreme"):
        ratios = severity[scen_name]
        for gen in p_base.columns:
            group = map_carrier_group(meta.at[gen, "carrier"])
            r_k = ratios[group]
            base_v = p_base.loc[plateau_mask, gen]
            scen_v = scenarios[scen_name].loc[plateau_mask, gen]
            mask = base_v > PLATEAU_RATIO_THRESHOLD
            if mask.any():
                rel = (scen_v[mask] / base_v[mask]).astype(float)
                if not np.allclose(rel.values, r_k, rtol=1e-4, atol=1e-4):
                    plateau_ok = False
    add("plateau_ratio", plateau_ok, "")

    solar_ok = True
    for scen_name, p_scen in scenarios.items():
        zero_base = p_base.values == 0
        if not np.allclose(p_scen.values[zero_base], 0.0, atol=VALIDATION_TOL):
            solar_ok = False
    add("solar_night_preservation", solar_ok, "")

    s = stress.values
    add("stress_starts_zero", s[0] == 0.0, f"s[0]={s[0]}")
    add("stress_reaches_one", np.max(s) >= 1.0 - 1e-9, f"max={np.max(s)}")
    add("stress_ends_zero", s[-1] == 0.0, f"s[-1]={s[-1]}")

    return pd.DataFrame(rows)


def export_pypsa_profiles(
    output_dir: Path,
    p_base: pd.DataFrame,
    scenarios: dict[str, pd.DataFrame],
    stress: pd.Series,
    severity: dict[str, dict[str, float]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cols = list(p_base.columns)
    p_base[cols].to_csv(output_dir / "matched_base_p_max_pu.csv", index_label="timestamp")
    for name, df in scenarios.items():
        df[cols].to_csv(output_dir / f"{name}_p_max_pu.csv", index_label="timestamp")
    stress.to_frame().to_csv(output_dir / "stress_envelope.csv", index_label="timestamp")

    rows = []
    for scen_name, ratios in severity.items():
        for ts, s_val in stress.items():
            for group, r_k in ratios.items():
                m_val = 1.0 - s_val * (1.0 - r_k)
                rows.append(
                    {
                        "timestamp": ts,
                        "scenario": scen_name,
                        "carrier_group": group,
                        "stress_intensity": s_val,
                        "remaining_factor": m_val,
                    }
                )
    pd.DataFrame(rows).to_csv(output_dir / "carrier_derating_factors.csv", index=False)


def export_gamspy_profiles(
    output_dir: Path,
    stress: pd.Series,
    severity: dict[str, dict[str, float]],
    meta: pd.DataFrame,
) -> dict[str, float]:
    output_dir.mkdir(parents=True, exist_ok=True)
    caps = {
        "onshore": float(meta.loc[meta["carrier_group"] == "onshore", "p_nom"].sum()),
        "offshore": float(meta.loc[meta["carrier_group"] == "offshore", "p_nom"].sum()),
        "solar": float(meta.loc[meta["carrier_group"] == "solar", "p_nom"].sum()),
    }
    for scen_name, ratios in severity.items():
        for group in ("onshore", "offshore", "solar"):
            r_k = ratios[group]
            factor = 1.0 - stress * (1.0 - r_k)
            pd.DataFrame({"timestamp": stress.index, "factor": factor.values}).to_csv(
                output_dir / f"{scen_name}_{group}_factors.csv",
                index=False,
            )
    p_on, p_off = caps["onshore"], caps["offshore"]
    if p_on + p_off > 0:
        for scen_name, ratios in severity.items():
            m_on = 1.0 - stress * (1.0 - ratios["onshore"])
            m_off = 1.0 - stress * (1.0 - ratios["offshore"])
            m_wind = (p_on * m_on + p_off * m_off) / (p_on + p_off)
            pd.DataFrame({"timestamp": stress.index, "factor": m_wind.values}).to_csv(
                output_dir / f"{scen_name}_wind_capacity_weighted_factors.csv",
                index=False,
            )
    return caps


def write_metadata(
    path: Path,
    *,
    network_path: Path,
    checksum: str,
    timestamps: pd.DatetimeIndex,
    core_start: pd.Timestamp,
    core_days: int,
    buffer_days: int,
    transition_hours: float,
    snapshot_hours: float,
    severity: dict,
    overlap_info: dict,
    generator_counts: dict,
    gamspy_caps: dict,
) -> None:
    core_end = core_start + pd.Timedelta(days=core_days) - pd.Timedelta(hours=snapshot_hours)
    meta = {
        "version": "stylised_dunkelflaute_v4",
        "deterministic_non_historical": True,
        "source_base_network": str(network_path.resolve()),
        "source_base_checksum_sha256": checksum,
        "simulation_start": str(timestamps[0]),
        "simulation_end": str(timestamps[-1]),
        "core_start": str(core_start),
        "core_end": str(core_end),
        "buffer_days_each_side": buffer_days,
        "core_days": core_days,
        "transition_hours": transition_hours,
        "snapshot_hours": snapshot_hours,
        "snapshot_count": len(timestamps),
        "severity_assumptions": severity,
        "carrier_mapping": CARRIER_TO_GROUP,
        "formulas": {
            "stress_envelope": "raised-cosine transitions; plateau s(t)=1",
            "derating_multiplier": "m[k,t] = 1 - s(t) * (1 - r_k)",
            "profile": "p_df[g,t] = p_base[g,t] * m[k,t]",
        },
        "renewable_generator_count_by_carrier": generator_counts,
        "buffer_profile_source": "local cutout archive (Atlite, availability matrices)",
        "core_profile_source": "Base network generators_t.p_max_pu",
        "cutout_overlap_diagnostic": overlap_info,
        "gamspy_capacity_mw": gamspy_caps,
        "no_return_period_statement": (
            "No return period or occurrence probability is assigned to the scenario."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)


def _save_fig(path: Path, formats: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    for fmt in formats:
        plt.savefig(path.with_suffix(f".{fmt}"), dpi=150, bbox_inches="tight")
    plt.close()


def _phase_ax(ax, timestamps, core_start, core_days, buffer_days, transition_hours, snapshot_hours):
    sim_start = timestamps[0]
    core_end = core_start + pd.Timedelta(days=core_days) - pd.Timedelta(hours=snapshot_hours)
    pre_end = core_start - pd.Timedelta(hours=snapshot_hours)
    post_start = core_end + pd.Timedelta(hours=snapshot_hours)
    core_hours = core_days * 24.0
    transition_in_end = core_start + pd.Timedelta(hours=transition_hours - snapshot_hours)
    plateau_start = core_start + pd.Timedelta(hours=transition_hours)
    trans_out_start = core_start + pd.Timedelta(hours=core_hours - transition_hours)
    plateau_end = trans_out_start - pd.Timedelta(hours=snapshot_hours)

    phases = [
        (sim_start, pre_end, "pre-buffer", "#e8f4fc"),
        (core_start, transition_in_end, "transition-in", "#fff3cd"),
        (plateau_start, plateau_end, "plateau", "#f8d7da"),
        (trans_out_start, core_end, "transition-out", "#fff3cd"),
        (post_start, timestamps[-1], "post-buffer", "#e8f4fc"),
    ]
    for x0, x1, label, color in phases:
        if x0 <= x1:
            ax.axvspan(x0, x1, alpha=0.25, color=color, label=label if label not in ax.get_legend_handles_labels()[1] else None)


def create_plots(
    plot_dir: Path,
    p_base: pd.DataFrame,
    scenarios: dict[str, pd.DataFrame],
    stress: pd.Series,
    meta: pd.DataFrame,
    severity: dict,
    core_start: pd.Timestamp,
    core_days: int,
    buffer_days: int,
    transition_hours: float,
    snapshot_hours: float,
    demand: pd.Series | None,
    plot_formats: list[str],
) -> list[str]:
    plot_dir.mkdir(parents=True, exist_ok=True)
    gen_plot_dir = plot_dir / "generators"
    gen_plot_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    timestamps = p_base.index
    core_end = core_start + pd.Timedelta(days=core_days) - pd.Timedelta(hours=snapshot_hours)
    core_mask = (timestamps >= core_start) & (timestamps <= core_end)

    # 1. Stress envelope
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(stress.index, stress.values, "k-", lw=2, label="s(t)")
    for scen_name, ratios in severity.items():
        for group, r_k in ratios.items():
            m = 1.0 - stress * (1.0 - r_k)
            ax.plot(m.index, m.values, ls="--", label=f"{scen_name} {group} m(t)")
    _phase_ax(ax, timestamps, core_start, core_days, buffer_days, transition_hours, snapshot_hours)
    ax.set_ylabel("Intensity / remaining factor")
    ax.set_title("Stylised Dunkelflaute V4 stress envelope")
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    ax.set_xlim(timestamps[0], timestamps[-1])
    p = plot_dir / "01_stress_envelope"
    _save_fig(p, plot_formats)
    written.append(str(p.with_suffix(f".{plot_formats[0]}")))

    agg_specs = [
        ("onshore_wind", None, "onshore"),
        ("offshore_wind", None, "offshore"),
        ("solar", "solar", None),
        ("solar_hsat", "solar-hsat", None),
        ("total_vre", None, None),
    ]

    def agg_cf(df, spec):
        name, carrier, group = spec
        if carrier:
            return aggregate_capacity_weighted_profiles(df, meta, carrier=carrier)
        if group:
            return aggregate_capacity_weighted_profiles(df, meta, carrier_group=group)
        parts = []
        for g in ("onshore", "offshore", "solar"):
            parts.append(aggregate_capacity_weighted_profiles(df, meta, carrier_group=g))
        caps = [meta.loc[meta.carrier_group == g, "p_nom"].sum() for g in ("onshore", "offshore", "solar")]
        return sum(p * c for p, c in zip(parts, caps, strict=True)) / sum(caps)

    # 2 & 3 aggregate comparisons
    for suffix, mask in [("full_window", slice(None)), ("core_zoom", core_mask)]:
        for spec in agg_specs:
            fig, ax = plt.subplots(figsize=(12, 4))
            ax.plot(timestamps[mask], agg_cf(p_base, spec).loc[mask], label="matched Base", lw=2)
            for scen_name in ("moderate", "severe", "extreme"):
                ax.plot(
                    timestamps[mask],
                    agg_cf(scenarios[scen_name], spec).loc[mask],
                    ls="--",
                    label=scen_name,
                )
            if suffix == "full_window":
                _phase_ax(ax, timestamps, core_start, core_days, buffer_days, transition_hours, snapshot_hours)
            ax.set_title(f"{spec[0]} — {suffix.replace('_', ' ')}")
            ax.legend(fontsize=8)
            fname = plot_dir / f"02_{spec[0]}_{suffix}"
            _save_fig(fname, plot_formats)
            written.append(str(fname.with_suffix(f".{plot_formats[0]}")))

    # 4. Cluster-level severe vs base
    for carrier in RENEWABLE_CARRIERS:
        gens = meta.index[meta["carrier"] == carrier]
        if len(gens) == 0:
            continue
        n_clusters = len(gens)
        ncols = min(5, n_clusters)
        nrows = int(np.ceil(n_clusters / ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(3.5 * ncols, 2.5 * nrows), squeeze=False)
        for i, gen in enumerate(gens):
            ax = axes[i // ncols][i % ncols]
            ax.plot(timestamps, p_base[gen], label="Base", lw=1.2)
            ax.plot(timestamps, scenarios["severe"][gen], label="severe", ls="--")
            ax.set_title(gen, fontsize=8)
            ax.tick_params(labelsize=7)
        for j in range(n_clusters, nrows * ncols):
            axes[j // ncols][j % ncols].axis("off")
        fig.suptitle(f"{carrier} clusters — Base vs severe", fontsize=11)
        fig.tight_layout()
        fname = plot_dir / f"04_{carrier.replace('-', '_')}_clusters_base_vs_severe"
        _save_fig(fname, plot_formats)
        written.append(str(fname.with_suffix(f".{plot_formats[0]}")))

    # 5. Generator-level plots
    index_rows = []
    for gen in p_base.columns:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.plot(timestamps, p_base[gen], label="matched Base")
        for scen_name in ("moderate", "severe", "extreme"):
            ax.plot(timestamps, scenarios[scen_name][gen], ls="--", label=scen_name)
        ax.legend(fontsize=7)
        ax.set_title(gen, fontsize=9)
        rel = gen.replace(" ", "_").replace("/", "_")
        fpath = gen_plot_dir / f"{rel}.png"
        _save_fig(fpath, plot_formats)
        index_rows.append(
            {
                "generator": gen,
                "carrier": meta.at[gen, "carrier"],
                "bus": meta.at[gen, "bus"],
                "plot_file": str(fpath.with_suffix(f".{plot_formats[0]}")),
            }
        )
        written.append(str(fpath.with_suffix(f".{plot_formats[0]}")))
    pd.DataFrame(index_rows).to_csv(plot_dir.parent / "generator_plot_index.csv", index=False)

    # 6. Available generation GW
    fig, ax = plt.subplots(figsize=(12, 5))
    for label, group in [("onshore", "onshore"), ("offshore", "offshore"), ("solar", "solar")]:
        cf_b = aggregate_capacity_weighted_profiles(p_base, meta, carrier_group=group)
        cf_s = aggregate_capacity_weighted_profiles(scenarios["severe"], meta, carrier_group=group)
        cap = meta.loc[meta.carrier_group == group, "p_nom"].sum() / 1000
        ax.plot(timestamps, cf_b * cap, label=f"{label} Base")
        ax.plot(timestamps, cf_s * cap, ls="--", label=f"{label} severe")
    vre_b = agg_cf(p_base, ("total_vre", None, None))
    vre_s = agg_cf(scenarios["severe"], ("total_vre", None, None))
    total_cap = meta["p_nom"].sum() / 1000
    ax.plot(timestamps, vre_b * total_cap, "k-", lw=2, label="total VRE Base")
    ax.plot(timestamps, vre_s * total_cap, "k--", lw=2, label="total VRE severe")
    ax.set_ylabel("Available generation (GW)")
    ax.set_title("Available renewable generation — Base vs severe")
    ax.legend(fontsize=8)
    fname = plot_dir / "06_available_generation_gw"
    _save_fig(fname, plot_formats)
    written.append(str(fname.with_suffix(f".{plot_formats[0]}")))

    # 7. Demand / residual load diagnostic
    if demand is not None and not demand.empty:
        vre_cap = meta["p_nom"].sum()
        avail_vre_b = agg_cf(p_base, ("total_vre", None, None)) * vre_cap / 1000
        avail_vre_s = agg_cf(scenarios["severe"], ("total_vre", None, None)) * vre_cap / 1000
        d = demand.reindex(timestamps)
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(timestamps, d, label="demand", color="black")
        ax.plot(timestamps, avail_vre_b, label="available VRE Base")
        ax.plot(timestamps, avail_vre_s, ls="--", label="available VRE severe")
        ax.plot(timestamps, d - avail_vre_b, label="residual load Base")
        ax.plot(timestamps, d - avail_vre_s, ls="--", label="residual load severe")
        ax.set_title("Availability-based diagnostic, not optimised dispatch")
        ax.set_ylabel("GW")
        ax.legend(fontsize=8)
        fname = plot_dir / "07_demand_residual_load_diagnostic"
        _save_fig(fname, plot_formats)
        written.append(str(fname.with_suffix(f".{plot_formats[0]}")))

    # 8. Duration curves
    for spec in agg_specs[:4] + [("total_vre", None, None)]:
        fig, ax = plt.subplots(figsize=(8, 5))
        for label, df in [("Base", p_base), ("moderate", scenarios["moderate"]), ("severe", scenarios["severe"]), ("extreme", scenarios["extreme"])]:
            s = np.sort(agg_cf(df, spec).values)[::-1]
            ax.plot(s, label=label)
        ax.set_title(f"Duration curve — {spec[0]}")
        ax.set_xlabel("Hours sorted")
        ax.set_ylabel("Capacity factor")
        ax.legend()
        fname = plot_dir / f"08_duration_curve_{spec[0]}"
        _save_fig(fname, plot_formats)
        written.append(str(fname.with_suffix(f".{plot_formats[0]}")))

    # 9. Core energy bar chart
    energy_rows = []
    for spec in [("onshore", None, "onshore"), ("offshore", None, "offshore"), ("solar", None, "solar"), ("total_vre", None, None)]:
        for label, df in [("Base", p_base), ("moderate", scenarios["moderate"]), ("severe", scenarios["severe"]), ("extreme", scenarios["extreme"])]:
            cf = agg_cf(df, spec).loc[core_mask]
            if spec[0] == "total_vre":
                cap_gw = meta["p_nom"].sum() / 1000
            else:
                cap_gw = meta.loc[meta.carrier_group == spec[2], "p_nom"].sum() / 1000
            energy_gwh = float(cf.sum() * cap_gw * snapshot_hours)
            energy_rows.append({"carrier": spec[0], "scenario": label, "energy_gwh": energy_gwh})
    edf = pd.DataFrame(energy_rows)
    fig, ax = plt.subplots(figsize=(10, 5))
    carriers = edf["carrier"].unique()
    x = np.arange(len(carriers))
    width = 0.2
    for i, scen in enumerate(["Base", "moderate", "severe", "extreme"]):
        vals = [edf.query("carrier == @c and scenario == @scen")["energy_gwh"].iloc[0] for c in carriers]
        ax.bar(x + i * width, vals, width, label=scen)
    ax.set_xticks(x + 1.5 * width)
    ax.set_xticklabels(carriers)
    ax.set_ylabel("Available energy (GWh)")
    ax.set_title("14-day core available energy")
    ax.legend()
    fname = plot_dir / "09_core_energy_comparison"
    _save_fig(fname, plot_formats)
    written.append(str(fname.with_suffix(f".{plot_formats[0]}")))

    # 10. Heatmaps
    for carrier, scen_key, tag in [
        ("onwind", "p_base", "base"),
        ("onwind", "severe", "severe"),
        ("solar", "p_base", "base"),
        ("solar", "severe", "severe"),
    ]:
        gens = list(meta.index[meta["carrier"] == carrier])
        if not gens:
            continue
        mat = p_base[gens] if scen_key == "p_base" else scenarios["severe"][gens]
        vmax = max(p_base[gens].max().max(), scenarios["severe"][gens].max().max())
        fig, ax = plt.subplots(figsize=(12, 4))
        im = ax.imshow(mat.T.values, aspect="auto", vmin=0, vmax=vmax, cmap="YlOrRd")
        ax.set_yticks(range(len(gens)))
        ax.set_yticklabels(gens, fontsize=7)
        ax.set_title(f"{carrier} {tag} heatmap")
        plt.colorbar(im, ax=ax, label="p_max_pu")
        fname = plot_dir / f"10_{carrier.replace('-', '_')}_{tag}_heatmap"
        _save_fig(fname, plot_formats)
        written.append(str(fname.with_suffix(f".{plot_formats[0]}")))

    return written


STITCH_JUMP_WARN = 0.05


def validate_profile_stitching(
    p_base: pd.DataFrame,
    meta: pd.DataFrame,
    core_start: pd.Timestamp,
    core_days: int,
    snapshot_hours: float,
    summary_dir: Path,
) -> pd.DataFrame:
    """Measure buffer-to-core discontinuities at stitch boundaries."""
    timestamps = p_base.index
    core_end = core_start + pd.Timedelta(days=core_days) - pd.Timedelta(hours=snapshot_hours)
    snap_delta = pd.Timedelta(hours=snapshot_hours)
    pre_core = core_start - snap_delta
    post_core = core_end + snap_delta

    rows = []
    for gen in p_base.columns:
        if pre_core not in timestamps or core_start not in timestamps:
            raise ValueError("Missing entry stitch timestamps")
        if core_end not in timestamps or post_core not in timestamps:
            raise ValueError("Missing exit stitch timestamps")
        entry_jump = float(abs(p_base.at[core_start, gen] - p_base.at[pre_core, gen]))
        exit_jump = float(abs(p_base.at[post_core, gen] - p_base.at[core_end, gen]))
        max_jump = max(entry_jump, exit_jump)
        warn = ""
        if max_jump > STITCH_JUMP_WARN:
            warn = (
                "possible_causes: renewable_config_mismatch; correction_factor; "
                "aggregation_settings; profile_reconstruction; weather_variation"
            )
        rows.append(
            {
                "generator": gen,
                "carrier": meta.at[gen, "carrier"],
                "bus": meta.at[gen, "bus"],
                "entry_jump": entry_jump,
                "exit_jump": exit_jump,
                "maximum_jump": max_jump,
                "warning": warn,
            }
        )
    df = pd.DataFrame(rows)
    summary_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(summary_dir / "profile_stitch_validation.csv", index=False)
    return df


def create_stitch_plots(
    plot_dir: Path,
    p_base: pd.DataFrame,
    meta: pd.DataFrame,
    core_start: pd.Timestamp,
    core_days: int,
    snapshot_hours: float,
    plot_formats: list[str],
) -> list[str]:
    """Plots 11–12: zoom on entry/exit stitch points."""
    written: list[str] = []
    timestamps = p_base.index
    core_end = core_start + pd.Timedelta(days=core_days) - pd.Timedelta(hours=snapshot_hours)
    snap_delta = pd.Timedelta(hours=snapshot_hours)
    window = pd.Timedelta(hours=24)

    def agg_cf(df, group):
        return aggregate_capacity_weighted_profiles(df, meta, carrier_group=group)

    cluster_gens = {
        "onshore": list(meta.index[meta.carrier_group == "onshore"][:3]),
        "offshore": list(meta.index[meta.carrier_group == "offshore"][:3]),
        "solar": list(meta.index[meta.carrier_group == "solar"][:3]),
    }

    for tag, center in [("entry", core_start), ("exit", core_end)]:
        mask = (timestamps >= center - window) & (timestamps <= center + window)
        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        ax0, ax1 = axes
        for group in ("onshore", "offshore", "solar"):
            ax0.plot(timestamps[mask], agg_cf(p_base, group).loc[mask], label=f"{group} aggregate")
        ax0.axvline(center, color="red", ls=":", lw=1.5, label="stitch")
        ax0.set_title(f"Stitch {tag} — aggregate profiles (no smoothing)")
        ax0.legend(fontsize=8)
        ax0.set_ylabel("Capacity factor")
        for group, gens in cluster_gens.items():
            for gen in gens:
                ax1.plot(timestamps[mask], p_base.loc[mask, gen], ls="--", alpha=0.8, label=gen)
        ax1.axvline(center, color="red", ls=":", lw=1.5)
        ax1.set_title(f"Stitch {tag} — selected cluster generators")
        ax1.legend(fontsize=6, ncol=2)
        ax1.set_ylabel("p_max_pu")
        fname = plot_dir / f"1{1 if tag == 'entry' else 2}_stitch_{tag}_zoom"
        _save_fig(fname, plot_formats)
        written.append(str(fname.with_suffix(f".{plot_formats[0]}")))
    return written


def infer_demand_unit(series: pd.Series) -> str:
    """Heuristic: German national hourly demand ~40–90 GW -> values in MW if mean > 500."""
    med = float(series.dropna().median())
    return "MW" if med > 500 else "GW"


def load_demand_series(
    timestamps: pd.DatetimeIndex,
    demand_csv: Path,
    snapshot_hours: float,
    summary_dir: Path,
) -> tuple[pd.Series, pd.DataFrame]:
    if not demand_csv.exists():
        validation = pd.DataFrame(
            [
                {
                    "source_file": str(demand_csv),
                    "source_unit": "n/a",
                    "converted_unit": "GW",
                    "minimum": np.nan,
                    "maximum": np.nan,
                    "mean": np.nan,
                    "missing_timestamps": len(timestamps),
                    "snapshot_count": 0,
                    "status": "missing_file",
                }
            ]
        )
        return pd.Series(dtype=float), validation

    df = pd.read_csv(demand_csv, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    if df.index.duplicated().any():
        raise ValueError(f"Duplicated timestamps in demand file: {demand_csv}")
    if "DE" not in df.columns:
        validation = pd.DataFrame(
            [
                {
                    "source_file": str(demand_csv),
                    "source_unit": "n/a",
                    "converted_unit": "GW",
                    "minimum": np.nan,
                    "maximum": np.nan,
                    "mean": np.nan,
                    "missing_timestamps": len(timestamps),
                    "snapshot_count": 0,
                    "status": "missing_DE_column",
                }
            ]
        )
        return pd.Series(dtype=float), validation

    hourly = df["DE"].astype(float)
    source_unit = infer_demand_unit(hourly)
    if source_unit == "MW":
        hourly_gw = hourly / 1000.0
    else:
        hourly_gw = hourly

    freq = f"{int(snapshot_hours)}h"
    d_resampled = hourly_gw.resample(freq).mean()
    aligned = d_resampled.reindex(timestamps)
    missing = int(aligned.isna().sum())
    status = "ok" if missing == 0 else "missing_timestamps"

    validation = pd.DataFrame(
        [
            {
                "source_file": str(demand_csv.resolve()),
                "source_unit": source_unit,
                "converted_unit": "GW",
                "minimum": float(aligned.min()) if missing < len(aligned) else np.nan,
                "maximum": float(aligned.max()) if missing < len(aligned) else np.nan,
                "mean": float(aligned.mean()) if missing < len(aligned) else np.nan,
                "missing_timestamps": missing,
                "snapshot_count": int(len(aligned.dropna())),
                "status": status,
            }
        ]
    )
    summary_dir.mkdir(parents=True, exist_ok=True)
    validation.to_csv(summary_dir / "demand_unit_validation.csv", index=False)
    return aligned, validation


def build_summaries(
    output_dir: Path,
    p_base: pd.DataFrame,
    scenarios: dict[str, pd.DataFrame],
    meta: pd.DataFrame,
    core_start: pd.Timestamp,
    core_days: int,
    buffer_days: int,
    transition_hours: float,
    snapshot_hours: float,
) -> None:
    timestamps = p_base.index
    scopes = _scope_masks(timestamps, core_start, core_days, buffer_days, transition_hours, snapshot_hours)
    profile_rows = []
    groups = {
        "onshore": meta.index[meta.carrier_group == "onshore"],
        "offshore": meta.index[meta.carrier_group == "offshore"],
        "solar": meta.index[meta.carrier_group == "solar"],
    }

    all_dfs = {"matched-base": p_base, **scenarios}
    for scen_name, df in all_dfs.items():
        for scope_name, mask in scopes.items():
            for carrier in RENEWABLE_CARRIERS:
                gens = [g for g in meta.index[meta.carrier == carrier] if g in df.columns]
                if not gens:
                    continue
                cap_gw = meta.loc[gens, "p_nom"].sum() / 1000
                sub = df.loc[mask, gens]
                mean_cf = float(
                    (sub.multiply(meta.loc[gens, "p_nom"], axis=1).sum(axis=1) / meta.loc[gens, "p_nom"].sum()).mean()
                ) if len(sub) else 0.0
                energy_gwh = float(
                    sum(meta.loc[g, "p_nom"] * sub[g].sum() * snapshot_hours / 1000 for g in gens)
                ) if len(sub) else 0.0
                profile_rows.append(
                    {
                        "scenario": scen_name,
                        "scope": scope_name,
                        "carrier": carrier,
                        "capacity_gw": cap_gw,
                        "mean_cf": mean_cf,
                        "min_cf": float(sub.min().min()) if len(sub) else 0.0,
                        "max_cf": float(sub.max().max()) if len(sub) else 0.0,
                        "available_energy_gwh": energy_gwh,
                    }
                )

    pd.DataFrame(profile_rows).to_csv(output_dir / "profile_summary.csv", index=False)

    def group_energy(df, group, mask):
        gens = [g for g in groups[group] if g in df.columns]
        cap_mw = meta.loc[gens, "p_nom"].sum()
        cf = aggregate_capacity_weighted_profiles(df.loc[mask], meta, carrier_group=group)
        return float(cf.sum() * cap_mw / 1000 * snapshot_hours)

    ratio_rows = []
    for scope in ("plateau", "core", "full-window"):
        mask = scopes[scope]
        for group in ("onshore", "offshore", "solar"):
            base_e = group_energy(p_base, group, mask)
            for scen in ("moderate", "severe", "extreme"):
                scen_e = group_energy(scenarios[scen], group, mask)
                ratio_rows.append(
                    {
                        "scope": scope,
                        "carrier_group": group,
                        "scenario": scen,
                        "base_energy_gwh": base_e,
                        "scenario_energy_gwh": scen_e,
                        "energy_ratio": scen_e / base_e if base_e > 0 else np.nan,
                    }
                )
        base_vre = sum(group_energy(p_base, g, mask) for g in groups)
        for scen in ("moderate", "severe", "extreme"):
            scen_vre = sum(group_energy(scenarios[scen], g, mask) for g in groups)
            ratio_rows.append(
                {
                    "scope": scope,
                    "carrier_group": "total_vre",
                    "scenario": scen,
                    "base_energy_gwh": base_vre,
                    "scenario_energy_gwh": scen_vre,
                    "energy_ratio": scen_vre / base_vre if base_vre > 0 else np.nan,
                }
            )

    ratio_df = pd.DataFrame(ratio_rows)
    ratio_df.to_csv(output_dir / "energy_ratio_summary.csv", index=False)
    ratio_df.query("scope == 'core'").to_csv(output_dir / "core_energy_summary.csv", index=False)
    ratio_df.query("scope == 'full-window'").to_csv(output_dir / "full_window_energy_summary.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stylised Dunkelflaute V4 profiles")
    parser.add_argument("--network", default="results/base/networks/base_s_10_elec_.nc")
    parser.add_argument("--output-dir", default="data/inre/profiles/stylised_dunkelflaute_v4")
    parser.add_argument("--plot-dir", default="output/stylised_dunkelflaute_v4/plots")
    parser.add_argument("--summary-dir", default="output/stylised_dunkelflaute_v4")
    parser.add_argument("--gamspy-dir", default="gamspy-de/profiles/stylised_dunkelflaute_v4")
    parser.add_argument("--core-start", default="2021-01-25")
    parser.add_argument("--core-days", type=int, default=14)
    parser.add_argument("--buffer-days", type=int, default=7)
    parser.add_argument("--transition-hours", type=float, default=48.0)
    parser.add_argument("--snapshot-hours", type=float, default=3.0)
    parser.add_argument("--plot-format", default="png,pdf")
    parser.add_argument(
        "--cutout",
        default="data/cutout/archive/v1.0/europe-2021-sarah3-era5.nc",
    )
    parser.add_argument(
        "--demand-csv",
        default="data/entsoe_electricity_demand/archive/2026-02-02/electricity_demand_entsoe_raw.csv",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    network_path = REPO_ROOT / args.network
    output_dir = REPO_ROOT / args.output_dir
    plot_dir = REPO_ROOT / args.plot_dir
    summary_dir = REPO_ROOT / args.summary_dir
    gamspy_dir = REPO_ROOT / args.gamspy_dir
    cutout_path = REPO_ROOT / args.cutout
    plot_formats = [x.strip() for x in args.plot_format.split(",") if x.strip()]

    core_start = pd.Timestamp(args.core_start)
    full_timestamps = build_full_window_timestamps(
        core_start, args.core_days, args.buffer_days, args.snapshot_hours
    )
    expected_snaps = int((2 * args.buffer_days + args.core_days) * 24 / args.snapshot_hours)
    validate_time_index(full_timestamps, args.snapshot_hours, expected_snaps)

    n, checksum = load_base_network(network_path)
    base_timestamps = pd.DatetimeIndex(n.snapshots)
    validate_time_index(base_timestamps, args.snapshot_hours)

    core_timestamps = pd.date_range(
        core_start,
        periods=int(args.core_days * 24 / args.snapshot_hours),
        freq=f"{int(args.snapshot_hours)}h",
    )
    if not base_timestamps.equals(core_timestamps):
        logger.warning("Base network snapshots differ from expected core window; using intersection")
        core_timestamps = base_timestamps

    p_base_core, meta = extract_renewable_profiles(n)
    if len(base_timestamps) < int(args.core_days * 24 / args.snapshot_hours):
        raise ValueError(
            f"Base network period shorter than {args.core_days}-day core; "
            "cannot proceed without fabricating data"
        )

    p_base, overlap_info = extend_profiles_to_28day(
        n,
        p_base_core,
        full_timestamps,
        core_timestamps,
        cutout_path,
        args.snapshot_hours,
        meta,
        summary_dir,
    )
    p_base = p_base.clip(lower=0.0, upper=1.0)

    stitch_df = validate_profile_stitching(
        p_base, meta, core_start, args.core_days, args.snapshot_hours, summary_dir
    )

    stress = build_stress_envelope(
        full_timestamps,
        core_start,
        args.core_days,
        args.transition_hours,
        args.snapshot_hours,
    )

    scenarios = {
        name: apply_derating(p_base, meta, stress, ratios)
        for name, ratios in SEVERITY_ASSUMPTIONS.items()
    }

    validation = validate_profiles(
        p_base,
        scenarios,
        meta,
        stress,
        core_start,
        args.core_days,
        args.buffer_days,
        args.transition_hours,
        args.snapshot_hours,
        SEVERITY_ASSUMPTIONS,
    )
    summary_dir.mkdir(parents=True, exist_ok=True)
    validation.to_csv(summary_dir / "profile_validation.csv", index=False)

    export_pypsa_profiles(output_dir, p_base, scenarios, stress, SEVERITY_ASSUMPTIONS)
    gamspy_caps = export_gamspy_profiles(gamspy_dir, stress, SEVERITY_ASSUMPTIONS, meta)

    gen_counts = meta.groupby("carrier").size().to_dict()
    write_metadata(
        output_dir / "metadata.yaml",
        network_path=network_path,
        checksum=checksum,
        timestamps=full_timestamps,
        core_start=core_start,
        core_days=args.core_days,
        buffer_days=args.buffer_days,
        transition_hours=args.transition_hours,
        snapshot_hours=args.snapshot_hours,
        severity=SEVERITY_ASSUMPTIONS,
        overlap_info=overlap_info,
        generator_counts=gen_counts,
        gamspy_caps=gamspy_caps,
    )

    demand, demand_validation = load_demand_series(
        full_timestamps,
        REPO_ROOT / args.demand_csv,
        args.snapshot_hours,
        summary_dir,
    )
    plot_paths = create_plots(
        plot_dir,
        p_base,
        scenarios,
        stress,
        meta,
        SEVERITY_ASSUMPTIONS,
        core_start,
        args.core_days,
        args.buffer_days,
        args.transition_hours,
        args.snapshot_hours,
        demand,
        plot_formats,
    )
    plot_paths.extend(
        create_stitch_plots(
            plot_dir,
            p_base,
            meta,
            core_start,
            args.core_days,
            args.snapshot_hours,
            plot_formats,
        )
    )
    build_summaries(
        summary_dir,
        p_base,
        scenarios,
        meta,
        core_start,
        args.core_days,
        args.buffer_days,
        args.transition_hours,
        args.snapshot_hours,
    )

    from scripts.inre.audit_stylised_dunkelflaute_v4 import run_full_audit

    validation = run_full_audit(
        REPO_ROOT,
        summary_dir,
        network_path,
        output_dir,
        args.demand_csv,
        validation,
        overlap_info=overlap_info,
        stitch_df=stitch_df,
        demand_validation=demand_validation,
        python_exe=sys.executable,
    )

    validation.to_csv(summary_dir / "validation_tests.csv", index=False)
    logger.info("Wrote profiles to %s", output_dir)
    logger.info("Wrote %d plots to %s", len(plot_paths), plot_dir)
    failed = validation.query("passed == False")
    if not failed.empty:
        logger.warning("Validation failures:\n%s", failed.to_string(index=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
