# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
INRE V4 reduced-form PyPSA–GAMSPy harmonisation (8 dispatch blocks).

Exports identical 8-variable copper-plate models for four severe scenarios,
solves with HiGHS, and compares adequacy, cost, and CO2 against PyPSA.

Usage::

    pixi run python scripts/inre/run_v4_pypsa_gamspy_validation.py
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pypsa
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GAMSPY_SRC = REPO_ROOT / "gamspy-de" / "src"
if str(GAMSPY_SRC) not in sys.path:
    sys.path.insert(0, str(GAMSPY_SRC))

from blocks import BLOCK_CARRIERS, DISPATCH_BLOCKS
from export_pypsa_rf import export_block_inputs_from_pypsa
from scripts.inre.audit_stylised_dunkelflaute_v4 import RENEWABLE_CARRIERS
from scripts.inre.run_v4_stage1 import VOLL, _co2_kt, _cost_breakdown, _gen_energy_by_carrier, _load_shed_metrics, _weight

logger = logging.getLogger(__name__)

OUTPUT_DIR = REPO_ROOT / "results/inre-comparison-v4-pypsa-gamspy"
GAMSPY_ROOT = REPO_ROOT / "gamspy-de"
GAMSPY_INPUTS_RF = GAMSPY_ROOT / "inputs_v4_rf"
SNAPSHOT_HOURS = 3.0
NUCLEAR_CARRIER = "nuclear-smr"

FIRM_THERMAL_CARRIERS = ["coal", "lignite", "CCGT", "OCGT", "oil", "biomass", "waste", "geothermal"]

SCENARIOS = {
    "severe-no-nuclear": {
        "gamspy": "v4-severe-no-nuclear",
        "pypsa_solved": REPO_ROOT / "results/inre-de-stylised-df-severe-v4/networks/base_s_10_elec_.nc",
        "pypsa_export": REPO_ROOT / "results/inre-de-stylised-df-severe-v4/networks/base_s_10_elec_.nc",
    },
    "severe-smr-4.5": {
        "gamspy": "v4-severe-smr-4.5",
        "pypsa_solved": REPO_ROOT / "results/inre-de-stylised-df-severe-smr-v4/networks/base_s_10_elec_.nc",
        "pypsa_export": REPO_ROOT / "results/inre-de-stylised-df-severe-smr-v4/networks/base_s_10_elec_.nc",
    },
    "severe-decarbonised-no-nuclear": {
        "gamspy": "v4-severe-decarbonised-no-nuclear",
        "pypsa_solved": REPO_ROOT / "results/inre-de-stylised-df-severe-decarb-v4/networks/base_s_10_elec_.nc",
        "pypsa_export": REPO_ROOT / "results/inre-de-stylised-df-severe-decarb-v4/networks/base_s_10_elec_.nc",
    },
    "severe-decarbonised-smr-4.5": {
        "gamspy": "v4-severe-decarbonised-smr-4.5",
        "pypsa_solved": REPO_ROOT
        / "results/inre-de-stylised-df-severe-decarb-smr-4.5-v4/networks/base_s_10_elec_.nc",
        "pypsa_export": REPO_ROOT
        / "results/inre-de-stylised-df-severe-decarb-smr-4.5-v4/networks/base_s_10_elec_.nc",
    },
}


def find_gamspy_python() -> str:
    env = os.environ.get("GAMSPY_PYTHON")
    if env and Path(env).exists():
        return env
    for candidate in ("/opt/anaconda3/bin/python", "python", "python3"):
        if shutil.which(candidate):
            try:
                subprocess.run([candidate, "-c", "import gamspy"], check=True, capture_output=True)
                return candidate
            except subprocess.CalledProcessError:
                continue
    raise RuntimeError("No Python with gamspy found.")


def pypsa_block_capacity(n: pypsa.Network, block: str) -> float:
    carriers = BLOCK_CARRIERS[block]
    gens = n.generators[n.generators.carrier.isin(carriers)]
    return float(gens.p_nom.sum()) if len(gens) else 0.0


def gamspy_block_capacity(scenario_gamspy: str, block: str) -> float:
    blocks_df = pd.read_csv(GAMSPY_INPUTS_RF / scenario_gamspy / "blocks.csv")
    scenario_yaml = yaml.safe_load((GAMSPY_ROOT / "scenarios" / f"{scenario_gamspy}.yaml").read_text())
    overrides = scenario_yaml.get("capacity_overrides", {}) or {}
    cap = float(blocks_df.loc[blocks_df["block"] == block, "installed_capacity_MW"].iloc[0])
    if block in overrides:
        cap = float(overrides[block])
    return cap


def build_capacity_harmonisation(scenario_key: str, cfg: dict) -> list[dict]:
    n = pypsa.Network(str(cfg["pypsa_export"]))
    rows = []
    for block in DISPATCH_BLOCKS:
        carriers = BLOCK_CARRIERS[block]
        p_cap = pypsa_block_capacity(n, block)
        g_cap = gamspy_block_capacity(cfg["gamspy"], block)
        diff = g_cap - p_cap
        if abs(diff) < 1.0:
            status = "matched"
        elif p_cap <= 0 and g_cap <= 0:
            status = "matched"
        else:
            status = "mismatch"
        rows.append(
            {
                "scenario": scenario_key,
                "block": block,
                "included_carriers": ",".join(carriers),
                "pypsa_mw": round(p_cap, 2),
                "gamspy_mw": round(g_cap, 2),
                "difference_mw": round(diff, 2),
                "status": status,
            }
        )
    return rows


def pypsa_kpis(network_path: Path) -> dict:
    n = pypsa.Network(str(network_path))
    snaps = pd.DatetimeIndex(n.snapshots)
    weight = _weight(n, snaps)
    demand_twh = float(n.loads_t.p_set.reindex(snaps).mul(weight, axis=0).sum().sum()) / 1e6
    gen_by = _gen_energy_by_carrier(n, snaps)
    eens_gwh, _, peak_ls_gw = _load_shed_metrics(n, snaps)
    var_opex, voll_cost, total_cost = _cost_breakdown(n, snaps)

    vre_twh = sum(float(gen_by.get(c, 0.0)) for c in RENEWABLE_CARRIERS)
    nuc_twh = float(gen_by.get(NUCLEAR_CARRIER, 0.0))
    firm_twh = sum(float(gen_by.get(c, 0.0)) for c in FIRM_THERMAL_CARRIERS)

    return {
        "demand_twh": demand_twh,
        "vre_generation_twh": vre_twh,
        "nuclear_generation_twh": nuc_twh,
        "firm_thermal_generation_twh": firm_twh,
        "eens_gwh": eens_gwh,
        "peak_load_shedding_gw": peak_ls_gw,
        "co2_mt": _co2_kt(n, snaps) / 1000.0,
        "variable_opex_excl_voll_meur": var_opex,
        "load_shedding_penalty_meur": voll_cost,
        "total_operational_cost_meur": total_cost,
    }


def gamspy_kpis(scenario_gamspy: str) -> dict:
    summary_path = GAMSPY_ROOT / "results_rf" / scenario_gamspy / "summary.yaml"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing GAMSPy results: {summary_path}")
    with open(summary_path) as f:
        return yaml.safe_load(f) or {}


def export_all_rf_inputs() -> None:
    for key, cfg in SCENARIOS.items():
        out_dir = GAMSPY_INPUTS_RF / cfg["gamspy"]
        logger.info("Exporting reduced-form inputs for %s -> %s", key, out_dir)
        export_block_inputs_from_pypsa(cfg["pypsa_export"], out_dir)


def run_gamspy_rf(python_exe: str) -> None:
    for key, cfg in SCENARIOS.items():
        logger.info("Running reduced-form GAMSPy scenario %s", cfg["gamspy"])
        result = subprocess.run(
            [python_exe, str(GAMSPY_ROOT / "src/run_rf.py"), "--scenario", cfg["gamspy"], "--root", str(GAMSPY_ROOT)],
            capture_output=True,
            text=True,
            cwd=str(GAMSPY_ROOT),
        )
        if result.returncode != 0:
            logger.error("GAMSPy stderr:\n%s", result.stderr)
            raise RuntimeError(f"GAMSPy failed for {cfg['gamspy']}: {result.stderr[-1200:]}")


def rel_pct(gamspy_val: float, pypsa_val: float) -> str:
    if abs(pypsa_val) < 1e-12:
        return "N/A"
    return f"{100.0 * (gamspy_val - pypsa_val) / pypsa_val:.2f}"


def decide_outcome(
    objective_rows: list[dict],
    capacity_rows: list[dict],
    comparison_rows: list[dict],
    adequacy_rows: list[dict],
    smr_rows: list[dict],
) -> str:
    if any(float(r.get("residual_percent", 0.0)) > 0.01 for r in objective_rows):
        return "GAMSPy aggregation remains inconsistent."

    mismatches = [r for r in capacity_rows if r["status"] == "mismatch" and (r["pypsa_mw"] > 1.0 or r["gamspy_mw"] > 1.0)]
    if mismatches:
        return "GAMSPy aggregation remains inconsistent."

    # Check no carrier removal between no-nuc and SMR decarb pair
    decarb_blocks = {r["block"]: r for r in capacity_rows if r["scenario"] == "severe-decarbonised-no-nuclear"}
    smr_blocks = {r["block"]: r for r in capacity_rows if r["scenario"] == "severe-decarbonised-smr-4.5"}
    for block in ("peaker", "other_firm", "ccgt"):
        if block in decarb_blocks and block in smr_blocks:
            if abs(decarb_blocks[block]["gamspy_mw"] - smr_blocks[block]["gamspy_mw"]) > 1.0:
                return "GAMSPy aggregation remains inconsistent."

    demand_bad = any(abs(float(r["demand_diff_pct"])) > 2.0 for r in comparison_rows if r["demand_diff_pct"] != "N/A")
    vre_bad = any(abs(float(r["vre_diff_pct"])) > 5.0 for r in comparison_rows if r["vre_diff_pct"] != "N/A")
    nuc_bad = any(abs(float(r["nuclear_diff_pct"])) > 5.0 for r in comparison_rows if r["nuclear_diff_pct"] != "N/A")
    eens_bad = any(
        abs(float(r["difference_percent"])) > 10.0 for r in adequacy_rows if r["difference_percent"] != "N/A"
    )

    pypsa_smr = next(r for r in smr_rows if r["model"] == "PyPSA")
    gamspy_smr = next(r for r in smr_rows if r["model"] == "GAMSPy")
    smr_sign_wrong = False
    if pypsa_smr["eens_without_smr_gwh"] > 0 and gamspy_smr["eens_without_smr_gwh"] > 0:
        pypsa_red = float(pypsa_smr["eens_reduction_percent"])
        gamspy_red = float(gamspy_smr["eens_reduction_percent"])
        if (pypsa_red > 5 and gamspy_red < 0) or abs(gamspy_red - pypsa_red) > 25:
            smr_sign_wrong = True

    if demand_bad or vre_bad or nuc_bad or eens_bad or smr_sign_wrong:
        return "Reduced-form GAMSPy model is suitable only for qualitative validation."

    return "Reduced-form GAMSPy model reproduces the main PyPSA adequacy mechanism."


def print_report(
    capacity_rows: list[dict],
    objective_rows: list[dict],
    adequacy_rows: list[dict],
    smr_rows: list[dict],
    co2_rows: list[dict],
    comparison_rows: list[dict],
    decision: str,
) -> None:
    print("\nCAPACITY HARMONISATION\n")
    print("Block | Included carriers | PyPSA MW | GAMSPy MW | Status")
    ref = "severe-decarbonised-no-nuclear"
    for r in capacity_rows:
        if r["scenario"] != ref:
            continue
        print(
            f"{r['block']} | {r['included_carriers']} | {r['pypsa_mw']:.1f} | "
            f"{r['gamspy_mw']:.1f} | {r['status']}"
        )

    print("\nOBJECTIVE RECONCILIATION\n")
    print("Scenario | Objective | Generation cost | VOLL cost | Residual %")
    for r in objective_rows:
        print(
            f"{r['scenario']} | {r['solver_objective_eur']:.2f} | {r['generation_cost_eur']:.2f} | "
            f"{r['voll_cost_eur']:.2f} | {r['residual_percent']:.6f}"
        )

    print("\nADEQUACY COMPARISON\n")
    print("Scenario | PyPSA EENS GWh | GAMSPy EENS GWh | Difference %")
    for r in adequacy_rows:
        print(f"{r['scenario']} | {r['pypsa_eens_gwh']:.2f} | {r['gamspy_eens_gwh']:.2f} | {r['difference_percent']}")

    print("\nSMR BENEFIT\n")
    print("Model | No-nuclear EENS | SMR EENS | EENS reduction %")
    for r in smr_rows:
        print(
            f"{r['model']} | {r['eens_without_smr_gwh']:.2f} | {r['eens_with_smr_gwh']:.2f} | "
            f"{r['eens_reduction_percent']}"
        )

    print("\nCO2 COMPARISON\n")
    print("Scenario | PyPSA Mt | GAMSPy Mt | Difference %")
    for r in co2_rows:
        print(f"{r['scenario']} | {r['pypsa_mt']:.4f} | {r['gamspy_mt']:.4f} | {r['difference_percent']}")

    print("\nADEQUACY DETAIL (selected KPIs)\n")
    print("Scenario | Demand % | VRE % | Nuclear % | Firm thermal % | Peak LS GW diff")
    for r in comparison_rows:
        print(
            f"{r['scenario']} | {r['demand_diff_pct']} | {r['vre_diff_pct']} | {r['nuclear_diff_pct']} | "
            f"{r['firm_thermal_diff_pct']} | {r['peak_ls_diff_gw']:.3f}"
        )

    print("\nCO2 LIMITATION\n")
    print(
        "Aggregated peaker (OCGT+oil) and other_firm (biomass+waste+geothermal) blocks use "
        "capacity-weighted electrical-output CO2 coefficients; dispatch mix within blocks is not resolved."
    )

    print("\nDECISION\n")
    print(decision)


def main() -> None:
    parser = argparse.ArgumentParser(description="INRE V4 reduced-form PyPSA–GAMSPy validation")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--skip-gamspy", action="store_true")
    parser.add_argument("--gamspy-python", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.skip_export:
        export_all_rf_inputs()

    if not args.skip_gamspy:
        python_exe = args.gamspy_python or find_gamspy_python()
        logger.info("Using GAMSPy Python: %s", python_exe)
        run_gamspy_rf(python_exe)

    objective_rows = []
    adequacy_rows = []
    co2_rows = []
    comparison_rows = []
    capacity_rows = []

    for key, cfg in SCENARIOS.items():
        p = pypsa_kpis(cfg["pypsa_solved"])
        g = gamspy_kpis(cfg["gamspy"])
        capacity_rows.extend(build_capacity_harmonisation(key, cfg))

        objective_rows.append(
            {
                "scenario": key,
                "solver_objective_eur": g.get("solver_objective_eur", g.get("objective")),
                "generation_cost_eur": g.get("variable_opex_excl_voll_meur", 0.0) * 1e6,
                "voll_cost_eur": g.get("load_shedding_penalty_meur", 0.0) * 1e6,
                "residual_percent": g.get("objective_residual_percent", 0.0),
            }
        )
        adequacy_rows.append(
            {
                "scenario": key,
                "pypsa_eens_gwh": p["eens_gwh"],
                "gamspy_eens_gwh": g["eens_gwh"],
                "difference_percent": rel_pct(g["eens_gwh"], p["eens_gwh"]),
            }
        )
        co2_rows.append(
            {
                "scenario": key,
                "pypsa_mt": p["co2_mt"],
                "gamspy_mt": g["co2_mt"],
                "difference_percent": rel_pct(g["co2_mt"], p["co2_mt"]),
            }
        )
        comparison_rows.append(
            {
                "scenario": key,
                "pypsa_demand_twh": p["demand_twh"],
                "gamspy_demand_twh": g["demand_twh"],
                "demand_diff_pct": rel_pct(g["demand_twh"], p["demand_twh"]),
                "pypsa_vre_twh": p["vre_generation_twh"],
                "gamspy_vre_twh": g["vre_generation_twh"],
                "vre_diff_pct": rel_pct(g["vre_generation_twh"], p["vre_generation_twh"]),
                "pypsa_nuclear_twh": p["nuclear_generation_twh"],
                "gamspy_nuclear_twh": g["nuclear_generation_twh"],
                "nuclear_diff_pct": rel_pct(g["nuclear_generation_twh"], p["nuclear_generation_twh"]),
                "pypsa_firm_thermal_twh": p["firm_thermal_generation_twh"],
                "gamspy_firm_thermal_twh": g["firm_thermal_generation_twh"],
                "firm_thermal_diff_pct": rel_pct(g["firm_thermal_generation_twh"], p["firm_thermal_generation_twh"]),
                "pypsa_peak_ls_gw": p["peak_load_shedding_gw"],
                "gamspy_peak_ls_gw": g["peak_load_shedding_gw"],
                "peak_ls_diff_gw": g["peak_load_shedding_gw"] - p["peak_load_shedding_gw"],
                "pypsa_opex_meur": p["total_operational_cost_meur"],
                "gamspy_opex_meur": g["total_operational_cost_meur"],
                "opex_diff_pct": rel_pct(g["total_operational_cost_meur"], p["total_operational_cost_meur"]),
            }
        )

    smr_rows = []
    for model, no_key, smr_key in [
        ("PyPSA", "severe-decarbonised-no-nuclear", "severe-decarbonised-smr-4.5"),
        ("GAMSPy", "severe-decarbonised-no-nuclear", "severe-decarbonised-smr-4.5"),
    ]:
        if model == "PyPSA":
            e0 = pypsa_kpis(SCENARIOS[no_key]["pypsa_solved"])["eens_gwh"]
            e1 = pypsa_kpis(SCENARIOS[smr_key]["pypsa_solved"])["eens_gwh"]
        else:
            e0 = gamspy_kpis(SCENARIOS[no_key]["gamspy"])["eens_gwh"]
            e1 = gamspy_kpis(SCENARIOS[smr_key]["gamspy"])["eens_gwh"]
        reduction = 100.0 * (e0 - e1) / e0 if e0 > 0 else float("nan")
        smr_rows.append(
            {
                "model": model,
                "eens_without_smr_gwh": e0,
                "eens_with_smr_gwh": e1,
                "eens_reduction_percent": f"{reduction:.1f}" if e0 > 0 else "N/A",
            }
        )

    decision = decide_outcome(objective_rows, capacity_rows, comparison_rows, adequacy_rows, smr_rows)

    pd.DataFrame(capacity_rows).to_csv(OUTPUT_DIR / "capacity_harmonisation.csv", index=False)
    pd.DataFrame(objective_rows).to_csv(OUTPUT_DIR / "objective_reconciliation.csv", index=False)
    pd.DataFrame(adequacy_rows).to_csv(OUTPUT_DIR / "adequacy_comparison.csv", index=False)
    pd.DataFrame(smr_rows).to_csv(OUTPUT_DIR / "smr_benefit.csv", index=False)
    pd.DataFrame(co2_rows).to_csv(OUTPUT_DIR / "co2_comparison.csv", index=False)
    pd.DataFrame(comparison_rows).to_csv(OUTPUT_DIR / "kpi_comparison.csv", index=False)

    for key, cfg in SCENARIOS.items():
        src = GAMSPY_INPUTS_RF / cfg["gamspy"] / "block_validation.csv"
        dst = OUTPUT_DIR / f"block_validation_{key}.csv"
        if src.exists():
            shutil.copy(src, dst)

    print_report(capacity_rows, objective_rows, adequacy_rows, smr_rows, co2_rows, comparison_rows, decision)
    logger.info("Exported results to %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
