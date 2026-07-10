# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
V4 equal-capacity SMR / MSR / LFR reactor comparison on stylised severe Dunkelflaute.

Solves stylised-df-severe-smr-v4, -msr-v4, -lfr-v4 at 4.5 GW (3×1.5 GW).
Reuses severe reference and generic-advanced-nuclear 4.5 GW solved networks.

Usage::

    pixi run python scripts/inre/run_v4_reactor_comparison.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

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
from scripts.inre.run_v4_nuclear_sweep import (
    FOSSIL_CARRIERS,
    NUCLEAR_SITES,
    PREPARED_SEVERE,
    carrier_twh,
    compare_non_nuclear_inputs,
    indicative_fixed_costs,
    load_nuclear_cost_parameters,
    nuclear_dispatch_metrics,
    validate_nuclear_capacity,
    validate_nuclear_dispatch,
)
from scripts.inre.run_v4_stage1 import (
    EXPECTED_SNAPSHOTS,
    METADATA_PATH,
    _cost_breakdown,
    _slice_snapshots,
    extract_metrics,
    load_metadata,
    prepare_for_solve,
    solve_network,
    validate_solved,
)

logger = logging.getLogger(__name__)

COMPARISON_CAPACITY_GW = 4.5
PER_SITE_MW = 1500.0
OUTPUT_DIR = REPO_ROOT / "results/inre-comparison-v4-reactor-comparison"
SWEEP_ECONOMICS = REPO_ROOT / "results/inre-comparison-v4-nuclear-sweep/indicative_fixed_cost_comparison.csv"

REACTOR_CARRIERS = ["nuclear-smr", "nuclear-msr", "nuclear-lfr"]

REACTOR_SCENARIOS = {
    "stylised-df-severe-smr-v4": {
        "carrier": "nuclear-smr",
        "label": "SMR",
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-smr-v4/networks/base_s_10_elec_.nc",
    },
    "stylised-df-severe-msr-v4": {
        "carrier": "nuclear-msr",
        "label": "MSR",
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-msr-v4/networks/base_s_10_elec_.nc",
    },
    "stylised-df-severe-lfr-v4": {
        "carrier": "nuclear-lfr",
        "label": "LFR",
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-lfr-v4/networks/base_s_10_elec_.nc",
    },
}

REUSED_SCENARIOS = {
    "severe_reference": {
        "carrier": None,
        "label": "Severe reference",
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-v4/networks/base_s_10_elec_.nc",
        "capacity_gw": 0.0,
    },
    "generic-advanced-nuclear": {
        "carrier": "generic-advanced-nuclear",
        "label": "Generic advanced nuclear",
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-4.5-v4/networks/base_s_10_elec_.nc",
        "capacity_gw": 4.5,
    },
}


def load_technology_cost_parameters(carrier: str, discount_rate: float = 0.07) -> dict:
    params = load_nuclear_cost_parameters(discount_rate=discount_rate)
    if carrier == "generic-advanced-nuclear":
        return params

    raw = pd.read_csv(REPO_ROOT / "data/inre/custom_costs_nuclear.csv")
    sub = raw.query("technology == @carrier and planning_horizon == '2050'")

    def _val(param: str) -> float:
        row = sub[sub.parameter == param]
        if row.empty:
            raise KeyError(f"Missing {param} for {carrier}")
        return float(row.iloc[0]["value"])

    investment_kw = _val("investment")
    investment_mw = investment_kw * 1e3
    fom_pct = _val("FOM")
    vom = _val("VOM")
    fuel = _val("fuel")
    efficiency = _val("efficiency")
    lifetime = _val("lifetime")
    crf = float(calculate_annuity(lifetime, discount_rate))
    annual_fom_per_mw = (fom_pct / 100.0) * investment_mw
    marginal_cost = vom + fuel / efficiency

    cfg = yaml.safe_load((REPO_ROOT / "config/inre/config.base.yaml").read_text())
    nuclear_cfg = cfg.get("inre", {}).get("nuclear", {})
    p_min_pu = 0.0
    ramp_limit_per_hour = float(nuclear_cfg.get("ramp_limit_per_hour", 0.5))
    p_max_pu = 0.9

    return {
        "carrier": carrier,
        "investment_eur_per_kw": investment_kw,
        "investment_eur_per_mw": investment_mw,
        "fom_pct_per_year": fom_pct,
        "annual_fom_eur_per_mw_year": annual_fom_per_mw,
        "fom_eur_per_kw_year": fom_pct / 100.0 * investment_kw,
        "vom_eur_per_mwh": vom,
        "fuel_eur_per_mwh_th": fuel,
        "marginal_cost_eur_per_mwh": marginal_cost,
        "efficiency": efficiency,
        "p_max_pu": p_max_pu,
        "p_min_pu": p_min_pu,
        "ramp_limit_per_hour_pu": ramp_limit_per_hour,
        "lifetime_years": lifetime,
        "discount_rate": discount_rate,
        "crf": crf,
        "p_min_pu_representation": "upper-flexibility representation without commitment binaries",
        "dispatch_mode": "unconstrained operational dispatch",
    }


def resolve_nuclear_buses(n: pypsa.Network) -> dict[str, str]:
    return {name: _nearest_bus(n, lat, lon) for name, lat, lon in NUCLEAR_SITES}


def add_fixed_nuclear(
    n: pypsa.Network,
    carrier: str,
    total_cap_mw: float,
    cost_params: dict,
    buses: dict[str, str],
) -> list[str]:
    if total_cap_mw <= 0:
        return []

    step_h = _snapshot_step_hours(n)
    ramp_per_snapshot = cost_params["ramp_limit_per_hour_pu"] * step_h
    per_site_mw = total_cap_mw / len(NUCLEAR_SITES)

    if carrier not in n.carriers.index:
        n.add("Carrier", carrier, co2_emissions=0.0)
    if carrier in NUCLEAR_COLORS:
        n.carriers.at[carrier, "color"] = NUCLEAR_COLORS[carrier]

    added: list[str] = []
    for site_name, bus in buses.items():
        gen_name = f"INRE {carrier} {site_name}"
        if gen_name in n.generators.index:
            raise RuntimeError(f"Generator {gen_name} already exists")
        n.add(
            "Generator",
            gen_name,
            bus=bus,
            carrier=carrier,
            p_nom=per_site_mw,
            p_nom_extendable=False,
            capital_cost=0.0,
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


def comparison_row(
    technology: str,
    scope: str,
    m: dict,
    nuc: dict,
    ref_co2_mt: float,
    ref_opex: float,
) -> dict:
    g = m["generation_by_carrier_twh"]
    fossil_total = carrier_twh(g, FOSSIL_CARRIERS)
    co2_avoided = ref_co2_mt - m["co2_mt"]
    return {
        "technology": technology,
        "scope": scope,
        "nuclear_generation_twh": round(nuc["nuclear_generation_twh"], 4),
        "nuclear_capacity_factor_pct": round(nuc["nuclear_capacity_factor_pct"], 2),
        "coal_generation_twh": round(float(g.get("coal", 0.0)), 4),
        "lignite_generation_twh": round(float(g.get("lignite", 0.0)), 4),
        "ccgt_generation_twh": round(float(g.get("CCGT", 0.0)), 4),
        "total_fossil_generation_twh": round(fossil_total, 4),
        "co2_mt": round(m["co2_mt"], 4),
        "co2_avoided_mt": round(co2_avoided, 4),
        "variable_opex_meur": round(m["variable_opex_excl_voll_meur"], 2),
        "operational_savings_meur": round(ref_opex - m["total_operational_cost_meur"], 2),
        "total_operational_cost_meur": round(m["total_operational_cost_meur"], 2),
        "renewable_curtailment_twh": round(m["renewable_curtailment_twh"], 4),
        "eens_gwh": round(m["eens_gwh"], 4),
        "dispatch_mode": "unconstrained operational dispatch",
    }


def create_plots(
    core_df: pd.DataFrame,
    full_df: pd.DataFrame,
    benefits_df: pd.DataFrame,
    economics_df: pd.DataFrame,
    avoided_df: pd.DataFrame,
    solved: dict[str, pypsa.Network],
    meta: dict,
    output_dir: Path,
) -> None:
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    techs = [t for t in core_df["technology"] if t != "Severe reference"]
    core_nuc = core_df[core_df["technology"].isin(techs)]

    def _save(fig, name: str) -> None:
        fig.tight_layout()
        fig.savefig(plot_dir / f"{name}.png", dpi=150)
        fig.savefig(plot_dir / f"{name}.pdf")
        plt.close(fig)

    labels = core_nuc["technology"]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, core_nuc["nuclear_generation_twh"])
    ax.set_ylabel("TWh")
    ax.set_title("Core: nuclear generation by technology")
    _save(fig, "01_nuclear_generation")

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, core_nuc["nuclear_capacity_factor_pct"])
    ax.set_ylabel("%")
    ax.set_title("Core: nuclear capacity factor")
    _save(fig, "02_capacity_factor")

    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(labels))
    w = 0.25
    ax.bar(x - w, benefits_df.set_index("technology").loc[labels, "coal_displacement_twh"], w, label="coal")
    ax.bar(x, benefits_df.set_index("technology").loc[labels, "lignite_displacement_twh"], w, label="lignite")
    ax.bar(x + w, benefits_df.set_index("technology").loc[labels, "ccgt_displacement_twh"], w, label="CCGT")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15)
    ax.set_title("Core: fossil displacement by fuel")
    ax.legend()
    _save(fig, "03_fossil_displacement")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].bar(labels, core_nuc["co2_mt"])
    axes[0].set_title("Core CO₂ [Mt]")
    axes[1].bar(labels, core_nuc["co2_avoided_mt"])
    axes[1].set_title("Core CO₂ avoided [Mt]")
    _save(fig, "04_co2_emissions_avoided")

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, core_nuc["total_operational_cost_meur"])
    ax.set_title("Core operational cost [M EUR]")
    _save(fig, "05_operational_cost")

    econ_core = economics_df[economics_df["scope"] == "core"]
    econ_full = economics_df[economics_df["scope"] == "full_window"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].bar(econ_core["technology"], econ_core["indicative_total_cost_meur"])
    axes[0].set_title("Core indicative total cost")
    axes[1].bar(econ_full["technology"], econ_full["indicative_total_cost_meur"])
    axes[1].set_title("Full-window indicative total cost")
    _save(fig, "06_indicative_total_cost")

    ac = avoided_df[avoided_df["scope"] == "core"]
    ac = ac[ac["avoided_co2_cost_eur_per_t"].notna()]
    if not ac.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(ac["technology"], ac["avoided_co2_cost_eur_per_t"])
        ax.set_title("Core: indicative cost of avoided CO₂ [EUR/t]")
        _save(fig, "07_avoided_co2_cost")

    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    fig, ax = plt.subplots(figsize=(12, 4))
    for key, n in solved.items():
        if key == "severe_reference":
            continue
        carrier_cols = [c for c in n.generators.carrier.unique() if "nuclear" in str(c)]
        if not carrier_cols:
            continue
        nuc_gens = n.generators[n.generators.carrier.isin(carrier_cols)].index
        snaps = _slice_snapshots(n, core_start, core_end)
        p = n.generators_t.p[nuc_gens].reindex(snaps).fillna(0).sum(axis=1) / 1e3
        label = REACTOR_SCENARIOS.get(key, REUSED_SCENARIOS.get(key, {})).get("label", key)
        ax.plot(snaps, p, label=label)
    ax.set_ylabel("GW")
    ax.set_title("Core nuclear dispatch")
    ax.legend(fontsize=8)
    _save(fig, "08_core_nuclear_dispatch")

    ref_n = solved["severe_reference"]
    snaps = _slice_snapshots(ref_n, core_start, core_end)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for ax, key, title in [
        (axes[0], "severe_reference", "Severe reference"),
        (axes[1], "stylised-df-severe-smr-v4", "SMR (example reactor stack)"),
    ]:
        n = solved[key]
        stack_carriers = ["onwind", "offwind-ac", "solar", "CCGT", "coal", "lignite"] + [
            c for c in n.generators.carrier.unique() if "nuclear" in str(c)
        ]
        stack, labs = [], []
        for car in stack_carriers:
            gens = n.generators[n.generators.carrier == car].index
            if len(gens):
                stack.append(n.generators_t.p[gens].reindex(snaps).fillna(0).sum(axis=1).values / 1e3)
                labs.append(car)
        if stack:
            ax.stackplot(snaps, stack, labels=labs, alpha=0.85)
        ax.plot(snaps, n.loads_t.p_set.reindex(snaps).sum(axis=1) / 1e3, "k--", lw=1)
        ax.set_ylabel("GW")
        ax.set_title(title)
    _save(fig, "09_reference_vs_reactor_stack")


def run_reactor_comparison(solver: str = "highs") -> dict:
    meta = load_metadata()
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    buses = resolve_nuclear_buses(pypsa.Network(str(PREPARED_SEVERE)))
    prepared_checksum = hashlib.sha256(PREPARED_SEVERE.read_bytes()).hexdigest()

    tech_params = {c: load_technology_cost_parameters(c) for c in REACTOR_CARRIERS + ["generic-advanced-nuclear"]}
    ramp_snapshot = tech_params["nuclear-smr"]["ramp_limit_per_hour_pu"] * 3.0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    solved_networks: dict[str, pypsa.Network] = {}
    solve_results: dict[str, dict] = {}
    validations: dict[str, dict] = {}
    equality_rows: list[dict] = []

    # Load reused scenarios
    for key, cfg in REUSED_SCENARIOS.items():
        if not cfg["solved"].exists():
            raise FileNotFoundError(f"Missing reused network: {cfg['solved']}")
        n = pypsa.Network(str(cfg["solved"]))
        info = {"status": "ok", "condition": "optimal", "objective": float(n.objective), "solve_time_s": 0.0, "reused": True}
        validations[key] = {
            "energy_balance": validate_solved(n, info),
            "nuclear_capacity": validate_nuclear_capacity(n, cfg["capacity_gw"]),
            "nuclear_dispatch": {"ok": True, "issues": [], "ramp_binding": False},
        }
        solved_networks[key] = n
        solve_results[key] = info

    ref_n = solved_networks["severe_reference"]

    # Solve reactor scenarios
    for key, cfg in REACTOR_SCENARIOS.items():
        carrier = cfg["carrier"]
        logger.info("Solving %s (%s, 4.5 GW)", key, carrier)
        n = pypsa.Network(str(PREPARED_SEVERE))
        cost_params = tech_params[carrier]
        add_fixed_nuclear(n, carrier, COMPARISON_CAPACITY_GW * 1000.0, cost_params, buses)
        prepare_for_solve(n)

        info = solve_network(n, solver=solver)
        info["reused"] = False
        validation = validate_solved(n, info)
        cap_val = validate_nuclear_capacity(n, COMPARISON_CAPACITY_GW, carrier=carrier)
        nuc_val = validate_nuclear_dispatch(n, cost_params, carrier=carrier)

        if not validation["ok"] or not nuc_val["ok"] or not cap_val["ok"]:
            raise RuntimeError(f"Validation failed for {key}")

        # Verify bus allocation
        nuc_gens = n.generators[n.generators.carrier == carrier]
        for bus, expected in [("DE0 3", PER_SITE_MW), ("DE0 8", PER_SITE_MW), ("DE0 4", PER_SITE_MW)]:
            at_bus = nuc_gens[nuc_gens.bus == bus]["p_nom"].sum()
            if abs(at_bus - expected) > 1e-6:
                raise RuntimeError(f"{key}: bus {bus} has {at_bus} MW, expected {expected}")

        eq_issues = compare_non_nuclear_inputs(ref_n, n)
        equality_rows.append({"scenario": key, "identical_non_nuclear": len(eq_issues) == 0, "issues": "; ".join(eq_issues)})
        if eq_issues:
            raise RuntimeError(f"Input mismatch: {eq_issues}")

        cfg["solved"].parent.mkdir(parents=True, exist_ok=True)
        n.export_to_netcdf(str(cfg["solved"]))
        solved_networks[key] = n
        solve_results[key] = info
        validations[key] = {"energy_balance": validation, "nuclear_capacity": cap_val, "nuclear_dispatch": nuc_val}

    # Build comparison tables
    all_cases = {
        **{k: {"label": v["label"], "capacity_gw": v["capacity_gw"], "carrier": v["carrier"]} for k, v in REUSED_SCENARIOS.items()},
        **{k: {"label": v["label"], "capacity_gw": COMPARISON_CAPACITY_GW, "carrier": v["carrier"]} for k, v in REACTOR_SCENARIOS.items()},
    }

    ref_core_m = extract_metrics(ref_n, "core", _slice_snapshots(ref_n, core_start, core_end))
    ref_full_m = extract_metrics(ref_n, "full_window", pd.DatetimeIndex(ref_n.snapshots))
    ref_core_opex = ref_core_m["total_operational_cost_meur"]
    ref_full_opex = ref_full_m["total_operational_cost_meur"]
    ref_core_co2 = ref_core_m["co2_mt"]
    ref_full_co2 = ref_full_m["co2_mt"]

    core_rows: list[dict] = []
    full_rows: list[dict] = []
    benefits_rows: list[dict] = []
    dispatch_rows: list[dict] = []
    ramp_rows: list[dict] = []
    balance_rows: list[dict] = []
    fixed_cap_rows: list[dict] = []
    solver_rows: list[dict] = []
    economics_rows: list[dict] = []
    avoided_rows: list[dict] = []

    for key, case in all_cases.items():
        n = solved_networks[key]
        label = case["label"]
        cap_gw = case["capacity_gw"]
        carrier = case["carrier"]

        for scope_name, snaps, ref_co2, ref_opex in [
            ("core", _slice_snapshots(n, core_start, core_end), ref_core_co2, ref_core_opex),
            ("full_window", pd.DatetimeIndex(n.snapshots), ref_full_co2, ref_full_opex),
        ]:
            m = extract_metrics(n, scope_name, snaps)
            nuc = nuclear_dispatch_metrics(n, snaps, cap_gw, carrier=case.get("carrier"))
            row = comparison_row(label, scope_name, m, nuc, ref_co2, ref_opex)
            if scope_name == "core":
                core_rows.append(row)
            else:
                full_rows.append(row)

        core_row = next(r for r in core_rows if r["technology"] == label)
        ref_core_fossil = next(r for r in core_rows if r["technology"] == "Severe reference")["total_fossil_generation_twh"]
        if label != "Severe reference":
            benefits_rows.append(
                {
                    "technology": label,
                    "coal_displacement_twh": round(
                        next(r for r in core_rows if r["technology"] == "Severe reference")["coal_generation_twh"]
                        - core_row["coal_generation_twh"],
                        4,
                    ),
                    "lignite_displacement_twh": round(
                        next(r for r in core_rows if r["technology"] == "Severe reference")["lignite_generation_twh"]
                        - core_row["lignite_generation_twh"],
                        4,
                    ),
                    "ccgt_displacement_twh": round(
                        next(r for r in core_rows if r["technology"] == "Severe reference")["ccgt_generation_twh"]
                        - core_row["ccgt_generation_twh"],
                        4,
                    ),
                    "total_fossil_displacement_twh": round(ref_core_fossil - core_row["total_fossil_generation_twh"], 4),
                    "co2_avoided_per_nuclear_twh": round(
                        core_row["co2_avoided_mt"] / core_row["nuclear_generation_twh"], 4
                    )
                    if core_row["nuclear_generation_twh"] > 0
                    else np.nan,
                    "fossil_displacement_per_nuclear_twh": round(
                        (ref_core_fossil - core_row["total_fossil_generation_twh"]) / core_row["nuclear_generation_twh"], 4
                    )
                    if core_row["nuclear_generation_twh"] > 0
                    else np.nan,
                    "operational_savings_per_nuclear_twh_meur": round(
                        core_row["operational_savings_meur"] / core_row["nuclear_generation_twh"], 4
                    )
                    if core_row["nuclear_generation_twh"] > 0
                    else np.nan,
                }
            )

        if carrier:
            cp = tech_params[carrier]
            fixed = indicative_fixed_costs(cap_gw, cp)
            for scope_name, op_row, period_key in [
                ("core", core_row, "core_period_equivalent_fixed_cost_meur"),
                ("full_window", next(r for r in full_rows if r["technology"] == label), "full_window_period_equivalent_fixed_cost_meur"),
            ]:
                fixed_cost = fixed[period_key]
                indicative_total = op_row["total_operational_cost_meur"] + fixed_cost
                ref_op = ref_core_opex if scope_name == "core" else ref_full_opex
                co2_av = op_row["co2_avoided_mt"]
                avoided_cost = (
                    (indicative_total - ref_op) / co2_av if co2_av > 0 else np.nan
                )
                economics_rows.append(
                    {
                        "technology": label,
                        "scope": scope_name,
                        "operational_cost_meur": op_row["total_operational_cost_meur"],
                        "period_equivalent_fixed_cost_meur": round(fixed_cost, 2),
                        "indicative_total_cost_meur": round(indicative_total, 2),
                        "annual_fixed_cost_meur_per_year": round(fixed["annual_fixed_cost_meur_per_year"], 2),
                        "annual_fom_included": True,
                        "label": fixed["label"],
                    }
                )
                avoided_rows.append(
                    {
                        "technology": label,
                        "scope": scope_name,
                        "indicative_total_cost_meur": round(indicative_total, 2),
                        "severe_reference_operational_cost_meur": ref_op,
                        "co2_avoided_mt": co2_av,
                        "avoided_co2_cost_eur_per_t": round(avoided_cost, 2) if co2_av > 0 else np.nan,
                        "status": "ok" if co2_av > 0 else "not_applicable",
                    }
                )
        else:
            for scope_name, op_row in [
                ("core", core_row),
                ("full_window", next(r for r in full_rows if r["technology"] == label)),
            ]:
                avoided_rows.append(
                    {
                        "technology": label,
                        "scope": scope_name,
                        "indicative_total_cost_meur": op_row["total_operational_cost_meur"],
                        "severe_reference_operational_cost_meur": op_row["total_operational_cost_meur"],
                        "co2_avoided_mt": 0.0,
                        "avoided_co2_cost_eur_per_t": np.nan,
                        "status": "not_applicable",
                    }
                )

        nuc_val = validations[key]["nuclear_dispatch"]
        ramp_rows.append(
            {
                "scenario": key,
                "technology": label,
                "ramp_limit_per_hour_pu": tech_params.get(carrier or "nuclear-smr", {})["ramp_limit_per_hour_pu"]
                if carrier
                else 0.5,
                "ramp_limit_per_snapshot_pu": ramp_snapshot if carrier else np.nan,
                "ramp_binding": nuc_val.get("ramp_binding", False),
                "status": "ok" if nuc_val.get("ok", True) else "fail",
            }
        )
        dispatch_rows.append(
            {
                "technology": label,
                "capacity_gw": cap_gw,
                **nuclear_dispatch_metrics(
                    n, _slice_snapshots(n, core_start, core_end), cap_gw, carrier=case.get("carrier")
                ),
            }
        )
        val = validations[key]["energy_balance"]
        balance_rows.append({"scenario": key, "technology": label, "max_imbalance_mw": val["max_imbalance_mw"], "validation_ok": val["ok"]})
        sr = solve_results[key]
        solver_rows.append(
            {
                "technology": label,
                "scenario": key,
                "status": sr["status"],
                "objective_meur": round(float(sr["objective"]) / 1e6, 2),
                "solve_time_s": round(sr.get("solve_time_s", 0.0), 1),
                "reused": sr.get("reused", False),
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
                    "extendable_count": int(getattr(obj, attr).sum()) if len(obj) else 0,
                    "status": "ok" if (not len(obj) or int(getattr(obj, attr).sum()) == 0) else "fail",
                }
            )

    # Parameter table (wide format)
    param_defs = [
        ("CAPEX [EUR/kW]", "investment_eur_per_kw"),
        ("annual FOM [EUR/kW-year]", "fom_eur_per_kw_year"),
        ("annual FOM [% CAPEX]", "fom_pct_per_year"),
        ("VOM [EUR/MWh]", "vom_eur_per_mwh"),
        ("fuel cost [EUR/MWh_th]", "fuel_eur_per_mwh_th"),
        ("efficiency", "efficiency"),
        ("marginal cost [EUR/MWh]", "marginal_cost_eur_per_mwh"),
        ("lifetime [years]", "lifetime_years"),
        ("discount rate", "discount_rate"),
        ("p_max_pu (availability)", "p_max_pu"),
        ("p_min_pu", "p_min_pu"),
        ("ramp [p.u./hour]", "ramp_limit_per_hour_pu"),
        ("ramp [p.u./3h snapshot]", None),
    ]
    param_wide = []
    for pname, pkey in param_defs:
        row = {"parameter": pname}
        for c in REACTOR_CARRIERS:
            short = c.replace("nuclear-", "").upper()
            if pkey is None:
                row[short] = tech_params[c]["ramp_limit_per_hour_pu"] * 3.0
            else:
                row[short] = tech_params[c][pkey]
        param_wide.append(row)

    location_rows = [
        {
            "site": s,
            "bus": buses[s],
            "allocation_mw": PER_SITE_MW,
            "label": "common analytical deployment nodes",
        }
        for s in buses
    ]

    core_df = pd.DataFrame(core_rows)
    full_df = pd.DataFrame(full_rows)
    benefits_df = pd.DataFrame(benefits_rows)
    economics_df = pd.DataFrame(economics_rows)
    avoided_df = pd.DataFrame(avoided_rows)

    core_df.to_csv(OUTPUT_DIR / "reactor_comparison_core.csv", index=False)
    full_df.to_csv(OUTPUT_DIR / "reactor_comparison_full_window.csv", index=False)
    pd.DataFrame(param_wide).to_csv(OUTPUT_DIR / "reactor_parameters.csv", index=False)
    pd.DataFrame(location_rows).to_csv(OUTPUT_DIR / "reactor_location_validation.csv", index=False)
    pd.DataFrame(
        [{"reference": "severe_reference", "prepared_checksum_sha256": prepared_checksum}] + equality_rows
    ).to_csv(OUTPUT_DIR / "scenario_input_equality.csv", index=False)
    pd.DataFrame(solver_rows).to_csv(OUTPUT_DIR / "solver_status.csv", index=False)
    benefits_df.to_csv(OUTPUT_DIR / "reactor_operational_benefits.csv", index=False)
    economics_df.to_csv(OUTPUT_DIR / "reactor_fixed_cost_comparison.csv", index=False)
    avoided_df.to_csv(OUTPUT_DIR / "avoided_co2_cost.csv", index=False)
    pd.DataFrame(dispatch_rows).to_csv(OUTPUT_DIR / "nuclear_dispatch_summary.csv", index=False)
    pd.DataFrame(ramp_rows).to_csv(OUTPUT_DIR / "ramp_validation.csv", index=False)
    pd.DataFrame(balance_rows).to_csv(OUTPUT_DIR / "energy_balance_validation.csv", index=False)
    pd.DataFrame(fixed_cap_rows).to_csv(OUTPUT_DIR / "fixed_capacity_validation.csv", index=False)

    create_plots(core_df, full_df, benefits_df, economics_df, avoided_df, solved_networks, meta, OUTPUT_DIR)

    all_ok = all(v["energy_balance"]["ok"] for v in validations.values())
    all_ok &= all(r["extendable_count"] == 0 for r in fixed_cap_rows)

    return {
        "all_ok": all_ok,
        "core_df": core_df,
        "full_df": full_df,
        "economics_df": economics_df,
        "benefits_df": benefits_df,
        "tech_params": tech_params,
        "buses": buses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V4 reactor technology comparison")
    parser.add_argument("--solver", default="highs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_reactor_comparison(solver=args.solver)
    print(json.dumps({"all_ok": result["all_ok"]}, indent=2))


if __name__ == "__main__":
    main()
