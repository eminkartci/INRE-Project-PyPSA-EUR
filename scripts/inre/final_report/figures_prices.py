# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Modelled marginal price figures (P1–P2)."""

from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from scripts.inre.final_report.data_loaders import PackageContext, VOLL, load_metadata, load_network
from scripts.inre.final_report.figure_utils import save_figure_with_data
from scripts.inre.final_report.prices import demand_weighted_system_price, price_duration_curve, validate_prices
from scripts.inre.report_style import LINE_WIDTH, add_core_shading, group_color

SCRIPT = "scripts/inre/final_report/figures_prices.py"

P1_SCENARIOS = [
    ("matched-base-v4", "Matched reference"),
    ("stylised-df-severe-v4", "Severe"),
]

P2_SCENARIOS = [
    ("matched-base-v4", "Matched reference"),
    ("stylised-df-severe-v4", "Severe fossil-rich"),
    ("stylised-df-severe-decarb-v4", "Decarbonised no nuclear"),
    ("stylised-df-severe-decarb-smr-4.5-v4", "Decarbonised +4.5 GW SMR"),
]


def figure_p1_price_timeseries(ctx: PackageContext) -> None:
    meta = ctx.meta
    fig, ax = plt.subplots(figsize=(10, 4.5))
    rows = []
    ymax = 0.0
    add_core_shading(ax, meta, alpha=0.12, label="14-day Dunkelflaute core")
    for key, label in P1_SCENARIOS:
        n = load_network(key, ctx)
        if n is None:
            continue
        val = validate_prices(n, key)
        if not val["ok"]:
            ctx.warnings.extend([f"P1 {key}: {i}" for i in val["issues"]])
        snaps = pd.DatetimeIndex(n.snapshots)
        p = demand_weighted_system_price(n, snaps)
        non_scarcity = p[p < 0.99 * VOLL]
        ymax = max(ymax, float(non_scarcity.max()) * 1.1 if len(non_scarcity) else 50)
        color = group_color("onshore wind") if "Matched" in label else group_color("CCGT")
        ax.plot(snaps, p, label=label, lw=LINE_WIDTH, color=color)
        for ts, price in zip(snaps, p):
            rows.append({"timestamp": ts, "scenario": label, "modelled_marginal_price_EUR_per_MWh": float(price)})
    ax.set_ylim(0, max(ymax, 10))
    ax.set_ylabel("Modelled marginal electricity price [EUR/MWh]")
    ax.set_xlabel("Date")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    handles, labels = ax.get_legend_handles_labels()
    legend_order = ["Matched reference", "Severe", "14-day Dunkelflaute core"]
    ax.legend(
        [handles[labels.index(name)] for name in legend_order],
        legend_order,
        fontsize=9,
    )
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_P1",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-de-matched-base-v4/; results/inre-de-stylised-df-severe-v4/",
        source_file="networks/base_s_10_elec_.nc (buses_t.marginal_price)",
        temporal_scope="28-day modelling window",
        scenarios="matched reference; severe",
        plotted_variables="demand-weighted national modelled marginal electricity price [EUR/MWh]",
        key_values_checked="y-limit based on non-scarcity values; no load shedding in either scenario",
    )


def figure_p2_duration_curve(ctx: PackageContext) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    rows = []
    zoom_limit = 500
    for key, label in P2_SCENARIOS:
        n = load_network(key, ctx)
        if n is None:
            continue
        p = price_duration_curve(demand_weighted_system_price(n))
        axes[0].plot(range(len(p)), p.values, label=label, lw=LINE_WIDTH)
        p_zoom = p[p <= zoom_limit]
        axes[1].plot(range(len(p_zoom)), p_zoom.values, label=label, lw=LINE_WIDTH)
        near_voll = int((p >= 0.99 * VOLL).sum())
        for rank, price in enumerate(p.values):
            rows.append(
                {
                    "scenario": label,
                    "rank": rank,
                    "modelled_marginal_price_EUR_per_MWh": float(price),
                    "near_VOLL": bool(price >= 0.99 * VOLL),
                }
            )
    axes[0].axhline(VOLL, color=group_color("load shedding"), ls=":", lw=1.0, label=f"VOLL ({VOLL:.0f} EUR/MWh)")
    axes[0].set_xlabel("Sorted snapshot rank")
    axes[0].set_ylabel("Modelled marginal electricity price [EUR/MWh]")
    axes[0].set_title("Panel A: full scale (including scarcity prices)")
    axes[1].set_ylim(0, zoom_limit)
    axes[1].set_xlabel("Sorted snapshot rank (non-scarcity subset)")
    axes[1].set_ylabel("Modelled marginal electricity price [EUR/MWh]")
    axes[1].set_title(f"Panel B: non-scarcity range (≤{zoom_limit} EUR/MWh)")
    axes[0].legend(fontsize=7)
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_P2",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-decarbonised-adequacy/",
        source_file="solved networks",
        temporal_scope="28-day modelling window",
        scenarios="matched reference; severe; decarbonised no nuclear; decarbonised +4.5 GW SMR",
        plotted_variables="sorted modelled marginal electricity prices [EUR/MWh]",
        key_values_checked="decarb no-nuclear≈69 VOLL snapshots; decarb SMR≈52 VOLL snapshots",
    )


def build_price_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_p1_price_timeseries(ctx)
    figure_p2_duration_curve(ctx)
