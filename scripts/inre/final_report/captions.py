# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Caption generation and OLD_FIGURE_AUDIT."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.inre.final_report.data_loaders import REPO_ROOT


def write_captions(ctx) -> None:
    cap_dir = ctx.output_dir / "captions"
    cap_dir.mkdir(parents=True, exist_ok=True)
    for fig_id, text in ctx.captions.items():
        (cap_dir / f"{fig_id.lower()}.txt").write_text(text)

    # Default captions for figures without explicit text
    for row in ctx.figure_manifest:
        fid = row["figure_id"]
        path = cap_dir / f"{fid.lower()}.txt"
        if not path.exists():
            path.write_text(
                f"{row['title']}. "
                f"Scenario: {row.get('source_scenarios', 'V4 final')}. "
                f"Key result: {row.get('key_message', '')}. "
                f"Limitation: fixed-capacity stylised Dunkelflaute model; not historical reconstruction or market forecast."
            )

    lines = ["# All figure captions\n"]
    for p in sorted(cap_dir.glob("figure_*.txt")) + sorted(cap_dir.glob("app_*.txt")):
        lines.append(f"## {p.stem.upper()}\n")
        lines.append(p.read_text())
        lines.append("\n")
    (cap_dir / "ALL_CAPTIONS.md").write_text("\n".join(lines))


def build_old_figure_audit(ctx) -> pd.DataFrame:
    old_roots = [
        REPO_ROOT / "output/stylised_dunkelflaute_v4/plots",
        REPO_ROOT / "results/inre-comparison-v4-stage1/plots",
        REPO_ROOT / "results/inre-comparison-v4-nuclear-sweep/plots",
        REPO_ROOT / "results/inre-comparison-v4-reactor-comparison/plots",
        REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy/plots",
        REPO_ROOT / "results/inre-comparison-v4-smr-flexibility/plots",
        REPO_ROOT / "results/inre-comparison-v4-pypsa-gamspy",
    ]
    replacement_map = {
        "01_stress_envelope": ("FIGURE_D1", "regenerated"),
        "07_demand_residual_load_diagnostic": ("FIGURE_D3", "regenerated"),
        "09_core_energy_comparison": ("FIGURE_D4", "replaced"),
        "00_demand_full_window": ("FIGURE_I1", "regenerated"),
        "01_core_generation_stack": ("FIGURE_R2", "regenerated"),
        "07_core_cost_co2": ("FIGURE_R4", "replaced"),
        "01_nuclear": ("FIGURE_N1", "regenerated"),
        "06_cumulative_eens": ("FIGURE_A2", "regenerated"),
    }
    rows = []
    for root in old_roots:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.suffix.lower() not in {".png", ".pdf"}:
                continue
            stem = f.stem
            rep, status = replacement_map.get(stem, ("", "appendix"))
            if not rep:
                if "stitch" in stem:
                    rep, status = "APP_D_stitch", "appendix"
                elif "heatmap" in stem or "duration" in stem or "cluster" in stem:
                    status = "appendix"
                elif "v2" in str(f) or "v3" in str(f):
                    status = "obsolete"
                else:
                    status = "regenerated"
            rows.append(
                {
                    "old_file": f.name,
                    "old_folder": str(f.parent.relative_to(REPO_ROOT)),
                    "status": status,
                    "replacement_figure": rep,
                    "reason": "Regenerated with unified report style in inre-final-report-package",
                }
            )
    df = pd.DataFrame(rows)
    df.to_csv(ctx.output_dir / "OLD_FIGURE_AUDIT.csv", index=False)
    return df


def write_report_asset_guide(ctx) -> None:
    main_figs = [r for r in ctx.figure_manifest if r.get("main_text_or_appendix") == "main"]
    main_tabs = [r for r in ctx.table_manifest if r.get("main_text_or_appendix") == "main"]
    text = """# INRE V4 Final Report Asset Guide

## MAIN TEXT — essential figures (recommended ≤10)

| Figure ID | Title | Section | Key message |
|-----------|-------|---------|-------------|
"""
    for r in main_figs[:12]:
        text += f"| {r['figure_id']} | {r['title']} | {r.get('report_section','')} | {r.get('key_message','')} |\n"

    text += """
## MAIN TEXT — essential tables (recommended ≤8)

| Table ID | Title | Section |
|----------|-------|---------|
"""
    for r in main_tabs:
        text += f"| {r['table_id']} | {r['title']} | {r.get('report_section','')} |\n"

    text += """
## APPENDIX — supporting assets

- Validation figures: APP_D_*, FIGURE_V1, FIGURE_G2–G3
- Full scenario table Z1 (longtable)
- Moderate/extreme profiles, stitch diagnostics
- Full PyPSA–GAMSPy reconciliation tables
- Nuclear sweep detail figures N2–N5

## Page-limit combinations

1. I1+I2 multi-panel (demand + capacity)
2. D1+D2 (envelope + Base/severe profiles)
3. R1+R4 (generation mix + consequences)
4. A2+A3 (cumulative EENS + headline adequacy)
5. N1+N3 (nuclear sweep generation + CO₂/OPEX)
"""
    (ctx.output_dir / "REPORT_ASSET_GUIDE.md").write_text(text)
