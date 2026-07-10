"""Prepare V4 scenario data for fixed-capacity dispatch validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from load_inputs_v4 import ModelInputsV4, load_inputs_v4, load_scenario_v4, validate_inputs_v4


@dataclass
class PreparedDataV4:
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
    nuclear_sites: pd.DataFrame
    nuclear_fixed_cap: dict[str, float]
    voll_eur_per_mwh: float
    config: dict


def _apply_capacity_overrides(
    existing: pd.DataFrame,
    overrides: dict | None,
) -> pd.DataFrame:
    if not overrides:
        return existing
    out = existing.copy()
    for tech, value in overrides.items():
        if tech not in out.columns:
            out[tech] = 0.0
        out[tech] = float(value)
    return out


def _apply_nuclear_config(
    nuclear_sites: pd.DataFrame,
    nuclear_cfg: dict,
) -> tuple[pd.DataFrame, dict[str, float]]:
    if not nuclear_cfg.get("enabled", False):
        return nuclear_sites.iloc[0:0].copy(), {}

    tech = nuclear_cfg["tech"]
    sites = nuclear_cfg.get("filter_sites", [])
    df = nuclear_sites[nuclear_sites["tech"] == tech].copy()
    if sites:
        df = df[df["site_id"].isin(sites)]

    fixed_cap: dict[str, float] = {}
    per_site = float(nuclear_cfg.get("fixed_capacity_mw_per_site", 1500.0))
    for site in df["site_id"]:
        fixed_cap[site] = per_site

    return df.reset_index(drop=True), fixed_cap


def prepare_scenario_v4(inputs: ModelInputsV4, scenario: dict) -> PreparedDataV4:
    snapshots = pd.DatetimeIndex(inputs.snapshots["timestamp"])
    weights = {
        str(ts): float(w)
        for ts, w in zip(inputs.snapshots["timestamp"], inputs.snapshots["weight_hours"])
    }

    tech_params = inputs.technologies.set_index("tech")
    techs = sorted(tech_params.index.unique().tolist())

    existing = inputs.capacity_existing.pivot_table(
        index="bus", columns="tech", values="p_nom_MW", aggfunc="sum", fill_value=0.0
    )
    existing = _apply_capacity_overrides(existing, scenario.get("capacity_overrides"))

    nuclear_sites, nuclear_fixed_cap = _apply_nuclear_config(
        inputs.nuclear_sites,
        scenario.get("nuclear", {}),
    )

    dispatch_techs = scenario.get("dispatch_techs")
    if dispatch_techs:
        model_techs = [t for t in dispatch_techs if t in tech_params.index]
    else:
        model_techs = [t for t in techs if not t.startswith("nuclear-")]

    return PreparedDataV4(
        scenario_name=scenario.get("name", "unnamed"),
        buses=sorted(inputs.buses["bus_id"].tolist()),
        techs=model_techs,
        lines=sorted(inputs.lines["line_id"].tolist()),
        times=list(snapshots),
        weights=weights,
        demand=inputs.demand.copy(),
        availability=inputs.availability.copy(),
        existing_cap=existing,
        tech_params=tech_params,
        line_params=inputs.lines.set_index("line_id"),
        nuclear_sites=nuclear_sites,
        nuclear_fixed_cap=nuclear_fixed_cap,
        voll_eur_per_mwh=float(inputs.config.get("voll_eur_per_mwh", 100_000.0)),
        config=inputs.config,
    )


def load_and_prepare_v4(
    root: Path,
    scenario_name: str,
    inputs_subdir: str = "inputs_v4",
) -> PreparedDataV4:
    inputs = load_inputs_v4(root, inputs_subdir=inputs_subdir)
    issues = validate_inputs_v4(inputs)
    if issues:
        raise ValueError("Input validation failed:\n" + "\n".join(f"  - {i}" for i in issues))
    scenario = load_scenario_v4(root, scenario_name)
    return prepare_scenario_v4(inputs, scenario)
