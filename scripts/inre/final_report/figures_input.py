# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Input and model-structure figures (I1–I4)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import pypsa

from scripts.inre.final_report.data_loaders import (
    PackageContext,
    core_snaps,
    load_metadata,
    load_network,
    national_demand_gw,
    snapshot_weight,
)
from scripts.inre.final_report.figure_utils import save_figure_with_data
from scripts.inre.report_style import (
    CARRIER_MAP,
    LINE_WIDTH,
    add_phase_shading,
    group_color,
)

SCRIPT = "scripts/inre/final_report/figures_input.py"
I2_CARRIER_ORDER = [
    "onshore wind",
    "offshore wind",
    "solar",
    "biomass",
    "waste",
    "geothermal",
    "coal",
    "lignite",
    "CCGT",
    "OCGT / oil / peaker",
]


def _capacity_by_group(n: pypsa.Network) -> pd.Series:
    groups: dict[str, float] = {}
    for _, g in n.generators.iterrows():
        if g.carrier == "load_shed":
            continue
        grp = CARRIER_MAP.get(g.carrier, g.carrier)
        groups[grp] = groups.get(grp, 0) + g.p_nom
    return pd.Series({k: groups.get(k, 0) / 1e3 for k in I2_CARRIER_ORDER})


def figure_i1_demand(ctx: PackageContext) -> None:
    meta = ctx.meta
    n = load_network("stylised-df-severe-v4", ctx)
    if n is None:
        return
    snaps = pd.DatetimeIndex(n.snapshots)
    demand = national_demand_gw(n, snaps)
    w = snapshot_weight(n, snaps)
    energy_twh = float((demand * 1e3 * w).sum()) / 1e6
    core = core_snaps(n, meta)
    core_energy_twh = float((demand.reindex(core) * 1e3 * w.reindex(core)).sum()) / 1e6

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(snaps, demand.values, color=group_color("demand"), lw=LINE_WIDTH)
    ax.set_ylabel("National demand [GW]")
    ax.set_xlabel("Date")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    y_pad = demand.max() * 0.08
    ax.set_ylim(demand.min() - y_pad, demand.max() + y_pad * 3)
    add_phase_shading(ax, meta, snaps, label=True)
    ax.set_title("German demand and Dunkelflaute event window")

    plot_data = pd.DataFrame({"timestamp": snaps, "demand_GW": demand.values})
    save_figure_with_data(
        fig,
        "FIGURE_I1",
        ctx,
        plot_data,
        script=SCRIPT,
        source_folder="results/inre-de-stylised-df-severe-v4/",
        source_file="networks/base_s_10_elec_.nc",
        temporal_scope="28-day modelling window",
        scenarios="stylised-df-severe-v4",
        plotted_variables="national demand [GW]",
        key_values_checked=f"full_window={energy_twh:.2f} TWh (target 42.74); core={core_energy_twh:.2f} TWh (target 21.15)",
    )


def figure_i2_capacity(ctx: PackageContext) -> None:
    panels = [
        ("Existing fossil-rich fleet", "stylised-df-severe-v4"),
        ("Coal- and lignite-free sensitivity", "stylised-df-severe-decarb-v4"),
    ]
    fig, ax = plt.subplots(figsize=(9, 5))
    bar_w = 0.35
    x = range(len(I2_CARRIER_ORDER))
    rows = []
    for i, (label, key) in enumerate(panels):
        n = load_network(key, ctx)
        if n is None:
            continue
        cap = _capacity_by_group(n)
        offset = (i - 0.5) * bar_w
        colors = [group_color(c) for c in I2_CARRIER_ORDER]
        ax.bar([xi + offset for xi in x], cap.values, width=bar_w, label=label, color=colors, edgecolor="white", linewidth=0.3)
        for carrier, gw in cap.items():
            rows.append({"scenario": label, "carrier_group": carrier, "installed_capacity_GW": gw})

    ax.set_xticks(list(x))
    ax.set_xticklabels(I2_CARRIER_ORDER, rotation=35, ha="right")
    ax.set_ylabel("Installed capacity [GW]")
    ax.legend(loc="upper right")
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_I2",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-de-stylised-df-severe-v4/; results/inre-de-stylised-df-severe-decarb-v4/",
        source_file="networks/base_s_10_elec_.nc",
        temporal_scope="static installed capacity",
        scenarios="fossil-rich; coal/lignite-free",
        plotted_variables="installed capacity by carrier group [GW]",
        key_values_checked="VRE≈133.3 GW; coal≈20.35; lignite≈19.46; CCGT≈30.78; OCGT/oil≈11.80; biomass/waste/geo≈11.18",
    )


def figure_i4_workflow(ctx: PackageContext) -> None:
    steps = [
        ("Prepared\nPyPSA-Eur network", "input"),
        ("Matched reference\nprofile", "input"),
        ("Stylised severe\nDunkelflaute", "scenario"),
        ("Fixed nuclear\nscenarios", "scenario"),
        ("Fossil-rich\ndispatch runs", "optim"),
        ("Coal/lignite-free\nadequacy", "optim"),
        ("Limited-flexibility\nsensitivity", "optim"),
        ("VOLL\nrobustness", "optim"),
        ("GAMSPy RF\nvalidation", "validation"),
        ("Post-processing\n& report outputs", "report"),
    ]
    colors = {
        "input": "#dbeafe",
        "scenario": "#fef3c7",
        "optim": "#ede9fe",
        "validation": "#d1fae5",
        "report": "#fce7f3",
    }
    fig, ax = plt.subplots(figsize=(12, 3.2))
    ax.set_xlim(0, len(steps))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, (label, kind) in enumerate(steps):
        ax.add_patch(plt.Rectangle((i + 0.05, 0.22), 0.9, 0.56, fc=colors[kind], ec="#374151", lw=0.8))
        ax.text(i + 0.5, 0.5, label, ha="center", va="center", fontsize=9)
        if i < len(steps) - 1:
            ax.annotate("", xy=(i + 1.05, 0.5), xytext=(i + 0.95, 0.5), arrowprops=dict(arrowstyle="->", lw=1.4))
    rows = [{"step": i + 1, "label": s[0].replace("\n", " "), "category": s[1]} for i, s in enumerate(steps)]
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_I4",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="V4 pipeline",
        source_file="scripts/inre/*.py",
        temporal_scope="n/a (workflow diagram)",
        scenarios="all V4 scenarios",
        plotted_variables="modelling workflow steps",
        key_values_checked="10 workflow boxes; V4 terminology only",
    )


def build_input_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_i1_demand(ctx)
    figure_i2_capacity(ctx)
    figure_i4_workflow(ctx)
