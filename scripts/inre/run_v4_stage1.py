# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
PyPSA Stage 1 solve for stylised Dunkelflaute V4 (matched-base + severe only).

Loads prepared networks, applies load shedding and CO2 patch, solves, validates,
and exports comparison tables/plots to results/inre-comparison-v4-stage1/.

Usage::

    python scripts/inre/run_v4_stage1.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.inre.apply_inre_network import _patch_co2_emissions_for_thermal
from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS, audit_scenario_differences
from scripts.inre.run_v3_operational_stress import _enable_load_shedding
from scripts.inre.verify_co2_accounting import network_co2_checks, physical_check_ccgt

logger = logging.getLogger(__name__)

VOLL = 100_000.0
EXPECTED_SNAPSHOTS = 224

STAGE1_SCENARIOS = {
    "matched-base-v4": {
        "prepared": REPO_ROOT / "results/stylised-df-matched-base-v4/networks/base_s_10_elec_.nc",
        "solved": REPO_ROOT / "results/inre-de-matched-base-v4/networks/base_s_10_elec_.nc",
        "label": "Matched Base",
    },
    "stylised-df-severe-v4": {
        "prepared": REPO_ROOT / "results/stylised-df-severe-v4/networks/base_s_10_elec_.nc",
        "solved": REPO_ROOT / "results/inre-de-stylised-df-severe-v4/networks/base_s_10_elec_.nc",
        "label": "Severe",
    },
}

OUTPUT_DIR = REPO_ROOT / "results/inre-comparison-v4-stage1"
METADATA_PATH = REPO_ROOT / "data/inre/profiles/stylised_dunkelflaute_v4/metadata.yaml"


def load_metadata() -> dict:
    return yaml.safe_load(METADATA_PATH.read_text())


def _weight(n: pypsa.Network, snapshots: pd.DatetimeIndex | None = None) -> pd.Series:
    snaps = snapshots if snapshots is not None else pd.DatetimeIndex(n.snapshots)
    return n.snapshot_weightings.objective.reindex(snaps).fillna(1.0)


def _slice_snapshots(n: pypsa.Network, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    snaps = pd.DatetimeIndex(n.snapshots)
    return snaps[(snaps >= start) & (snaps <= end)]


def verify_prepared_networks() -> dict:
    """Pre-solve checks on prepared (unsolved) networks."""
    paths = {k: v["prepared"] for k, v in STAGE1_SCENARIOS.items()}
    networks = {k: pypsa.Network(str(p)) for k, p in paths.items()}
    base_key = "matched-base-v4"
    n0 = networks[base_key]
    issues: list[str] = []

    for key, n in networks.items():
        if len(n.snapshots) != EXPECTED_SNAPSHOTS:
            issues.append(f"{key}: expected {EXPECTED_SNAPSHOTS} snapshots, got {len(n.snapshots)}")
        for comp, attr in [
            ("generators", "p_nom_extendable"),
            ("storage_units", "p_nom_extendable"),
            ("stores", "e_nom_extendable"),
            ("lines", "s_nom_extendable"),
            ("links", "p_nom_extendable"),
        ]:
            obj = getattr(n, comp)
            ext = int(getattr(obj, attr).sum()) if len(obj) else 0
            if ext:
                issues.append(f"{key}: {comp}.{attr} has {ext} extendable assets")

    if not _series_equal_df(n0.loads_t.p_set, networks["stylised-df-severe-v4"].loads_t.p_set):
        issues.append("Demand differs between matched-base and severe prepared networks")

    static_checks = [
        ("generators", "p_nom"),
        ("storage_units", "p_nom"),
        ("stores", "e_nom"),
        ("lines", "s_nom"),
        ("links", "p_nom"),
    ]
    for comp, attr in static_checks:
        v0 = getattr(n0, comp)[attr]
        v1 = getattr(networks["stylised-df-severe-v4"], comp)[attr]
        if not _series_equal_df(v0, v1):
            issues.append(f"{comp}.{attr} differs between scenarios")

    ren0 = n0.generators[n0.generators.carrier.isin(RENEWABLE_CARRIERS)].index
    pm0 = n0.generators_t.p_max_pu[ren0]
    pm1 = networks["stylised-df-severe-v4"].generators_t.p_max_pu[ren0]
    if _series_equal_df(pm0, pm1):
        issues.append("Renewable p_max_pu is identical between matched-base and severe (unexpected)")

    nonren = n0.generators.index.difference(ren0)
    for col in nonren:
        if col in n0.generators_t.p_max_pu.columns and col in networks["stylised-df-severe-v4"].generators_t.p_max_pu.columns:
            if not np.allclose(
                n0.generators_t.p_max_pu[col].values,
                networks["stylised-df-severe-v4"].generators_t.p_max_pu[col].values,
                rtol=1e-9,
                atol=1e-9,
            ):
                issues.append(f"Non-renewable p_max_pu differs for {col}")

    diff_audit = audit_scenario_differences(REPO_ROOT)
    unexpected = diff_audit[(diff_audit["difference_expected"] == False) & (diff_audit["status"] != "ok")]
    if not unexpected.empty:
        issues.append(f"Scenario difference audit unexpected rows: {len(unexpected)}")

    return {"ok": len(issues) == 0, "issues": issues, "networks": networks}


def _series_equal_df(a, b, rtol=1e-9, atol=1e-9) -> bool:
    if isinstance(a, pd.Series) and isinstance(b, pd.Series):
        if not a.index.equals(b.index):
            return False
        return bool(np.allclose(a.values, b.values, rtol=rtol, atol=atol, equal_nan=True))
    if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
        if not a.columns.equals(b.columns):
            return False
        if len(a) != len(b):
            return False
        return bool(np.allclose(a.values, b.values, rtol=rtol, atol=atol, equal_nan=True))
    return bool(np.allclose(np.asarray(a), np.asarray(b), rtol=rtol, atol=atol, equal_nan=True))


def prepare_for_solve(n: pypsa.Network) -> None:
    _enable_load_shedding(n, voll=VOLL)
    _patch_co2_emissions_for_thermal(n)


def solve_network(n: pypsa.Network, solver: str = "highs") -> dict:
    t0 = time.perf_counter()
    status = n.optimize(solver_name=solver)
    elapsed = time.perf_counter() - t0
    return {
        "status": str(status[0]) if isinstance(status, tuple) else str(status),
        "condition": str(status[1]) if isinstance(status, tuple) and len(status) > 1 else "",
        "objective": float(n.objective) if n.objective is not None else float("nan"),
        "solve_time_s": elapsed,
    }


def _gen_energy_by_carrier(n: pypsa.Network, snaps: pd.DatetimeIndex) -> pd.Series:
    weight = _weight(n, snaps)
    p = n.generators_t.p.reindex(snaps).fillna(0.0)
    by_carrier: dict[str, float] = {}
    for gen in p.columns:
        carrier = n.generators.at[gen, "carrier"]
        by_carrier[carrier] = by_carrier.get(carrier, 0.0) + float((p[gen] * weight).sum())
    return pd.Series(by_carrier) / 1e6  # TWh


def _available_vre_twh(n: pypsa.Network, snaps: pd.DatetimeIndex) -> float:
    weight = _weight(n, snaps)
    ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
    total = 0.0
    for gen in ren.index:
        if gen not in n.generators_t.p_max_pu.columns:
            continue
        p_nom = float(n.generators.at[gen, "p_nom"])
        avail = n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0.0) * p_nom
        total += float((avail * weight).sum())
    return total / 1e6


def _curtailment_twh(n: pypsa.Network, snaps: pd.DatetimeIndex) -> float:
    weight = _weight(n, snaps)
    ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
    total = 0.0
    for gen in ren.index:
        if gen not in n.generators_t.p_max_pu.columns or gen not in n.generators_t.p.columns:
            continue
        p_nom = float(n.generators.at[gen, "p_nom"])
        avail = n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0.0) * p_nom
        disp = n.generators_t.p[gen].reindex(snaps).fillna(0.0)
        total += float(((avail - disp).clip(lower=0.0) * weight).sum())
    return total / 1e6


def _storage_flows(n: pypsa.Network, snaps: pd.DatetimeIndex) -> tuple[float, float]:
    weight = _weight(n, snaps)
    charge = discharge = 0.0
    if hasattr(n, "storage_units_t") and "p" in n.storage_units_t and len(n.storage_units):
        p = n.storage_units_t.p.reindex(snaps).fillna(0.0)
        discharge += float((p.clip(lower=0.0) * weight.values[:, None]).sum().sum())
        charge += float(((-p.clip(upper=0.0)) * weight.values[:, None]).sum().sum())
    if hasattr(n, "links_t") and "p0" in n.links_t and len(n.links):
        # Battery links if present
        bat_links = n.links[n.links.carrier.str.contains("battery", case=False, na=False)].index
        for link in bat_links:
            if link in n.links_t.p0.columns:
                p0 = n.links_t.p0[link].reindex(snaps).fillna(0.0)
                discharge += float((p0.clip(lower=0.0) * weight).sum())
                charge += float(((-p0.clip(upper=0.0)) * weight).sum())
    return charge / 1e6, discharge / 1e6


def _storage_soc_gwh(n: pypsa.Network, snaps: pd.DatetimeIndex) -> tuple[float, float]:
    if not hasattr(n, "storage_units_t") or "state_of_charge" not in n.storage_units_t:
        return 0.0, 0.0
    soc = n.storage_units_t.state_of_charge.reindex(snaps).fillna(0.0)
    if soc.empty:
        return 0.0, 0.0
    initial = float(soc.iloc[0].sum()) / 1e3
    final = float(soc.iloc[-1].sum()) / 1e3
    return initial, final


def _load_shed_metrics(n: pypsa.Network, snaps: pd.DatetimeIndex) -> tuple[float, float, float]:
    weight = _weight(n, snaps)
    ls = n.generators[n.generators.carrier == "load_shed"].index
    if len(ls) == 0:
        return 0.0, 0.0, 0.0
    p = n.generators_t.p[ls].reindex(snaps).fillna(0.0)
    total_mwh = float((p.mul(weight, axis=0)).sum().sum())
    peak_gw = float(p.sum(axis=1).max())
    demand_mwh = float(n.loads_t.p_set.reindex(snaps).mul(weight, axis=0).sum().sum())
    pct = 100.0 * total_mwh / demand_mwh if demand_mwh else 0.0
    return total_mwh / 1e3, pct, peak_gw / 1e3


def _co2_kt(n: pypsa.Network, snaps: pd.DatetimeIndex) -> float:
    weight = _weight(n, snaps)
    emissions = n.generators.carrier.map(n.carriers.co2_emissions).fillna(0.0)
    gen_p = n.generators_t.p.reindex(snaps).fillna(0.0)
    total = 0.0
    for gen in gen_p.columns:
        if n.generators.at[gen, "carrier"] == "load_shed":
            continue
        co2 = emissions.get(gen, emissions.get(n.generators.at[gen, "carrier"], 0.0))
        total += float((gen_p[gen] * weight * co2).sum())
    return total / 1e3


def _cost_breakdown(n: pypsa.Network, snaps: pd.DatetimeIndex) -> tuple[float, float, float]:
    weight = _weight(n, snaps)
    gen_p = n.generators_t.p.reindex(snaps).fillna(0.0)
    var_opex = 0.0
    voll_cost = 0.0
    for gen in gen_p.columns:
        mc = float(n.generators.at[gen, "marginal_cost"])
        energy_cost = float((gen_p[gen] * weight * mc).sum())
        if n.generators.at[gen, "carrier"] == "load_shed":
            voll_cost += energy_cost
        else:
            var_opex += energy_cost
    total = var_opex + voll_cost
    return var_opex / 1e6, voll_cost / 1e6, total / 1e6


def extract_metrics(n: pypsa.Network, scope: str, snaps: pd.DatetimeIndex) -> dict:
    weight = _weight(n, snaps)
    demand_twh = float(n.loads_t.p_set.reindex(snaps).mul(weight, axis=0).sum().sum()) / 1e6
    gen_by_carrier = _gen_energy_by_carrier(n, snaps)
    charge_twh, discharge_twh = _storage_flows(n, snaps)
    soc_init, soc_final = _storage_soc_gwh(n, snaps)
    eens_gwh, eens_pct, peak_ls_gw = _load_shed_metrics(n, snaps)
    var_opex, voll_cost, total_cost = _cost_breakdown(n, snaps)
    return {
        "scope": scope,
        "demand_twh": demand_twh,
        "generation_by_carrier_twh": gen_by_carrier,
        "available_vre_twh": _available_vre_twh(n, snaps),
        "renewable_curtailment_twh": _curtailment_twh(n, snaps),
        "ccgt_generation_twh": float(gen_by_carrier.get("CCGT", 0.0)),
        "storage_charge_twh": charge_twh,
        "storage_discharge_twh": discharge_twh,
        "soc_initial_gwh": soc_init,
        "soc_final_gwh": soc_final,
        "peak_load_shedding_gw": peak_ls_gw,
        "eens_gwh": eens_gwh,
        "eens_pct_demand": eens_pct,
        "co2_kt": _co2_kt(n, snaps),
        "variable_opex_excl_voll_meur": var_opex,
        "load_shedding_penalty_meur": voll_cost,
        "total_operational_cost_meur": total_cost,
    }


def validate_solved(n: pypsa.Network, solve_info: dict) -> dict:
    issues: list[str] = []
    status = solve_info["status"].lower()
    if "ok" not in status and "optimal" not in status:
        issues.append(f"Solver status not optimal: {solve_info['status']}")

    for comp, attr in [
        ("generators", "p_nom_extendable"),
        ("storage_units", "p_nom_extendable"),
        ("stores", "e_nom_extendable"),
        ("lines", "s_nom_extendable"),
        ("links", "p_nom_extendable"),
    ]:
        obj = getattr(n, comp)
        if len(obj) and int(getattr(obj, attr).sum()):
            issues.append(f"{comp}.{attr} still extendable after solve")

    if n.generators_t.p.isna().any().any():
        issues.append("NaN in generators_t.p")
    if n.loads_t.p_set.isna().any().any():
        issues.append("NaN in loads_t.p_set")

    snaps = pd.DatetimeIndex(n.snapshots)
    weight = _weight(n, snaps)
    gen_sum = n.generators_t.p.mul(weight, axis=0).sum(axis=1)
    load_sum = n.loads_t.p_set.mul(weight, axis=0).sum(axis=1)
    ls = n.generators[n.generators.carrier == "load_shed"].index
    ls_sum = n.generators_t.p[ls].mul(weight, axis=0).sum(axis=1) if len(ls) else 0.0
    stor = 0.0
    if len(n.storage_units) and "p" in n.storage_units_t:
        stor = n.storage_units_t.p.mul(weight, axis=0).sum(axis=1)
    imbalance = (gen_sum - load_sum - ls_sum - stor).abs()
    max_imbalance_mw = float(imbalance.max())
    if max_imbalance_mw > 1.0:
        issues.append(f"Max nodal energy balance imbalance {max_imbalance_mw:.2f} MW")

    var_opex, voll, total = _cost_breakdown(n, snaps)
    obj_meur = float(n.objective) / 1e6 if n.objective is not None else float("nan")
    if abs(total - obj_meur) > 0.5:
        issues.append(f"Cost reconciliation gap: computed {total:.2f} vs objective {obj_meur:.2f} MEUR")

    co2_checks = network_co2_checks(n)
    expected_co2 = 0.198 / 0.6
    if abs(co2_checks.get("carrier_co2_emissions", 0) - expected_co2) > 0.01:
        issues.append("CO2 carrier not on validated MWh_el basis")

    return {"ok": len(issues) == 0, "issues": issues, "max_imbalance_mw": max_imbalance_mw}


def metrics_to_row(scenario: str, m: dict) -> dict:
    row = {
        "scenario": scenario,
        "scope": m["scope"],
        "demand_twh": round(m["demand_twh"], 4),
        "available_vre_twh": round(m["available_vre_twh"], 4),
        "renewable_curtailment_twh": round(m["renewable_curtailment_twh"], 4),
        "ccgt_generation_twh": round(m["ccgt_generation_twh"], 4),
        "storage_charge_twh": round(m["storage_charge_twh"], 4),
        "storage_discharge_twh": round(m["storage_discharge_twh"], 4),
        "soc_initial_gwh": round(m["soc_initial_gwh"], 2),
        "soc_final_gwh": round(m["soc_final_gwh"], 2),
        "peak_load_shedding_gw": round(m["peak_load_shedding_gw"], 4),
        "eens_gwh": round(m["eens_gwh"], 4),
        "eens_pct_demand": round(m["eens_pct_demand"], 4),
        "co2_kt": round(m["co2_kt"], 2),
        "variable_opex_excl_voll_meur": round(m["variable_opex_excl_voll_meur"], 2),
        "load_shedding_penalty_meur": round(m["load_shedding_penalty_meur"], 2),
        "total_operational_cost_meur": round(m["total_operational_cost_meur"], 2),
    }
    for carrier, val in m["generation_by_carrier_twh"].items():
        row[f"gen_{carrier}_twh"] = round(float(val), 4)
    return row


def create_plots(
    solved: dict[str, pypsa.Network],
    meta: dict,
    output_dir: Path,
) -> None:
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    snaps_full = pd.DatetimeIndex(solved["matched-base-v4"].snapshots)
    snaps_core = _slice_snapshots(solved["matched-base-v4"], core_start, core_end)

    def _ts_series(n, snaps, fn):
        return fn(n, snaps)

    def demand_gw(n, snaps):
        w = _weight(n, snaps)
        return n.loads_t.p_set.reindex(snaps).sum(axis=1) / 1e3

    def vre_avail_gw(n, snaps):
        ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
        out = pd.Series(0.0, index=snaps)
        for gen in ren.index:
            if gen in n.generators_t.p_max_pu.columns:
                out += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
        return out / 1e3

    def residual_load_gw(n, snaps):
        return demand_gw(n, snaps) - vre_avail_gw(n, snaps)

    # Generation stack (core, severe vs base)
    fig, ax = plt.subplots(figsize=(12, 5))
    n_sev = solved["stylised-df-severe-v4"]
    carriers_plot = ["onwind", "offwind-ac", "solar", "CCGT", "load_shed"]
    stack = []
    labels = []
    for car in carriers_plot:
        gens = n_sev.generators[n_sev.generators.carrier == car].index
        if len(gens):
            s = n_sev.generators_t.p[gens].reindex(snaps_core).fillna(0).sum(axis=1) / 1e3
            stack.append(s.values)
            labels.append(car)
    if stack:
        ax.stackplot(snaps_core, stack, labels=labels, alpha=0.85)
    ax.plot(snaps_core, demand_gw(n_sev, snaps_core), "k--", lw=1.2, label="demand")
    ax.set_title("Core event: generation stack (Severe)")
    ax.set_ylabel("GW")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(plot_dir / "01_core_generation_stack.png", dpi=150)
    fig.savefig(plot_dir / "01_core_generation_stack.pdf")
    plt.close(fig)

    # Residual load comparison
    fig, ax = plt.subplots(figsize=(12, 5))
    for key, label, color in [
        ("matched-base-v4", "Matched Base", "C0"),
        ("stylised-df-severe-v4", "Severe", "C3"),
    ]:
        ax.plot(snaps_full, residual_load_gw(solved[key], snaps_full), label=label, color=color, lw=1)
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15, label="core")
    ax.set_title("Residual load (availability-based)")
    ax.set_ylabel("GW")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "02_residual_load.png", dpi=150)
    fig.savefig(plot_dir / "02_residual_load.pdf")
    plt.close(fig)

    # CCGT dispatch
    fig, ax = plt.subplots(figsize=(12, 4))
    for key, label in [("matched-base-v4", "Matched Base"), ("stylised-df-severe-v4", "Severe")]:
        n = solved[key]
        ccgt = n.generators[n.generators.carrier == "CCGT"].index
        if len(ccgt):
            ax.plot(snaps_full, n.generators_t.p[ccgt].reindex(snaps_full).fillna(0).sum(axis=1) / 1e3, label=label)
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_title("CCGT dispatch")
    ax.set_ylabel("GW")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "03_ccgt_dispatch.png", dpi=150)
    plt.close(fig)

    # Load shedding
    fig, ax = plt.subplots(figsize=(12, 4))
    for key, label in [("matched-base-v4", "Matched Base"), ("stylised-df-severe-v4", "Severe")]:
        n = solved[key]
        ls = n.generators[n.generators.carrier == "load_shed"].index
        if len(ls):
            ax.plot(snaps_full, n.generators_t.p[ls].reindex(snaps_full).fillna(0).sum(axis=1) / 1e3, label=label)
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_title("Load shedding")
    ax.set_ylabel("GW")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "04_load_shedding.png", dpi=150)
    plt.close(fig)

    # Storage SOC (severe)
    n = solved["stylised-df-severe-v4"]
    if hasattr(n, "storage_units_t") and "state_of_charge" in n.storage_units_t:
        fig, ax = plt.subplots(figsize=(12, 4))
        soc = n.storage_units_t.state_of_charge.reindex(snaps_full).fillna(0).sum(axis=1) / 1e3
        ax.plot(snaps_full, soc, color="C2")
        ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
        ax.set_title("Storage state of charge (Severe)")
        ax.set_ylabel("GWh")
        fig.tight_layout()
        fig.savefig(plot_dir / "05_storage_soc_severe.png", dpi=150)
        plt.close(fig)

    # Cumulative EENS
    fig, ax = plt.subplots(figsize=(12, 4))
    for key, label in [("matched-base-v4", "Matched Base"), ("stylised-df-severe-v4", "Severe")]:
        n = solved[key]
        ls = n.generators[n.generators.carrier == "load_shed"].index
        if len(ls):
            w = _weight(n, snaps_full)
            eens = n.generators_t.p[ls].reindex(snaps_full).fillna(0).sum(axis=1).mul(w) / 1e3
            ax.plot(snaps_full, eens.cumsum(), label=label)
    ax.axvspan(core_start, core_end, color="grey", alpha=0.15)
    ax.set_title("Cumulative EENS")
    ax.set_ylabel("GWh")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "06_cumulative_eens.png", dpi=150)
    plt.close(fig)

    # Core cost + CO2 bar charts
    summary_path = output_dir / "stage1_summary.csv"
    if summary_path.exists():
        df = pd.read_csv(summary_path)
        core = df[df["scope"] == "core_event"]
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        scenarios = core["scenario"].tolist()
        axes[0].bar(scenarios, core["total_operational_cost_meur"])
        axes[0].set_title("Core total operational cost [MEUR]")
        axes[0].tick_params(axis="x", rotation=15)
        axes[1].bar(scenarios, core["co2_kt"])
        axes[1].set_title("Core CO2 [kt]")
        axes[1].tick_params(axis="x", rotation=15)
        fig.tight_layout()
        fig.savefig(plot_dir / "07_core_cost_co2.png", dpi=150)
        plt.close(fig)


def run_stage1(solver: str = "gurobi") -> dict:
    meta = load_metadata()
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])

    prep = verify_prepared_networks()
    if not prep["ok"]:
        logger.warning("Pre-solve verification issues: %s", prep["issues"])

    solve_results: dict[str, dict] = {}
    solved_networks: dict[str, pypsa.Network] = {}

    for key, cfg in STAGE1_SCENARIOS.items():
        logger.info("Solving %s from %s", key, cfg["prepared"])
        n = pypsa.Network(str(cfg["prepared"]))
        prepare_for_solve(n)
        ls = n.generators[n.generators.carrier == "load_shed"]
        if len(ls) == 0:
            raise RuntimeError(f"Load shedding not configured for {key}")
        if abs(float(ls.marginal_cost.iloc[0]) - VOLL) > 1e-6:
            raise RuntimeError(f"VOLL mismatch for {key}")

        info = solve_network(n, solver=solver)
        solve_results[key] = info
        validation = validate_solved(n, info)
        solve_results[key]["validation"] = validation

        cfg["solved"].parent.mkdir(parents=True, exist_ok=True)
        n.export_to_netcdf(str(cfg["solved"]))
        logger.info("Wrote solved network %s", cfg["solved"])
        solved_networks[key] = n

    # Metrics
    rows = []
    gen_rows = []
    for key, n in solved_networks.items():
        label = STAGE1_SCENARIOS[key]["label"]
        for scope_name, snaps in [
            ("core_event", _slice_snapshots(n, core_start, core_end)),
            ("full_window", pd.DatetimeIndex(n.snapshots)),
        ]:
            m = extract_metrics(n, scope_name, snaps)
            rows.append(metrics_to_row(label, m))
            for carrier, val in m["generation_by_carrier_twh"].items():
                gen_rows.append(
                    {
                        "scenario": label,
                        "scope": scope_name,
                        "carrier": carrier,
                        "generation_twh": round(float(val), 4),
                    }
                )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(OUTPUT_DIR / "stage1_summary.csv", index=False)
    pd.DataFrame(gen_rows).to_csv(OUTPUT_DIR / "generation_by_carrier.csv", index=False)

    # Delta table helper
    def pivot_metric(scope: str, metric: str) -> pd.Series:
        sub = summary_df[summary_df["scope"] == scope].set_index("scenario")
        return sub[metric]

    # Validations export
    eens_rows = []
    cost_rows = []
    co2_rows = []
    storage_rows = []
    balance_rows = []
    for key, n in solved_networks.items():
        label = STAGE1_SCENARIOS[key]["label"]
        val = solve_results[key]["validation"]
        for scope_name, snaps in [
            ("core_event", _slice_snapshots(n, core_start, core_end)),
            ("full_window", pd.DatetimeIndex(n.snapshots)),
        ]:
            eens_gwh, eens_pct, peak = _load_shed_metrics(n, snaps)
            eens_rows.append(
                {
                    "scenario": label,
                    "scope": scope_name,
                    "eens_gwh": eens_gwh,
                    "eens_pct_demand": eens_pct,
                    "peak_load_shedding_gw": peak,
                    "status": "ok" if eens_gwh >= 0 else "check",
                }
            )
            var_opex, voll, total = _cost_breakdown(n, snaps)
            obj = float(n.objective) / 1e6
            cost_rows.append(
                {
                    "scenario": label,
                    "scope": scope_name,
                    "variable_opex_excl_voll_meur": var_opex,
                    "load_shedding_penalty_meur": voll,
                    "total_computed_meur": total,
                    "objective_meur": obj if scope_name == "full_window" else np.nan,
                    "reconciliation_gap_meur": abs(total - obj) if scope_name == "full_window" else np.nan,
                    "status": "ok" if (scope_name != "full_window" or abs(total - obj) < 0.5) else "gap",
                }
            )
            co2_rows.append(
                {
                    "scenario": label,
                    "scope": scope_name,
                    "co2_kt": _co2_kt(n, snaps),
                    "ccgt_co2_intensity": float(n.carriers.at["CCGT", "co2_emissions"])
                    if "CCGT" in n.carriers.index
                    else np.nan,
                    "status": "ok",
                }
            )
            soc_i, soc_f = _storage_soc_gwh(n, snaps)
            storage_rows.append(
                {
                    "scenario": label,
                    "scope": scope_name,
                    "soc_initial_gwh": soc_i,
                    "soc_final_gwh": soc_f,
                    "status": "ok",
                }
            )
        balance_rows.append(
            {
                "scenario": label,
                "max_imbalance_mw": val["max_imbalance_mw"],
                "validation_ok": val["ok"],
                "issues": "; ".join(val["issues"]) if val["issues"] else "",
            }
        )

    pd.DataFrame(eens_rows).to_csv(OUTPUT_DIR / "eens_validation.csv", index=False)
    pd.DataFrame(cost_rows).to_csv(OUTPUT_DIR / "cost_reconciliation.csv", index=False)
    pd.DataFrame(co2_rows).to_csv(OUTPUT_DIR / "co2_validation.csv", index=False)
    pd.DataFrame(storage_rows).to_csv(OUTPUT_DIR / "storage_summary.csv", index=False)
    pd.DataFrame(balance_rows).to_csv(OUTPUT_DIR / "energy_balance_validation.csv", index=False)

    create_plots(solved_networks, meta, OUTPUT_DIR)

    # Build comparison for return
    def compare_scope(scope: str) -> pd.DataFrame:
        sub = summary_df[summary_df["scope"] == scope].set_index("scenario")
        base = sub.loc["Matched Base"]
        sev = sub.loc["Severe"]
        metrics = [
            "demand_twh",
            "available_vre_twh",
            "renewable_curtailment_twh",
            "ccgt_generation_twh",
            "storage_charge_twh",
            "storage_discharge_twh",
            "soc_initial_gwh",
            "soc_final_gwh",
            "peak_load_shedding_gw",
            "eens_gwh",
            "eens_pct_demand",
            "co2_kt",
            "variable_opex_excl_voll_meur",
            "load_shedding_penalty_meur",
            "total_operational_cost_meur",
        ]
        rows_cmp = []
        for m in metrics:
            rows_cmp.append(
                {
                    "metric": m,
                    "matched_base": base[m],
                    "severe": sev[m],
                    "difference": sev[m] - base[m],
                }
            )
        return pd.DataFrame(rows_cmp)

    return {
        "prep": prep,
        "solve_results": solve_results,
        "core_comparison": compare_scope("core_event"),
        "full_comparison": compare_scope("full_window"),
        "summary_df": summary_df,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PyPSA V4 Stage 1 solve")
    parser.add_argument(
        "--solver",
        default="gurobi",
        help="LP solver (gurobi recommended for 224-snap / ~5900-gen models; needs ~16+ GB free RAM)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_stage1(solver=args.solver)
    print(json.dumps({k: v for k, v in result["prep"].items() if k != "networks"}, indent=2))


if __name__ == "__main__":
    main()
