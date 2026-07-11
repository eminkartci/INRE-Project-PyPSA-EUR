# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""
Regenerate final LaTeX report figures from V4 results.

Usage::

    python scripts/inre/regenerate_final_figures.py
    python scripts/inre/regenerate_final_figures.py --no-backup
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.inre.final_report.data_loaders import (
    COMPARISON_DIRS,
    PackageContext,
    core_snaps,
    ensure_dirs,
    load_metadata,
    load_network,
    national_demand_gw,
    read_csv,
    snapshot_weight,
)
from scripts.inre.final_report.figure_utils import (
    REQUIRED_FIGURES,
    backup_final_figures,
    deploy_to_final_figures,
)
from scripts.inre.final_report.figures_dunkelflaute import build_dunkelflaute_figures
from scripts.inre.final_report.figures_input import build_input_figures
from scripts.inre.final_report.figures_prices import build_price_figures
from scripts.inre.final_report.figures_results import build_results_figures
from scripts.inre.final_report.figures_sensitivity import build_sensitivity_figures
from scripts.inre.report_style import apply_style

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = REPO_ROOT / "results/inre-final-report-package"


def _check(name: str, plotted: float, expected: float, tol: float = 0.05) -> dict:
    diff = abs(plotted - expected)
    return {
        "check": name,
        "plotted": plotted,
        "expected": expected,
        "difference": diff,
        "passed": diff <= tol,
    }


def run_figure_validation(ctx: PackageContext) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict] = []
    notes: list[str] = []
    meta = load_metadata()

    n = load_network("stylised-df-severe-v4", ctx)
    if n is not None:
        snaps = pd.DatetimeIndex(n.snapshots)
        demand = national_demand_gw(n, snaps)
        w = snapshot_weight(n, snaps)
        full_twh = float((demand * 1e3 * w).sum()) / 1e6
        core = core_snaps(n, meta)
        core_twh = float((demand.reindex(core) * 1e3 * w.reindex(core)).sum()) / 1e6
        for chk in [
            _check("FIGURE_I1 full_window_demand_TWh", full_twh, 42.74, 0.15),
            _check("FIGURE_I1 core_demand_TWh", core_twh, 21.15, 0.15),
        ]:
            rows.append({**chk, "figure_id": "FIGURE_I1"})

    stage1 = read_csv(COMPARISON_DIRS["stage1"] / "stage1_summary.csv")
    if not stage1.empty:
        base = stage1[(stage1["scenario"] == "Matched Base") & (stage1["scope"] == "full_window")].iloc[0]
        sev = stage1[(stage1["scenario"] == "Severe") & (stage1["scope"] == "full_window")].iloc[0]
        ccgt_delta = float(sev["ccgt_generation_twh"]) - float(base["ccgt_generation_twh"])
        rows.append({**_check("FIGURE_R1 CCGT_increase_TWh", ccgt_delta, 1.95, 0.1), "figure_id": "FIGURE_R1"})
        rows.append(
            {
                **_check("FIGURE_R1 EENS_severe_GWh", float(sev["eens_gwh"]), 0.0, 0.01),
                "figure_id": "FIGURE_R1",
            }
        )

    nuc = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "nuclear_sweep_summary.csv")
    core_nuc = nuc[nuc["scope"] == "core"].sort_values("nuclear_installed_capacity_gw")
    expected_nuc = {
        0.0: (0.0, 0.0),
        1.5: (0.44, 87.3),
        3.0: (0.87, 86.7),
        4.5: (1.30, 86.3),
        7.5: (2.15, 85.5),
    }
    for cap, (gen, cf) in expected_nuc.items():
        row = core_nuc[core_nuc["nuclear_installed_capacity_gw"] == cap]
        if row.empty:
            continue
        r = row.iloc[0]
        rows.append({**_check(f"FIGURE_N1 gen_{cap}GW_TWh", float(r["nuclear_generation_twh"]), gen, 0.02), "figure_id": "FIGURE_N1"})
        if cap > 0:
            rows.append(
                {
                    **_check(f"FIGURE_N1 cf_{cap}GW_pct", float(r["nuclear_capacity_factor_pct"]), cf, 0.5),
                    "figure_id": "FIGURE_N1",
                }
            )

    ade = read_csv(COMPARISON_DIRS["decarbonised"] / "adequacy_summary_full_window.csv")
    if not ade.empty:
        no_nuc = ade[ade["scenario_key"].str.contains("decarb-v4") & ~ade["scenario_key"].str.contains("smr")].iloc[0]
        smr = ade[ade["scenario_key"].str.contains("smr")].iloc[0]
        rows.append({**_check("FIGURE_A2 EENS_no_nuclear_GWh", float(no_nuc["eens_gwh"]), 1840.0, 5), "figure_id": "FIGURE_A2"})
        rows.append({**_check("FIGURE_A2 EENS_SMR_GWh", float(smr["eens_gwh"]), 1088.7, 5), "figure_id": "FIGURE_A2"})
        rows.append(
            {
                **_check("FIGURE_A1 peak_no_nuclear_GW", float(no_nuc["peak_load_shedding_gw"]), 18.06, 0.1),
                "figure_id": "FIGURE_A1",
            }
        )
        rows.append(
            {
                **_check("FIGURE_A1 peak_SMR_GW", float(smr["peak_load_shedding_gw"]), 14.01, 0.1),
                "figure_id": "FIGURE_A1",
            }
        )

    pg = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "adequacy_comparison.csv")
    kpi = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "kpi_comparison.csv")
    dec_pg = pg[pg["scenario"].str.contains("decarbonised")]
    dec_kpi = kpi[kpi["scenario"].str.contains("decarbonised")]
    for _, r in dec_pg.iterrows():
        diff = abs(float(r["pypsa_eens_gwh"]) - float(r["gamspy_eens_gwh"]))
        rows.append({**_check(f"FIGURE_G1 EENS_{r['scenario']}", diff, 0.0, 0.01), "figure_id": "FIGURE_G1"})
    for _, r in dec_kpi.iterrows():
        diff = abs(float(r["pypsa_peak_ls_gw"]) - float(r["gamspy_peak_ls_gw"]))
        rows.append({**_check(f"FIGURE_G1 peak_LS_{r['scenario']}", diff, 0.0, 0.01), "figure_id": "FIGURE_G1"})

    flex = read_csv(COMPARISON_DIRS["flexibility"] / "flexibility_impact_summary.csv")
    if not flex.empty:
        rows.append(
            {
                **_check(
                    "FIGURE_F1 curtailment_delta_TWh",
                    float(flex.iloc[0]["curtailment_impact_twh_full_window"]),
                    0.11,
                    0.02,
                ),
                "figure_id": "FIGURE_F1",
            }
        )

    val_df = pd.DataFrame(rows)
    failed = val_df[~val_df["passed"]] if not val_df.empty else pd.DataFrame()
    if not failed.empty:
        for _, r in failed.iterrows():
            notes.append(f"DISCREPANCY: {r['figure_id']} {r['check']}: plotted={r['plotted']}, expected={r['expected']}")

    return val_df, notes


def write_validation_markdown(
    output_dir: Path,
    backup_path: Path | None,
    val_df: pd.DataFrame,
    notes: list[str],
    deployed: list[Path],
) -> None:
    regenerated = ", ".join(REQUIRED_FIGURES)
    passed = int(val_df["passed"].sum()) if not val_df.empty else 0
    failed = int((~val_df["passed"]).sum()) if not val_df.empty else 0
    lines = [
        "# Final report figure validation",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Regenerated figures",
        "",
        regenerated,
        "",
        "## Source folders (V4 final only)",
        "",
        "- `results/inre-comparison-v4-stage1/`",
        "- `results/inre-comparison-v4-nuclear-sweep/`",
        "- `results/inre-comparison-v4-reactor-comparison/`",
        "- `results/inre-comparison-v4-decarbonised-adequacy/`",
        "- `results/inre-comparison-v4-smr-flexibility/`",
        "- `results/inre-comparison-v4-pypsa-gamspy/`",
        "- solved networks under `results/inre-de-*-v4/`",
        "- profile metadata `data/inre/profiles/stylised_dunkelflaute_v4/metadata.yaml`",
        "",
        "## Legacy results",
        "",
        "No V3, legacy 14-day-only, expansion, or obsolete 7.5 GW SMR folders were used for the final report figures listed above.",
        "",
        "## Numerical checks",
        "",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
    ]
    if notes:
        lines.extend(["## Discrepancies", ""] + [f"- {n}" for n in notes] + [""])
    else:
        lines.extend(["## Discrepancies", "", "None identified against final report tables.", ""])

    lines.extend(
        [
            "## Units and temporal scope",
            "",
            "- Power/capacity: GW",
            "- Energy: TWh or GWh as labelled",
            "- Prices: EUR/MWh (modelled marginal electricity price)",
            "- Emissions: MtCO₂ (direct operational CO₂ emissions, where applicable)",
            "- 14-day Dunkelflaute core and 28-day modelling window are labelled explicitly per figure",
            "",
            "## Readability",
            "",
            "All figures use white background, colour-blind-safe carrier colours, minimum 9 pt effective labels, and 300 dpi PNG exports sized for A4 report width.",
            "",
            "## Deployment",
            "",
            f"- Package output: `{output_dir}`",
            f"- Backup of previous `final_figures/`: `{backup_path or 'skipped'}`",
            f"- Deployed files: {len(deployed)} PDF copies in `final_figures/`",
            "",
        ]
    )
    (output_dir / "figure_validation.md").write_text("\n".join(lines))


def regenerate(output_dir: Path, do_backup: bool = True) -> PackageContext:
    apply_style()
    ensure_dirs(output_dir)
    ctx = PackageContext(output_dir=output_dir)

    backup_path = backup_final_figures() if do_backup else None
    logger.info("Backed up final_figures to %s", backup_path)

    logger.info("Building input figures...")
    build_input_figures(ctx)
    logger.info("Building Dunkelflaute figures...")
    build_dunkelflaute_figures(ctx)
    logger.info("Building results figures...")
    build_results_figures(ctx)
    logger.info("Building price figures...")
    build_price_figures(ctx)
    logger.info("Building sensitivity figures...")
    build_sensitivity_figures(ctx)

    val_df, notes = run_figure_validation(ctx)
    val_df.to_csv(output_dir / "validation" / "figure_numerical_checks.csv", index=False)

    audit_df = pd.DataFrame(ctx.audit_entries)
    audit_df.to_csv(output_dir / "figure_audit.csv", index=False)

    deployed = deploy_to_final_figures(output_dir)
    write_validation_markdown(output_dir, backup_path, val_df, notes, deployed)

    missing = [f for f in REQUIRED_FIGURES if not (output_dir / "figures" / "pdf" / f"{f}.pdf").exists()]
    if missing:
        ctx.warnings.append(f"Missing figures after build: {missing}")
    if notes:
        ctx.warnings.extend(notes)

    logger.info("Regeneration complete: %d figures, %d deployed files", len(ctx.audit_entries), len(deployed))
    return ctx


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Regenerate INRE V4 final LaTeX report figures")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    ctx = regenerate(args.output, do_backup=not args.no_backup)
    print(f"\nFigures written to {args.output}/figures/")
    print(f"Audit table: {args.output}/figure_audit.csv")
    print(f"Validation: {args.output}/figure_validation.md")
    print(f"Deployed to final_figures/: {len(REQUIRED_FIGURES)} figure IDs")
    if ctx.warnings:
        print(f"\nWarnings ({len(ctx.warnings)}):")
        for w in ctx.warnings[:15]:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
