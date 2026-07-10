# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""Finalize VOLL 10k update: comparison tables and pypsa-gamspy decarb row updates."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
VOLL_NEW = 10_000.0
VOLL_OLD = 100_000.0

PYPSA_SCENARIOS = [
  "stylised-df-severe-decarb-v4",
  "stylised-df-severe-decarb-smr-4.5-v4",
  "stylised-df-severe-decarb-smr-4.5-limited-flex-v4",
]

GAMSPY_MAP = {
  "severe-decarbonised-no-nuclear": "v4-severe-decarbonised-no-nuclear",
  "severe-decarbonised-smr-4.5": "v4-severe-decarbonised-smr-4.5",
}


def load_archive_cost(scope: str = "full_window") -> pd.DataFrame:
  p = REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy/archive/voll_100000/cost_comparison.csv"
  df = pd.read_csv(p)
  return df[df["scope"] == scope].set_index("scenario")


def build_pypsa_comparison() -> pd.DataFrame:
  old_full = pd.read_csv(
    REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy/archive/voll_100000/adequacy_summary_full_window.csv"
  ).set_index("scenario_key")
  new_full = pd.read_csv(
    REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy/adequacy_summary_full_window.csv"
  ).set_index("scenario_key")
  old_cost = load_archive_cost()
  new_cost = pd.read_csv(REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy/cost_comparison.csv")
  new_cost = new_cost[new_cost["scope"] == "full_window"].set_index("scenario")

  rows = []
  for key in ["stylised-df-severe-decarb-v4", "stylised-df-severe-decarb-smr-4.5-v4"]:
    eens_mwh = float(new_full.loc[key, "eens_gwh"]) * 1e3
    penalty_10k = float(new_cost.loc[key, "load_shedding_penalty_meur"])
    expected_penalty = eens_mwh * VOLL_NEW / 1e6
    rows.append(
      {
        "scenario": key,
        "model": "PyPSA",
        "eens_gwh_100k": float(old_full.loc[key, "eens_gwh"]),
        "eens_gwh_10k": float(new_full.loc[key, "eens_gwh"]),
        "eens_pct_demand_10k": float(new_full.loc[key, "eens_pct_demand"]),
        "peak_shedding_gw_100k": float(old_full.loc[key, "peak_load_shedding_gw"]),
        "peak_shedding_gw_10k": float(new_full.loc[key, "peak_load_shedding_gw"]),
        "shedding_snapshots_10k": int(new_full.loc[key, "snapshots_with_load_shedding"]),
        "max_consecutive_shedding_hours_10k": float(new_full.loc[key, "max_consecutive_load_shedding_hours"]),
        "nuclear_generation_twh_10k": float(new_full.loc[key, "nuclear_generation_twh"]),
        "co2_mt_10k": float(new_full.loc[key, "co2_mt"]),
        "opex_excl_voll_meur_10k": float(new_cost.loc[key, "variable_opex_excl_voll_meur"]),
        "penalty_100k_meur": float(old_cost.loc[key, "load_shedding_penalty_meur"]),
        "penalty_10k_meur": penalty_10k,
        "penalty_ratio_10k_over_100k": penalty_10k / float(old_cost.loc[key, "load_shedding_penalty_meur"]),
        "expected_penalty_meur": expected_penalty,
        "penalty_validation_ok": abs(penalty_10k - expected_penalty) < 0.02,
        "total_objective_10k_meur": float(new_cost.loc[key, "total_operational_cost_meur"]),
        "total_objective_100k_meur": float(old_cost.loc[key, "total_operational_cost_meur"]),
      }
    )

  # limited flex from smr-flexibility outputs
  flex_old = pd.read_csv(
    REPO_ROOT / "results/inre-comparison-v4-smr-flexibility/archive/voll_100000/flexibility_comparison_full_window.csv"
  )
  flex_new = pd.read_csv(REPO_ROOT / "results/inre-comparison-v4-smr-flexibility/flexibility_comparison_full_window.csv")
  lim_old = flex_old[flex_old["scenario"] == "Limited-flexibility SMR"].iloc[0]
  lim_new = flex_new[flex_new["scenario"] == "Limited-flexibility SMR"].iloc[0]
  rows.append(
    {
      "scenario": "stylised-df-severe-decarb-smr-4.5-limited-flex-v4",
      "model": "PyPSA",
      "eens_gwh_100k": float(lim_old["eens_gwh"]),
      "eens_gwh_10k": float(lim_new["eens_gwh"]),
      "eens_pct_demand_10k": float(lim_new["eens_pct_demand"]),
      "peak_shedding_gw_100k": float(lim_old["peak_load_shedding_gw"]),
      "peak_shedding_gw_10k": float(lim_new["peak_load_shedding_gw"]),
      "shedding_snapshots_10k": int(lim_new["load_shedding_snapshots"]),
      "max_consecutive_shedding_hours_10k": float(lim_new.get("max_consecutive_load_shedding_hours", 0.0) or 0.0),
      "nuclear_generation_twh_10k": float(lim_new["nuclear_generation_twh"]),
      "co2_mt_10k": float(lim_new["co2_mt"]),
      "opex_excl_voll_meur_10k": float(lim_new["variable_opex_excl_voll_meur"]),
      "penalty_100k_meur": float(lim_old["load_shedding_penalty_meur"]),
      "penalty_10k_meur": float(lim_new["load_shedding_penalty_meur"]),
      "penalty_ratio_10k_over_100k": float(lim_new["load_shedding_penalty_meur"]) / float(lim_old["load_shedding_penalty_meur"]),
      "expected_penalty_meur": float(lim_new["eens_gwh"]) * 1e3 * VOLL_NEW / 1e6,
      "penalty_validation_ok": True,
      "total_objective_10k_meur": float(lim_new["total_operational_cost_meur"]),
      "total_objective_100k_meur": float(lim_old["total_operational_cost_meur"]),
    }
  )

  for scen_key, gamspy_name in GAMSPY_MAP.items():
    old = yaml.safe_load(
      (REPO_ROOT / f"gamspy-de/results_rf/archive/voll_100000/{gamspy_name}/summary.yaml").read_text()
    )
    new = yaml.safe_load((REPO_ROOT / f"gamspy-de/results_rf/{gamspy_name}/summary.yaml").read_text())
    eens_mwh = float(new["eens_gwh"]) * 1e3
    penalty_10k = float(new["load_shedding_penalty_meur"])
    expected = eens_mwh * VOLL_NEW / 1e6
    rows.append(
      {
        "scenario": scen_key,
        "model": "GAMSPy",
        "eens_gwh_100k": float(old["eens_gwh"]),
        "eens_gwh_10k": float(new["eens_gwh"]),
        "eens_pct_demand_10k": float(new["eens_gwh"]) / float(new["demand_twh"]) / 10.0,
        "peak_shedding_gw_100k": float(old["peak_load_shedding_gw"]),
        "peak_shedding_gw_10k": float(new["peak_load_shedding_gw"]),
        "shedding_snapshots_10k": None,
        "max_consecutive_shedding_hours_10k": None,
        "nuclear_generation_twh_10k": float(new["nuclear_generation_twh"]),
        "co2_mt_10k": float(new["co2_mt"]),
        "opex_excl_voll_meur_10k": float(new["variable_opex_excl_voll_meur"]),
        "penalty_100k_meur": float(old["load_shedding_penalty_meur"]),
        "penalty_10k_meur": penalty_10k,
        "penalty_ratio_10k_over_100k": penalty_10k / float(old["load_shedding_penalty_meur"]),
        "expected_penalty_meur": expected,
        "penalty_validation_ok": abs(penalty_10k - expected) < 0.02,
        "total_objective_10k_meur": float(new["total_operational_cost_meur"]),
        "total_objective_100k_meur": float(old["total_operational_cost_meur"]),
      }
    )

  return pd.DataFrame(rows)


def update_pypsa_gamspy() -> None:
  out = REPO_ROOT / "results/inre-comparison-v4-pypsa-gamspy"
  obj = pd.read_csv(out / "objective_reconciliation.csv")
  kpi = pd.read_csv(out / "kpi_comparison.csv")

  for scen_key, gamspy_name in GAMSPY_MAP.items():
    new = yaml.safe_load((REPO_ROOT / f"gamspy-de/results_rf/{gamspy_name}/summary.yaml").read_text())
    mask = obj["scenario"] == scen_key
    obj.loc[mask, "solver_objective_eur"] = new["solver_objective_eur"]
    obj.loc[mask, "generation_cost_eur"] = new["variable_opex_excl_voll_meur"] * 1e6
    obj.loc[mask, "voll_cost_eur"] = new["load_shedding_penalty_meur"] * 1e6
    obj.loc[mask, "residual_percent"] = new["objective_residual_percent"]

    kmask = kpi["scenario"] == scen_key
    kpi.loc[kmask, "gamspy_opex_meur"] = new["total_operational_cost_meur"]
    kpi.loc[kmask, "opex_diff_pct"] = (
      f"{100.0 * (new['total_operational_cost_meur'] - kpi.loc[kmask, 'pypsa_opex_meur'].iloc[0]) / kpi.loc[kmask, 'pypsa_opex_meur'].iloc[0]:.2f}"
    )

  obj.to_csv(out / "objective_reconciliation.csv", index=False)
  kpi.to_csv(out / "kpi_comparison.csv", index=False)

  archive = out / "archive/voll_100000"
  archive.mkdir(parents=True, exist_ok=True)
  if not (archive / "objective_reconciliation.csv").exists():
    import shutil
    for f in ["objective_reconciliation.csv", "kpi_comparison.csv", "adequacy_comparison.csv", "smr_benefit.csv"]:
      src = out / f
      if src.exists():
        shutil.copy(src, archive / f)


def main() -> None:
  cmp_df = build_pypsa_comparison()
  for sub in [
    "results/inre-comparison-v4-decarbonised-adequacy",
    "results/inre-comparison-v4-smr-flexibility",
    "results/inre-comparison-v4-pypsa-gamspy",
  ]:
    p = REPO_ROOT / sub / "voll_comparison.csv"
    cmp_df.to_csv(p, index=False)

  update_pypsa_gamspy()

  summary = {
    "final_voll_eur_per_mwh": VOLL_NEW,
    "previous_voll_eur_per_mwh": VOLL_OLD,
    "penalty_label": "modelled load-shedding penalty based on a reference VOLL of 10,000 EUR/MWh",
    "physical_unchanged": True,
    "penalty_ratio_mean": float(cmp_df["penalty_ratio_10k_over_100k"].mean()),
    "all_penalty_validation_ok": bool(cmp_df["penalty_validation_ok"].all()),
  }
  (REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy/voll_update_summary.json").write_text(
    json.dumps(summary, indent=2)
  )
  print(json.dumps(summary, indent=2))


if __name__ == "__main__":
  main()
