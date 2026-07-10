# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
V4 decarbonised-fleet adequacy sensitivity on stylised severe Dunkelflaute.

Coal/lignite retired (p_nom=0); optional 4.5 GW SMR. Evaluates EENS under
"a stylised decarbonised-fleet adequacy sensitivity, not a forecast of the German power system."

Usage::

    pixi run python scripts/inre/run_v4_decarbonised_adequacy.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS
from scripts.inre.run_v3_operational_stress import _enable_load_shedding
from scripts.inre.run_v4_reactor_comparison import (
    add_fixed_nuclear,
    load_technology_cost_parameters,
    resolve_nuclear_buses,
)
from scripts.inre.run_v4_nuclear_sweep import (
    NUCLEAR_SITES,
    PREPARED_SEVERE,
    carrier_twh,
    nuclear_dispatch_metrics,
)
from scripts.inre.run_v4_stage1 import (
    EXPECTED_SNAPSHOTS,
    VOLL,
    _co2_kt,
    _cost_breakdown,
    _curtailment_twh,
    _gen_energy_by_carrier,
    _load_shed_metrics,
    _series_equal_df,
    _slice_snapshots,
    _weight,
    load_metadata,
    prepare_for_solve,
    solve_network,
    validate_solved,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy"
SMR_CAPACITY_GW = 4.5
SMR_CARRIER = "nuclear-smr"
DESCRIPTION = (
    "a stylised decarbonised-fleet adequacy sensitivity, not a forecast of the German power system"
)

SCENARIOS = {
    "stylised-df-severe-decarb-v4": {
        "label": "Decarbonised no nuclear",
        "add_smr": False,
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-decarb-v4/networks/base_s_10_elec_.nc",
    },
    "stylised-df-severe-decarb-smr-4.5-v4": {
        "label": "Decarbonised + 4.5 GW SMR",
        "add_smr": True,
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-decarb-smr-4.5-v4/networks/base_s_10_elec_.nc",
    },
}


def retire_coal_lignite(n: pypsa.Network) -> None:
    for carrier in ("coal", "lignite"):
        gens = n.generators[n.generators.carrier == carrier].index
        n.generators.loc[gens, "p_nom"] = 0.0
        n.generators.loc[gens, "p_nom_extendable"] = False


def _renewable_generation_twh(n: pypsa.Network, snaps: pd.DatetimeIndex) -> float:
    return carrier_twh(_gen_energy_by_carrier(n, snaps), list(RENEWABLE_CARRIERS))


def load_shedding_duration_metrics(n: pypsa.Network, snaps: pd.DatetimeIndex) -> dict:
    weight = _weight(n, snaps)
    step_h = float(weight.iloc[0]) if len(weight) else 3.0
    ls = n.generators[n.generators.carrier == "load_shed"].index
    if len(ls) == 0:
        return {
            "snapshots_with_load_shedding": 0,
            "equivalent_load_shedding_duration_hours": 0.0,
            "max_consecutive_load_shedding_hours": 0.0,
        }

    p = n.generators_t.p[ls].reindex(snaps).fillna(0.0).sum(axis=1)
    active = p > 1e-3
    n_active = int(active.sum())
    equiv_hours = float((p * weight).sum() / p.max()) if p.max() > 1e-3 else 0.0
    # Alternative: hours with any shedding weighted
    hours_with_shedding = float(weight[active].sum()) if n_active else 0.0

    max_consec_snaps = 0
    current = 0
    for flag in active:
        if flag:
            current += 1
            max_consec_snaps = max(max_consec_snaps, current)
        else:
            current = 0
    max_consec_hours = max_consec_snaps * step_h

    return {
        "snapshots_with_load_shedding": n_active,
        "equivalent_load_shedding_duration_hours": round(hours_with_shedding, 2),
        "max_consecutive_load_shedding_hours": round(max_consec_hours, 2),
        "eens_weighted_mwh": float((p * weight).sum()),
    }


def adequacy_metrics(n: pypsa.Network, scope: str, snaps: pd.DatetimeIndex, capacity_gw: float) -> dict:
    weight = _weight(n, snaps)
    demand_twh = float(n.loads_t.p_set.reindex(snaps).mul(weight, axis=0).sum().sum()) / 1e6
    gen_by = _gen_energy_by_carrier(n, snaps)
    nuc = nuclear_dispatch_metrics(n, snaps, capacity_gw, carrier=SMR_CARRIER if capacity_gw > 0 else None)
    eens_gwh, eens_pct, peak_ls_gw = _load_shed_metrics(n, snaps)
    var_opex, voll_cost, total_cost = _cost_breakdown(n, snaps)
    ls_dur = load_shedding_duration_metrics(n, snaps)
    return {
        "scenario": scope,
        "scope": scope,
        "description": DESCRIPTION,
        "demand_twh": round(demand_twh, 4),
        "nuclear_generation_twh": round(nuc["nuclear_generation_twh"], 4),
        "nuclear_capacity_factor_pct": round(nuc["nuclear_capacity_factor_pct"], 2),
        "ccgt_generation_twh": round(float(gen_by.get("CCGT", 0.0)), 4),
        "biomass_generation_twh": round(float(gen_by.get("biomass", 0.0)), 4),
        "renewable_generation_twh": round(_renewable_generation_twh(n, snaps), 4),
        "renewable_curtailment_twh": round(_curtailment_twh(n, snaps), 4),
        "peak_load_shedding_gw": round(peak_ls_gw, 4),
        "eens_gwh": round(eens_gwh, 4),
        "eens_pct_demand": round(eens_pct, 4),
        "snapshots_with_load_shedding": ls_dur["snapshots_with_load_shedding"],
        "equivalent_load_shedding_duration_hours": ls_dur["equivalent_load_shedding_duration_hours"],
        "max_consecutive_load_shedding_hours": ls_dur["max_consecutive_load_shedding_hours"],
        "co2_mt": round(_co2_kt(n, snaps) / 1000.0, 4),
        "variable_opex_excl_voll_meur": round(var_opex, 2),
        "load_shedding_penalty_meur": round(voll_cost, 2),
        "total_operational_cost_meur": round(total_cost, 2),
        "dispatch_mode": "unconstrained operational dispatch",
    }


def validate_scenario_inputs(
    ref: pypsa.Network,
    scenario: pypsa.Network,
    key: str,
    add_smr: bool,
) -> dict:
    issues: list[str] = []
    coal_ref = float(ref.generators.loc[ref.generators.carrier == "coal", "p_nom"].sum())
    lig_ref = float(ref.generators.loc[ref.generators.carrier == "lignite", "p_nom"].sum())
    coal_sc = float(scenario.generators.loc[scenario.generators.carrier == "coal", "p_nom"].sum())
    lig_sc = float(scenario.generators.loc[scenario.generators.carrier == "lignite", "p_nom"].sum())

    if coal_sc != 0:
        issues.append(f"{key}: coal p_nom sum = {coal_sc} MW, expected 0")
    if lig_sc != 0:
        issues.append(f"{key}: lignite p_nom sum = {lig_sc} MW, expected 0")

    ccgt_ref = ref.generators.loc[ref.generators.carrier == "CCGT", "p_nom"]
    ccgt_sc = scenario.generators.loc[scenario.generators.carrier == "CCGT", "p_nom"]
    if not _series_equal_df(ccgt_ref, ccgt_sc):
        issues.append("CCGT p_nom differs from severe reference")

    bio_ref = ref.generators.loc[ref.generators.carrier == "biomass", "p_nom"]
    bio_sc = scenario.generators.loc[scenario.generators.carrier == "biomass", "p_nom"]
    if not _series_equal_df(bio_ref, bio_sc):
        issues.append("biomass p_nom differs")

    if not _series_equal_df(ref.loads_t.p_set, scenario.loads_t.p_set):
        issues.append("demand differs")
    if not _series_equal_df(ref.snapshot_weightings.objective, scenario.snapshot_weightings.objective):
        issues.append("snapshot weights differ")

    ren = ref.generators[ref.generators.carrier.isin(RENEWABLE_CARRIERS)].index
    for gen in ren:
        if gen in ref.generators_t.p_max_pu.columns and gen in scenario.generators_t.p_max_pu.columns:
            if not _series_equal_df(ref.generators_t.p_max_pu[gen], scenario.generators_t.p_max_pu[gen]):
                issues.append(f"renewable p_max_pu differs for {gen}")
                break

    if not _series_equal_df(ref.lines.s_nom, scenario.lines.s_nom):
        issues.append("transmission s_nom differs")

    ls = scenario.generators[scenario.generators.carrier == "load_shed"]
    if len(ls) == 0:
        issues.append("load shedding generators missing")
    elif abs(float(ls.marginal_cost.iloc[0]) - VOLL) > 1e-6:
        issues.append(f"VOLL != {VOLL}")

    smr_mw = float(scenario.generators[scenario.generators.carrier == SMR_CARRIER]["p_nom"].sum())
    expected_smr = SMR_CAPACITY_GW * 1000.0 if add_smr else 0.0
    if abs(smr_mw - expected_smr) > 1e-6:
        issues.append(f"SMR capacity {smr_mw} MW, expected {expected_smr}")

    for comp, attr in [
        ("generators", "p_nom_extendable"),
        ("storage_units", "p_nom_extendable"),
        ("stores", "e_nom_extendable"),
        ("lines", "s_nom_extendable"),
        ("links", "p_nom_extendable"),
    ]:
        obj = getattr(scenario, comp)
        if len(obj) and int(getattr(obj, attr).sum()):
            issues.append(f"{comp}.{attr} extendable")

    if len(scenario.snapshots) != EXPECTED_SNAPSHOTS:
        issues.append(f"expected {EXPECTED_SNAPSHOTS} snapshots")

    if scenario.loads_t.p_set.isna().any().any():
        issues.append("NaN in demand")

    return {
        "scenario": key,
        "coal_p_nom_mw": coal_sc,
        "lignite_p_nom_mw": lig_sc,
        "coal_p_nom_mw_reference": coal_ref,
        "lignite_p_nom_mw_reference": lig_ref,
        "ccgt_unchanged": _series_equal_df(ccgt_ref, ccgt_sc),
        "demand_unchanged": _series_equal_df(ref.loads_t.p_set, scenario.loads_t.p_set),
        "renewable_profiles_unchanged": len([i for i in issues if "renewable" in i]) == 0,
        "smr_capacity_mw": smr_mw,
        "ok": len(issues) == 0,
        "issues": "; ".join(issues),
    }


def build_prepared_scenario(ref: pypsa.Network, add_smr: bool, smr_params: dict, buses: dict[str, str]) -> pypsa.Network:
    n = ref.copy()
    retire_coal_lignite(n)
    _enable_load_shedding(n, voll=VOLL)
    if add_smr:
        add_fixed_nuclear(n, SMR_CARRIER, SMR_CAPACITY_GW * 1000.0, smr_params, buses)
    return n


def create_plots(
    solved: dict[str, pypsa.Network],
    meta: dict,
    output_dir: Path,
) -> None:
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    key_no = "stylised-df-severe-decarb-v4"
    key_smr = "stylised-df-severe-decarb-smr-4.5-v4"
    snaps_full = pd.DatetimeIndex(solved[key_no].snapshots)
    snaps_core = _slice_snapshots(solved[key_no], core_start, core_end)

    def ls_gw(n, snaps):
        ls = n.generators[n.generators.carrier == "load_shed"].index
        if len(ls) == 0:
            return pd.Series(0.0, index=snaps)
        return n.generators_t.p[ls].reindex(snaps).fillna(0).sum(axis=1) / 1e3

    def demand_gw(n, snaps):
        return n.loads_t.p_set.reindex(snaps).sum(axis=1) / 1e3

    def vre_avail_gw(n, snaps):
        ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
        out = pd.Series(0.0, index=snaps)
        for gen in ren.index:
            if gen in n.generators_t.p_max_pu.columns:
                out += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
        return out / 1e3

    def firm_avail_gw(n, snaps):
        firm_carriers = ["CCGT", "biomass", SMR_CARRIER]
        out = pd.Series(0.0, index=snaps)
        for car in firm_carriers:
            gens = n.generators[n.generators.carrier == car].index
            for gen in gens:
                pmax = float(n.generators.at[gen, "p_nom"])
                if gen in n.generators_t.p_max_pu.columns:
                    pu = n.generators_t.p_max_pu[gen].reindex(snaps).fillna(1.0)
                else:
                    pu = 1.0
                out += pu * pmax
        return out / 1e3

    # Load shedding time series
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(snaps_full, ls_gw(solved[key_no], snaps_full), label="Decarbonised no nuclear", color="C3")
    ax.plot(snaps_full, ls_gw(solved[key_smr], snaps_full), label="Decarbonised + SMR", color="C0")
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_ylabel("GW")
    ax.set_title("Load shedding time series")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "01_load_shedding_timeseries.png", dpi=150)
    plt.close(fig)

    # Cumulative EENS
    fig, ax = plt.subplots(figsize=(12, 4))
    for key, label, color in [
        (key_no, "No nuclear", "C3"),
        (key_smr, "+ 4.5 GW SMR", "C0"),
    ]:
        n = solved[key]
        w = _weight(n, snaps_full)
        ls = n.generators[n.generators.carrier == "load_shed"].index
        eens = n.generators_t.p[ls].reindex(snaps_full).fillna(0).sum(axis=1).mul(w) / 1e3
        ax.plot(snaps_full, eens.cumsum(), label=label, color=color)
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_ylabel("GWh")
    ax.set_title("Cumulative EENS")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "02_cumulative_eens.png", dpi=150)
    plt.close(fig)

    # Residual load vs firm available (no nuclear)
    fig, ax = plt.subplots(figsize=(12, 4))
    n = solved[key_no]
    res = demand_gw(n, snaps_full) - vre_avail_gw(n, snaps_full)
    firm = firm_avail_gw(n, snaps_full)
    ax.plot(snaps_full, res, label="residual load", color="black")
    ax.plot(snaps_full, firm, label="available firm (CCGT+biomass)", color="C2")
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_ylabel("GW")
    ax.set_title("Residual load vs firm capacity (decarbonised, no nuclear)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "03_residual_load_firm_no_nuclear.png", dpi=150)
    plt.close(fig)

    # Generation stacks (core)
    for key, title, fname in [
        (key_no, "Decarbonised no nuclear", "04_generation_stack_no_nuclear"),
        (key_smr, "Decarbonised + 4.5 GW SMR", "05_generation_stack_with_smr"),
    ]:
        n = solved[key]
        fig, ax = plt.subplots(figsize=(12, 5))
        carriers = ["onwind", "offwind-ac", "solar", "biomass", "CCGT", SMR_CARRIER, "load_shed"]
        stack, labels = [], []
        for car in carriers:
            gens = n.generators[n.generators.carrier == car].index
            if len(gens):
                s = n.generators_t.p[gens].reindex(snaps_core).fillna(0).sum(axis=1) / 1e3
                if s.max() > 1e-6 or car == "load_shed":
                    stack.append(s.values)
                    labels.append(car)
        if stack:
            ax.stackplot(snaps_core, stack, labels=labels, alpha=0.85)
        ax.plot(snaps_core, demand_gw(n, snaps_core), "k--", lw=1.2, label="demand")
        ax.set_ylabel("GW")
        ax.set_title(f"Core generation stack: {title}")
        ax.legend(loc="upper left", fontsize=8)
        fig.tight_layout()
        fig.savefig(plot_dir / f"{fname}.png", dpi=150)
        plt.close(fig)

    # SMR dispatch core
    n = solved[key_smr]
    smr_gens = n.generators[n.generators.carrier == SMR_CARRIER].index
    if len(smr_gens):
        fig, ax = plt.subplots(figsize=(12, 4))
        p = n.generators_t.p[smr_gens].reindex(snaps_core).fillna(0).sum(axis=1) / 1e3
        ax.plot(snaps_core, p, color="C0")
        ax.set_ylabel("GW")
        ax.set_title("SMR dispatch (core event)")
        fig.tight_layout()
        fig.savefig(plot_dir / "06_smr_dispatch_core.png", dpi=150)
        plt.close(fig)


def run_decarbonised_adequacy(solver: str = "highs") -> dict:
    meta = load_metadata()
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])

    ref = pypsa.Network(str(PREPARED_SEVERE))
    smr_params = load_technology_cost_parameters(SMR_CARRIER)
  # Enforce validated SMR operational parameters
    smr_params.update(
        {
            "marginal_cost_eur_per_mwh": 12.09,
            "efficiency": 0.33,
            "p_max_pu": 0.9,
            "p_min_pu": 0.0,
            "ramp_limit_per_hour_pu": 0.5,
        }
    )
    buses = resolve_nuclear_buses(ref)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prepared: dict[str, pypsa.Network] = {}
    validation_rows: list[dict] = []

    for key, cfg in SCENARIOS.items():
        n = build_prepared_scenario(ref, cfg["add_smr"], smr_params, buses)
        val = validate_scenario_inputs(ref, n, key, cfg["add_smr"])
        validation_rows.append(val)
        if not val["ok"]:
            raise RuntimeError(f"Pre-solve validation failed for {key}: {val['issues']}")
        prepared[key] = n

    solved: dict[str, pypsa.Network] = {}
    solve_rows: list[dict] = []
    balance_rows: list[dict] = []
    fixed_cap_rows: list[dict] = []

    for key, cfg in SCENARIOS.items():
        logger.info("Solving %s", key)
        n = prepared[key]
        prepare_for_solve(n)
        info = solve_network(n, solver=solver)
        val = validate_solved(n, info)
        if not val["ok"]:
            raise RuntimeError(f"Post-solve validation failed: {val['issues']}")

        cfg["solved"].parent.mkdir(parents=True, exist_ok=True)
        n.export_to_netcdf(str(cfg["solved"]))
        solved[key] = n
        solve_rows.append(
            {
                "scenario": key,
                "status": info["status"],
                "objective_meur": round(float(info["objective"]) / 1e6, 2),
                "solve_time_s": round(info.get("solve_time_s", 0.0), 1),
                "dispatch_mode": "unconstrained operational dispatch",
            }
        )
        balance_rows.append(
            {
                "scenario": key,
                "max_imbalance_mw": val["max_imbalance_mw"],
                "validation_ok": val["ok"],
                "issues": "; ".join(val["issues"]),
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

    core_rows: list[dict] = []
    full_rows: list[dict] = []
    gen_rows: list[dict] = []
    cost_rows: list[dict] = []
    co2_rows: list[dict] = []
    ls_duration_rows: list[dict] = []

    for key, cfg in SCENARIOS.items():
        n = solved[key]
        cap_gw = SMR_CAPACITY_GW if cfg["add_smr"] else 0.0
        label = cfg["label"]
        for scope_name, snaps, bucket in [
            ("core", _slice_snapshots(n, core_start, core_end), core_rows),
            ("full_window", pd.DatetimeIndex(n.snapshots), full_rows),
        ]:
            m = adequacy_metrics(n, label, snaps, cap_gw)
            m["scenario_key"] = key
            bucket.append(m)
            for carrier, val in _gen_energy_by_carrier(n, snaps).items():
                gen_rows.append(
                    {
                        "scenario": key,
                        "label": label,
                        "scope": scope_name,
                        "carrier": carrier,
                        "generation_twh": round(float(val), 4),
                    }
                )
            var, voll, total = _cost_breakdown(n, snaps)
            obj = float(n.objective) / 1e6 if scope_name == "full_window" else np.nan
            cost_rows.append(
                {
                    "scenario": key,
                    "label": label,
                    "scope": scope_name,
                    "variable_opex_excl_voll_meur": var,
                    "load_shedding_penalty_meur": voll,
                    "total_operational_cost_meur": total,
                    "objective_meur": obj,
                    "reconciliation_gap_meur": abs(total - obj) if scope_name == "full_window" else np.nan,
                    "status": "ok" if (scope_name != "full_window" or abs(total - obj) < 0.5) else "fail",
                }
            )
            co2_rows.append(
                {
                    "scenario": key,
                    "label": label,
                    "scope": scope_name,
                    "co2_mt": _co2_kt(n, snaps) / 1000.0,
                }
            )
            ls_dur = load_shedding_duration_metrics(n, snaps)
            ls_duration_rows.append({"scenario": key, "label": label, "scope": scope_name, **ls_dur})

    core_df = pd.DataFrame(core_rows)
    full_df = pd.DataFrame(full_rows)
    key_no = "stylised-df-severe-decarb-v4"
    key_smr = "stylised-df-severe-decarb-smr-4.5-v4"

    def _get(df, key, col):
        return float(df[df["scenario_key"] == key].iloc[0][col])

    benefit = {
        "description": DESCRIPTION,
        "eens_reduction_gwh_core": round(_get(core_df, key_no, "eens_gwh") - _get(core_df, key_smr, "eens_gwh"), 4),
        "eens_reduction_gwh_full_window": round(_get(full_df, key_no, "eens_gwh") - _get(full_df, key_smr, "eens_gwh"), 4),
        "relative_eens_reduction_pct_core": round(
            100.0
            * (_get(core_df, key_no, "eens_gwh") - _get(core_df, key_smr, "eens_gwh"))
            / _get(core_df, key_no, "eens_gwh")
            if _get(core_df, key_no, "eens_gwh") > 0
            else np.nan,
            2,
        ),
        "relative_eens_reduction_pct_full_window": round(
            100.0
            * (_get(full_df, key_no, "eens_gwh") - _get(full_df, key_smr, "eens_gwh"))
            / _get(full_df, key_no, "eens_gwh")
            if _get(full_df, key_no, "eens_gwh") > 0
            else np.nan,
            2,
        ),
        "peak_shedding_reduction_gw_core": round(
            _get(core_df, key_no, "peak_load_shedding_gw") - _get(core_df, key_smr, "peak_load_shedding_gw"), 4
        ),
        "avoided_modelled_load_shedding_penalty_meur_core": round(
            _get(core_df, key_no, "load_shedding_penalty_meur") - _get(core_df, key_smr, "load_shedding_penalty_meur"), 2
        ),
        "avoided_modelled_load_shedding_penalty_meur_full_window": round(
            _get(full_df, key_no, "load_shedding_penalty_meur") - _get(full_df, key_smr, "load_shedding_penalty_meur"), 2
        ),
        "co2_reduction_mt_core": round(_get(core_df, key_no, "co2_mt") - _get(core_df, key_smr, "co2_mt"), 4),
        "co2_reduction_mt_full_window": round(_get(full_df, key_no, "co2_mt") - _get(full_df, key_smr, "co2_mt"), 4),
    }

    eens_no_core = _get(core_df, key_no, "eens_gwh")
    eens_smr_core = _get(core_df, key_smr, "eens_gwh")
    if eens_no_core <= 0 and eens_smr_core <= 0:
        benefit["smr_adequacy_effect"] = "no adequacy effect — system remains adequate without coal and lignite"
        benefit["load_shedding_eliminated"] = True
    elif eens_no_core > 0 and eens_smr_core <= 0:
        benefit["smr_adequacy_effect"] = "completely eliminates load shedding"
        benefit["load_shedding_eliminated"] = True
    elif benefit["eens_reduction_gwh_core"] > 0:
        benefit["smr_adequacy_effect"] = "partially reduces load shedding"
        benefit["load_shedding_eliminated"] = False
    else:
        benefit["smr_adequacy_effect"] = "no measurable adequacy benefit"
        benefit["load_shedding_eliminated"] = False

    eens_cmp = []
    for scope, df in [("core", core_df), ("full_window", full_df)]:
        for col in ["eens_gwh", "eens_pct_demand", "peak_load_shedding_gw", "snapshots_with_load_shedding"]:
            eens_cmp.append(
                {
                    "scope": scope,
                    "metric": col,
                    "decarbonised_no_nuclear": _get(df, key_no, col),
                    "decarbonised_with_smr": _get(df, key_smr, col),
                    "difference": _get(df, key_no, col) - _get(df, key_smr, col),
                }
            )

    pd.DataFrame(solve_rows).to_csv(OUTPUT_DIR / "solver_status.csv", index=False)
    pd.DataFrame(validation_rows).to_csv(OUTPUT_DIR / "scenario_input_validation.csv", index=False)
    core_df.to_csv(OUTPUT_DIR / "adequacy_summary_core.csv", index=False)
    full_df.to_csv(OUTPUT_DIR / "adequacy_summary_full_window.csv", index=False)
    pd.DataFrame(eens_cmp).to_csv(OUTPUT_DIR / "eens_comparison.csv", index=False)
    pd.DataFrame(ls_duration_rows).to_csv(OUTPUT_DIR / "load_shedding_duration.csv", index=False)
    pd.DataFrame([benefit]).to_csv(OUTPUT_DIR / "smr_adequacy_benefit.csv", index=False)
    pd.DataFrame(gen_rows).to_csv(OUTPUT_DIR / "generation_by_carrier.csv", index=False)
    pd.DataFrame(co2_rows).to_csv(OUTPUT_DIR / "co2_comparison.csv", index=False)
    pd.DataFrame(cost_rows).to_csv(OUTPUT_DIR / "cost_comparison.csv", index=False)
    pd.DataFrame(balance_rows).to_csv(OUTPUT_DIR / "energy_balance_validation.csv", index=False)
    pd.DataFrame(fixed_cap_rows).to_csv(OUTPUT_DIR / "fixed_capacity_validation.csv", index=False)

    create_plots(solved, meta, OUTPUT_DIR)

    all_ok = all(v["ok"] for v in validation_rows)
    all_ok &= all(r["validation_ok"] for r in balance_rows)
    all_ok &= all(r["status"] == "ok" for r in cost_rows if r["scope"] == "full_window")

    return {
        "all_ok": all_ok,
        "core_df": core_df,
        "full_df": full_df,
        "benefit": benefit,
        "validation_rows": validation_rows,
        "solve_rows": solve_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V4 decarbonised adequacy sensitivity")
    parser.add_argument("--solver", default="highs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_decarbonised_adequacy(solver=args.solver)
    print(json.dumps({"all_ok": result["all_ok"], "benefit": result["benefit"]}, indent=2))


if __name__ == "__main__":
    main()
