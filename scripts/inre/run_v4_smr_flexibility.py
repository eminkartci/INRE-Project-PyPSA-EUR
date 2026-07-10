# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
V4 lean SMR operational flexibility sensitivity (decarbonised + 4.5 GW SMR).

Compares flexible SMR (p_min=0, ramp 0.5/h) vs limited-flex (p_min=0.30, ramp 0.05/h).

Usage::

    pixi run python scripts/inre/run_v4_smr_flexibility.py
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
from scripts.inre.run_v4_decarbonised_adequacy import build_prepared_scenario, retire_coal_lignite
from scripts.inre.run_v4_reactor_comparison import (
    add_fixed_nuclear,
    load_technology_cost_parameters,
    resolve_nuclear_buses,
)
from scripts.inre.run_v4_nuclear_sweep import (
    PREPARED_SEVERE,
    _series_equal_df,
    non_nuclear_generators,
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
    _slice_snapshots,
    _weight,
    load_metadata,
    prepare_for_solve,
    solve_network,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = REPO_ROOT / "results/inre-comparison-v4-smr-flexibility"
SMR_CARRIER = "nuclear-smr"
SMR_CAPACITY_GW = 4.5
DESCRIPTION = "a stylised limited-flexibility sensitivity, not a technology-specific operational forecast"

FLEXIBLE_REF = {
    "key": "stylised-df-severe-decarb-smr-4.5-v4",
    "label": "Flexible SMR",
    "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-decarb-smr-4.5-v4/networks/base_s_10_elec_.nc",
    "p_min_pu": 0.0,
    "ramp_per_hour": 0.5,
    "ramp_per_snapshot": 1.5,
}

LIMITED_FLEX = {
    "key": "stylised-df-severe-decarb-smr-4.5-limited-flex-v4",
    "label": "Limited-flexibility SMR",
    "solved": REPO_ROOT
    / "results/inre-de-stylised-df-severe-decarb-smr-4.5-limited-flex-v4/networks/base_s_10_elec_.nc",
    "p_min_pu": 0.30,
    "ramp_per_hour": 0.05,
    "ramp_per_snapshot": 0.15,
}

BINDING_TOL_MW = 1.0


def smr_generators(n: pypsa.Network) -> pd.Index:
    return n.generators[n.generators.carrier == SMR_CARRIER].index


def apply_limited_flex_params(n: pypsa.Network, p_min_pu: float, ramp_per_snapshot: float) -> None:
    gens = smr_generators(n)
    n.generators.loc[gens, "p_min_pu"] = p_min_pu
    n.generators.loc[gens, "ramp_limit_up"] = ramp_per_snapshot
    n.generators.loc[gens, "ramp_limit_down"] = ramp_per_snapshot


def validate_input_differences(ref: pypsa.Network, limited: pypsa.Network) -> dict:
    issues: list[str] = []
    ref_gens = smr_generators(ref)
    lim_gens = smr_generators(limited)

    if abs(float(ref.generators.loc[ref_gens, "p_nom"].sum()) - 4500.0) > 1e-6:
        issues.append("reference SMR capacity != 4500 MW")
    if abs(float(limited.generators.loc[lim_gens, "p_nom"].sum()) - 4500.0) > 1e-6:
        issues.append("limited SMR capacity != 4500 MW")

    for bus, mw in [("DE0 3", 1500.0), ("DE0 8", 1500.0), ("DE0 4", 1500.0)]:
        at = float(limited.generators.loc[lim_gens].query("bus == @bus")["p_nom"].sum())
        if abs(at - mw) > 1e-6:
            issues.append(f"bus {bus} SMR allocation {at} != {mw}")

    ref_idx = non_nuclear_generators(ref)
    lim_idx = non_nuclear_generators(limited)
    for attr in ["p_nom", "marginal_cost", "efficiency"]:
        if not _series_equal_df(ref.generators.loc[ref_idx, attr], limited.generators.loc[lim_idx, attr]):
            issues.append(f"non-nuclear generators.{attr} differs")

    if not _series_equal_df(ref.loads_t.p_set, limited.loads_t.p_set):
        issues.append("demand differs")

    ren = ref.generators[ref.generators.carrier.isin(RENEWABLE_CARRIERS)].index
    for gen in ren:
        if gen in ref.generators_t.p_max_pu.columns and gen in limited.generators_t.p_max_pu.columns:
            if not _series_equal_df(ref.generators_t.p_max_pu[gen], limited.generators_t.p_max_pu[gen]):
                issues.append("renewable p_max_pu differs")
                break

    if not _series_equal_df(ref.lines.s_nom, limited.lines.s_nom):
        issues.append("transmission differs")

    ls = limited.generators[limited.generators.carrier == "load_shed"]
    if len(ls) == 0:
        issues.append("load shedding missing")
    elif abs(float(ls.marginal_cost.iloc[0]) - VOLL) > 1e-6:
        issues.append("VOLL mismatch")

    for comp, attr in [
        ("generators", "p_nom_extendable"),
        ("storage_units", "p_nom_extendable"),
        ("stores", "e_nom_extendable"),
        ("lines", "s_nom_extendable"),
        ("links", "p_nom_extendable"),
    ]:
        obj = getattr(limited, comp)
        if len(obj) and int(getattr(obj, attr).sum()):
            issues.append(f"{comp}.{attr} extendable")

    if len(limited.snapshots) != EXPECTED_SNAPSHOTS:
        issues.append(f"snapshots != {EXPECTED_SNAPSHOTS}")

    # SMR static params — only p_min and ramp should differ
    ref_smr = ref.generators.loc[ref_gens]
    lim_smr = limited.generators.loc[lim_gens]
    for col in ["p_nom", "marginal_cost", "efficiency", "p_max_pu"]:
        if not _series_equal_df(ref_smr[col], lim_smr[col]):
            issues.append(f"SMR {col} differs unexpectedly")
    if not ref_smr["bus"].equals(lim_smr["bus"]):
        issues.append("SMR bus differs unexpectedly")

    if not np.allclose(ref_smr["p_min_pu"], 0.0):
        issues.append(f"reference p_min_pu expected 0.0, got {ref_smr['p_min_pu'].iloc[0]}")
    if not np.allclose(lim_smr["p_min_pu"], LIMITED_FLEX["p_min_pu"]):
        issues.append(f"limited p_min_pu expected {LIMITED_FLEX['p_min_pu']}")
    if not np.allclose(ref_smr["ramp_limit_up"], FLEXIBLE_REF["ramp_per_snapshot"]):
        issues.append("reference ramp_limit_up unexpected")
    if not np.allclose(lim_smr["ramp_limit_up"], LIMITED_FLEX["ramp_per_snapshot"]):
        issues.append("limited ramp_limit_up unexpected")

    unexpected = [
        i
        for i in issues
        if "unexpected" in i
        or i
        in (
            "demand differs",
            "renewable p_max_pu differs",
            "transmission differs",
        )
        or i.startswith("non-nuclear")
    ]

    return {
        "p_min_pu_flexible": float(ref_smr["p_min_pu"].iloc[0]),
        "p_min_pu_limited": float(lim_smr["p_min_pu"].iloc[0]),
        "ramp_per_hour_flexible": FLEXIBLE_REF["ramp_per_hour"],
        "ramp_per_hour_limited": LIMITED_FLEX["ramp_per_hour"],
        "ramp_per_snapshot_flexible": FLEXIBLE_REF["ramp_per_snapshot"],
        "ramp_per_snapshot_limited": LIMITED_FLEX["ramp_per_snapshot"],
        "all_other_inputs_identical": len(unexpected) == 0,
        "ok": len(unexpected) == 0,
        "issues": "; ".join(issues),
        "allowed_differences": "p_min_pu; ramp_limit_up; ramp_limit_down",
    }


def constraint_binding_summary(n: pypsa.Network, p_min_pu: float, ramp_per_snapshot: float) -> dict:
    snaps = pd.DatetimeIndex(n.snapshots)
    gens = smr_generators(n)
    p = n.generators_t.p[gens].reindex(snaps).fillna(0.0)
    p_nom = n.generators.loc[gens, "p_nom"]

    min_binding = 0
    ramp_up_binding = 0
    ramp_down_binding = 0
    max_up_gw = 0.0
    max_down_gw = 0.0

    for gen in gens:
        pmin_mw = float(p_nom[gen] * p_min_pu)
        rlim_mw = float(p_nom[gen] * ramp_per_snapshot)
        pg = p[gen]
        if pmin_mw > 0:
            min_binding += int((pg <= pmin_mw + BINDING_TOL_MW).sum())
        delta = pg.diff()
        up = delta.clip(lower=0.0)
        down = (-delta).clip(lower=0.0)
        ramp_up_binding += int((up >= rlim_mw - BINDING_TOL_MW).sum())
        ramp_down_binding += int((down >= rlim_mw - BINDING_TOL_MW).sum())
        max_up_gw = max(max_up_gw, float(up.max()) / 1e3)
        max_down_gw = max(max_down_gw, float(down.max()) / 1e3)

    total_p = p.sum(axis=1)
    return {
        "minimum_output_binding_snapshots": min_binding,
        "ramp_up_binding_snapshots": ramp_up_binding,
        "ramp_down_binding_snapshots": ramp_down_binding,
        "max_upward_ramp_gw_per_snapshot": round(max_up_gw, 4),
        "max_downward_ramp_gw_per_snapshot": round(max_down_gw, 4),
        "min_nuclear_dispatch_gw": round(float(total_p.min()) / 1e3, 4),
        "max_nuclear_dispatch_gw": round(float(total_p.max()) / 1e3, 4),
    }


def flexibility_row(
    label: str,
    n: pypsa.Network,
    snaps: pd.DatetimeIndex,
    p_min_pu: float,
    ramp_per_snapshot: float,
) -> dict:
    nuc = nuclear_dispatch_metrics(n, snaps, SMR_CAPACITY_GW, carrier=SMR_CARRIER)
    eens_gwh, eens_pct, peak_ls = _load_shed_metrics(n, snaps)
    var_opex, voll, total = _cost_breakdown(n, snaps)
    gen_by = _gen_energy_by_carrier(n, snaps)
    bind = constraint_binding_summary(n, p_min_pu, ramp_per_snapshot)
    ls_gens = n.generators[n.generators.carrier == "load_shed"].index
    weight = _weight(n, snaps)
    ls_p = n.generators_t.p[ls_gens].reindex(snaps).fillna(0).sum(axis=1) if len(ls_gens) else pd.Series(0, index=snaps)
    ls_snaps = int((ls_p > 1e-3).sum())

    return {
        "scenario": label,
        "p_min_pu": p_min_pu,
        "ramp_per_hour_pu": ramp_per_snapshot / 3.0,
        "ramp_per_snapshot_pu": ramp_per_snapshot,
        "nuclear_generation_twh": round(nuc["nuclear_generation_twh"], 4),
        "nuclear_capacity_factor_pct": round(nuc["nuclear_capacity_factor_pct"], 2),
        "min_nuclear_dispatch_gw": bind["min_nuclear_dispatch_gw"],
        "max_nuclear_dispatch_gw": bind["max_nuclear_dispatch_gw"],
        "max_upward_ramp_gw_per_snapshot": bind["max_upward_ramp_gw_per_snapshot"],
        "max_downward_ramp_gw_per_snapshot": bind["max_downward_ramp_gw_per_snapshot"],
        "minimum_output_binding_snapshots": bind["minimum_output_binding_snapshots"],
        "ramp_up_binding_snapshots": bind["ramp_up_binding_snapshots"],
        "ramp_down_binding_snapshots": bind["ramp_down_binding_snapshots"],
        "renewable_curtailment_twh": round(_curtailment_twh(n, snaps), 4),
        "ccgt_generation_twh": round(float(gen_by.get("CCGT", 0.0)), 4),
        "peak_load_shedding_gw": round(peak_ls, 4),
        "eens_gwh": round(eens_gwh, 4),
        "eens_pct_demand": round(eens_pct, 4),
        "load_shedding_snapshots": ls_snaps,
        "co2_mt": round(_co2_kt(n, snaps) / 1000.0, 4),
        "variable_opex_excl_voll_meur": round(var_opex, 2),
        "load_shedding_penalty_meur": round(voll, 2),
        "total_operational_cost_meur": round(total, 2),
        "dispatch_mode": "unconstrained operational dispatch",
    }


def create_plots(flex_n: pypsa.Network, lim_n: pypsa.Network, meta: dict, output_dir: Path) -> None:
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    snaps_full = pd.DatetimeIndex(flex_n.snapshots)
    snaps_core = _slice_snapshots(flex_n, core_start, core_end)

    def smr_gw(n, snaps):
        g = smr_generators(n)
        return n.generators_t.p[g].reindex(snaps).fillna(0).sum(axis=1) / 1e3

    def ls_gw(n, snaps):
        ls = n.generators[n.generators.carrier == "load_shed"].index
        return n.generators_t.p[ls].reindex(snaps).fillna(0).sum(axis=1) / 1e3 if len(ls) else pd.Series(0, index=snaps)

    def cum_eens(n, snaps):
        w = _weight(n, snaps)
        ls = n.generators[n.generators.carrier == "load_shed"].index
        e = n.generators_t.p[ls].reindex(snaps).fillna(0).sum(axis=1).mul(w) / 1e3
        return e.cumsum()

    def curtail_gw(n, snaps):
        ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
        total = pd.Series(0.0, index=snaps)
        for gen in ren.index:
            if gen in n.generators_t.p_max_pu.columns and gen in n.generators_t.p.columns:
                avail = n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
                disp = n.generators_t.p[gen].reindex(snaps).fillna(0)
                total += (avail - disp).clip(lower=0)
        return total / 1e3

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(snaps_core, smr_gw(flex_n, snaps_core), label="Flexible", color="C0")
    ax.plot(snaps_core, smr_gw(lim_n, snaps_core), label="Limited-flex", color="C3")
    ax.set_ylabel("GW")
    ax.set_title("SMR dispatch comparison (core)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "01_smr_dispatch_comparison.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(snaps_full, ls_gw(flex_n, snaps_full), label="Flexible", color="C0")
    ax.plot(snaps_full, ls_gw(lim_n, snaps_full), label="Limited-flex", color="C3")
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_ylabel("GW")
    ax.set_title("Load shedding comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "02_load_shedding_comparison.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(snaps_full, cum_eens(flex_n, snaps_full), label="Flexible", color="C0")
    ax.plot(snaps_full, cum_eens(lim_n, snaps_full), label="Limited-flex", color="C3")
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_ylabel("GWh")
    ax.set_title("Cumulative EENS comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "03_cumulative_eens_comparison.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(snaps_full, curtail_gw(flex_n, snaps_full), label="Flexible", color="C0")
    ax.plot(snaps_full, curtail_gw(lim_n, snaps_full), label="Limited-flex", color="C3")
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_ylabel("GW curtailed")
    ax.set_title("Renewable curtailment comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "04_curtailment_comparison.png", dpi=150)
    plt.close(fig)


def validate_flex_solve(n: pypsa.Network, solve_info: dict) -> dict:
    """Post-solve checks without CO2 carrier nominal reference (decarb stress dispatch)."""
    issues: list[str] = []
    status = solve_info["status"].lower()
    if "ok" not in status and "optimal" not in status:
        issues.append(f"Solver status not optimal: {solve_info['status']}")

    snaps = pd.DatetimeIndex(n.snapshots)
    weight = _weight(n, snaps)
    gen_sum = n.generators_t.p.mul(weight, axis=0).sum(axis=1)
    load_sum = n.loads_t.p_set.mul(weight, axis=0).sum(axis=1)
    stor = 0.0
    if len(n.storage_units) and "p" in n.storage_units_t:
        stor = n.storage_units_t.p.mul(weight, axis=0).sum(axis=1)
    max_imbalance_mw = float((gen_sum - load_sum - stor).abs().max())

    if max_imbalance_mw > 1.0:
        issues.append(f"Max nodal energy balance imbalance {max_imbalance_mw:.2f} MW")
    if n.generators_t.p.isna().any().any():
        issues.append("NaN in generators_t.p")

    var, voll, total = _cost_breakdown(n, snaps)
    obj_meur = float(n.objective) / 1e6
    if abs(total - obj_meur) > 0.5:
        issues.append(f"Cost reconciliation gap: {total:.2f} vs {obj_meur:.2f} MEUR")

    return {"ok": len(issues) == 0, "issues": issues, "max_imbalance_mw": max_imbalance_mw}


def run_smr_flexibility(solver: str = "highs") -> dict:
    meta = load_metadata()
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])

    if not FLEXIBLE_REF["solved"].exists():
        raise FileNotFoundError(f"Missing flexible reference: {FLEXIBLE_REF['solved']}")

    flex_n = pypsa.Network(str(FLEXIBLE_REF["solved"]))

    smr_params = load_technology_cost_parameters(SMR_CARRIER)
    smr_params.update(
        {
            "marginal_cost_eur_per_mwh": 12.09,
            "efficiency": 0.33,
            "p_max_pu": 0.9,
            "p_min_pu": 0.0,
            "ramp_limit_per_hour_pu": 0.5,
        }
    )
    buses = resolve_nuclear_buses(pypsa.Network(str(PREPARED_SEVERE)))
    lim_prep = build_prepared_scenario(
        pypsa.Network(str(PREPARED_SEVERE)), True, smr_params, buses
    )
    apply_limited_flex_params(lim_prep, LIMITED_FLEX["p_min_pu"], LIMITED_FLEX["ramp_per_snapshot"])
    lim_n = lim_prep

    # Validate against flexible solved network (static inputs); limited built from prepared base.
    ref_static = pypsa.Network(str(PREPARED_SEVERE))
    retire_coal_lignite(ref_static)
    _enable_load_shedding(ref_static, voll=VOLL)
    add_fixed_nuclear(ref_static, SMR_CARRIER, SMR_CAPACITY_GW * 1000.0, smr_params, buses)
    validation = validate_input_differences(ref_static, lim_n)
    if not validation["ok"]:
        raise RuntimeError(f"Pre-solve validation failed: {validation['issues']}")

    prepare_for_solve(lim_n)
    solve_info = solve_network(lim_n, solver=solver)
    val = validate_flex_solve(lim_n, solve_info)
    if not val["ok"]:
        raise RuntimeError(f"Post-solve validation failed: {val['issues']}")

    LIMITED_FLEX["solved"].parent.mkdir(parents=True, exist_ok=True)
    lim_n.export_to_netcdf(str(LIMITED_FLEX["solved"]))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    core_rows = []
    full_rows = []
    for cfg, n in [(FLEXIBLE_REF, flex_n), (LIMITED_FLEX, lim_n)]:
        for scope, snaps, bucket in [
            ("core", _slice_snapshots(n, core_start, core_end), core_rows),
            ("full_window", pd.DatetimeIndex(n.snapshots), full_rows),
        ]:
            row = flexibility_row(cfg["label"], n, snaps, cfg["p_min_pu"], cfg["ramp_per_snapshot"])
            row["scope"] = scope
            bucket.append(row)

    core_df = pd.DataFrame(core_rows)
    full_df = pd.DataFrame(full_rows)

    def impact(df: pd.DataFrame, metric: str) -> float:
        flex = float(df[df["scenario"] == FLEXIBLE_REF["label"]].iloc[0][metric])
        lim = float(df[df["scenario"] == LIMITED_FLEX["label"]].iloc[0][metric])
        return lim - flex

    impacts = {
        "description": DESCRIPTION,
        "eens_impact_gwh_core": round(impact(core_df, "eens_gwh"), 4),
        "eens_impact_gwh_full_window": round(impact(full_df, "eens_gwh"), 4),
        "peak_shedding_impact_gw_core": round(impact(core_df, "peak_load_shedding_gw"), 4),
        "peak_shedding_impact_gw_full_window": round(impact(full_df, "peak_load_shedding_gw"), 4),
        "curtailment_impact_twh_core": round(impact(core_df, "renewable_curtailment_twh"), 4),
        "curtailment_impact_twh_full_window": round(impact(full_df, "renewable_curtailment_twh"), 4),
        "modelled_penalty_change_meur_core": round(impact(core_df, "load_shedding_penalty_meur"), 2),
        "modelled_penalty_change_meur_full_window": round(impact(full_df, "load_shedding_penalty_meur"), 2),
    }

    eens_cmp = []
    for scope, df in [("core", core_df), ("full_window", full_df)]:
        for m in ["eens_gwh", "eens_pct_demand", "peak_load_shedding_gw", "load_shedding_snapshots"]:
            eens_cmp.append(
                {
                    "scope": scope,
                    "metric": m,
                    "flexible_smr": float(df[df["scenario"] == FLEXIBLE_REF["label"]].iloc[0][m]),
                    "limited_flex_smr": float(df[df["scenario"] == LIMITED_FLEX["label"]].iloc[0][m]),
                    "difference": impact(df, m),
                }
            )

    curt_cmp = []
    for scope, df in [("core", core_df), ("full_window", full_df)]:
        curt_cmp.append(
            {
                "scope": scope,
                "flexible_smr_twh": float(df[df["scenario"] == FLEXIBLE_REF["label"]].iloc[0]["renewable_curtailment_twh"]),
                "limited_flex_smr_twh": float(df[df["scenario"] == LIMITED_FLEX["label"]].iloc[0]["renewable_curtailment_twh"]),
                "curtailment_impact_twh": impact(df, "renewable_curtailment_twh"),
            }
        )

    lim_core = core_df[core_df["scenario"] == LIMITED_FLEX["label"]].iloc[0]
    ramp_bind = pd.DataFrame(
        [
            {
                "scenario": FLEXIBLE_REF["label"],
                "scope": "core",
                "ramp_up_binding_snapshots": int(
                    core_df[core_df["scenario"] == FLEXIBLE_REF["label"]].iloc[0]["ramp_up_binding_snapshots"]
                ),
                "ramp_down_binding_snapshots": int(
                    core_df[core_df["scenario"] == FLEXIBLE_REF["label"]].iloc[0]["ramp_down_binding_snapshots"]
                ),
            },
            {
                "scenario": LIMITED_FLEX["label"],
                "scope": "core",
                "ramp_up_binding_snapshots": int(lim_core["ramp_up_binding_snapshots"]),
                "ramp_down_binding_snapshots": int(lim_core["ramp_down_binding_snapshots"]),
            },
            {
                "scenario": LIMITED_FLEX["label"],
                "scope": "full_window",
                "ramp_up_binding_snapshots": int(
                    full_df[full_df["scenario"] == LIMITED_FLEX["label"]].iloc[0]["ramp_up_binding_snapshots"]
                ),
                "ramp_down_binding_snapshots": int(
                    full_df[full_df["scenario"] == LIMITED_FLEX["label"]].iloc[0]["ramp_down_binding_snapshots"]
                ),
            },
        ]
    )
    min_bind = pd.DataFrame(
        [
            {
                "scenario": FLEXIBLE_REF["label"],
                "scope": "core",
                "minimum_output_binding_snapshots": int(
                    core_df[core_df["scenario"] == FLEXIBLE_REF["label"]].iloc[0]["minimum_output_binding_snapshots"]
                ),
            },
            {
                "scenario": LIMITED_FLEX["label"],
                "scope": "core",
                "minimum_output_binding_snapshots": int(lim_core["minimum_output_binding_snapshots"]),
            },
            {
                "scenario": LIMITED_FLEX["label"],
                "scope": "full_window",
                "minimum_output_binding_snapshots": int(
                    full_df[full_df["scenario"] == LIMITED_FLEX["label"]].iloc[0]["minimum_output_binding_snapshots"]
                ),
            },
        ]
    )

    pd.DataFrame(
        [
            {
                "scenario": LIMITED_FLEX["key"],
                "status": solve_info["status"],
                "objective_meur": round(float(solve_info["objective"]) / 1e6, 2),
                "solve_time_s": round(solve_info.get("solve_time_s", 0.0), 1),
            },
            {
                "scenario": FLEXIBLE_REF["key"],
                "status": "ok",
                "objective_meur": round(float(flex_n.objective) / 1e6, 2),
                "solve_time_s": 0.0,
                "reused": True,
            },
        ]
    ).to_csv(OUTPUT_DIR / "solver_status.csv", index=False)
    pd.DataFrame([validation]).to_csv(OUTPUT_DIR / "scenario_input_validation.csv", index=False)
    core_df.to_csv(OUTPUT_DIR / "flexibility_comparison_core.csv", index=False)
    full_df.to_csv(OUTPUT_DIR / "flexibility_comparison_full_window.csv", index=False)
    ramp_bind.to_csv(OUTPUT_DIR / "ramp_binding_summary.csv", index=False)
    min_bind.to_csv(OUTPUT_DIR / "minimum_output_binding_summary.csv", index=False)
    pd.DataFrame(eens_cmp).to_csv(OUTPUT_DIR / "eens_comparison.csv", index=False)
    pd.DataFrame(curt_cmp).to_csv(OUTPUT_DIR / "curtailment_comparison.csv", index=False)
    pd.DataFrame(
        [
            {
                "scenario": LIMITED_FLEX["key"],
                "max_imbalance_mw": val["max_imbalance_mw"],
                "validation_ok": val["ok"],
            }
        ]
    ).to_csv(OUTPUT_DIR / "energy_balance_validation.csv", index=False)
    pd.DataFrame([impacts]).to_csv(OUTPUT_DIR / "flexibility_impact_summary.csv", index=False)

    create_plots(flex_n, lim_n, meta, OUTPUT_DIR)

    return {
        "all_ok": val["ok"] and validation["ok"],
        "core_df": core_df,
        "full_df": full_df,
        "impacts": impacts,
        "validation": validation,
        "solve_info": solve_info,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V4 SMR flexibility sensitivity")
    parser.add_argument("--solver", default="highs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_smr_flexibility(solver=args.solver)
    print(json.dumps({"all_ok": result["all_ok"], "impacts": result["impacts"]}, indent=2))


if __name__ == "__main__":
    main()
