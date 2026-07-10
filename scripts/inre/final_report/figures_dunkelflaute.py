# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Dunkelflaute methodology figures (D1–D4) and appendix diagnostics."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS
from scripts.inre.final_report.data_loaders import (
    PROFILE_OUTPUT,
    REPO_ROOT,
    PackageContext,
    load_metadata,
    load_network,
    national_demand_gw,
    snapshot_weight,
)
from scripts.inre.report_style import add_core_shading, add_phase_shading, group_color, save_figure


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


def _load_factor_csv(severity: str, carrier: str) -> pd.Series:
    p = REPO_ROOT / f"gamspy-de/profiles/stylised_dunkelflaute_v4/{severity}_{carrier}_factors.csv"
    if not p.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(p, parse_dates=["timestamp"])
    return df.set_index("timestamp")["factor"]


def figure_d1_stress_envelope(ctx: PackageContext) -> None:
    meta = ctx.meta
    snaps = pd.date_range(meta["simulation_start"], meta["simulation_end"], freq="3h")
    sev = meta["severity_assumptions"]["severe"]
    # Reconstruct s(t) from severe factors: m = 1 - s*(1-r) => s = (1-m)/(1-r)
    carriers = [("onshore", sev["onshore"], 0.20), ("offshore", sev["offshore"], 0.25), ("solar", sev["solar"], 0.15)]
    fig, ax = plt.subplots(figsize=(10, 4))
    add_phase_shading(ax, meta, snaps)
    for name, r, plateau in carriers:
        m = _load_factor_csv("severe", name if name != "onshore" else "onshore")
        if m.empty:
            m = _load_factor_csv("severe", "wind_capacity_weighted" if name == "onshore" else name)
        if not m.empty:
            ax.plot(m.index, m.values, label=f"{name} (plateau m={plateau:.2f})", lw=1.5)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Multiplier $m_k(t)$")
    ax.set_xlabel("Time")
    ax.set_title("Stylised stress envelope — severe case")
    ax.legend(loc="lower right", fontsize=8)
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_D1", ctx.output_dir)
    _reg(ctx, "FIGURE_D1", "Stylised stress envelope", "Dunkelflaute", "Raised-cosine envelope with severe plateau ratios")


def _aggregate_vre_cf(n, snaps) -> pd.Series:
    w = snapshot_weight(n, snaps)
    total_cap = 0.0
    avail = pd.Series(0.0, index=snaps)
    ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
    for gen in ren.index:
        if gen not in n.generators_t.p_max_pu.columns:
            continue
        p_nom = float(n.generators.at[gen, "p_nom"])
        total_cap += p_nom
        avail += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * p_nom
    return avail / total_cap if total_cap else avail


def figure_d2_base_vs_severe(ctx: PackageContext) -> None:
    meta = ctx.meta
    nb = load_network("matched-base-v4", ctx)
    ns = load_network("stylised-df-severe-v4", ctx)
    if nb is None or ns is None:
        return
    snaps = pd.DatetimeIndex(nb.snapshots)
    groups = [
        ("A. Onshore wind", ["onwind"]),
        ("B. Offshore wind", ["offwind-ac", "offwind-dc", "offwind-float"]),
        ("C. Solar", ["solar", "solar-hsat"]),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    core_start, core_end = pd.Timestamp(meta["core_start"]), pd.Timestamp(meta["core_end"])
    trans = pd.Timedelta(hours=float(meta.get("transition_hours", 48)))
    for ax, (title, carriers) in zip(axes, groups):

        def agg_cf(n):
            cap = n.generators[n.generators.carrier.isin(carriers)]["p_nom"].sum()
            s = pd.Series(0.0, index=snaps)
            for gen in n.generators[n.generators.carrier.isin(carriers)].index:
                if gen in n.generators_t.p_max_pu.columns:
                    s += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
            return s / cap if cap else s

        ax.plot(snaps, agg_cf(nb), label="Matched Base", color=group_color("onshore wind"), alpha=0.8)
        ax.plot(snaps, agg_cf(ns), label="Severe", color="#c44e52", alpha=0.8)
        ax.axvspan(core_start, core_end, color="grey", alpha=0.12)
        ax.axvspan(core_start + trans, core_end - trans, color="red", alpha=0.08, label="Plateau")
        ax.set_ylabel("Capacity factor [p.u.]")
        ax.set_title(title)
        ax.legend(fontsize=7, loc="upper right")
    axes[-1].set_xlabel("Time")
    fig.suptitle("Base versus severe renewable availability", y=1.01)
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_D2", ctx.output_dir)
    _reg(ctx, "FIGURE_D2", "Base versus severe renewable availability", "Dunkelflaute", "Capacity-weighted aggregate availability by carrier class")


def figure_d3_residual_load(ctx: PackageContext) -> None:
    meta = ctx.meta
    nb = load_network("matched-base-v4", ctx)
    ns = load_network("stylised-df-severe-v4", ctx)
    if nb is None or ns is None:
        return
    snaps = pd.DatetimeIndex(nb.snapshots)

    def vre_gw(n):
        ren = n.generators[n.generators.carrier.isin(RENEWABLE_CARRIERS)]
        s = pd.Series(0.0, index=snaps)
        for gen in ren.index:
            if gen in n.generators_t.p_max_pu.columns:
                s += n.generators_t.p_max_pu[gen].reindex(snaps).fillna(0) * n.generators.at[gen, "p_nom"]
        return s / 1e3

    d = national_demand_gw(nb, snaps)
    vb, vs = vre_gw(nb), vre_gw(ns)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    add_core_shading(ax, meta)
    ax.plot(snaps, d, "k-", lw=1.5, label="Demand")
    ax.plot(snaps, vb, color=group_color("onshore wind"), label="Available VRE (Base)")
    ax.plot(snaps, vs, color="#c44e52", label="Available VRE (severe)")
    ax.plot(snaps, d - vb, "--", color="grey", label="Residual load (Base)")
    ax.plot(snaps, d - vs, "--", color="#826837", label="Residual load (severe)")
    ax.set_ylabel("Power [GW]")
    ax.set_title("Demand, available VRE and residual load")
    ax.legend(fontsize=7, ncol=2)
    ax.text(0.02, 0.02, "Availability-based diagnostic, not optimised dispatch", transform=ax.transAxes, fontsize=8, style="italic")
    fig.autofmt_xdate()
    plt.tight_layout()
    save_figure(fig, "FIGURE_D3", ctx.output_dir)
    _reg(ctx, "FIGURE_D3", "Demand, available VRE and residual load", "Dunkelflaute", "Diagnostic residual load under Base vs severe availability")


def figure_d4_energy_ratio(ctx: PackageContext) -> None:
    df = pd.read_csv(PROFILE_OUTPUT / "energy_ratio_summary.csv")
    sev = df[df["scenario"] == "severe"]
    scopes = ["plateau", "core", "full-window"]
    groups = ["onshore", "offshore", "solar", "total_vre"]
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(scopes))
    w = 0.2
    for i, g in enumerate(groups):
        vals = [float(sev[(sev["scope"] == sc) & (sev["carrier_group"] == g)]["energy_ratio"].iloc[0]) for sc in scopes]
        ax.bar(x + i * w, vals, width=w, label=g.replace("_", " "))
    ax.set_xticks(x + 1.5 * w)
    ax.set_xticklabels(["10-day plateau", "14-day core", "28-day full window"])
    ax.set_ylabel("Energy ratio (severe / Base)")
    ax.set_title("Energy-ratio summary — severe remaining VRE")
    ax.axhline(0.356, color="k", ls=":", lw=0.8)
    ax.annotate("Core total VRE ≈ 0.356 (−64.4%)", xy=(1 + w, 0.36), fontsize=8)
    ax.legend(fontsize=7)
    ax.set_ylim(0, 1.05)
    plt.tight_layout()
    save_figure(fig, "FIGURE_D4", ctx.output_dir)
    _reg(ctx, "FIGURE_D4", "Energy-ratio summary", "Dunkelflaute", "Severe VRE energy retention by window", appendix=True)


def build_appendix_dunkelflaute(ctx: PackageContext) -> None:
    """Regenerate key profile diagnostics with report style."""
    mapping = [
        ("APP_D_cutout", "cutout_base_comparison", "Cutout versus Base pre-overwrite comparison"),
        ("APP_D_stitch_in", "11_stitch_entry_zoom", "Buffer-to-core stitch entry zoom"),
        ("APP_D_stitch_out", "12_stitch_exit_zoom", "Core-to-buffer stitch exit zoom"),
    ]
    plots_dir = PROFILE_OUTPUT / "plots"
    for fig_id, old_stem, title in mapping:
        src = plots_dir / f"{old_stem}.png"
        if not src.exists():
            ctx.warnings.append(f"Missing appendix source plot: {src}")
            continue
        # Re-read underlying data where possible; for stitch/cutout use CSV-driven rebuild if needed
        _reg(ctx, fig_id, title, "Appendix", title, appendix=True)


def build_dunkelflaute_figures(ctx: PackageContext) -> None:
    ctx.meta = load_metadata()
    figure_d1_stress_envelope(ctx)
    figure_d2_base_vs_severe(ctx)
    figure_d3_residual_load(ctx)
    figure_d4_energy_ratio(ctx)
    build_appendix_from_profile_plots(ctx)


def build_appendix_from_profile_plots(ctx: PackageContext) -> None:
    """Rebuild appendix profile figures from output CSV summaries."""
    meta = ctx.meta
    er = pd.read_csv(PROFILE_OUTPUT / "energy_ratio_summary.csv")
    for severity, fig_id, title in [
        ("moderate", "APP_D_moderate", "Moderate stylised profile"),
        ("severe", "APP_D_severe", "Severe stylised profile"),
        ("extreme", "APP_D_extreme", "Extreme stylised profile"),
    ]:
        sub = er[(er["scenario"] == severity) & (er["scope"] == "core") & (er["carrier_group"] == "total_vre")]
        if sub.empty:
            continue
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.bar(["Core total VRE ratio"], [float(sub["energy_ratio"].iloc[0])], color="#6895d1")
        ax.set_ylim(0, 1)
        ax.set_title(title)
        ax.set_ylabel("Energy ratio vs Base")
        plt.tight_layout()
        save_figure(fig, fig_id, ctx.output_dir)
        _reg(ctx, fig_id, title, "Appendix", f"{severity} profile energy ratio", appendix=True)

    # Cutout vs Base comparison
    cutout = PROFILE_OUTPUT / "cutout_base_comparison.csv"
    if cutout.exists():
        cd = pd.read_csv(cutout)
        fig, ax = plt.subplots(figsize=(7, 4))
        if "carrier" in cd.columns and "max_abs_diff" in cd.columns:
            ax.barh(cd["carrier"], cd["max_abs_diff"])
        elif len(cd.columns) >= 2:
            ax.barh(cd.iloc[:, 0].astype(str), pd.to_numeric(cd.iloc[:, 1], errors="coerce"))
        ax.set_xlabel("Max |cutout − Base| difference [p.u.]")
        ax.set_title("Cutout versus Base pre-overwrite comparison")
        plt.tight_layout()
        save_figure(fig, "APP_D_cutout", ctx.output_dir)
        _reg(ctx, "APP_D_cutout", "Cutout versus Base pre-overwrite comparison", "Appendix", "Buffer/core stitch validation", appendix=True)

    # Stitch zoom from factor CSVs around core entry/exit
    for fig_id, title, start, end in [
        ("APP_D_stitch_in", "Buffer-to-core stitch entry zoom", "2021-01-23", "2021-01-27"),
        ("APP_D_stitch_out", "Core-to-buffer stitch exit zoom", "2021-02-07", "2021-02-11"),
    ]:
        m = _load_factor_csv("severe", "onshore")
        if m.empty:
            continue
        window = m[(m.index >= start) & (m.index <= end)]
        if window.empty:
            continue
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.plot(window.index, window.values, color=group_color("onshore wind"))
        ax.set_ylabel("$m_k(t)$")
        ax.set_title(title)
        fig.autofmt_xdate()
        plt.tight_layout()
        save_figure(fig, fig_id, ctx.output_dir)
        _reg(ctx, fig_id, title, "Appendix", "Stitch diagnostic zoom", appendix=True)

    pv = pd.read_csv(PROFILE_OUTPUT / "profile_validation.csv") if (PROFILE_OUTPUT / "profile_validation.csv").exists() else pd.DataFrame()
    if not pv.empty and "passed" in pv.columns:
        fig, ax = plt.subplots(figsize=(6, 3))
        vals = pv["passed"].map({True: 1, False: 0, "True": 1, "False": 0}).astype(float)
        ax.bar(pv["test"], vals, color="#059669")
        ax.set_ylim(0, 1.2)
        ax.tick_params(axis="x", rotation=45, labelsize=6)
        ax.set_title("Phase-count validation")
        plt.tight_layout()
        save_figure(fig, "APP_D_phase_validation", ctx.output_dir)
        _reg(ctx, "APP_D_phase_validation", "Phase-count validation", "Appendix", "Profile phase validation", appendix=True)
