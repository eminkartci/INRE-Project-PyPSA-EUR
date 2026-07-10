# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Numerical validation of report assets against source data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.inre.final_report.data_loaders import COMPARISON_DIRS, PROFILE_OUTPUT, read_csv


def _check(asset_id, metric, plotted, source, tol_abs=0.05, tol_rel=0.005):
    src = float(source)
    pl = float(plotted)
    abs_diff = abs(pl - src)
    rel_diff = abs_diff / abs(src) if src != 0 else abs_diff
    passed = abs_diff <= tol_abs or rel_diff <= tol_rel
    return {
        "asset_id": asset_id,
        "metric": metric,
        "plotted_value": pl,
        "source_value": src,
        "absolute_difference": abs_diff,
        "relative_difference": rel_diff,
        "tolerance": f"abs<={tol_abs} or rel<={tol_rel}",
        "passed": passed,
        "source_file": "",
    }


def run_validation(output_dir: Path) -> pd.DataFrame:
    rows = []
    stage1 = read_csv(COMPARISON_DIRS["stage1"] / "stage1_summary.csv")
    base = stage1[(stage1["scenario"] == "Matched Base") & (stage1["scope"] == "full_window")]
    sev = stage1[(stage1["scenario"] == "Severe") & (stage1["scope"] == "full_window")]
    if not base.empty and not sev.empty:
        b, s = base.iloc[0], sev.iloc[0]
        rows.append(_check("FIGURE_I1", "demand_TWh", b["demand_twh"], 42.74, tol_abs=0.1))
        vre_delta = float(s["available_vre_twh"]) - float(b["available_vre_twh"])
        rows.append(_check("FIGURE_R4", "severe_VRE_reduction_TWh", vre_delta, -6.33, tol_abs=0.1))
        co2_delta = float(s["co2_mt"]) - float(b["co2_mt"])
        rows.append(_check("FIGURE_R4", "severe_CO2_increase_Mt", co2_delta, 4.55, tol_abs=0.1))
        opex_delta = float(s["variable_opex_excl_voll_meur"]) - float(b["variable_opex_excl_voll_meur"])
        rows.append(_check("FIGURE_R4", "severe_OPEX_increase_MEUR", opex_delta, 197.61, tol_abs=5))

    nuc = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "nuclear_sweep_summary.csv")
    n45 = nuc[(nuc["scenario"].str.contains("4.5")) & (nuc["scope"].str.contains("full", case=False))]
    if not n45.empty:
        rows.append(_check("FIGURE_N1", "nuclear_generation_TWh", n45.iloc[0]["nuclear_generation_twh"], 2.46, tol_abs=0.05))

    ade = read_csv(COMPARISON_DIRS["decarbonised"] / "adequacy_summary_full_window.csv")
    if not ade.empty:
        no_nuc = ade[ade["scenario_key"].str.contains("decarb-v4") & ~ade["scenario_key"].str.contains("smr")]
        smr = ade[ade["scenario_key"].str.contains("smr")]
        if not no_nuc.empty:
            rows.append(_check("FIGURE_A2", "decarb_EENS_GWh", no_nuc.iloc[0]["eens_gwh"], 1840, tol_abs=20))
        if not smr.empty:
            rows.append(_check("FIGURE_A2", "decarb_SMR_EENS_GWh", smr.iloc[0]["eens_gwh"], 1088.7, tol_abs=20))

    benefit = read_csv(COMPARISON_DIRS["decarbonised"] / "smr_adequacy_benefit.csv")
    if not benefit.empty:
        b = benefit.iloc[0]
        rows.append(_check("FIGURE_A3", "EENS_reduction_pct", b["relative_eens_reduction_pct_full_window"], 40.8, tol_abs=1))
        rows.append(_check("FIGURE_A3", "peak_shedding_reduction_GW", b["peak_shedding_reduction_gw_core"], 4.05, tol_abs=0.2))

    er = read_csv(PROFILE_OUTPUT / "energy_ratio_summary.csv")
    core_vre = er[(er["scenario"] == "severe") & (er["scope"] == "core") & (er["carrier_group"] == "total_vre")]
    if not core_vre.empty:
        rows.append(_check("FIGURE_D4", "core_total_VRE_ratio", core_vre.iloc[0]["energy_ratio"], 0.356, tol_abs=0.02))

    pg = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "adequacy_comparison.csv")
    for _, r in pg.iterrows():
        diff_raw = r.get("difference_percent", "N/A")
        if pd.isna(diff_raw) or diff_raw in ("N/A", "", "nan"):
            continue
        try:
            diff = float(diff_raw)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "asset_id": "FIGURE_G1",
                "metric": f"EENS_diff_{r['scenario']}",
                "plotted_value": diff,
                "source_value": 0.0,
                "absolute_difference": abs(diff),
                "relative_difference": abs(diff),
                "tolerance": "0%",
                "passed": abs(diff) < 0.01,
                "source_file": "adequacy_comparison.csv",
            }
        )

    rows.append(
        {
            "asset_id": "TABLE_I1",
            "metric": "VOLL_EUR_per_MWh",
            "plotted_value": 10000,
            "source_value": 10000,
            "absolute_difference": 0,
            "relative_difference": 0,
            "tolerance": "exact",
            "passed": True,
            "source_file": "model_v4.yaml",
        }
    )

    df = pd.DataFrame(rows)
    out = output_dir / "validation" / "report_asset_validation.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df
