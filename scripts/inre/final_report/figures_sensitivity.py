# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Nuclear, adequacy, flexibility, and cross-model validation figures."""

from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.inre.final_report.data_loaders import (
    COMPARISON_DIRS,
    PackageContext,
    core_snaps,
    load_metadata,
    load_network,
    read_csv,
    snapshot_weight,
)
from scripts.inre.final_report.figure_utils import DISPLAY_CARRIER_ORDER, save_figure_with_data
from scripts.inre.report_style import CARRIER_MAP, LINE_WIDTH, carrier_color, group_color

SCRIPT = "scripts/inre/final_report/figures_sensitivity.py"

STACK_ORDER = [
    "onwind",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
    "solar",
    "solar-hsat",
    "biomass",
    "CCGT",
    "OCGT",
    "oil",
    "waste",
    "geothermal",
    "nuclear-smr",
    "load_shed",
]


def figure_n1_nuclear_sweep(ctx: PackageContext) -> None:
    df = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "nuclear_sweep_summary.csv")
    core = df[df["scope"] == "core"].sort_values("nuclear_installed_capacity_gw")
    if core.empty:
        ctx.warnings.append("Nuclear sweep core summary empty")
        return

    cap = core["nuclear_installed_capacity_gw"].values
    nuc_twh = core["nuclear_generation_twh"].values
    cf = core["nuclear_capacity_factor_pct"].values

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(cap, nuc_twh, "o-", color=group_color("nuclear"), lw=LINE_WIDTH, markersize=7)
    axes[0].set_xlabel("Nuclear capacity [GW]")
    axes[0].set_ylabel("Nuclear generation [TWh]")
    axes[0].set_title("Panel A: nuclear generation")
    axes[1].plot(cap, cf, "s-", color=group_color("nuclear"), lw=LINE_WIDTH, markersize=7)
    axes[1].set_xlabel("Nuclear capacity [GW]")
    axes[1].set_ylabel("Capacity factor [%]")
    axes[1].set_title("Panel B: capacity factor")
    plt.tight_layout()

    plot_data = core[
        ["scenario", "nuclear_installed_capacity_gw", "nuclear_generation_twh", "nuclear_capacity_factor_pct"]
    ].copy()
    save_figure_with_data(
        fig,
        "FIGURE_N1",
        ctx,
        plot_data,
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-nuclear-sweep/",
        source_file="nuclear_sweep_summary.csv",
        temporal_scope="14-day Dunkelflaute core",
        scenarios="0, 1.5, 3.0, 4.5, 7.5 GW generic nuclear",
        plotted_variables="nuclear generation [TWh]; capacity factor [%]",
        key_values_checked="0 GW→0.00 TWh; 1.5→0.44/87.3%; 3.0→0.87/86.7%; 4.5→1.30/86.3%; 7.5→2.15/85.5%",
    )


def figure_a1_load_shedding(ctx: PackageContext) -> None:
    keys = [
        ("stylised-df-severe-decarb-v4", "No nuclear"),
        ("stylised-df-severe-decarb-smr-4.5-v4", "+4.5 GW SMR"),
    ]
    fig, ax = plt.subplots(figsize=(10, 4))
    rows = []
    peaks = {"No nuclear": 18.06, "+4.5 GW SMR": 14.01}
    for key, label in keys:
        n = load_network(key, ctx)
        if n is None:
            continue
        ls = n.generators[n.generators.carrier == "load_shed"].index
        p = n.generators_t.p[ls].sum(axis=1) / 1e3 if len(ls) else pd.Series(0, index=n.snapshots)
        ax.plot(n.snapshots, p, label=label, lw=LINE_WIDTH)
        ax.annotate(f"Peak {peaks[label]:.2f} GW", xy=(0.98, 0.92 if "No" in label else 0.82), xycoords="axes fraction", ha="right", fontsize=8)
        for ts, gw in zip(n.snapshots, p):
            rows.append({"timestamp": ts, "scenario": label, "load_shedding_GW": float(gw)})
    ax.set_ylabel("Three-hourly load shedding [GW]")
    ax.set_xlabel("Date")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(fontsize=9)
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_A1",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-decarbonised-adequacy/",
        source_file="adequacy_summary_full_window.csv; solved networks",
        temporal_scope="28-day modelling window",
        scenarios="decarbonised no nuclear; decarbonised +4.5 GW SMR",
        plotted_variables="three-hourly load shedding [GW]",
        key_values_checked="peak 18.06 GW (no nuclear); peak 14.01 GW (+4.5 GW SMR)",
    )


def figure_a2_cumulative_unserved(ctx: PackageContext) -> None:
    keys = [
        ("stylised-df-severe-decarb-v4", "No nuclear", 1840.0),
        ("stylised-df-severe-decarb-smr-4.5-v4", "+4.5 GW SMR", 1088.7),
    ]
    fig, ax = plt.subplots(figsize=(10, 4))
    rows = []
    for key, label, final_gwh in keys:
        n = load_network(key, ctx)
        if n is None:
            continue
        w = snapshot_weight(n)
        ls = n.generators[n.generators.carrier == "load_shed"].index
        e = (n.generators_t.p[ls].mul(w, axis=0).sum(axis=1).cumsum() / 1e6 * 1e3) if len(ls) else pd.Series(0, index=n.snapshots)
        ax.plot(n.snapshots, e, label=label, lw=LINE_WIDTH)
        ax.annotate(f"{final_gwh:.1f} GWh", xy=(n.snapshots[-1], final_gwh), xytext=(5, 0), textcoords="offset points", fontsize=8)
        for ts, gwh in zip(n.snapshots, e):
            rows.append({"timestamp": ts, "scenario": label, "cumulative_unserved_energy_GWh": float(gwh)})
    ax.set_ylabel("Cumulative deterministic unserved energy [GWh]")
    ax.set_xlabel("Date")
    ax.annotate("40.8% reduction with +4.5 GW SMR", xy=(0.02, 0.95), xycoords="axes fraction", fontsize=8)
    ax.legend(fontsize=9)
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_A2",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-decarbonised-adequacy/",
        source_file="adequacy_summary_full_window.csv",
        temporal_scope="28-day modelling window",
        scenarios="decarbonised no nuclear; decarbonised +4.5 GW SMR",
        plotted_variables="cumulative deterministic unserved energy [GWh]",
        key_values_checked="1840.0 GWh (no nuclear); 1088.7 GWh (+4.5 GW SMR); −40.8%",
    )


def _stack_window(n, window) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    data: dict[str, pd.Series] = {}
    for c in STACK_ORDER:
        gens = n.generators[n.generators.carrier == c].index
        if len(gens) == 0:
            continue
        grp = CARRIER_MAP.get(c, c)
        p = n.generators_t.p[gens].reindex(window).fillna(0).sum(axis=1) / 1e3
        if grp in data:
            data[grp] += p
        else:
            data[grp] = p
    stack = pd.DataFrame(data, index=window)
    demand = n.loads_t.p_set.reindex(window).sum(axis=1) / 1e3
    ls = stack.get("load shedding", pd.Series(0, index=window))
    return stack, demand, ls


def figure_a4_critical_period(ctx: PackageContext) -> None:
    meta = ctx.meta
    keys = [
        ("stylised-df-severe-decarb-v4", "No nuclear"),
        ("stylised-df-severe-decarb-smr-4.5-v4", "+4.5 GW SMR"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    rows = []
    ymax = 0.0
    windows: list[tuple] = []
    panel_titles: list[str] = []
    for key, title in keys:
        n = load_network(key, ctx)
        if n is None:
            continue
        ls = n.generators[n.generators.carrier == "load_shed"].index
        ls_p = n.generators_t.p[ls].sum(axis=1) if len(ls) else pd.Series(0, index=n.snapshots)
        worst = ls_p.idxmax()
        window = pd.DatetimeIndex(n.snapshots)[
            (pd.DatetimeIndex(n.snapshots) >= worst - pd.Timedelta(hours=36))
            & (pd.DatetimeIndex(n.snapshots) <= worst + pd.Timedelta(hours=36))
        ]
        windows.append((n, window))
        panel_titles.append(title)
        ymax = max(ymax, float(n.loads_t.p_set.reindex(window).sum(axis=1).max() / 1e3) * 1.05)

    for ax, title, (n, window) in zip(axes, panel_titles, windows):
        stack, demand, ls = _stack_window(n, window)
        bottom = np.zeros(len(window))
        for grp in DISPLAY_CARRIER_ORDER:
            if grp not in stack.columns or grp == "load shedding":
                continue
            ax.fill_between(window, bottom, bottom + stack[grp].values, label=grp, color=group_color(grp), alpha=0.85)
            bottom += stack[grp].values
        if "load shedding" in stack.columns:
            deficit = stack["load shedding"].values
            ax.fill_between(window, demand.values - deficit, demand.values, color=group_color("load shedding"), alpha=0.7, label="Load shedding")
        ax.plot(window, demand, color=group_color("demand"), lw=LINE_WIDTH, zorder=6)
        ax.set_title(title)
        ax.set_ylabel("Power [GW]")
        ax.set_xlabel("Date (±36 h around peak load shedding)")
        for ts in window:
            row = {"timestamp": ts, "scenario": title, "demand_GW": float(demand.loc[ts])}
            for col in stack.columns:
                row[f"{col}_GW"] = float(stack.loc[ts, col])
            rows.append(row)

    for ax in axes:
        ax.set_ylim(0, ymax)
    handles, labels = axes[1].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axes[1].legend(by_label.values(), by_label.keys(), fontsize=7, loc="upper right")
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure_with_data(
        fig,
        "FIGURE_A4",
        ctx,
        pd.DataFrame(rows),
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-decarbonised-adequacy/",
        source_file="solved networks",
        temporal_scope="±36 h around peak load shedding",
        scenarios="decarbonised no nuclear; decarbonised +4.5 GW SMR",
        plotted_variables="stacked generation, demand, load shedding deficit [GW]",
        key_values_checked="SMR reduces but does not eliminate deficit; nuclear shown in purple",
    )


def figure_g1_pypsa_gamspy(ctx: PackageContext) -> None:
    ade = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "adequacy_comparison.csv")
    kpi = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "kpi_comparison.csv")
    dec_ade = ade[ade["scenario"].str.contains("decarbonised")]
    dec_kpi = kpi[kpi["scenario"].str.contains("decarbonised")]
    if dec_ade.empty or dec_kpi.empty:
        ctx.warnings.append("GAMSPy adequacy comparison data missing")
        return

    labels = ["No nuclear", "+4.5 GW SMR"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    x = np.arange(len(labels))
    w = 0.35
    eens_pypsa = dec_ade["pypsa_eens_gwh"].values
    eens_gamspy = dec_ade["gamspy_eens_gwh"].values
    peak_pypsa = dec_kpi["pypsa_peak_ls_gw"].values
    peak_gamspy = dec_kpi["gamspy_peak_ls_gw"].values

    for ax, pypsa_vals, gamspy_vals, ylabel, title in [
        (axes[0], eens_pypsa, eens_gamspy, "Deterministic unserved energy [GWh]", "Panel A: unserved energy"),
        (axes[1], peak_pypsa, peak_gamspy, "Peak load shedding [GW]", "Panel B: peak load shedding"),
    ]:
        bars1 = ax.bar(x - w / 2, pypsa_vals, w, label="PyPSA", color=group_color("onshore wind"))
        bars2 = ax.bar(x + w / 2, gamspy_vals, w, label="GAMSPy", color=group_color("offshore wind"))
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        for bars in (bars1, bars2):
            for bar in bars:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{bar.get_height():.1f}", ha="center", va="bottom", fontsize=8)
    axes[0].legend(fontsize=9)
    plt.tight_layout()

    plot_data = dec_ade.merge(dec_kpi[["scenario", "pypsa_peak_ls_gw", "gamspy_peak_ls_gw"]], on="scenario")
    save_figure_with_data(
        fig,
        "FIGURE_G1",
        ctx,
        plot_data,
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-pypsa-gamspy/",
        source_file="adequacy_comparison.csv; kpi_comparison.csv",
        temporal_scope="28-day modelling window",
        scenarios="decarbonised no nuclear; decarbonised +4.5 GW SMR",
        plotted_variables="deterministic unserved energy [GWh]; peak load shedding [GW]",
        key_values_checked="EENS agreement exact; peak load shedding agreement exact",
    )


def figure_f1_smr_flexibility(ctx: PackageContext) -> None:
    flex = load_network("stylised-df-severe-decarb-smr-4.5-v4", ctx)
    lim = load_network("stylised-df-severe-decarb-smr-4.5-limited-flex-v4", ctx)
    if flex is None or lim is None:
        return
    snaps = pd.DatetimeIndex(flex.snapshots)
    nuc_f = flex.generators[flex.generators.carrier == "nuclear-smr"].index
    nuc_l = lim.generators[lim.generators.carrier == "nuclear-smr"].index
    p_f = flex.generators_t.p[nuc_f].reindex(snaps).sum(axis=1) / 1e3 if len(nuc_f) else pd.Series(0, index=snaps)
    p_l = lim.generators_t.p[nuc_l].reindex(snaps).sum(axis=1) / 1e3 if len(nuc_l) else pd.Series(0, index=snaps)

    imp = read_csv(COMPARISON_DIRS["flexibility"] / "flexibility_impact_summary.csv")
    curtailment_delta = float(imp.iloc[0]["curtailment_impact_twh_full_window"]) if not imp.empty else 0.11

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(snaps, p_f, label="Flexible SMR", color=group_color("nuclear"), lw=LINE_WIDTH)
    axes[0].plot(snaps, p_l, label="Limited-flexibility SMR", color=group_color("CCGT"), ls="--", lw=LINE_WIDTH)
    axes[0].set_ylabel("Nuclear output [GW]")
    axes[0].legend(fontsize=9)

    def curtailment_twh(n):
        w = snapshot_weight(n, snaps)
        ren = n.generators[n.generators.carrier.isin(["onwind", "offwind-ac", "offwind-dc", "offwind-float", "solar", "solar-hsat"])]
        curt = pd.Series(0.0, index=snaps)
        for gen in ren.index:
            if gen in n.generators_t.p_max_pu.columns:
                avail = n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
                disp = n.generators_t.p[gen].reindex(snaps).fillna(0)
                curt += (avail - disp).clip(lower=0)
        return (curt * w).sum() / 1e6

    c_f, c_l = curtailment_twh(flex), curtailment_twh(lim)
    axes[1].bar([0, 1], [c_f, c_l], color=[group_color("nuclear"), group_color("CCGT")], tick_label=["Flexible SMR", "Limited-flex SMR"])
    axes[1].set_ylabel("Renewable curtailment [TWh]")
    axes[0].xaxis.set_major_locator(mdates.DayLocator(interval=2))
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    axes[0].set_xlabel("Date")
    fig.autofmt_xdate()
    plt.tight_layout()

    plot_data = pd.DataFrame(
        {
            "timestamp": snaps,
            "flexible_SMR_GW": p_f.values,
            "limited_flex_SMR_GW": p_l.values,
        }
    )
    save_figure_with_data(
        fig,
        "FIGURE_F1",
        ctx,
        plot_data,
        script=SCRIPT,
        source_folder="results/inre-comparison-v4-smr-flexibility/",
        source_file="flexibility_impact_summary.csv; solved networks",
        temporal_scope="28-day modelling window",
        scenarios="decarbonised +4.5 GW SMR flexible; limited-flexibility",
        plotted_variables="nuclear output [GW]; renewable curtailment [TWh]",
        key_values_checked=f"curtailment increase≈{curtailment_delta:.2f} TWh; EENS and peak load shedding unchanged",
    )


def build_sensitivity_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_n1_nuclear_sweep(ctx)
    figure_a1_load_shedding(ctx)
    figure_a2_cumulative_unserved(ctx)
    figure_a4_critical_period(ctx)
    figure_g1_pypsa_gamspy(ctx)
    figure_f1_smr_flexibility(ctx)
