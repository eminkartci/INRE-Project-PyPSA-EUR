# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Modelled marginal price figures (P1–P3)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.inre.final_report.data_loaders import PackageContext, load_metadata, load_network
from scripts.inre.final_report.prices import (
    demand_weighted_system_price,
    nodal_price_band,
    price_duration_curve,
    price_statistics,
    validate_prices,
)
from scripts.inre.final_report.tables import export_table
from scripts.inre.report_style import add_core_shading, save_figure, short_scenario

PRICE_SCENARIOS = [
    ("matched-base-v4", "Matched Base"),
    ("stylised-df-severe-v4", "Severe"),
    ("stylised-df-severe-nuc-4.5-v4", "Severe + 4.5 GW SMR"),
    ("stylised-df-severe-decarb-v4", "Decarbonised no nuclear"),
    ("stylised-df-severe-decarb-smr-4.5-v4", "Decarbonised + 4.5 GW SMR"),
]

PRICE_CAPTION_LIMIT = (
    "These are optimisation shadow prices from a fixed-capacity dispatch model, "
    "not observed or forecast day-ahead market prices."
)


def _reg(ctx, fig_id, title, msg, appendix=False):
    ctx.figure_manifest.append(
        {
            "figure_id": fig_id,
            "filename": fig_id.lower(),
            "title": title,
            "report_section": "Prices",
            "main_text_or_appendix": "appendix" if appendix else "main",
            "source_scenarios": ";".join(k for k, _ in PRICE_SCENARIOS[:3]),
            "key_message": msg,
            "recommended_width": "\\textwidth",
            "caption_file": f"captions/{fig_id.lower()}.txt",
            "validation_status": "generated",
        }
    )
    ctx.captions[fig_id] = f"{title}. {PRICE_CAPTION_LIMIT}"


def figure_p1_price_timeseries(ctx: PackageContext) -> None:
    meta = ctx.meta
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for key, label in PRICE_SCENARIOS[:2]:
        n = load_network(key, ctx)
        if n is None:
            continue
        val = validate_prices(n, key)
        if not val["ok"]:
            ctx.warnings.extend([f"P1 {key}: {i}" for i in val["issues"]])
        snaps = pd.DatetimeIndex(n.snapshots)
        p = demand_weighted_system_price(n, snaps)
        pmin, pmax = nodal_price_band(n, snaps)
        for ax in axes:
            add_core_shading(ax, meta, alpha=0.12)
            ax.fill_between(snaps, pmin, pmax, alpha=0.15, color="grey")
            ax.plot(snaps, p, label=label, lw=1)
    axes[0].set_ylabel("EUR/MWh")
    axes[0].set_ylim(0, 50)
    axes[0].set_title("Zoomed scale (0–50 EUR/MWh)")
    axes[0].legend(fontsize=8)
    cap = 500
    axes[1].set_ylim(0, cap)
    axes[1].set_ylabel("EUR/MWh")
    axes[1].set_xlabel("Time")
    axes[1].set_title(f"Full scale (0–{cap} EUR/MWh)")
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_P1", ctx.output_dir)
    _reg(ctx, "FIGURE_P1", "Matched Base versus severe price time series", "Demand-weighted nodal marginal price with min–max band")


def figure_p2_duration_curve(ctx: PackageContext) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for key, label in PRICE_SCENARIOS:
        n = load_network(key, ctx)
        if n is None:
            continue
        p = price_duration_curve(demand_weighted_system_price(n))
        axes[0].plot(p.values, label=label, lw=1)
        p_cap = p[p <= 500]
        axes[1].plot(p_cap.values, label=label, lw=1)
    axes[0].set_xlabel("Hours (sorted)")
    axes[0].set_ylabel("EUR/MWh")
    axes[0].set_title("Panel A: full scale")
    axes[1].set_title("Panel B: non-scarcity range (≤500 EUR/MWh)")
    axes[0].legend(fontsize=6)
    plt.tight_layout()
    save_figure(fig, "FIGURE_P2", ctx.output_dir)
    _reg(ctx, "FIGURE_P2", "Price-duration curve", "Five-scenario price duration curves", appendix=True)


def figure_p3_price_distribution(ctx: PackageContext) -> None:
    data = []
    labels = []
    for key, label in PRICE_SCENARIOS[:3]:
        n = load_network(key, ctx)
        if n is None:
            continue
        p = demand_weighted_system_price(n).values
        data.append(p)
        labels.append(label)
    if not data:
        return
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot(data, labels=labels, showfliers=True)
    ax.set_ylabel("EUR/MWh")
    ax.set_title("Modelled marginal-price distribution and summary")
    plt.tight_layout()
    save_figure(fig, "FIGURE_P3", ctx.output_dir)
    _reg(ctx, "FIGURE_P3", "Price distribution and summary", "Box plot for Base, Severe, Severe+SMR", appendix=True)


def build_price_tables_and_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    stats = []
    for key, label in PRICE_SCENARIOS:
        n = load_network(key, ctx)
        if n is None:
            continue
        stats.append(price_statistics(n, key, label))
    if stats:
        df = pd.DataFrame(stats)
        export_table(df, "TABLE_P1", "Modelled marginal-price statistics", ctx.output_dir)
        ctx.table_manifest.append(
            {
                "table_id": "P1",
                "filename": "tables/table_p1_modelled_marginal_price_statistics.csv",
                "title": "Modelled marginal-price statistics",
                "report_section": "Prices",
                "main_text_or_appendix": "main",
                "source_scenarios": "Base; Severe; nuclear; decarb",
                "key_message": "3-hourly demand-weighted shadow prices",
                "validation_status": "generated",
            }
        )
    figure_p1_price_timeseries(ctx)
    figure_p2_duration_curve(ctx)
    figure_p3_price_distribution(ctx)
