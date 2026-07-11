# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Consistent publication style for INRE V4 final report figures."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]

# Colour-blind-friendly carrier palette (fixed across all report figures).
CARRIER_GROUPS: dict[str, str] = {
    "onshore wind": "#235ebc",
    "offshore wind": "#1a4480",
    "solar": "#f0a202",
    "biomass": "#2ca02c",
    "coal": "#545454",
    "lignite": "#826837",
    "CCGT": "#d94801",
    "OCGT / oil / peaker": "#8b0000",
    "nuclear": "#7b3294",
    "load shedding": "#cc0077",
    "demand": "#000000",
    "other firm": "#6b7280",
    "waste": "#228b22",
    "geothermal": "#006400",
    "curtailment": "#9ca3af",
}

# PyPSA carrier name → report group
CARRIER_MAP: dict[str, str] = {
    "onwind": "onshore wind",
    "offwind-ac": "offshore wind",
    "offwind-dc": "offshore wind",
    "offwind-float": "offshore wind",
    "solar": "solar",
    "solar-hsat": "solar",
    "biomass": "biomass",
    "coal": "coal",
    "lignite": "lignite",
    "CCGT": "CCGT",
    "OCGT": "OCGT / oil / peaker",
    "oil": "OCGT / oil / peaker",
    "waste": "waste",
    "geothermal": "geothermal",
    "load_shed": "load shedding",
    "nuclear-smr": "nuclear",
    "nuclear-msr": "nuclear",
    "nuclear-lfr": "nuclear",
    "generic-advanced-nuclear": "nuclear",
    "ror": "other firm",
}

SCENARIO_SHORT: dict[str, str] = {
    "matched-base-v4": "Matched Base",
    "stylised-df-severe-v4": "Severe",
    "stylised-df-moderate-v4": "Moderate (profile)",
    "stylised-df-extreme-v4": "Extreme (profile)",
    "stylised-df-severe-nuc-1.5-v4": "Severe + 1.5 GW",
    "stylised-df-severe-nuc-3.0-v4": "Severe + 3.0 GW",
    "stylised-df-severe-nuc-4.5-v4": "Severe + 4.5 GW",
    "stylised-df-severe-nuc-7.5-v4": "Severe + 7.5 GW",
    "stylised-df-severe-smr-v4": "Severe + SMR 4.5 GW",
    "stylised-df-severe-msr-v4": "Severe + MSR 4.5 GW",
    "stylised-df-severe-lfr-v4": "Severe + LFR 4.5 GW",
    "stylised-df-severe-decarb-v4": "Decarb no nuclear",
    "stylised-df-severe-decarb-smr-4.5-v4": "Decarb + SMR 4.5 GW",
    "stylised-df-severe-decarb-smr-4.5-limited-flex-v4": "Decarb + SMR (limited flex)",
}

PHASE_COLORS = {
    "pre-buffer": "#e8f4fc",
    "transition-in": "#fff3cd",
    "plateau": "#f8d7da",
    "transition-out": "#fff3cd",
    "post-buffer": "#e8f4fc",
    "core": "#f0f0f0",
}

DPI = 300
FONT_SIZE = 10
TITLE_SIZE = 11
LINE_WIDTH = 1.4


def apply_style() -> None:
    mpl.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "font.size": FONT_SIZE,
            "axes.titlesize": TITLE_SIZE,
            "axes.labelsize": FONT_SIZE,
            "legend.fontsize": FONT_SIZE - 1,
            "xtick.labelsize": FONT_SIZE - 1,
            "ytick.labelsize": FONT_SIZE - 1,
            "axes.grid": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica", "sans-serif"],
        }
    )


def carrier_color(carrier: str) -> str:
    group = CARRIER_MAP.get(carrier, carrier)
    return CARRIER_GROUPS.get(group, "#888888")


def group_color(group: str) -> str:
    return CARRIER_GROUPS.get(group, "#888888")


def short_scenario(name: str) -> str:
    return SCENARIO_SHORT.get(name, name)


def save_figure(fig: plt.Figure, figure_id: str, output_dir: Path, suffix: str = "") -> dict[str, Path]:
    """Export figure to pdf, svg, png subdirectories."""
    stem = f"{figure_id}{suffix}"
    paths: dict[str, Path] = {}
    for fmt, sub in [("pdf", "pdf"), ("svg", "svg"), ("png", "png")]:
        d = output_dir / "figures" / sub
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{stem}.{fmt}"
        kw = {"bbox_inches": "tight", "facecolor": "white"}
        if fmt == "png":
            kw["dpi"] = DPI
        fig.savefig(p, format=fmt, **kw)
        paths[fmt] = p
    plt.close(fig)
    return paths


def add_phase_shading(ax, meta: dict, snaps: pd.DatetimeIndex, alpha: float = 0.22, label: bool = False) -> None:
    """Shade pre-buffer, 14-day core, and post-buffer from metadata."""
    core_start = pd.Timestamp(meta["core_start"])
    core_end = pd.Timestamp(meta["core_end"])
    sim_start = pd.Timestamp(meta["simulation_start"])
    sim_end = pd.Timestamp(meta["simulation_end"])

    ax.axvspan(sim_start, core_start, color=PHASE_COLORS["pre-buffer"], alpha=alpha, lw=0)
    ax.axvspan(core_start, core_end, color=PHASE_COLORS["plateau"], alpha=alpha, lw=0)
    ax.axvspan(core_end, sim_end, color=PHASE_COLORS["post-buffer"], alpha=alpha, lw=0)

    if label:
        y_top = ax.get_ylim()[1]
        y_text = y_top * 0.97 if y_top else 0
        for x0, x1, text in [
            (sim_start, core_start, "7-day pre-event buffer"),
            (core_start, core_end, "14-day Dunkelflaute core"),
            (core_end, sim_end, "7-day post-event buffer"),
        ]:
            xm = x0 + (x1 - x0) / 2
            ax.text(
                xm,
                y_text,
                text,
                ha="center",
                va="top",
                fontsize=8,
                rotation=0,
                clip_on=True,
            )


def add_core_shading(ax, meta: dict, alpha: float = 0.15) -> None:
    ax.axvspan(
        pd.Timestamp(meta["core_start"]),
        pd.Timestamp(meta["core_end"]),
        color=PHASE_COLORS["core"],
        alpha=alpha,
        lw=0,
        label="Core event",
    )


def export_carrier_colour_map(path: Path) -> None:
    rows = []
    for group, hex_code in CARRIER_GROUPS.items():
        carriers = [c for c, g in CARRIER_MAP.items() if g == group]
        rows.append(
            {
                "carrier_group": group,
                "hex_colour": hex_code,
                "pypsa_carriers": ";".join(sorted(carriers)) if carriers else "",
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
