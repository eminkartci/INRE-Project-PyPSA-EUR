# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
V4 generic advanced nuclear fixed-capacity sweep on stylised severe Dunkelflaute.

Solves stylised-df-severe-v4 (reference) and four nuclear capacity scenarios,
validates, exports KPIs/plots to results/inre-comparison-v4-nuclear-sweep/.

Usage::

    pixi run python scripts/inre/run_v4_nuclear_sweep.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.add_electricity import calculate_annuity
from scripts.inre.add_nuclear_technologies import NUCLEAR_COLORS, _nearest_bus, _snapshot_step_hours
from scripts.inre.apply_inre_network import _patch_co2_emissions_for_thermal
from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS
from scripts.inre.run_v4_stage1 import (
    EXPECTED_SNAPSHOTS,
    METADATA_PATH,
    VOLL,
    _co2_kt,
    _cost_breakdown,
    _curtailment_twh,
    _gen_energy_by_carrier,
    _load_shed_metrics,
    _series_equal_df,
    _slice_snapshots,
    _weight,
    demand_by_phase_twh,
    extract_metrics,
    load_metadata,
    prepare_for_solve,
    solve_network,
    validate_solved,
)

logger = logging.getLogger(__name__)

CARRIER = "generic-advanced-nuclear"
CUSTOM_COSTS = REPO_ROOT / "data/inre/custom_costs_nuclear.csv"
CONFIG_PATH = REPO_ROOT / "config/inre/config.base.yaml"
PREPARED_SEVERE = REPO_ROOT / "results/stylised-df-severe-v4/networks/base_s_10_elec_.nc"
OUTPUT_DIR = REPO_ROOT / "results/inre-comparison-v4-nuclear-sweep"

NUCLEAR_SITES = [
    ("Grohnde", 51.906, 9.401),
    ("Brokdorf", 53.851, 9.345),
    ("Isar", 48.617, 12.293),
]

SWEEP_SCENARIOS: dict[str, dict] = {
    "stylised-df-severe-v4": {
        "capacity_gw": 0.0,
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-v4/networks/base_s_10_elec_.nc",
    },
    "stylised-df-severe-nuc-1.5-v4": {
        "capacity_gw": 1.5,
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-1.5-v4/networks/base_s_10_elec_.nc",
    },
    "stylised-df-severe-nuc-3.0-v4": {
        "capacity_gw": 3.0,
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-3.0-v4/networks/base_s_10_elec_.nc",
    },
    "stylised-df-severe-nuc-4.5-v4": {
        "capacity_gw": 4.5,
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-4.5-v4/networks/base_s_10_elec_.nc",
    },
    "stylised-df-severe-nuc-7.5-v4": {
        "capacity_gw": 7.5,
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-7.5-v4/networks/base_s_10_elec_.nc",
    },
}

OFFSHORE_CARRIERS = ["offwind-ac", "offwind-dc", "offwind-float"]
FOSSIL_CARRIERS = ["coal", "lignite", "CCGT", "biomass", "oil", "OCGT", "waste"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_inre_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def load_nuclear_cost_parameters(discount_rate: float = 0.07) -> dict:
    """Read generic-advanced-nuclear parameters from custom costs + project config."""
    raw = pd.read_csv(CUSTOM_COSTS)
    sub = raw.query("technology == @CARRIER and planning_horizon == '2050'")
    if sub.empty:
        raise KeyError(f"{CARRIER} not found in {CUSTOM_COSTS}")

    def _val(param: str) -> float:
        row = sub[sub.parameter == param]
        if row.empty:
            raise KeyError(f"Missing parameter {param} for {CARRIER}")
        return float(row.iloc[0]["value"])

    investment_kw = _val("investment")
    investment_mw = investment_kw * 1e3  # EUR/MW
    fom_pct = _val("FOM")
    vom = _val("VOM")
    fuel = _val("fuel")
    efficiency = _val("efficiency")
    lifetime = _val("lifetime")

    crf = float(calculate_annuity(lifetime, discount_rate))
    annuity_factor_fom = crf + fom_pct / 100.0
    capital_cost_per_mw_year = annuity_factor_fom * investment_mw
    marginal_cost = vom + fuel / efficiency
    annual_fom_per_mw = (fom_pct / 100.0) * investment_mw

    cfg = load_inre_config()
    nuclear_cfg = cfg.get("inre", {}).get("nuclear", {})
    p_min_pu = float(nuclear_cfg.get("p_min_pu", 0.0))
    ramp_limit_per_hour = float(nuclear_cfg.get("ramp_limit_per_hour", 0.5))
    p_max_pu = 0.9  # add_nuclear_technologies default availability

    return {
        "carrier": CARRIER,
        "investment_eur_per_kw": investment_kw,
        "investment_eur_per_mw": investment_mw,
        "capital_cost_eur_per_mw_year": capital_cost_per_mw_year,
        "fom_pct_per_year": fom_pct,
        "annual_fom_eur_per_mw_year": annual_fom_per_mw,
        "vom_eur_per_mwh": vom,
        "fuel_eur_per_mwh_th": fuel,
        "marginal_cost_eur_per_mwh": marginal_cost,
        "efficiency": efficiency,
        "p_max_pu": p_max_pu,
        "p_min_pu": p_min_pu,
        "ramp_limit_per_hour_pu": ramp_limit_per_hour,
        "lifetime_years": lifetime,
        "discount_rate": discount_rate,
        "annualisation_method": "calculate_annuity (PyPSA-EUR): CRF = r/(1-(1+r)^-n); "
        "capital_cost = (CRF + FOM/100) × investment [EUR/MW-year]",
        "crf": crf,
        "co2_intensity_t_per_mwh_el": 0.0,
        "p_min_pu_representation": "upper-flexibility representation without commitment binaries",
        "dispatch_mode": "unconstrained operational dispatch",
    }


def resolve_nuclear_buses(n: pypsa.Network) -> dict[str, str]:
    return {name: _nearest_bus(n, lat, lon) for name, lat, lon in NUCLEAR_SITES}


def add_fixed_nuclear(
    n: pypsa.Network,
    total_cap_mw: float,
    cost_params: dict,
    buses: dict[str, str],
) -> list[str]:
    """Add fixed generic nuclear at equal-site allocation."""
    if total_cap_mw <= 0:
        return []

    step_h = _snapshot_step_hours(n)
    ramp_per_snapshot = cost_params["ramp_limit_per_hour_pu"] * step_h
    per_site_mw = total_cap_mw / len(NUCLEAR_SITES)

    if CARRIER not in n.carriers.index:
        n.add("Carrier", CARRIER, co2_emissions=0.0)
    if CARRIER in NUCLEAR_COLORS:
        n.carriers.at[CARRIER, "color"] = NUCLEAR_COLORS[CARRIER]

    added: list[str] = []
    for site_name, bus in buses.items():
        gen_name = f"INRE {CARRIER} {site_name}"
        if gen_name in n.generators.index:
            raise RuntimeError(f"Generator {gen_name} already exists")
        n.add(
            "Generator",
            gen_name,
            bus=bus,
            carrier=CARRIER,
            p_nom=per_site_mw,
            p_nom_extendable=False,
            capital_cost=cost_params["capital_cost_eur_per_mw_year"],
            marginal_cost=cost_params["marginal_cost_eur_per_mwh"],
            efficiency=cost_params["efficiency"],
            lifetime=cost_params["lifetime_years"],
            p_max_pu=cost_params["p_max_pu"],
            p_min_pu=cost_params["p_min_pu"],
            ramp_limit_up=ramp_per_snapshot,
            ramp_limit_down=ramp_per_snapshot,
        )
        added.append(gen_name)
    return added


def non_nuclear_generators(n: pypsa.Network) -> pd.Index:
    return n.generators[
        ~n.generators.carrier.str.contains("nuclear", case=False, na=False)
    ].index


def compare_non_nuclear_inputs(ref: pypsa.Network, other: pypsa.Network) -> list[str]:
    issues: list[str] = []
    if not _series_equal_df(ref.loads_t.p_set, other.loads_t.p_set):
        issues.append("loads_t.p_set differs")
    if not _series_equal_df(ref.snapshot_weightings.objective, other.snapshot_weightings.objective):
        issues.append("snapshot_weightings.objective differs")

    ren_ref = ref.generators[ref.generators.carrier.isin(RENEWABLE_CARRIERS)].index
    for gen in ren_ref:
        if gen in ref.generators_t.p_max_pu.columns and gen in other.generators_t.p_max_pu.columns:
            if not _series_equal_df(ref.generators_t.p_max_pu[gen], other.generators_t.p_max_pu[gen]):
                issues.append(f"renewable p_max_pu differs for {gen}")
                break

    for comp, attr in [
        ("generators", "p_nom"),
        ("storage_units", "p_nom"),
        ("stores", "e_nom"),
        ("lines", "s_nom"),
        ("links", "p_nom"),
    ]:
        ref_idx = non_nuclear_generators(ref) if comp == "generators" else ref.generators.index
        if comp == "generators":
            v0 = ref.generators.loc[ref_idx, attr]
            v1 = other.generators.loc[non_nuclear_generators(other), attr]
        else:
            v0 = getattr(ref, comp)[attr]
            v1 = getattr(other, comp)[attr]
        if not _series_equal_df(v0, v1):
            issues.append(f"{comp}.{attr} differs (non-nuclear)")
            break

    for comp, attr in [
        ("generators", "p_nom_extendable"),
        ("storage_units", "p_nom_extendable"),
        ("stores", "e_nom_extendable"),
        ("lines", "s_nom_extendable"),
        ("links", "p_nom_extendable"),
    ]:
        obj = getattr(other, comp)
        if len(obj) and int(getattr(obj, attr).sum()):
            issues.append(f"{comp}.{attr} has extendable assets")

    ref_idx = non_nuclear_generators(ref)
    other_idx = non_nuclear_generators(other)
    if not _series_equal_df(ref.generators.loc[ref_idx, "marginal_cost"], other.generators.loc[other_idx, "marginal_cost"]):
        issues.append("non-nuclear marginal_cost differs")

    nuclear_carriers = set(ref.carriers.index).union(other.carriers.index)
    nuclear_carriers = {c for c in nuclear_carriers if "nuclear" in str(c).lower()}
    for car in ref.carriers.index.intersection(other.carriers.index):
        if car in nuclear_carriers:
            continue
        if not np.isclose(ref.carriers.at[car, "co2_emissions"], other.carriers.at[car, "co2_emissions"], rtol=1e-9):
            issues.append(f"carrier co2_emissions differs for {car}")
            break

    return issues


def nuclear_dispatch_metrics(
    n: pypsa.Network,
    snaps: pd.DatetimeIndex,
    capacity_gw: float,
    carrier: str | None = None,
) -> dict:
    if carrier:
        nuc_gens = n.generators[n.generators.carrier == carrier].index
    elif capacity_gw > 0:
        nuc_gens = n.generators[
            n.generators.carrier.str.contains("nuclear", case=False, na=False)
        ].index
    else:
        nuc_gens = n.generators.index[:0]
    if len(nuc_gens) == 0:
        return {
            "nuclear_installed_capacity_gw": 0.0,
            "nuclear_generation_twh": 0.0,
            "nuclear_capacity_factor_pct": 0.0,
            "nuclear_min_output_gw": 0.0,
            "nuclear_max_output_gw": 0.0,
            "max_nuclear_ramp_gw_per_snapshot": 0.0,
        }

    weight = _weight(n, snaps)
    p = n.generators_t.p[nuc_gens].reindex(snaps).fillna(0.0)
    total_p = p.sum(axis=1)
    energy_mwh = float((total_p * weight).sum())
    hours_equiv = float(weight.sum())
    p_nom_mw = float(n.generators.loc[nuc_gens, "p_nom"].sum())

    ramp = total_p.diff().abs()
    max_ramp_gw = float(ramp.max()) / 1e3 if len(ramp) else 0.0

    cf = 100.0 * energy_mwh / (p_nom_mw * hours_equiv) if p_nom_mw > 0 and hours_equiv > 0 else 0.0

    return {
        "nuclear_installed_capacity_gw": capacity_gw,
        "nuclear_generation_twh": energy_mwh / 1e6,
        "nuclear_capacity_factor_pct": cf,
        "nuclear_min_output_gw": float(total_p.min()) / 1e3,
        "nuclear_max_output_gw": float(total_p.max()) / 1e3,
        "max_nuclear_ramp_gw_per_snapshot": max_ramp_gw,
    }


def validate_nuclear_dispatch(n: pypsa.Network, cost_params: dict, carrier: str | None = None) -> dict:
    issues: list[str] = []
    car = carrier or cost_params.get("carrier") or CARRIER
    nuc_gens = n.generators[n.generators.carrier == car]
    if nuc_gens.empty:
        return {"ok": True, "issues": [], "ramp_binding": False, "max_ramp_violation_gw": 0.0}

    snaps = pd.DatetimeIndex(n.snapshots)
    p = n.generators_t.p[nuc_gens.index].reindex(snaps).fillna(0.0)
    p_nom = nuc_gens["p_nom"]
    p_max = cost_params["p_max_pu"]
    p_min = cost_params["p_min_pu"]

    for gen in nuc_gens.index:
        pmax = p_nom[gen] * p_max
        pmin = p_nom[gen] * p_min
        if (p[gen] > pmax + 1e-3).any():
            issues.append(f"{gen} exceeds p_max_pu")
        if (p[gen] < pmin - 1e-3).any():
            issues.append(f"{gen} below p_min_pu")

    step_h = _snapshot_step_hours(n)
    ramp_limit = cost_params["ramp_limit_per_hour_pu"] * step_h
    max_violation = 0.0
    ramp_binding = False
    for gen in nuc_gens.index:
        delta = p[gen].diff().abs()
        limit_mw = ramp_limit * p_nom[gen]
        viol = (delta - limit_mw - 1e-3).clip(lower=0.0)
        if viol.max() > 0:
            issues.append(f"{gen} ramp violation max {viol.max():.1f} MW")
        max_violation = max(max_violation, float(viol.max()))
        if limit_mw > 0 and (delta >= limit_mw - 1e-3).any():
            ramp_binding = True

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "ramp_binding": ramp_binding,
        "max_ramp_violation_gw": max_violation / 1e3,
        "ramp_limit_per_snapshot_pu": ramp_limit,
    }


def validate_nuclear_capacity(n: pypsa.Network, expected_gw: float, carrier: str | None = None) -> dict:
    car = carrier or CARRIER
    actual_mw = float(n.generators[n.generators.carrier == car]["p_nom"].sum())
    expected_mw = expected_gw * 1000.0
    ok = abs(actual_mw - expected_mw) < 1e-6
    return {
        "expected_gw": expected_gw,
        "actual_gw": actual_mw / 1000.0,
        "ok": ok,
    }


def carrier_twh(gen_by_carrier: pd.Series, carriers: list[str]) -> float:
    return float(sum(gen_by_carrier.get(c, 0.0) for c in carriers))


def build_summary_row(scenario: str, scope: str, m: dict, nuc: dict) -> dict:
    g = m["generation_by_carrier_twh"]
    fossil_total = carrier_twh(g, FOSSIL_CARRIERS)
    return {
        "scenario": scenario,
        "scope": scope,
        "dispatch_mode": "unconstrained operational dispatch",
        "demand_twh": round(m["demand_twh"], 4),
        "nuclear_installed_capacity_gw": round(nuc["nuclear_installed_capacity_gw"], 4),
        "nuclear_generation_twh": round(nuc["nuclear_generation_twh"], 4),
        "nuclear_capacity_factor_pct": round(nuc["nuclear_capacity_factor_pct"], 2),
        "nuclear_min_output_gw": round(nuc["nuclear_min_output_gw"], 4),
        "nuclear_max_output_gw": round(nuc["nuclear_max_output_gw"], 4),
        "max_nuclear_ramp_gw_per_snapshot": round(nuc["max_nuclear_ramp_gw_per_snapshot"], 4),
        "onshore_generation_twh": round(float(g.get("onwind", 0.0)), 4),
        "offshore_generation_twh": round(carrier_twh(g, OFFSHORE_CARRIERS), 4),
        "solar_generation_twh": round(float(g.get("solar", 0.0) + g.get("solar-hsat", 0.0)), 4),
        "coal_generation_twh": round(float(g.get("coal", 0.0)), 4),
        "lignite_generation_twh": round(float(g.get("lignite", 0.0)), 4),
        "ccgt_generation_twh": round(float(g.get("CCGT", 0.0)), 4),
        "biomass_generation_twh": round(float(g.get("biomass", 0.0)), 4),
        "total_fossil_generation_twh": round(fossil_total, 4),
        "renewable_curtailment_twh": round(m["renewable_curtailment_twh"], 4),
        "peak_load_shedding_gw": round(m["peak_load_shedding_gw"], 4),
        "eens_gwh": round(m["eens_gwh"], 4),
        "eens_pct_demand": round(m["eens_pct_demand"], 4),
        "co2_kt": round(m["co2_kt"], 2),
        "co2_mt": round(m["co2_mt"], 4),
        "variable_opex_excl_voll_meur": round(m["variable_opex_excl_voll_meur"], 2),
        "load_shedding_penalty_meur": round(m["load_shedding_penalty_meur"], 2),
        "total_operational_cost_meur": round(m["total_operational_cost_meur"], 2),
    }


def indicative_fixed_costs(capacity_gw: float, cost_params: dict) -> dict:
    """Annual fixed cost = annualised CAPEX (CRF) + annual FOM; prorated to 14d/28d windows."""
    p_nom_mw = capacity_gw * 1000.0
    inv = cost_params["investment_eur_per_mw"]
    crf = cost_params["crf"]
    fom_per_mw = cost_params["annual_fom_eur_per_mw_year"]
    annualised_capital_eur = p_nom_mw * inv * crf
    annual_fom_eur = p_nom_mw * fom_per_mw
    annual_fixed_eur = annualised_capital_eur + annual_fom_eur
    return {
        "capacity_gw": capacity_gw,
        "annualised_capital_cost_meur_per_year": annualised_capital_eur / 1e6,
        "annual_fom_meur_per_year": annual_fom_eur / 1e6,
        "annual_fixed_cost_meur_per_year": annual_fixed_eur / 1e6,
        "core_period_equivalent_fixed_cost_meur": annual_fixed_eur * 14.0 / 365.0 / 1e6,
        "full_window_period_equivalent_fixed_cost_meur": annual_fixed_eur * 28.0 / 365.0 / 1e6,
        "annual_fom_included": True,
        "label": "indicative period-equivalent economic comparison",
        "comparison_capacity_note": (
            "4.5 GW is a standardised three-node comparison capacity, not an economic optimum"
        ),
    }


def can_reuse_reference(solved_path: Path, prepared_checksum: str) -> tuple[bool, str]:
    if not solved_path.exists():
        return False, "solved network missing"
    n = pypsa.Network(str(solved_path))
    if len(n.snapshots) != EXPECTED_SNAPSHOTS:
        return False, f"expected {EXPECTED_SNAPSHOTS} snapshots, got {len(n.snapshots)}"
    meta = load_metadata()
    phases = demand_by_phase_twh(n, meta)
    if abs(phases["full-window"] - 42.74) > 0.5:
        return False, f"full-window demand {phases['full-window']:.2f} TWh != ~42.74"
    if n.generators[n.generators.carrier == CARRIER].shape[0] > 0:
        return False, "reference contains nuclear generators"
    return True, f"prepared checksum {prepared_checksum[:16]}…; demand validated"


def create_plots(
    summary_core: pd.DataFrame,
    summary_full: pd.DataFrame,
    benefits: pd.DataFrame,
    marginal: pd.DataFrame,
    economics: pd.DataFrame,
    solved: dict[str, pypsa.Network],
    meta: dict,
    output_dir: Path,
) -> None:
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    nuc = summary_core[summary_core["nuclear_installed_capacity_gw"] > 0].copy()
    if nuc.empty:
        return

    cap = nuc["nuclear_installed_capacity_gw"]

    def _save(fig, name: str) -> None:
        fig.tight_layout()
        fig.savefig(plot_dir / f"{name}.png", dpi=150)
        fig.savefig(plot_dir / f"{name}.pdf")
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cap, nuc["nuclear_generation_twh"], "o-")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("Nuclear generation [TWh]")
    ax.set_title("Core: nuclear capacity vs generation")
    _save(fig, "01_capacity_vs_nuclear_generation")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cap, nuc["nuclear_capacity_factor_pct"], "o-")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("Capacity factor [%]")
    ax.set_title("Core: nuclear capacity factor")
    _save(fig, "02_capacity_vs_capacity_factor")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cap, nuc["total_fossil_generation_twh"], "o-")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("Fossil generation [TWh]")
    ax.set_title("Core: fossil generation vs nuclear capacity")
    _save(fig, "03_capacity_vs_fossil_generation")

    fig, ax = plt.subplots(figsize=(8, 4))
    width = 0.25
    x = np.arange(len(cap))
    ax.bar(x - width, benefits["coal_displacement_twh"], width, label="coal")
    ax.bar(x, benefits["lignite_displacement_twh"], width, label="lignite")
    ax.bar(x + width, benefits["ccgt_displacement_twh"], width, label="CCGT")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{c:.1f}" for c in cap])
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("Displacement [TWh]")
    ax.set_title("Core: fossil displacement by fuel")
    ax.legend()
    _save(fig, "04_fossil_displacement_by_fuel")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cap, nuc["co2_mt"], "o-")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("CO₂ [Mt]")
    ax.set_title("Core: CO₂ emissions")
    _save(fig, "05_capacity_vs_co2")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cap, benefits["co2_avoided_mt"], "o-")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("CO₂ avoided [Mt]")
    ax.set_title("Core: CO₂ avoided vs severe reference")
    _save(fig, "06_capacity_vs_co2_avoided")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cap, nuc["total_operational_cost_meur"], "o-")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("Operational cost [M EUR]")
    ax.set_title("Core: operational cost")
    _save(fig, "07_capacity_vs_operational_cost")

    fig, ax = plt.subplots(figsize=(7, 4))
    econ_core = economics_df[economics_df["scope"] == "core"]
    econ_full = economics_df[economics_df["scope"] == "full_window"]
    caps = econ_core["capacity_gw"]
    ax.plot(caps, econ_core["indicative_total_cost_meur"], "o-", label="core indicative total")
    ax.plot(caps, econ_full["indicative_total_cost_meur"], "s--", label="full-window indicative total")
    ax.plot(caps, econ_core["operational_cost_meur"], "^:", label="core operational")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("Cost [M EUR]")
    ax.set_title("Indicative period-equivalent total cost (core vs full window)")
    ax.legend()
    _save(fig, "08_capacity_vs_indicative_total_cost")

    if not marginal.empty:
        fig, ax = plt.subplots(figsize=(7, 4))
        labels = marginal["capacity_interval"]
        ax.bar(range(len(labels)), marginal["marginal_co2_benefit_mt_per_gw"])
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=15)
        ax.set_ylabel("Marginal CO₂ benefit [Mt/GW]")
        ax.set_title("Marginal CO₂ benefit per additional GW")
        _save(fig, "09_marginal_co2_benefit")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cap, benefits["curtailment_change_twh"], "o-")
    ax.set_xlabel("Nuclear capacity [GW]")
    ax.set_ylabel("Curtailment change [TWh]")
    ax.set_title("Core: renewable curtailment change vs reference")
    _save(fig, "10_curtailment_vs_capacity")

    # Nuclear dispatch core
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    fig, ax = plt.subplots(figsize=(12, 4))
    for key in sorted(solved.keys()):
        if key == "stylised-df-severe-v4":
            continue
        n = solved[key]
        nuc_gens = n.generators[n.generators.carrier == CARRIER].index
        if len(nuc_gens) == 0:
            continue
        snaps = _slice_snapshots(n, core_start, core_end)
        p_gw = n.generators_t.p[nuc_gens].reindex(snaps).fillna(0).sum(axis=1) / 1e3
        ax.plot(snaps, p_gw, label=f"{SWEEP_SCENARIOS[key]['capacity_gw']:.1f} GW")
    ax.set_title("Core: nuclear dispatch by capacity scenario")
    ax.set_ylabel("GW")
    ax.legend(fontsize=8)
    _save(fig, "11_nuclear_dispatch_core")

    # Generation stack severe vs 7.5 GW
    ref_key = "stylised-df-severe-v4"
    nuc_key = "stylised-df-severe-nuc-7.5-v4"
    if ref_key in solved and nuc_key in solved:
        snaps = _slice_snapshots(solved[ref_key], core_start, core_end)
        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        for ax, key, title in [
            (axes[0], ref_key, "Severe reference"),
            (axes[1], nuc_key, "7.5 GW nuclear"),
        ]:
            n = solved[key]
            stack_carriers = ["onwind", "offwind-ac", "solar", "CCGT", "coal", "lignite", CARRIER]
            stack, labels = [], []
            for car in stack_carriers:
                gens = n.generators[n.generators.carrier == car].index
                if len(gens):
                    s = n.generators_t.p[gens].reindex(snaps).fillna(0).sum(axis=1) / 1e3
                    stack.append(s.values)
                    labels.append(car)
            if stack:
                ax.stackplot(snaps, stack, labels=labels, alpha=0.85)
            demand = n.loads_t.p_set.reindex(snaps).sum(axis=1) / 1e3
            ax.plot(snaps, demand, "k--", lw=1)
            ax.set_ylabel("GW")
            ax.set_title(title)
        axes[1].set_xlabel("Time")
        _save(fig, "12_reference_vs_nuclear_stack")


def identify_knee(marginal: pd.DataFrame, benefits: pd.DataFrame, economics: pd.DataFrame) -> dict:
    """Heuristic knee: largest relative drop in marginal CO2 benefit between intervals."""
    if marginal.empty:
        return {"knee_observed": False, "recommended_capacity_gw": 3.0, "reason": "insufficient data"}

    mco2 = marginal["marginal_co2_benefit_mt_per_gw"].values
    caps = benefits["capacity_gw"].values
    intervals = marginal["capacity_interval"].tolist()

    drops = []
    for i in range(1, len(mco2)):
        if mco2[i - 1] > 0:
            drops.append((i, (mco2[i - 1] - mco2[i]) / mco2[i - 1]))
        else:
            drops.append((i, 0.0))

    knee_idx = max(drops, key=lambda x: x[1])[0] if drops else 0
    knee_cap = caps[knee_idx] if knee_idx < len(caps) else caps[-1]

    # Recommend capacity balancing marginal benefit and indicative total cost
    econ = economics_df[economics_df["scope"] == "core"].copy()
    econ["marginal_total"] = econ["indicative_total_cost_meur"].diff()
    # Default to 3 GW unless 4.5 clearly dominates on CO2 per GW at knee
    recommended = 3.0
    if knee_cap <= 3.0:
        recommended = 3.0
    elif knee_cap == 4.5:
        recommended = 4.5

    return {
        "knee_observed": any(d[1] > 0.25 for d in drops),
        "knee_interval": intervals[knee_idx] if knee_idx < len(intervals) else None,
        "recommended_capacity_gw": recommended,
        "marginal_co2_values": mco2.tolist(),
    }


def run_nuclear_sweep(solver: str = "highs") -> dict:
    meta = load_metadata()
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    cost_params = load_nuclear_cost_parameters()
    prepared_checksum = sha256_file(PREPARED_SEVERE)

    if not PREPARED_SEVERE.exists():
        raise FileNotFoundError(f"Prepared severe network missing: {PREPARED_SEVERE}")

    buses = resolve_nuclear_buses(pypsa.Network(str(PREPARED_SEVERE)))
    step_h = 3.0
    ramp_snapshot = cost_params["ramp_limit_per_hour_pu"] * step_h

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    solve_results: dict[str, dict] = {}
    solved_networks: dict[str, pypsa.Network] = {}
    validations: dict[str, dict] = {}
    equality_rows: list[dict] = []
    location_rows = [
        {"site": s, "bus": b, "lat": lat, "lon": lon}
        for s, lat, lon in NUCLEAR_SITES
        for b in [buses[s]]
    ]

    ref_key = "stylised-df-severe-v4"
    reuse_ref, reuse_reason = can_reuse_reference(
        SWEEP_SCENARIOS[ref_key]["solved"], prepared_checksum
    )
    logger.info("Reference reuse: %s (%s)", reuse_ref, reuse_reason)

    for key, cfg in SWEEP_SCENARIOS.items():
        capacity_gw = cfg["capacity_gw"]
        solved_path = cfg["solved"]

        if key == ref_key and reuse_ref:
            logger.info("Loading reused reference %s", solved_path)
            n = pypsa.Network(str(solved_path))
            info = {
                "status": "ok",
                "condition": "optimal",
                "objective": float(n.objective),
                "solve_time_s": 0.0,
                "reused": True,
            }
            validation = validate_solved(n, info)
            solve_results[key] = {**info, "validation": validation}
            solved_networks[key] = n
            validations[key] = {
                "energy_balance": validation,
                "nuclear_capacity": validate_nuclear_capacity(n, capacity_gw),
                "nuclear_dispatch": {"ok": True, "issues": [], "ramp_binding": False},
            }
            continue

        logger.info("Solving %s (%.1f GW nuclear)", key, capacity_gw)
        n = pypsa.Network(str(PREPARED_SEVERE))
        add_fixed_nuclear(n, capacity_gw * 1000.0, cost_params, buses)
        prepare_for_solve(n)

        info = solve_network(n, solver=solver)
        info["reused"] = False
        validation = validate_solved(n, info)
        nuc_val = validate_nuclear_dispatch(n, cost_params)
        cap_val = validate_nuclear_capacity(n, capacity_gw)

        solve_results[key] = {**info, "validation": validation}
        validations[key] = {
            "energy_balance": validation,
            "nuclear_capacity": cap_val,
            "nuclear_dispatch": nuc_val,
        }

        if not validation["ok"] or not nuc_val["ok"] or not cap_val["ok"]:
            issues = validation["issues"] + nuc_val["issues"]
            if not cap_val["ok"]:
                issues.append(f"nuclear capacity mismatch: {cap_val}")
            raise RuntimeError(f"Validation failed for {key}: {issues}")

        solved_path.parent.mkdir(parents=True, exist_ok=True)
        n.export_to_netcdf(str(solved_path))
        solved_networks[key] = n

        if key != ref_key:
            eq_issues = compare_non_nuclear_inputs(solved_networks[ref_key], n)
            equality_rows.append(
                {
                    "scenario": key,
                    "identical_non_nuclear": len(eq_issues) == 0,
                    "issues": "; ".join(eq_issues) if eq_issues else "",
                }
            )
            if eq_issues:
                raise RuntimeError(f"Non-nuclear input mismatch for {key}: {eq_issues}")

    # Metrics export
    summary_rows: list[dict] = []
    gen_core_rows: list[dict] = []
    gen_full_rows: list[dict] = []
    dispatch_rows: list[dict] = []
    ramp_rows: list[dict] = []
    fixed_cap_rows: list[dict] = []
    solver_rows: list[dict] = []
    balance_rows: list[dict] = []

    for key, n in solved_networks.items():
        capacity_gw = SWEEP_SCENARIOS[key]["capacity_gw"]
        for scope_name, snaps in [
            ("core", _slice_snapshots(n, core_start, core_end)),
            ("full_window", pd.DatetimeIndex(n.snapshots)),
        ]:
            m = extract_metrics(n, scope_name, snaps)
            nuc = nuclear_dispatch_metrics(n, snaps, capacity_gw)
            summary_rows.append(build_summary_row(key, scope_name, m, nuc))
            for carrier, val in m["generation_by_carrier_twh"].items():
                row = {"scenario": key, "carrier": carrier, "generation_twh": round(float(val), 4)}
                if scope_name == "core":
                    gen_core_rows.append(row)
                else:
                    gen_full_rows.append(row)

        nuc_val = validations[key]["nuclear_dispatch"]
        ramp_rows.append(
            {
                "scenario": key,
                "ramp_limit_per_hour_pu": cost_params["ramp_limit_per_hour_pu"],
                "ramp_limit_per_snapshot_pu": ramp_snapshot,
                "snapshot_hours": step_h,
                "ramp_binding": nuc_val.get("ramp_binding", False),
                "max_ramp_violation_gw": nuc_val.get("max_ramp_violation_gw", 0.0),
                "status": "ok" if nuc_val.get("ok", True) else "fail",
            }
        )
        dispatch_rows.append(
            {
                "scenario": key,
                "capacity_gw": capacity_gw,
                **{k: v for k, v in nuclear_dispatch_metrics(n, _slice_snapshots(n, core_start, core_end), capacity_gw).items()},
            }
        )
        for comp, attr in [
            ("generators", "p_nom_extendable"),
            ("storage_units", "p_nom_extendable"),
            ("stores", "e_nom_extendable"),
            ("lines", "s_nom_extendable"),
            ("links", "p_nom_extendable"),
        ]:
            obj = getattr(n, comp)
            fixed_cap_rows.append(
                {
                    "scenario": key,
                    "component": comp,
                    "attribute": attr,
                    "extendable_count": int(getattr(obj, attr).sum()) if len(obj) else 0,
                    "status": "ok" if (not len(obj) or int(getattr(obj, attr).sum()) == 0) else "fail",
                }
            )

        sr = solve_results[key]
        solver_rows.append(
            {
                "scenario": key,
                "status": sr["status"],
                "condition": sr.get("condition", ""),
                "objective_meur": round(float(sr["objective"]) / 1e6, 2),
                "solve_time_s": round(sr.get("solve_time_s", 0.0), 1),
                "reused": sr.get("reused", False),
                "dispatch_mode": "unconstrained operational dispatch",
            }
        )
        balance_rows.append(
            {
                "scenario": key,
                "max_imbalance_mw": validations[key]["energy_balance"]["max_imbalance_mw"],
                "validation_ok": validations[key]["energy_balance"]["ok"],
                "issues": "; ".join(validations[key]["energy_balance"]["issues"]),
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_core = summary_df[summary_df["scope"] == "core"].copy()
    summary_full = summary_df[summary_df["scope"] == "full_window"].copy()

    ref_core = summary_core[summary_core["scenario"] == ref_key].iloc[0]
    ref_full = summary_full[summary_full["scenario"] == ref_key].iloc[0]

    benefits_rows: list[dict] = []
    for _, row in summary_core[summary_core["scenario"] != ref_key].iterrows():
        cap = row["nuclear_installed_capacity_gw"]
        benefits_rows.append(
            {
                "scenario": row["scenario"],
                "capacity_gw": cap,
                "co2_avoided_mt": ref_core["co2_mt"] - row["co2_mt"],
                "coal_displacement_twh": ref_core["coal_generation_twh"] - row["coal_generation_twh"],
                "lignite_displacement_twh": ref_core["lignite_generation_twh"] - row["lignite_generation_twh"],
                "ccgt_displacement_twh": ref_core["ccgt_generation_twh"] - row["ccgt_generation_twh"],
                "total_fossil_displacement_twh": ref_core["total_fossil_generation_twh"] - row["total_fossil_generation_twh"],
                "operational_cost_change_meur": row["total_operational_cost_meur"] - ref_core["total_operational_cost_meur"],
                "curtailment_change_twh": row["renewable_curtailment_twh"] - ref_core["renewable_curtailment_twh"],
                "co2_avoided_per_nuclear_twh": (
                    (ref_core["co2_mt"] - row["co2_mt"]) / row["nuclear_generation_twh"]
                    if row["nuclear_generation_twh"] > 0
                    else np.nan
                ),
            }
        )
    benefits_df = pd.DataFrame(benefits_rows)

    caps_sorted = sorted([c for c in SWEEP_SCENARIOS.values() if c["capacity_gw"] > 0], key=lambda x: x["capacity_gw"])
    marginal_rows: list[dict] = []
    prev_cap = 0.0
    prev_co2 = ref_core["co2_mt"]
    prev_fossil = ref_core["total_fossil_generation_twh"]
    for cfg in caps_sorted:
        cap = cfg["capacity_gw"]
        row = summary_core[summary_core["nuclear_installed_capacity_gw"] == cap].iloc[0]
        dcap = cap - prev_cap
        if dcap > 0:
            marginal_rows.append(
                {
                    "capacity_interval": f"{prev_cap:.1f}→{cap:.1f} GW",
                    "marginal_co2_benefit_mt_per_gw": (prev_co2 - row["co2_mt"]) / dcap,
                    "marginal_fossil_displacement_twh_per_gw": (prev_fossil - row["total_fossil_generation_twh"]) / dcap,
                }
            )
        prev_cap = cap
        prev_co2 = row["co2_mt"]
        prev_fossil = row["total_fossil_generation_twh"]
    marginal_df = pd.DataFrame(marginal_rows)

    economics_rows: list[dict] = []
    for cap in sorted(summary_core["nuclear_installed_capacity_gw"].unique()):
        fixed = indicative_fixed_costs(cap, cost_params)
        core_row = summary_core[summary_core["nuclear_installed_capacity_gw"] == cap].iloc[0]
        full_row = summary_full[summary_full["nuclear_installed_capacity_gw"] == cap].iloc[0]
        economics_rows.append(
            {
                "capacity_gw": cap,
                "scope": "core",
                "operational_cost_meur": round(core_row["total_operational_cost_meur"], 2),
                "period_equivalent_fixed_cost_meur": round(fixed["core_period_equivalent_fixed_cost_meur"], 2),
                "indicative_total_cost_meur": round(
                    core_row["total_operational_cost_meur"] + fixed["core_period_equivalent_fixed_cost_meur"], 2
                ),
                "annualised_capital_cost_meur_per_year": round(fixed["annualised_capital_cost_meur_per_year"], 2),
                "annual_fom_meur_per_year": round(fixed["annual_fom_meur_per_year"], 2),
                "annual_fixed_cost_meur_per_year": round(fixed["annual_fixed_cost_meur_per_year"], 2),
                "annual_fom_included": True,
                "label": fixed["label"],
                "comparison_capacity_note": fixed["comparison_capacity_note"],
            }
        )
        economics_rows.append(
            {
                "capacity_gw": cap,
                "scope": "full_window",
                "operational_cost_meur": round(full_row["total_operational_cost_meur"], 2),
                "period_equivalent_fixed_cost_meur": round(fixed["full_window_period_equivalent_fixed_cost_meur"], 2),
                "indicative_total_cost_meur": round(
                    full_row["total_operational_cost_meur"] + fixed["full_window_period_equivalent_fixed_cost_meur"], 2
                ),
                "annualised_capital_cost_meur_per_year": round(fixed["annualised_capital_cost_meur_per_year"], 2),
                "annual_fom_meur_per_year": round(fixed["annual_fom_meur_per_year"], 2),
                "annual_fixed_cost_meur_per_year": round(fixed["annual_fixed_cost_meur_per_year"], 2),
                "annual_fom_included": True,
                "label": fixed["label"],
                "comparison_capacity_note": fixed["comparison_capacity_note"],
            }
        )
    economics_df = pd.DataFrame(economics_rows)

    # Nuclear parameters export
    param_rows = [
        {"parameter": k, "value": v}
        for k, v in {
            **cost_params,
            "selected_buses": ", ".join(f"{s}→{b}" for s, b in buses.items()),
            "ramp_limit_per_snapshot_pu": ramp_snapshot,
            "allocation": "equal per site: total/3",
        }.items()
    ]

    # Cost reconciliation full window
    cost_validation_rows: list[dict] = []
    for key, n in solved_networks.items():
        snaps = pd.DatetimeIndex(n.snapshots)
        var, voll, total = _cost_breakdown(n, snaps)
        obj = float(n.objective) / 1e6
        cost_validation_rows.append(
            {
                "scenario": key,
                "computed_meur": total,
                "objective_meur": obj,
                "gap_meur": abs(total - obj),
                "status": "ok" if abs(total - obj) < 0.5 else "fail",
            }
        )

    # Write exports
    summary_df.to_csv(OUTPUT_DIR / "nuclear_sweep_summary.csv", index=False)
    pd.DataFrame(param_rows).to_csv(OUTPUT_DIR / "nuclear_parameters.csv", index=False)
    pd.DataFrame(location_rows).to_csv(OUTPUT_DIR / "nuclear_location_validation.csv", index=False)
    pd.DataFrame(
        [{"reference": ref_key, "prepared_checksum_sha256": prepared_checksum, "reference_reused": reuse_ref, "reuse_reason": reuse_reason}]
        + equality_rows
    ).to_csv(OUTPUT_DIR / "scenario_input_equality.csv", index=False)
    pd.DataFrame(gen_core_rows).to_csv(OUTPUT_DIR / "generation_by_carrier_core.csv", index=False)
    pd.DataFrame(gen_full_rows).to_csv(OUTPUT_DIR / "generation_by_carrier_full_window.csv", index=False)
    benefits_df.to_csv(OUTPUT_DIR / "fossil_displacement.csv", index=False)
    benefits_df[["scenario", "capacity_gw", "co2_avoided_mt", "co2_avoided_per_nuclear_twh"]].to_csv(
        OUTPUT_DIR / "co2_avoided.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "scenario": r["scenario"],
                "capacity_gw": r["capacity_gw"],
                "operational_cost_change_meur": r["operational_cost_change_meur"],
                "reference_opex_meur": ref_core["total_operational_cost_meur"],
                "scenario_opex_meur": summary_core[summary_core["scenario"] == r["scenario"]].iloc[0]["total_operational_cost_meur"],
            }
            for r in benefits_rows
        ]
    ).to_csv(OUTPUT_DIR / "operational_cost_comparison.csv", index=False)
    economics_df.to_csv(OUTPUT_DIR / "indicative_fixed_cost_comparison.csv", index=False)
    pd.DataFrame(dispatch_rows).to_csv(OUTPUT_DIR / "nuclear_dispatch_summary.csv", index=False)
    pd.DataFrame(ramp_rows).to_csv(OUTPUT_DIR / "nuclear_ramp_validation.csv", index=False)
    pd.DataFrame(balance_rows).to_csv(OUTPUT_DIR / "energy_balance_validation.csv", index=False)
    pd.DataFrame(fixed_cap_rows).to_csv(OUTPUT_DIR / "fixed_capacity_validation.csv", index=False)
    pd.DataFrame(solver_rows).to_csv(OUTPUT_DIR / "solver_status.csv", index=False)
    pd.DataFrame(cost_validation_rows).to_csv(OUTPUT_DIR / "cost_reconciliation.csv", index=False)

    knee = identify_knee(marginal_df, benefits_df, economics_df)
    create_plots(summary_core, summary_full, benefits_df, marginal_df, economics_df, solved_networks, meta, OUTPUT_DIR)

    all_ok = all(v["energy_balance"]["ok"] for v in validations.values())
    all_ok &= all(r["status"] == "ok" for r in cost_validation_rows)
    all_ok &= all(r["extendable_count"] == 0 for r in fixed_cap_rows)

    return {
        "cost_params": cost_params,
        "buses": buses,
        "ramp_snapshot": ramp_snapshot,
        "solve_results": solve_results,
        "summary_core": summary_core,
        "summary_full": summary_full,
        "benefits": benefits_df,
        "marginal": marginal_df,
        "economics": economics_df,
        "validations": validations,
        "knee": knee,
        "reference_reused": reuse_ref,
        "all_ok": all_ok,
        "cost_validation": cost_validation_rows,
        "equality_rows": equality_rows,
    }


def regenerate_indicative_economics(output_dir: Path | None = None) -> pd.DataFrame:
    """Regenerate indicative_fixed_cost_comparison.csv from existing sweep summary."""
    out = output_dir or OUTPUT_DIR
    summary_path = out / "nuclear_sweep_summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing {summary_path}; run nuclear sweep first")
    summary_df = pd.read_csv(summary_path)
    summary_core = summary_df[summary_df["scope"] == "core"]
    summary_full = summary_df[summary_df["scope"] == "full_window"]
    cost_params = load_nuclear_cost_parameters()
    economics_rows: list[dict] = []
    for cap in sorted(summary_core["nuclear_installed_capacity_gw"].unique()):
        fixed = indicative_fixed_costs(cap, cost_params)
        core_row = summary_core[summary_core["nuclear_installed_capacity_gw"] == cap].iloc[0]
        full_row = summary_full[summary_full["nuclear_installed_capacity_gw"] == cap].iloc[0]
        for scope_name, op_row, period_key in [
            ("core", core_row, "core_period_equivalent_fixed_cost_meur"),
            ("full_window", full_row, "full_window_period_equivalent_fixed_cost_meur"),
        ]:
            economics_rows.append(
                {
                    "capacity_gw": cap,
                    "scope": scope_name,
                    "operational_cost_meur": round(op_row["total_operational_cost_meur"], 2),
                    "period_equivalent_fixed_cost_meur": round(fixed[period_key], 2),
                    "indicative_total_cost_meur": round(
                        op_row["total_operational_cost_meur"] + fixed[period_key], 2
                    ),
                    "annualised_capital_cost_meur_per_year": round(fixed["annualised_capital_cost_meur_per_year"], 2),
                    "annual_fom_meur_per_year": round(fixed["annual_fom_meur_per_year"], 2),
                    "annual_fixed_cost_meur_per_year": round(fixed["annual_fixed_cost_meur_per_year"], 2),
                    "annual_fom_included": True,
                    "label": fixed["label"],
                    "comparison_capacity_note": fixed["comparison_capacity_note"],
                }
            )
    economics_df = pd.DataFrame(economics_rows)
    economics_df.to_csv(out / "indicative_fixed_cost_comparison.csv", index=False)
    return economics_df


def main() -> None:
    parser = argparse.ArgumentParser(description="V4 generic nuclear capacity sweep")
    parser.add_argument("--solver", default="highs")
    parser.add_argument(
        "--economics-only",
        action="store_true",
        help="Regenerate indicative_fixed_cost_comparison.csv from existing sweep summary",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.economics_only:
        regenerate_indicative_economics()
        print("Regenerated indicative_fixed_cost_comparison.csv")
        return
    result = run_nuclear_sweep(solver=args.solver)
    print(json.dumps({"all_ok": result["all_ok"], "knee": result["knee"]}, indent=2))


if __name__ == "__main__":
    main()
