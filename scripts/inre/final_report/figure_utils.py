# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Shared helpers for final report figure generation, data export, and audit."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts.inre.final_report.data_loaders import REPO_ROOT
from scripts.inre.report_style import save_figure

FINAL_FIGURES_DIR = REPO_ROOT / "final_figures"

REQUIRED_FIGURES = [
    "FIGURE_I1",
    "FIGURE_I2",
    "FIGURE_I4",
    "FIGURE_D2",
    "FIGURE_D3",
    "FIGURE_R1",
    "FIGURE_P1",
    "FIGURE_N1",
    "FIGURE_A2",
    "FIGURE_G1",
    "FIGURE_R2",
    "FIGURE_R3",
    "FIGURE_P2",
    "FIGURE_A1",
    "FIGURE_A4",
    "FIGURE_F1",
]

DISPLAY_CARRIER_ORDER = [
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
    "nuclear",
    "other firm",
    "load shedding",
    "other",
]


def export_plot_data(df: pd.DataFrame, figure_id: str, output_dir: Path) -> Path:
    data_dir = output_dir / "data" / "figures"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{figure_id.lower()}_data.csv"
    df.to_csv(path, index=False)
    return path


def register_audit(
    ctx,
    *,
    figure_id: str,
    source_folder: str,
    source_file: str,
    script: str,
    temporal_scope: str,
    scenarios: str,
    plotted_variables: str,
    key_values_checked: str = "",
    pdf_output: str = "",
    png_output: str = "",
    status: str = "generated",
    notes: str = "",
) -> None:
    ctx.audit_entries.append(
        {
            "figure_id": figure_id,
            "source_folder": source_folder,
            "source_file": source_file,
            "plotted_variables": plotted_variables,
            "temporal_scope": temporal_scope,
            "script": script,
            "scenarios": scenarios,
            "key_values_checked": key_values_checked,
            "pdf_output": pdf_output,
            "png_output": png_output,
            "status": status,
            "notes": notes,
        }
    )


def save_figure_with_data(
    fig,
    figure_id: str,
    ctx,
    plot_data: pd.DataFrame | None,
    *,
    script: str,
    source_folder: str,
    source_file: str,
    temporal_scope: str,
    scenarios: str,
    plotted_variables: str,
    key_values_checked: str = "",
    notes: str = "",
) -> dict[str, Path]:
    paths = save_figure(fig, figure_id, ctx.output_dir)
    data_path = ""
    if plot_data is not None and not plot_data.empty:
        data_path = str(export_plot_data(plot_data, figure_id, ctx.output_dir))
    register_audit(
        ctx,
        figure_id=figure_id,
        source_folder=source_folder,
        source_file=source_file,
        script=script,
        temporal_scope=temporal_scope,
        scenarios=scenarios,
        plotted_variables=plotted_variables,
        key_values_checked=key_values_checked,
        pdf_output=str(paths["pdf"]),
        png_output=str(paths["png"]),
        status="generated",
        notes=notes + (f"; data_csv={data_path}" if data_path else ""),
    )
    return paths


def backup_final_figures() -> Path:
    backup = REPO_ROOT / f"final_figures_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if FINAL_FIGURES_DIR.exists():
        shutil.copytree(FINAL_FIGURES_DIR, backup)
    else:
        backup.mkdir(parents=True, exist_ok=True)
    return backup


def deploy_to_final_figures(package_dir: Path, figure_ids: list[str] | None = None) -> list[Path]:
    """Copy PDF figures only into final_figures/ (LaTeX report source)."""
    figure_ids = figure_ids or REQUIRED_FIGURES
    FINAL_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    deployed: list[Path] = []
    for fig_id in figure_ids:
        src = package_dir / "figures" / "pdf" / f"{fig_id}.pdf"
        if not src.exists():
            continue
        dst = FINAL_FIGURES_DIR / f"{fig_id}.pdf"
        shutil.copy2(src, dst)
        deployed.append(dst)
    return deployed
