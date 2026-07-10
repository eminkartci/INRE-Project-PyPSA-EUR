# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Input and model-structure figures (I1–I4)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa

from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS
from scripts.inre.final_report.data_loaders import (
    INPUTS_V4,
    PackageContext,
    load_metadata,
    load_network,
    national_demand_gw,
    snapshot_weight,
)
from scripts.inre.report_style import (
    CARRIER_MAP,
    add_phase_shading,
    carrier_color,
    group_color,
    save_figure,
    short_scenario,
)


def _register_fig(ctx, fig_id, title, section, sources, message, appendix=False):
    ctx.figure_manifest.append(
        {
            "figure_id": fig_id,
            "filename": fig_id.lower(),
            "title": title,
            "report_section": section,
            "main_text_or_appendix": "appendix" if appendix else "main",
            "source_scenarios": sources,
            "source_files": "",
            "key_message": message,
            "recommended_width": "\\textwidth" if not appendix else "0.85\\textwidth",
            "caption_file": f"captions/{fig_id.lower()}.txt",
            "validation_status": "generated",
        }
    )
    ctx.captions[fig_id] = (
        f"{title}. Model scope: Germany, 10 PyPSA clusters, 224 three-hour snapshots, "
        f"fixed-capacity dispatch. Limitation: stylised inputs, not historical reconstruction."
    )


def figure_i1_demand(ctx: PackageContext) -> None:
    meta = ctx.meta
    n = load_network("stylised-df-severe-v4", ctx)
    if n is None:
        return
    snaps = pd.DatetimeIndex(n.snapshots)
    demand = national_demand_gw(n, snaps)
    w = snapshot_weight(n, snaps)
    energy_twh = float((demand * 1e3 * w).sum()) / 1e6

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]
    add_phase_shading(ax, meta, snaps)
    ax.plot(snaps, demand.values, color=group_color("demand"), lw=1.2)
    ax.set_ylabel("National demand [GW]")
    ax.set_title("Electricity demand over the 28-day modelling window")
    ax.annotate(
        f"Full-window energy ≈ {energy_twh:.2f} TWh\n"
        f"Min {demand.min():.1f} GW | Mean {demand.mean():.1f} GW | Peak {demand.max():.1f} GW",
        xy=(0.02, 0.95),
        xycoords="axes fraction",
        va="top",
        fontsize=8,
        bbox=dict(boxstyle="round", fc="white", alpha=0.8),
    )

    ax2 = axes[1]
    hod = snaps.hour + snaps.minute / 60
    daily = pd.DataFrame({"hour": hod, "demand": demand.values}).groupby("hour")["demand"].mean()
    ax2.plot(daily.index, daily.values, color=group_color("demand"))
    ax2.set_xlabel("Hour of day")
    ax2.set_ylabel("Mean demand [GW]")
    ax2.set_title("Average daily demand profile")
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_I1", ctx.output_dir)
    _register_fig(
        ctx,
        "FIGURE_I1",
        "Electricity demand over the 28-day modelling window",
        "Inputs",
        "all V4",
        f"28-day demand ≈ {energy_twh:.2f} TWh; 224 three-hour snapshots",
    )


def _capacity_by_group(n: pypsa.Network) -> pd.Series:
    groups: dict[str, float] = {}
    for _, g in n.generators.iterrows():
        if g.carrier == "load_shed":
            continue
        grp = CARRIER_MAP.get(g.carrier, g.carrier)
        if grp in ("offshore wind", "solar"):
            groups[grp] = groups.get(grp, 0) + g.p_nom
        else:
            groups[grp] = groups.get(grp, 0) + g.p_nom
    return pd.Series(groups) / 1e3  # GW


def figure_i2_capacity(ctx: PackageContext) -> None:
    panels = [
        ("A. Existing severe-reference fleet", "stylised-df-severe-v4"),
        ("B. Decarbonised sensitivity and 4.5 GW SMR", "stylised-df-severe-decarb-smr-4.5-v4"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), sharey=True)
    for ax, (title, key) in zip(axes, panels):
        n = load_network(key, ctx)
        if n is None:
            continue
        cap = _capacity_by_group(n).sort_values()
        colors = [group_color(CARRIER_MAP.get(c, c)) if c in CARRIER_MAP else group_color(c) for c in cap.index]
        ax.barh(cap.index, cap.values, color=colors)
        ax.set_xlabel("Installed capacity [GW]")
        ax.set_title(title)
    fig.suptitle("Installed generation capacity by carrier", y=1.02)
    plt.tight_layout()
    save_figure(fig, "FIGURE_I2", ctx.output_dir)
    _register_fig(ctx, "FIGURE_I2", "Installed generation capacity by carrier", "Inputs", "severe; decarb+SMR", "Reference vs decarbonised fleet capacities")


def figure_i3_network_map(ctx: PackageContext) -> None:
    n = load_network("stylised-df-severe-v4", ctx)
    if n is None:
        return
    buses = n.buses.copy()
    if "x" not in buses.columns or buses["x"].isna().all():
        bf = pd.read_csv(INPUTS_V4 / "buses.csv")
        for _, r in bf.iterrows():
            idx = [i for i in buses.index if str(r["bus_id"]) in str(i)]
            if idx:
                buses.loc[idx[0], "x"] = r["lon"]
                buses.loc[idx[0], "y"] = r["lat"]

    fig, ax = plt.subplots(figsize=(7, 7))
    nuclear_buses = {"DE0 3", "DE0 8", "DE0 4"}
    for _, line in n.lines.iterrows():
        b0, b1 = line.bus0, line.bus1
        if b0 in buses.index and b1 in buses.index:
            x0, y0 = buses.loc[b0, "x"], buses.loc[b0, "y"]
            x1, y1 = buses.loc[b1, "x"], buses.loc[b1, "y"]
            lw = 0.5 + 3 * line.s_nom / n.lines.s_nom.max()
            ax.plot([x0, x1], [y0, y1], "k-", alpha=0.4, lw=lw)

    for bus in buses.index:
        is_nuc = any(nb in bus for nb in nuclear_buses)
        ax.scatter(
            buses.loc[bus, "x"],
            buses.loc[bus, "y"],
            s=120 if is_nuc else 60,
            c="#ff8c00" if is_nuc else "#235ebc",
            edgecolors="k",
            zorder=3,
        )
        ax.annotate(bus.replace(" ", "\n"), (buses.loc[bus, "x"], buses.loc[bus, "y"]), fontsize=7, ha="center")

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Spatial model structure: Germany 10-cluster network")
    ax.set_aspect("equal")
    plt.tight_layout()
    save_figure(fig, "FIGURE_I3", ctx.output_dir)
    _register_fig(ctx, "FIGURE_I3", "Spatial model structure", "Inputs", "severe", "10 clusters, transmission corridors, nuclear sites DE0 3/8/4")


def figure_i4_workflow(ctx: PackageContext) -> None:
    steps = [
        "Raw data",
        "PyPSA-Eur\nprepared network",
        "Matched Base\nprofiles",
        "Stylised Dunkelflaute\nprofiles",
        "Fixed-capacity\nPyPSA dispatch",
        "Nuclear\nscenarios",
        "Decarbonised\nadequacy",
        "GAMSPy RF\nvalidation",
        "KPIs & report",
    ]
    fig, ax = plt.subplots(figsize=(12, 2.5))
    ax.set_xlim(0, len(steps))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, s in enumerate(steps):
        ax.add_patch(plt.Rectangle((i + 0.05, 0.25), 0.9, 0.5, fc="#e8f4fc", ec="#235ebc"))
        ax.text(i + 0.5, 0.5, s, ha="center", va="center", fontsize=8)
        if i < len(steps) - 1:
            ax.annotate("", xy=(i + 1.05, 0.5), xytext=(i + 0.95, 0.5), arrowprops=dict(arrowstyle="->", lw=1.2))
    ax.set_title("Technology and model-input architecture")
    plt.tight_layout()
    save_figure(fig, "FIGURE_I4", ctx.output_dir)
    _register_fig(ctx, "FIGURE_I4", "Technology and model-input architecture", "Methods", "V4 pipeline", "End-to-end workflow from raw data to validation KPIs")


def build_input_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_i1_demand(ctx)
    figure_i2_capacity(ctx)
    figure_i3_network_map(ctx)
    figure_i4_workflow(ctx)
