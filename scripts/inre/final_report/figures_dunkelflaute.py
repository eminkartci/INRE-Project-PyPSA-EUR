# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Dunkelflaute methodology figures (D2–D3 for final report)."""

from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from scripts.inre.final_report.data_loaders import (
    RENEWABLE_CARRIERS,
    PackageContext,
    load_metadata,
    load_network,
    national_demand_gw,
)
from scripts.inre.final_report.figure_utils import save_figure_with_data
from scripts.inre.report_style import LINE_WIDTH, add_core_shading, group_color

SCRIPT = "scripts/inre/final_report/figures_dunkelflaute.py"


def _agg_cf(n, snaps, carriers) -> pd.Series:
    cap = n.generators[n.generators.carrier.isin(carriers)]["p_nom"].sum()
    s = pd.Series(0.0, index=snaps)
    for gen in n.generators[n.generators.carrier.isin(carriers)].index:
        if gen in n.generators_t.p_max_pu.columns:
            s += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
    return s / cap if cap else s


def figure_d2_base_vs_severe(ctx: PackageContext) -> None:
    meta = ctx.meta
    nb = load_network("matched-base-v4", ctx)
    ns = load_network("stylised-df-severe-v4", ctx)
    if nb is None or ns is None:
        return
    snaps = pd.DatetimeIndex(nb.snapshots)
    groups = [
        ("Onshore wind", ["onwind"]),
        ("Offshore wind", ["offwind-ac", "offwind-dc", "offwind-float"]),
        ("Solar", ["solar", "solar-hsat"]),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, sharey=True)
    rows = []
    for ax, (title, carriers) in zip(axes, groups):
        ref = _agg_cf(nb, snaps, carriers)
        sev = _agg_cf(ns, snaps, carriers)
        add_core_shading(ax, meta, alpha=0.15)
        ax.plot(snaps, ref, label="Matched reference", color=group_color("onshore wind"), ls="-", lw=LINE_WIDTH)
        ax.plot(snaps, sev, label="Severe profile", color=group_color("CCGT"), ls="--", lw=LINE_WIDTH)
        ax.set_ylabel("Capacity factor [p.u.]")
        ax.set_title(title)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=9, loc="upper right")
        for ts, rv, sv in zip(snaps, ref, sev):
            rows.append(
                {
                    "timestamp": ts,
                    "technology": title,
                    "matched_reference_cf": rv,
                    "severe_cf": sv,
                }
            )
    axes[-1].set_xlabel("Date")
    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_D2",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-de-matched-base-v4/; results/inre-de-stylised-df-severe-v4/",
        source_file="networks/base_s_10_elec_.nc",
        temporal_scope="28-day modelling window",
        scenarios="matched reference; severe",
        plotted_variables="capacity-weighted capacity factor [p.u.] by VRE technology",
        key_values_checked="severe plateau multipliers: onshore 0.20, offshore 0.25, solar 0.15",
    )


def figure_d3_residual_load(ctx: PackageContext) -> None:
    meta = ctx.meta
    ns = load_network("stylised-df-severe-v4", ctx)
    if ns is None:
        return
    snaps = pd.DatetimeIndex(ns.snapshots)

    def vre_gw(n):
        ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
        s = pd.Series(0.0, index=snaps)
        for gen in ren.index:
            if gen in n.generators_t.p_max_pu.columns:
                s += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
        return s / 1e3

    demand = national_demand_gw(ns, snaps)
    vre = vre_gw(ns)
    residual = demand - vre

    fig, ax = plt.subplots(figsize=(10, 4.5))
    add_core_shading(ax, meta, alpha=0.15)
    ax.fill_between(snaps, 0, vre, alpha=0.35, color=group_color("solar"), label="Available VRE")
    ax.plot(snaps, residual, color=group_color("lignite"), ls="--", lw=LINE_WIDTH, label="Residual load")
    ax.plot(snaps, demand, color=group_color("demand"), lw=LINE_WIDTH, label="Demand", zorder=5)
    ax.set_ylabel("Power [GW]")
    ax.set_xlabel("Date")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(fontsize=9, loc="upper right")
    fig.autofmt_xdate()
    plt.tight_layout()

    plot_data = pd.DataFrame(
        {
            "timestamp": snaps,
            "demand_GW": demand.values,
            "available_VRE_GW": vre.values,
            "residual_load_GW": residual.values,
        }
    )
    save_figure_with_data(
        fig,
        "FIGURE_D3",
        ctx,
        plot_data,
        script=SCRIPT,
        source_folder="results/inre-de-stylised-df-severe-v4/",
        source_file="networks/base_s_10_elec_.nc",
        temporal_scope="28-day modelling window (severe profile)",
        scenarios="severe",
        plotted_variables="demand, available VRE, residual load [GW]",
        key_values_checked="residual load = demand − available VRE (not dispatched VRE)",
    )


def build_dunkelflaute_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_d2_base_vs_severe(ctx)
    figure_d3_residual_load(ctx)
