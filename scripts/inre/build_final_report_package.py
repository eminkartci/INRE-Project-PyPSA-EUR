# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""
Build the INRE V4 final report figure and table package.

Usage::

    python scripts/inre/build_final_report_package.py
    python scripts/inre/build_final_report_package.py --output results/inre-final-report-package
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.inre.final_report.captions import build_old_figure_audit, write_captions, write_report_asset_guide
from scripts.inre.final_report.data_loaders import PackageContext, ensure_dirs
from scripts.inre.final_report.figures_dunkelflaute import build_dunkelflaute_figures
from scripts.inre.final_report.figures_input import build_input_figures
from scripts.inre.final_report.figures_prices import build_price_figures
from scripts.inre.final_report.figures_results import build_results_figures
from scripts.inre.final_report.figures_sensitivity import build_sensitivity_figures
from scripts.inre.final_report.tables import build_all_tables
from scripts.inre.final_report.validate import run_validation
from scripts.inre.report_style import apply_style, export_carrier_colour_map

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = REPO_ROOT / "results/inre-final-report-package"


def build_package(output_dir: Path) -> PackageContext:
    apply_style()
    ensure_dirs(output_dir)
    ctx = PackageContext(output_dir=output_dir)

    export_carrier_colour_map(output_dir / "data" / "carrier_colour_map.csv")

    logger.info("Building tables...")
    build_all_tables(ctx)

    logger.info("Building input figures...")
    build_input_figures(ctx)

    logger.info("Building Dunkelflaute figures...")
    build_dunkelflaute_figures(ctx)

    logger.info("Building results figures...")
    build_results_figures(ctx)

    logger.info("Building price figures...")
    build_price_figures(ctx)

    logger.info("Building sensitivity & validation figures...")
    build_sensitivity_figures(ctx)

    logger.info("Running validation...")
    val = run_validation(output_dir)
    passed = int(val["passed"].sum()) if not val.empty and "passed" in val.columns else 0
    failed = int((~val["passed"]).sum()) if not val.empty and "passed" in val.columns else 0

    write_captions(ctx)
    build_old_figure_audit(ctx)
    write_report_asset_guide(ctx)

    pd.DataFrame(ctx.figure_manifest).to_csv(output_dir / "FIGURE_MANIFEST.csv", index=False)
    pd.DataFrame(ctx.table_manifest).to_csv(output_dir / "TABLE_MANIFEST.csv", index=False)

    n_fig = len(list((output_dir / "figures" / "png").glob("*.png")))
    n_tab = len(list((output_dir / "tables").glob("*.csv")))
    n_cap = len(list((output_dir / "captions").glob("*.txt")))

    summary_path = output_dir / "PACKAGE_BUILD_SUMMARY.txt"
    summary_path.write_text(
        f"Figures (png): {n_fig}\n"
        f"Tables (csv): {n_tab}\n"
        f"Captions: {n_cap}\n"
        f"Validation passed: {passed}\n"
        f"Validation failed: {failed}\n"
        f"Warnings: {len(ctx.warnings)}\n"
    )
    if ctx.warnings:
        (output_dir / "BUILD_WARNINGS.txt").write_text("\n".join(ctx.warnings))

    logger.info("Package complete: %s", output_dir)
    return ctx


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build INRE V4 final report asset package")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    ctx = build_package(args.output)
    print(f"\nPackage written to {args.output}")
    print(f"Figures: {len(ctx.figure_manifest)} registered")
    print(f"Tables: {len(ctx.table_manifest)} registered")
    if ctx.warnings:
        print(f"Warnings ({len(ctx.warnings)}):")
        for w in ctx.warnings[:10]:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
