# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Dispatch and consequence figures (R1–R4)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS
from scripts.inre.final_report.data_loaders import (
    COMPARISON_DIRS,
    PackageContext,
    core_snaps,
    load_metadata,
    load_network,
    national_demand_gw,
    read_csv,
    snapshot_weight,
)
from scripts.inre.final_report.prices import demand_weighted_system_price
from scripts.inre.report_style import CARRIER_MAP, add_core_shading, carrier_color, group_color, save_figure
from scripts.inre.final_report.data_loaders import RENEWABLE_CARRIERS, gen_energy_by_carrier


STACK_ORDER = [
    "onwind",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
    "solar",
    "solar-hsat",
    "biomass",
    "coal",
    "lignite",
    "CCGT",
    "OCGT",
    "oil",
    "waste",
    "geothermal",
    "generic-advanced-nuclear",
    "nuclear-smr",
    "load_shed",
]


def _reg(ctx, fig_id, title, section, msg, appendix=False):
    ctx.figure_manifest.append(
        {
            "figure_id": fig_id,
            "filename": fig_id.lower(),
            "title": title,
            "report_section": section,
            "main_text_or_appendix": "appendix" if appendix else "main",
            "source_scenarios": "matched-base; severe",
            "key_message": msg,
            "recommended_width": "\\textwidth",
            "caption_file": f"captions/{fig_id.lower()}.txt",
            "validation_status": "generated",
        }
    )


def _dispatch_stack_gw(n, snaps):
    w = snapshot_weight(n, snaps)
    data = {}
    for c in STACK_ORDER:
        gens = n.generators[n.generators.carrier == c].index
        if len(gens) == 0:
            continue
        p = n.generators_t.p[gens].reindex(snaps).fillna(0).sum(axis=1) / 1e3
        data[c] = p
    return pd.DataFrame(data, index=snaps)


def figure_r1_generation_mix(ctx: PackageContext) -> None:
    meta = ctx.meta
    scenarios = [("Matched Base", "matched-base-v4"), ("Severe Dunkelflaute", "stylised-df-severe-v4")]
    fig, ax = plt.subplots(figsize=(8, 4))
    xpos = []
    labels = []
    demand_vals = []
    bottoms = None
    bar_w = 0.35
    for i, (label, key) in enumerate(scenarios):
        n = load_network(key, ctx)
        if n is None:
            continue
        snaps = pd.DatetimeIndex(n.snapshots)
        gen = gen_energy_by_carrier(n, snaps)
        demand = float(n.loads_t.p_set.mul(snapshot_weight(n, snaps), axis=0).sum().sum()) / 1e6
        demand_vals.append(demand)
        x = i
        labels.append(label)
        bottom = 0.0
        for c in STACK_ORDER:
            val = float(gen.get(c, 0))
            if val <= 0:
                continue
            ax.bar(x, val, bottom=bottom, width=bar_w, color=carrier_color(c), label=c if i == 0 else "")
            bottom += val
        ax.plot(x, demand, "kD", ms=8, zorder=5)
        xpos.append(x)
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Energy [TWh]")
    ax.set_title("Generation mix comparison — full 28-day window")
    ax.legend(fontsize=6, bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    save_figure(fig, "FIGURE_R1", ctx.output_dir)
    _reg(ctx, "FIGURE_R1", "Generation mix comparison", "Results", "Stacked generation by carrier vs total demand")


def figure_r2_core_dispatch(ctx: PackageContext) -> None:
    meta = ctx.meta
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, (title, key) in zip(axes, [("Matched Base", "matched-base-v4"), ("Severe", "stylised-df-severe-v4")]):
        n = load_network(key, ctx)
        if n is None:
            continue
        snaps = core_snaps(n, meta)
        stack = _dispatch_stack_gw(n, snaps)
        demand = national_demand_gw(n, snaps)
        bottom = np.zeros(len(snaps))
        for c in stack.columns:
            ax.fill_between(snaps, bottom, bottom + stack[c].values, label=c, color=carrier_color(c), alpha=0.85)
            bottom += stack[c].values
        ax.plot(snaps, demand, "k-", lw=1.2, label="Demand")
        ax.set_title(title)
        ax.set_ylabel("Power [GW]")
    axes[1].legend(fontsize=5, ncol=2, loc="upper right")
    fig.suptitle("Dispatch time series during the 14-day core event")
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_R2", ctx.output_dir)
    _reg(ctx, "FIGURE_R2", "Dispatch time series during the full core event", "Results", "Core-period stacked dispatch", appendix=True)


def figure_r3_critical_hours(ctx: PackageContext) -> None:
    meta = ctx.meta
    ns = load_network("stylised-df-severe-v4", ctx)
    nd = load_network("stylised-df-severe-decarb-v4", ctx)
    if ns is None:
        return
    snaps = pd.DatetimeIndex(ns.snapshots)
    w = snapshot_weight(ns, snaps)

    def residual(n):
        d = n.loads_t.p_set.reindex(snaps).sum(axis=1)
        vre = pd.Series(0.0, index=snaps)
        for gen in n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)].index:
            if gen in n.generators_t.p_max_pu.columns:
                vre += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * ns.generators.at[gen, "p_nom"]
        return d - vre

    ccgt = ns.generators_t.p[ns.generators[ns.generators.carrier == "CCGT"].index].sum(axis=1)
    vre_avail = pd.Series(0.0, index=snaps)
    for gen in ns.generators[ns.generators.carrier.isin(RENEWABLE_CARRIERS)].index:
        if gen in ns.generators_t.p_max_pu.columns:
            vre_avail += ns.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * ns.generators.at[gen, "p_nom"]
    price = demand_weighted_system_price(ns, snaps)

    selections = [
        (residual(ns).idxmax(), "Max residual load", ns),
        (ccgt.idxmax(), "Max CCGT dispatch", ns),
        (vre_avail.idxmin(), "Min available VRE", ns),
        (price.idxmax(), "Max modelled marginal price", ns),
    ]
    if nd is not None:
        ls = nd.generators[nd.generators.carrier == "load_shed"].index
        if len(ls):
            ls_sum = nd.generators_t.p[ls].sum(axis=1)
            selections.append((ls_sum.idxmax(), "Peak load shedding (decarb)", nd))

    rows = []
    fig, axes = plt.subplots(1, len(selections), figsize=(3 * len(selections), 4))
    if len(selections) == 1:
        axes = [axes]
    for ax, (ts, reason, n) in zip(axes, selections):
        snap = pd.Timestamp(ts)
        d = float(n.loads_t.p_set.loc[snap].sum()) / 1e3
        comps = {}
        for c in STACK_ORDER:
            gens = n.generators[n.generators.carrier == c].index
            if len(gens):
                comps[c] = float(n.generators_t.p.loc[snap, gens].sum()) / 1e3
        vre_a = sum(
            float(n.generators_t.p_max_pu.loc[snap, g] * n.generators.at[g, "p_nom"])
            for g in n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)].index
            if g in n.generators_t.p_max_pu.columns
        ) / 1e3
        vre_d = sum(comps.get(c, 0) for c in RENEWABLE_CARRIERS)
        bottom = 0
        for c, v in comps.items():
            if v > 0:
                ax.bar(0, v, bottom=bottom, color=carrier_color(c), width=0.5)
                bottom += v
        ax.axhline(d, color="k", ls="--", lw=1)
        ax.set_title(f"{reason}\n{snap}", fontsize=7)
        ax.set_xticks([])
        rows.append(
            {
                "snapshot": str(snap),
                "selection_reason": reason,
                "scenario": "severe" if n is ns else "decarb",
                "demand_GW": d,
                "available_VRE_GW": vre_a,
                "dispatched_VRE_GW": vre_d,
                "coal_GW": comps.get("coal", 0),
                "lignite_GW": comps.get("lignite", 0),
                "CCGT_GW": comps.get("CCGT", 0),
                "other_firm_GW": sum(comps.get(c, 0) for c in ["biomass", "OCGT", "oil", "waste", "geothermal"]),
                "nuclear_GW": sum(comps.get(c, 0) for c in ["generic-advanced-nuclear", "nuclear-smr"]),
                "load_shedding_GW": comps.get("load_shed", 0),
                "modelled_marginal_price_EUR_per_MWh": float(demand_weighted_system_price(n).loc[snap]),
            }
        )
    fig.suptitle("Critical-hours dispatch comparison")
    plt.tight_layout()
    save_figure(fig, "FIGURE_R3", ctx.output_dir)
    pd.DataFrame(rows).to_csv(ctx.output_dir / "tables" / "critical_snapshot_summary.csv", index=False)
    _reg(ctx, "FIGURE_R3", "Critical-hours dispatch comparison", "Results", "Objective critical snapshot decomposition", appendix=True)


def figure_r4_consequences(ctx: PackageContext) -> None:
    s = read_csv(COMPARISON_DIRS["stage1"] / "stage1_summary.csv")
    if s.empty:
        return
    base = s[(s["scenario"] == "Matched Base") & (s["scope"] == "full_window")].iloc[0]
    sev = s[(s["scenario"] == "Severe") & (s["scope"] == "full_window")].iloc[0]
    metrics = [
        ("Available VRE [TWh]", float(sev["available_vre_twh"]) - float(base["available_vre_twh"])),
        ("CCGT generation [TWh]", float(sev["gen_CCGT_twh"]) - float(base.get("gen_CCGT_twh", sev["ccgt_generation_twh"] - 0))),
        ("Coal generation [TWh]", float(sev.get("gen_coal_twh", 0)) - float(base.get("gen_coal_twh", 0))),
        ("Lignite generation [TWh]", float(sev.get("gen_lignite_twh", 0)) - float(base.get("gen_lignite_twh", 0))),
        ("CO₂ [Mt]", float(sev["co2_mt"]) - float(base["co2_mt"])),
        ("OPEX excl. VOLL [M EUR]", float(sev["variable_opex_excl_voll_meur"]) - float(base["variable_opex_excl_voll_meur"])),
        ("EENS [GWh]", float(sev["eens_gwh"]) - float(base["eens_gwh"])),
    ]
    fig, ax = plt.subplots(figsize=(8, 4))
    labels, vals = zip(*metrics)
    colors = ["#6895d1" if v < 0 else "#a85522" for v in vals]
    ax.barh(labels, vals, color=colors)
    ax.axvline(0, color="k", lw=0.8)
    ax.set_xlabel("Severe minus Matched Base")
    ax.set_title("Severe-event system consequences (28-day window)")
    plt.tight_layout()
    save_figure(fig, "FIGURE_R4", ctx.output_dir)
    _reg(ctx, "FIGURE_R4", "Severe-event system consequences", "Results", "Delta KPIs: VRE −6.33 TWh, CO₂ +4.55 Mt, OPEX +197.61 M EUR")


def build_results_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_r1_generation_mix(ctx)
    figure_r2_core_dispatch(ctx)
    figure_r3_critical_hours(ctx)
    figure_r4_consequences(ctx)
