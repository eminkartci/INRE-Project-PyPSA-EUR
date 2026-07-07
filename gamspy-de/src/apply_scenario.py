"""Apply INRE-style scenario overrides (Dunkelflaute, nuclear) to model inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from load_inputs import ModelInputs


@dataclass
class PreparedData:
    scenario_name: str
    buses: list[str]
    techs: list[str]
    lines: list[str]
    times: list[pd.Timestamp]
    weights: dict[str, float]
    demand: pd.DataFrame
    availability: pd.DataFrame
    existing_cap: pd.DataFrame
    tech_params: pd.DataFrame
    line_params: pd.DataFrame
    storage_params: pd.DataFrame
    nuclear_sites: pd.DataFrame
    co2_limit_window: float
    config: dict


def _load_factor_profile(path: Path, snapshots: pd.DatetimeIndex) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    series = df.set_index("timestamp")["factor"].astype(float)
    series.index = pd.DatetimeIndex(series.index).tz_localize(None)
    snapshots_naive = snapshots.tz_localize(None) if snapshots.tz else snapshots
    aligned = series.reindex(snapshots_naive, method="nearest")
    if aligned.isna().any():
        raise ValueError(f"Profile {path} does not cover all snapshots")
    return pd.Series(aligned.values, index=snapshots)


def _build_stress_mask(
    availability: pd.DataFrame,
    snapshots: pd.DatetimeIndex,
    wind_carriers: list[str],
    solar_carriers: list[str],
    auto_worst_days: int | None,
    time_start: str | None,
    time_end: str | None,
) -> pd.Series:
    if auto_worst_days:
        vre = availability[availability["tech"].isin(wind_carriers + solar_carriers)].copy()
        cap = (
            availability.groupby(["bus", "tech", "timestamp"])["p_max_pu"]
            .first()
            .reset_index()
        )
        merged = vre.merge(
            cap,
            on=["bus", "tech", "timestamp"],
            how="left",
            suffixes=("", "_base"),
        )
        daily = merged.groupby(merged["timestamp"].dt.normalize())["p_max_pu"].mean()
        worst_days = daily.nsmallest(int(auto_worst_days)).index
        mask = pd.Series(False, index=snapshots)
        for day in worst_days:
            mask |= snapshots.normalize() == day.normalize()
        return mask

    start = pd.Timestamp(time_start)
    end = pd.Timestamp(time_end)
    return pd.Series(
        (snapshots >= start) & (snapshots < end + pd.Timedelta(days=1)),
        index=snapshots,
    )


def _ramp_weights(mask: pd.Series, ramp_hours: int, snapshot_hours: float) -> pd.Series:
    if not ramp_hours or ramp_hours <= 0:
        return mask.astype(float)

    ramp_steps = max(1, int(round(ramp_hours / snapshot_hours)))
    weights = mask.astype(float).copy()
    idx = np.arange(len(weights))
    active = idx[weights.to_numpy(dtype=bool)]
    if len(active) == 0:
        return weights

    start, end = active[0], active[-1]
    for i in range(len(weights)):
        if i < start:
            dist = start - i
            if dist < ramp_steps:
                weights.iloc[i] = max(weights.iloc[i], 1.0 - dist / ramp_steps)
        elif i > end:
            dist = i - end
            if dist < ramp_steps:
                weights.iloc[i] = max(weights.iloc[i], 1.0 - dist / ramp_steps)
    return weights


def apply_dunkelflaute(
    availability: pd.DataFrame,
    snapshots: pd.DatetimeIndex,
    scenario_cfg: dict,
    root: Path,
    snapshot_hours: float,
) -> pd.DataFrame:
    if not scenario_cfg.get("enabled", False):
        return availability.copy()

    wind_carriers = scenario_cfg.get("wind_carriers", ["onwind", "offwind"])
    solar_carriers = scenario_cfg.get("solar_carriers", ["solar"])
    out = availability.copy()

    wind_profile = (
        _load_factor_profile(root / scenario_cfg["wind_profile"], snapshots)
        if scenario_cfg.get("wind_profile")
        else None
    )
    solar_profile = (
        _load_factor_profile(root / scenario_cfg["solar_profile"], snapshots)
        if scenario_cfg.get("solar_profile")
        else None
    )

    ramp_hours = int(scenario_cfg.get("ramp_hours", 0) or 0)
    mask = _build_stress_mask(
        availability,
        snapshots,
        wind_carriers,
        solar_carriers,
        scenario_cfg.get("auto_worst_days"),
        scenario_cfg.get("time_start"),
        scenario_cfg.get("time_end"),
    )
    if wind_profile is None and solar_profile is None:
        if not mask.any():
            return out
        ramp = _ramp_weights(mask, ramp_hours, snapshot_hours)
        wind_factor = float(scenario_cfg.get("wind_factor", 0.15))
        solar_factor = float(scenario_cfg.get("solar_factor", 0.10))
        for t_idx, ts in enumerate(snapshots):
            multiplier_w = 1.0 - ramp.iloc[t_idx] * (1.0 - wind_factor)
            multiplier_s = 1.0 - ramp.iloc[t_idx] * (1.0 - solar_factor)
            sel_w = out["tech"].isin(wind_carriers) & (out["timestamp"] == ts)
            sel_s = out["tech"].isin(solar_carriers) & (out["timestamp"] == ts)
            out.loc[sel_w, "p_max_pu"] *= multiplier_w
            out.loc[sel_s, "p_max_pu"] *= multiplier_s
        return out

    # Profile path — aligned with PyPSA apply_dunkelflaute (mask + ramp on 14-day window).
    if not mask.any():
        mask = pd.Series(True, index=snapshots)
    ramp = _ramp_weights(mask, ramp_hours, snapshot_hours)
    wind_fallback = float(scenario_cfg.get("wind_factor", 1.0))
    solar_fallback = float(scenario_cfg.get("solar_factor", 1.0))
    wind_target = (
        wind_profile.reindex(snapshots).fillna(wind_fallback)
        if wind_profile is not None
        else pd.Series(wind_fallback, index=snapshots)
    )
    solar_target = (
        solar_profile.reindex(snapshots).fillna(solar_fallback)
        if solar_profile is not None
        else pd.Series(solar_fallback, index=snapshots)
    )

    for t_idx, ts in enumerate(snapshots):
        ts_val = pd.Timestamp(ts)
        multiplier_w = 1.0 - ramp.iloc[t_idx] * (1.0 - float(wind_target.iloc[t_idx]))
        multiplier_s = 1.0 - ramp.iloc[t_idx] * (1.0 - float(solar_target.iloc[t_idx]))
        sel_w = out["tech"].isin(wind_carriers) & (out["timestamp"] == ts_val)
        sel_s = out["tech"].isin(solar_carriers) & (out["timestamp"] == ts_val)
        out.loc[sel_w, "p_max_pu"] *= multiplier_w
        out.loc[sel_s, "p_max_pu"] *= multiplier_s
    return out


def apply_nuclear_capex_multiplier(
    tech_params: pd.DataFrame,
    nuclear_cfg: dict,
) -> pd.DataFrame:
    mult = nuclear_cfg.get("capex_multiplier")
    if not mult or not nuclear_cfg.get("enabled"):
        return tech_params
    tech = nuclear_cfg.get("tech")
    if not tech or tech not in tech_params.index:
        return tech_params
    out = tech_params.copy()
    out.loc[tech, "capital_cost_EUR_per_MWyr"] *= float(mult)
    return out


def apply_nuclear_sites(
    nuclear_sites: pd.DataFrame,
    scenario_cfg: dict,
) -> pd.DataFrame:
    if not scenario_cfg.get("enabled", False):
        return nuclear_sites.iloc[0:0].copy()

    tech = scenario_cfg["tech"]
    sites = scenario_cfg.get("filter_sites", [])
    df = nuclear_sites[nuclear_sites["tech"] == tech].copy()
    if sites:
        df = df[df["site_id"].isin(sites)]
    return df.reset_index(drop=True)


def prepare_scenario(inputs: ModelInputs, scenario: dict) -> PreparedData:
    snapshots = pd.DatetimeIndex(inputs.snapshots["timestamp"])
    snapshot_hours = float(inputs.snapshots["weight_hours"].iloc[0])
    weights = {
        str(ts): float(w)
        for ts, w in zip(inputs.snapshots["timestamp"], inputs.snapshots["weight_hours"])
    }

    availability = apply_dunkelflaute(
        inputs.availability,
        snapshots,
        scenario.get("dunkelflaute", {}),
        inputs.root,
        snapshot_hours,
    )
    nuclear = apply_nuclear_sites(inputs.nuclear_sites, scenario.get("nuclear", {}))

    policy = scenario.get("policy", {})
    annual_co2 = float(policy.get("co2_annual_limit_t", inputs.config["co2"]["annual_limit_t"]))
    total_hours = sum(weights.values())
    co2_limit = annual_co2 * (total_hours / 8760.0) if inputs.config["co2"].get("enable", True) else 1e18

    tech_params = apply_nuclear_capex_multiplier(
        inputs.technologies.set_index("tech"),
        scenario.get("nuclear", {}),
    )
    techs = sorted(tech_params.index.unique().tolist())
    model_techs = [t for t in techs if not t.startswith("nuclear-")]

    existing = inputs.capacity_existing.pivot_table(
        index="bus", columns="tech", values="p_nom_MW", aggfunc="sum", fill_value=0.0
    )

    return PreparedData(
        scenario_name=scenario.get("name", "unnamed"),
        buses=sorted(inputs.buses["bus_id"].tolist()),
        techs=model_techs,
        lines=sorted(inputs.lines["line_id"].tolist()),
        times=list(snapshots),
        weights=weights,
        demand=inputs.demand.copy(),
        availability=availability,
        existing_cap=existing,
        tech_params=tech_params,
        line_params=inputs.lines.set_index("line_id"),
        storage_params=inputs.storage.set_index("bus"),
        nuclear_sites=nuclear,
        co2_limit_window=co2_limit,
        config=inputs.config,
    )


def load_and_prepare(root: Path, scenario_name: str) -> PreparedData:
    from load_inputs import load_inputs, validate_inputs

    inputs = load_inputs(root)
    validate_inputs(inputs)
    scenario_path = root / "scenarios" / f"{scenario_name}.yaml"
    with open(scenario_path) as f:
        scenario = yaml.safe_load(f) or {}
    return prepare_scenario(inputs, scenario)
