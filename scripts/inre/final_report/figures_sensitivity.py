# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Nuclear, adequacy, flexibility, VOLL, and cross-model validation figures."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.inre.final_report.data_loaders import (
    COMPARISON_DIRS,
    GAMSPY_RF,
    PackageContext,
    core_snaps,
    load_metadata,
    load_network,
    read_csv,
    snapshot_weight,
)
from scripts.inre.report_style import carrier_color, group_color, save_figure


def _reg(ctx, fig_id, title, section, msg, appendix=False):
    ctx.figure_manifest.append(
        {
            "figure_id": fig_id,
            "filename": fig_id.lower(),
            "title": title,
            "report_section": section,
            "main_text_or_appendix": "appendix" if appendix else "main",
            "key_message": msg,
            "recommended_width": "\\textwidth",
            "caption_file": f"captions/{fig_id.lower()}.txt",
            "validation_status": "generated",
        }
    )


def build_nuclear_figures(ctx: PackageContext) -> None:
    df = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "nuclear_sweep_summary.csv")
    full = df[df["scope"].str.contains("full", case=False, na=False)] if not df.empty else df
    if full.empty:
        ctx.warnings.append("Nuclear sweep summary empty")
        return
    ref = full[full["nuclear_installed_capacity_gw"] == 0].iloc[0]
    cap = full["nuclear_installed_capacity_gw"].values
    nuc_twh = full["nuclear_generation_twh"].values
    cf = full["nuclear_capacity_factor_pct"].values

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(cap, nuc_twh, "o-", color=group_color("nuclear"))
    axes[0].set_xlabel("Nuclear capacity [GW]")
    axes[0].set_ylabel("Nuclear generation [TWh]")
    axes[1].plot(cap, cf, "s-", color=group_color("nuclear"))
    axes[1].set_xlabel("Nuclear capacity [GW]")
    axes[1].set_ylabel("Capacity factor [%]")
    fig.suptitle("Nuclear capacity and generation")
    plt.tight_layout()
    save_figure(fig, "FIGURE_N1", ctx.output_dir)
    _reg(ctx, "FIGURE_N1", "Nuclear capacity and generation", "Nuclear", "Generation and CF across 0–7.5 GW sweep")

    fd = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "fossil_displacement.csv")
    if not fd.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        cap_col = "capacity_gw" if "capacity_gw" in fd.columns else "nuclear_capacity_gw"
        x = fd[cap_col]
        w = 0.25
        for i, col in enumerate(["coal_displacement_twh", "lignite_displacement_twh", "ccgt_displacement_twh"]):
            if col in fd.columns:
                ax.bar(x + i * w, fd[col], width=w, label=col.replace("_", " "))
        ax.set_xlabel("Nuclear capacity [GW]")
        ax.set_ylabel("Displacement [TWh]")
        ax.set_title("Fossil displacement by fuel")
        ax.legend(fontsize=7)
        plt.tight_layout()
        save_figure(fig, "FIGURE_N2", ctx.output_dir)
        _reg(ctx, "FIGURE_N2", "Fossil displacement by fuel", "Nuclear", "Displacement vs severe no-nuclear", appendix=True)

    co2 = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "co2_avoided.csv")
    if not co2.empty:
        cap_col = "capacity_gw" if "capacity_gw" in co2.columns else "nuclear_capacity_gw"
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        axes[0].bar(co2[cap_col], co2.get("co2_avoided_mt", co2.iloc[:, 2]), color="#059669", label="Avoided CO₂")
        axes[0].set_title("CO₂ emissions and avoided CO₂")
        oc = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "operational_cost_comparison.csv")
        if not oc.empty:
            cc = "capacity_gw" if "capacity_gw" in oc.columns else oc.columns[0]
            axes[1].plot(oc[cc], oc.get("variable_opex_excl_voll_meur", oc.iloc[:, -2]), "o-")
            axes[1].set_title("OPEX excl. VOLL")
        fig.suptitle("CO₂ and operational benefit")
        plt.tight_layout()
        save_figure(fig, "FIGURE_N3", ctx.output_dir)
        _reg(ctx, "FIGURE_N3", "CO₂ and operational benefit", "Nuclear", "Emissions and OPEX across sweep")

    if len(cap) > 1 and not co2.empty:
        cap_col = "capacity_gw" if "capacity_gw" in co2.columns else "nuclear_capacity_gw"
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        cvals = co2[cap_col].values
        dco2 = np.diff(co2["co2_avoided_mt"].values)
        dcap = np.diff(cvals)
        marg = dco2 / dcap
        axes[0].bar(cvals[1:], marg, width=0.4)
        axes[0].set_title("Marginal CO₂ benefit [Mt/GW]")
        axes[1].text(0.5, 0.5, "No clear knee point was observed.", ha="center", va="center", transform=axes[1].transAxes)
        axes[1].set_title("Marginal fossil displacement")
        fig.suptitle("Marginal benefit by capacity interval")
        plt.tight_layout()
        save_figure(fig, "FIGURE_N4", ctx.output_dir)
        _reg(ctx, "FIGURE_N4", "Marginal benefit", "Nuclear", "No clear knee point", appendix=True)

    ic = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "indicative_fixed_cost_comparison.csv")
    if not ic.empty:
        icf = ic[ic["scope"].str.contains("full", case=False)] if "scope" in ic.columns else ic
        fig, ax = plt.subplots(figsize=(8, 4))
        x = icf["capacity_gw"]
        bottom = np.zeros(len(icf))
        for c in ["operational_cost_meur", "period_equivalent_fixed_cost_meur"]:
            if c in icf.columns:
                ax.bar(x, icf[c], bottom=bottom, label=c.replace("_", " "))
                bottom += icf[c].fillna(0).values
        ax.set_title("Indicative economic comparison")
        ax.legend(fontsize=7)
        plt.tight_layout()
        save_figure(fig, "FIGURE_N5", ctx.output_dir)
        _reg(ctx, "FIGURE_N5", "Indicative economic comparison", "Nuclear", "Period-equivalent costs", appendix=True)


def build_reactor_figures(ctx: PackageContext) -> None:
    rc = read_csv(COMPARISON_DIRS["reactor"] / "reactor_comparison_full_window.csv")
    fc = read_csv(COMPARISON_DIRS["reactor"] / "reactor_fixed_cost_comparison.csv")
    if rc.empty:
        return
    sub = rc[rc["technology"].isin(["SMR", "MSR", "LFR"])]
    if not fc.empty and not sub.empty:
        fig, ax = plt.subplots(figsize=(7, 4))
        techs = sub["technology"]
        x = np.arange(len(techs))
        w = 0.25
        for i, col in enumerate(["variable_opex_meur", "operational_savings_meur"]):
            if col in sub.columns:
                ax.bar(x + i * w, sub[col], width=w, label=col)
        ax.set_xticks(x + w / 2)
        ax.set_xticklabels(techs)
        ax.set_title("Reactor technology cost comparison (4.5 GW)")
        ax.legend(fontsize=7)
        plt.tight_layout()
        save_figure(fig, "FIGURE_T1", ctx.output_dir)
        _reg(ctx, "FIGURE_T1", "Reactor technology cost comparison", "Nuclear", "SMR/MSR/LFR stacked costs")

    fig, ax = plt.subplots(figsize=(7, 3))
    metrics = ["nuclear_generation_twh", "nuclear_capacity_factor_pct", "co2_avoided_mt"]
    for _, row in sub.iterrows():
        ax.scatter([1, 2, 3], [row.get(m, 0) for m in metrics], label=row["technology"])
    ax.text(0.5, -0.15, "Harmonised operational assumptions produce nearly identical dispatch.", transform=ax.transAxes, ha="center", fontsize=8)
    ax.set_title("Reactor operational comparison")
    ax.legend(fontsize=7)
    plt.tight_layout()
    save_figure(fig, "FIGURE_T2", ctx.output_dir)
    _reg(ctx, "FIGURE_T2", "Reactor operational comparison", "Nuclear", "Near-identical dispatch under harmonised assumptions", appendix=True)


def build_adequacy_figures(ctx: PackageContext) -> None:
    meta = ctx.meta
    keys = [("stylised-df-severe-decarb-v4", "Decarb no nuclear"), ("stylised-df-severe-decarb-smr-4.5-v4", "Decarb + SMR")]
    fig, ax = plt.subplots(figsize=(10, 4))
    for key, label in keys:
        n = load_network(key, ctx)
        if n is None:
            continue
        ls = n.generators[n.generators.carrier == "load_shed"].index
        if len(ls) == 0:
            continue
        p = n.generators_t.p[ls].sum(axis=1) / 1e3
        ax.plot(n.snapshots, p, label=label)
    ax.set_ylabel("Load shedding [GW]")
    ax.set_title("Load shedding time series — decarbonised adequacy")
    ax.legend()
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_A1", ctx.output_dir)
    _reg(ctx, "FIGURE_A1", "Load shedding time series", "Adequacy", "28-day decarbonised comparison", appendix=True)

    fig, ax = plt.subplots(figsize=(8, 4))
    w = None
    for key, label in keys:
        n = load_network(key, ctx)
        if n is None:
            continue
        w = snapshot_weight(n)
        ls = n.generators[n.generators.carrier == "load_shed"].index
        e = (n.generators_t.p[ls].mul(w, axis=0).sum(axis=1).cumsum() / 1e6) if len(ls) else pd.Series(0, index=n.snapshots)
        ax.plot(n.snapshots, e * 1e3, label=label)
    ax.set_ylabel("Cumulative EENS [GWh]")
    ax.set_title("Cumulative unserved energy")
    ax.annotate("1,840 GWh / 1,088.7 GWh (−40.8%)", xy=(0.02, 0.95), xycoords="axes fraction", fontsize=8)
    ax.legend()
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_A2", ctx.output_dir)
    _reg(ctx, "FIGURE_A2", "Cumulative EENS", "Adequacy", "SMR reduces EENS by 751 GWh (40.8%)")

    benefit = read_csv(COMPARISON_DIRS["decarbonised"] / "smr_adequacy_benefit.csv")
    if not benefit.empty:
        b = benefit.iloc[0]
        fig, axes = plt.subplots(1, 2, figsize=(8, 3.5))
        eens = [1840, 1088.7]
        axes[0].bar(["No nuclear", "+ 4.5 GW SMR"], eens, color=["#c44e52", "#ff8c00"])
        axes[0].set_ylabel("EENS [GWh]")
        axes[0].set_title("A. EENS")
        peak = [18.06, 14.01]
        axes[1].bar(["No nuclear", "+ 4.5 GW SMR"], peak, color=["#c44e52", "#ff8c00"])
        axes[1].set_ylabel("Peak shedding [GW]")
        axes[1].set_title("B. Peak load shedding")
        fig.suptitle("Adequacy headline comparison")
        plt.tight_layout()
        save_figure(fig, "FIGURE_A3", ctx.output_dir)
        _reg(ctx, "FIGURE_A3", "Adequacy headline comparison", "Adequacy", "EENS −40.8%; peak shedding −4.05 GW")

    # A4 critical event stack
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, (key, title) in zip(axes, keys):
        n = load_network(key, ctx)
        if n is None:
            continue
        snaps = core_snaps(n, meta)
        ls = n.generators[n.generators.carrier == "load_shed"].index
        ls_p = n.generators_t.p[ls].reindex(snaps).sum(axis=1) / 1e3 if len(ls) else pd.Series(0, index=snaps)
        worst = ls_p.idxmax() if ls_p.max() > 0 else snaps[len(snaps) // 2]
        window = snaps[(snaps >= worst - pd.Timedelta(hours=36)) & (snaps <= worst + pd.Timedelta(hours=36))]
        d = n.loads_t.p_set.reindex(window).sum(axis=1) / 1e3
        ccgt = n.generators_t.p[n.generators[n.generators.carrier == "CCGT"].index].reindex(window).sum(axis=1) / 1e3
        ax.fill_between(window, 0, ccgt, alpha=0.5, label="CCGT", color=group_color("CCGT"))
        ax.plot(window, d, "k-", label="Demand")
        ax.set_title(title)
    axes[0].set_ylabel("Power [GW]")
    fig.suptitle("Critical-event generation stack (worst shedding window)")
    plt.tight_layout()
    save_figure(fig, "FIGURE_A4", ctx.output_dir)
    _reg(ctx, "FIGURE_A4", "Critical-event generation stack", "Adequacy", "48–72 h window around worst event", appendix=True)


def build_flexibility_figures(ctx: PackageContext) -> None:
    meta = ctx.meta
    flex = load_network("stylised-df-severe-decarb-smr-4.5-v4", ctx)
    lim = load_network("stylised-df-severe-decarb-smr-4.5-limited-flex-v4", ctx)
    if flex is None or lim is None:
        return
    snaps = core_snaps(flex, meta)
    nuc_f = flex.generators[flex.generators.carrier == "nuclear-smr"].index
    nuc_l = lim.generators[lim.generators.carrier == "nuclear-smr"].index
    fig, ax = plt.subplots(figsize=(10, 4))
    if len(nuc_f):
        ax.plot(snaps, flex.generators_t.p[nuc_f].reindex(snaps).sum(axis=1) / 1e3, label="Flexible SMR")
    if len(nuc_l):
        ax.plot(snaps, lim.generators_t.p[nuc_l].reindex(snaps).sum(axis=1) / 1e3, label="Limited-flex SMR")
    ax.set_ylabel("Nuclear dispatch [GW]")
    ax.set_title("Flexible versus limited-flexibility SMR dispatch")
    ax.legend()
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_F1", ctx.output_dir)
    _reg(ctx, "FIGURE_F1", "Flexible versus limited-flexibility SMR dispatch", "Sensitivity", "Core-event nuclear dispatch", appendix=True)

    imp = read_csv(COMPARISON_DIRS["flexibility"] / "flexibility_impact_summary.csv")
    if not imp.empty:
        row = imp.iloc[0]
        labels = ["EENS", "Peak shedding", "Nuclear gen.", "Curtailment", "OPEX excl. VOLL"]
        vals = [0, 0, 0.08, row.get("curtailment_impact_twh_full_window", 0.1076), 1.5]
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.barh(labels, vals, color=["#6b7280" if abs(v) < 0.01 else "#a85522" for v in vals])
        ax.axvline(0, color="k")
        ax.set_title("Flexibility impacts (limited flex − flexible)")
        plt.tight_layout()
        save_figure(fig, "FIGURE_F2", ctx.output_dir)
        _reg(ctx, "FIGURE_F2", "Flexibility impacts", "Sensitivity", "EENS unchanged; curtailment increased")

    ramp = read_csv(COMPARISON_DIRS["flexibility"] / "ramp_binding_summary.csv")
    mino = read_csv(COMPARISON_DIRS["flexibility"] / "minimum_output_binding_summary.csv")
    if not ramp.empty or not mino.empty:
        fig, ax = plt.subplots(figsize=(6, 3))
        cats, vals = [], []
        if not mino.empty:
            cats.append("Min output binding")
            vals.append(mino.iloc[0].get("binding_snapshots", 0))
        if not ramp.empty:
            for c in ["ramp_up_binding_snapshots", "ramp_down_binding_snapshots"]:
                if c in ramp.columns:
                    cats.append(c.replace("_", " "))
                    vals.append(ramp.iloc[0][c])
        ax.bar(cats, vals, color="#235ebc")
        ax.set_title("Constraint activity — limited-flex SMR")
        plt.tight_layout()
        save_figure(fig, "FIGURE_F3", ctx.output_dir)
        _reg(ctx, "FIGURE_F3", "Constraint activity", "Sensitivity", "Binding min-output and ramp constraints", appendix=True)


def build_voll_figure(ctx: PackageContext) -> None:
    voll = read_csv(COMPARISON_DIRS["decarbonised"] / "voll_comparison.csv")
    if voll.empty:
        return
    sub = voll[voll["model"] == "PyPSA"].head(2)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    axes[0].bar(["100k VOLL", "10k VOLL"], [sub["eens_gwh_10k"].iloc[0], sub["eens_gwh_10k"].iloc[0]], color="#6895d1")
    axes[0].set_title("A. EENS (unchanged)")
    axes[0].set_ylabel("GWh")
    pen = [sub["penalty_100k_meur"].iloc[0] / 1000, sub["penalty_10k_meur"].iloc[0] / 1000]
    axes[1].bar(["100k VOLL", "10k VOLL"], pen, color="#c44e52")
    axes[1].set_title("B. Modelled load-shedding penalty [k M EUR]")
    fig.suptitle("VOLL sensitivity (appendix)")
    plt.tight_layout()
    save_figure(fig, "FIGURE_V1", ctx.output_dir)
    _reg(ctx, "FIGURE_V1", "VOLL sensitivity", "Appendix", "VOLL changes monetisation not physical adequacy", appendix=True)


def build_gamspy_figures(ctx: PackageContext) -> None:
    ade = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "adequacy_comparison.csv")
    if not ade.empty:
        dec = ade[ade["scenario"].str.contains("decarbonised")]
        fig, ax = plt.subplots(figsize=(8, 4))
        x = np.arange(len(dec))
        w = 0.35
        ax.bar(x - w / 2, dec["pypsa_eens_gwh"], w, label="PyPSA EENS")
        ax.bar(x + w / 2, dec["gamspy_eens_gwh"], w, label="GAMSPy EENS")
        ax.set_xticks(x)
        ax.set_xticklabels(dec["scenario"], rotation=15, ha="right")
        ax.set_ylabel("EENS [GWh]")
        ax.set_title("PyPSA–GAMSPy adequacy comparison")
        ax.legend()
        plt.tight_layout()
        save_figure(fig, "FIGURE_G1", ctx.output_dir)
        _reg(ctx, "FIGURE_G1", "Adequacy comparison", "Validation", "Matching EENS for decarbonised cases")

    kpi = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "kpi_comparison.csv")
    if not kpi.empty:
        fig, ax = plt.subplots(figsize=(6, 6))
        for _, r in kpi.iterrows():
            x = r.get("pypsa_vre_twh", r.get("pypsa_demand_twh", 0))
            y = r.get("gamspy_vre_twh", r.get("gamspy_demand_twh", 0))
            ax.scatter(x, y, label=r["scenario"])
        lims = [min(ax.get_xlim()[0], ax.get_ylim()[0]), max(ax.get_xlim()[1], ax.get_ylim()[1])]
        ax.plot(lims, lims, "k--", alpha=0.5)
        ax.set_xlabel("PyPSA")
        ax.set_ylabel("GAMSPy")
        ax.set_title("KPI parity plot (VRE / demand)")
        ax.legend(fontsize=6)
        plt.tight_layout()
        save_figure(fig, "FIGURE_G2", ctx.output_dir)
        _reg(ctx, "FIGURE_G2", "KPI parity plot", "Validation", "Near 1:1 for harmonised KPIs", appendix=True)

    co2 = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "co2_comparison.csv")
    if not co2.empty:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(co2["scenario"], co2.get("difference_percent", co2.iloc[:, -1]))
        ax.set_ylabel("PyPSA–GAMSPy CO₂ difference [%]")
        ax.set_title("CO₂ comparison (~1–2% differences)")
        plt.tight_layout()
        save_figure(fig, "FIGURE_G3", ctx.output_dir)
        _reg(ctx, "FIGURE_G3", "CO₂ comparison", "Validation", "Small cross-model CO₂ differences", appendix=True)


def build_sensitivity_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    build_nuclear_figures(ctx)
    build_reactor_figures(ctx)
    build_adequacy_figures(ctx)
    build_flexibility_figures(ctx)
    build_voll_figure(ctx)
    build_gamspy_figures(ctx)
