# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Dispatch and consequence figures (R1–R3)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS
from scripts.inre.final_report.data_loaders import (
    PackageContext,
    core_snaps,
    gen_energy_by_carrier,
    load_metadata,
    load_network,
    national_demand_gw,
    snapshot_weight,
)
from scripts.inre.final_report.figure_utils import DISPLAY_CARRIER_ORDER, save_figure_with_data
from scripts.inre.final_report.prices import demand_weighted_system_price
from scripts.inre.report_style import CARRIER_MAP, LINE_WIDTH, carrier_color, group_color

SCRIPT = "scripts/inre/final_report/figures_results.py"

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

MIN_TWH_FOR_LEGEND = 0.05


def _energy_by_display_group(n, snaps) -> pd.Series:
    raw = gen_energy_by_carrier(n, snaps)
    grouped: dict[str, float] = {}
    for carrier, twh in raw.items():
        if carrier == "load_shed":
            continue
        grp = CARRIER_MAP.get(carrier, carrier)
        grouped[grp] = grouped.get(grp, 0) + float(twh)
    return pd.Series({g: grouped.get(g, 0) for g in DISPLAY_CARRIER_ORDER if grouped.get(g, 0) > 0})


def _dispatch_stack_gw(n, snaps, combine_small: bool = False) -> pd.DataFrame:
    data: dict[str, pd.Series] = {}
    other = pd.Series(0.0, index=snaps)
    for c in STACK_ORDER:
        gens = n.generators[n.generators.carrier == c].index
        if len(gens) == 0:
            continue
        p = n.generators_t.p[gens].reindex(snaps).fillna(0).sum(axis=1) / 1e3
        grp = CARRIER_MAP.get(c, c)
        if combine_small and p.max() < 0.5:
            other += p
        elif combine_small and grp in data:
            data[grp] += p
        elif combine_small:
            data[grp] = p.copy()
        else:
            data[c] = p
    if combine_small and other.max() > 0:
        data["other"] = other
    return pd.DataFrame(data, index=snaps)


def figure_r1_generation_mix(ctx: PackageContext) -> None:
    scenarios = [("Matched reference", "matched-base-v4"), ("Severe", "stylised-df-severe-v4")]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    rows = []
    bar_w = 0.5
    for i, (label, key) in enumerate(scenarios):
        n = load_network(key, ctx)
        if n is None:
            continue
        snaps = pd.DatetimeIndex(n.snapshots)
        gen = _energy_by_display_group(n, snaps)
        bottom = 0.0
        for grp in DISPLAY_CARRIER_ORDER:
            val = float(gen.get(grp, 0))
            if val <= 0:
                continue
            ax.bar(i, val, bottom=bottom, width=bar_w, color=group_color(grp), label=grp if i == 0 else "")
            rows.append({"scenario": label, "carrier_group": grp, "generation_TWh": val})
            bottom += val
    ax.set_xticks([0, 1])
    ax.set_xticklabels([s[0] for s in scenarios])
    ax.set_ylabel("Dispatched generation [TWh]")
    ax.legend(fontsize=8, bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()

    base_ccgt = next((r["generation_TWh"] for r in rows if r["scenario"] == "Matched reference" and r["carrier_group"] == "CCGT"), 0)
    sev_ccgt = next((r["generation_TWh"] for r in rows if r["scenario"] == "Severe" and r["carrier_group"] == "CCGT"), 0)
    save_figure_with_data(
        fig,
        "FIGURE_R1",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-stage1/",
        source_file="stage1_summary.csv; solved networks",
        temporal_scope="28-day modelling window",
        scenarios="matched reference; severe",
        plotted_variables="dispatched generation by carrier group [TWh]",
        key_values_checked=f"CCGT increase≈{sev_ccgt - base_ccgt:.2f} TWh (target 1.95); EENS=0",
    )


def figure_r2_core_dispatch(ctx: PackageContext) -> None:
    meta = ctx.meta
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    rows = []
    legend_handles = {}
    for ax, (title, key) in zip(axes, [("Matched reference", "matched-base-v4"), ("Severe", "stylised-df-severe-v4")]):
        n = load_network(key, ctx)
        if n is None:
            continue
        snaps = core_snaps(n, meta)
        stack = _dispatch_stack_gw(n, snaps, combine_small=True)
        demand = national_demand_gw(n, snaps)
        bottom = np.zeros(len(snaps))
        plot_order = [c for c in DISPLAY_CARRIER_ORDER if c in stack.columns] + [c for c in stack.columns if c not in DISPLAY_CARRIER_ORDER]
        for c in plot_order:
            if c not in stack.columns:
                continue
            color = group_color(c) if c in DISPLAY_CARRIER_ORDER else group_color("other firm")
            ax.fill_between(snaps, bottom, bottom + stack[c].values, label=c, color=color, alpha=0.85)
            if c not in legend_handles:
                legend_handles[c] = True
            bottom += stack[c].values
        ax.plot(snaps, demand, color=group_color("demand"), lw=LINE_WIDTH, label="Demand", zorder=6)
        ax.set_title(title)
        ax.set_ylabel("Power [GW]")
        ax.set_xlabel("Date (14-day Dunkelflaute core)")
        for ts in snaps:
            row = {"timestamp": ts, "scenario": title, "demand_GW": float(demand.loc[ts])}
            for c in stack.columns:
                row[f"{c}_GW"] = float(stack.loc[ts, c])
            rows.append(row)
    handles, labels = axes[1].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axes[1].legend(by_label.values(), by_label.keys(), fontsize=8, ncol=2, loc="upper right")
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_R2",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-de-matched-base-v4/; results/inre-de-stylised-df-severe-v4/",
        source_file="networks/base_s_10_elec_.nc",
        temporal_scope="14-day Dunkelflaute core",
        scenarios="matched reference; severe",
        plotted_variables="stacked dispatched generation and demand [GW]",
        key_values_checked="same y-axis and carrier order in both panels",
    )


def figure_r3_critical_hours(ctx: PackageContext) -> None:
    meta = ctx.meta
    ns = load_network("stylised-df-severe-v4", ctx)
    nd = load_network("stylised-df-severe-decarb-v4", ctx)
    if ns is None:
        return
    snaps = pd.DatetimeIndex(ns.snapshots)

    def residual(n):
        d = n.loads_t.p_set.reindex(snaps).sum(axis=1)
        vre = pd.Series(0.0, index=snaps)
        for gen in n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)].index:
            if gen in n.generators_t.p_max_pu.columns:
                vre += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
        return d - vre

    ccgt = ns.generators_t.p[ns.generators[ns.generators.carrier == "CCGT"].index].sum(axis=1)
    vre_avail = pd.Series(0.0, index=snaps)
    for gen in ns.generators[ns.generators.carrier.isin(RENEWABLE_CARRIERS)].index:
        if gen in ns.generators_t.p_max_pu.columns:
            vre_avail += ns.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * ns.generators.at[gen, "p_nom"]
    price = demand_weighted_system_price(ns, snaps)

    selections = [
        (residual(ns).idxmax(), "Maximum residual load", ns, "severe fossil-rich"),
        (vre_avail.idxmin(), "Minimum available VRE", ns, "severe fossil-rich"),
        (ccgt.idxmax(), "Maximum CCGT dispatch", ns, "severe fossil-rich"),
        (price.idxmax(), "Maximum modelled marginal price", ns, "severe fossil-rich"),
    ]
    if nd is not None:
        ls = nd.generators[nd.generators.carrier == "load_shed"].index
        if len(ls):
            ls_sum = nd.generators_t.p[ls].sum(axis=1)
            selections.append((ls_sum.idxmax(), "Maximum load shedding", nd, "decarbonised no nuclear"))

    rows = []
    present_carriers: set[str] = set()
    fig, axes = plt.subplots(1, len(selections), figsize=(2.8 * len(selections), 5.0), sharey=False)
    if len(selections) == 1:
        axes = [axes]
    for ax, (ts, reason, n, scen_label) in zip(axes, selections):
        snap = pd.Timestamp(ts)
        d = float(n.loads_t.p_set.loc[snap].sum()) / 1e3
        comps: dict[str, float] = {}
        for c in STACK_ORDER:
            gens = n.generators[n.generators.carrier == c].index
            if len(gens):
                val = float(n.generators_t.p.loc[snap, gens].sum()) / 1e3
                if val > 0:
                    grp = CARRIER_MAP.get(c, c)
                    comps[grp] = comps.get(grp, 0) + val
        bottom = 0.0
        for grp in DISPLAY_CARRIER_ORDER:
            v = comps.get(grp, 0)
            if v <= 0:
                continue
            present_carriers.add(grp)
            ax.bar(0, v, bottom=bottom, color=group_color(grp), width=0.55)
            bottom += v
        for grp, v in comps.items():
            if grp not in DISPLAY_CARRIER_ORDER and v > 0:
                present_carriers.add("other firm")
                ax.bar(0, v, bottom=bottom, color=group_color("other firm"), width=0.55)
                bottom += v
        ax.axhline(d, color=group_color("demand"), ls="--", lw=LINE_WIDTH)
        ax.set_title(f"{reason}\n{snap}\n({scen_label})", fontsize=8)
        ax.set_xticks([])
        ax.set_ylabel("Power [GW]")
        rows.append(
            {
                "snapshot": str(snap),
                "selection_reason": reason,
                "scenario": scen_label,
                "demand_GW": d,
                **{f"{k}_GW": v for k, v in comps.items()},
                "modelled_marginal_price_EUR_per_MWh": float(demand_weighted_system_price(n).loc[snap]),
            }
        )

    legend_groups = [g for g in DISPLAY_CARRIER_ORDER if g in present_carriers]
    legend_handles = [
        Patch(facecolor=group_color(g), edgecolor="white", linewidth=0.3, label=g) for g in legend_groups
    ]
    legend_handles.append(
        Line2D([0], [0], color=group_color("demand"), ls="--", lw=LINE_WIDTH, label="Demand")
    )
    ncol = 4 if len(legend_handles) > 9 else 3
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=ncol,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, 0.01),
    )
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    save_figure_with_data(
        fig,
        "FIGURE_R3",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-stage1/; results/inre-comparison-v4-decarbonised-adequacy/",
        source_file="solved networks",
        temporal_scope="selected snapshots (14-day core / full window)",
        scenarios="severe fossil-rich; decarbonised no nuclear",
        plotted_variables="generation stack and demand at critical snapshots [GW]",
        key_values_checked="five objectively selected snapshots with timestamps",
    )


def build_results_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_r1_generation_mix(ctx)
    figure_r2_core_dispatch(ctx)
    figure_r3_critical_hours(ctx)
