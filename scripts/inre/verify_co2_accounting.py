# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Verify CO2 emission accounting units across PyPSA-Eur INRE stack.

Physical check (CCGT, eta=0.6, e_gas=0.198 t/MWh_fuel):
    1 MWh_el -> 1/0.6 MWh_fuel -> 0.33 tCO2/MWh_el expected at electrical output.

Run from repository root::

    python scripts/inre/verify_co2_accounting.py
    python scripts/inre/verify_co2_accounting.py --network results/base/networks/base_s_10_elec_.nc
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_processed_costs(path: Path) -> pd.Series:
    df = pd.read_csv(path, index_col=0)
    return df


def physical_check_ccgt(costs: pd.DataFrame) -> dict:
    eta = float(costs.loc["CCGT", "efficiency"])
    e_gas = float(costs.loc["gas", "CO2 intensity"])
    e_ccgt_carrier = float(costs.loc["CCGT", "CO2 intensity"])
    expected_el = e_gas / eta
    return {
        "ccgt_efficiency": eta,
        "gas_co2_intensity_t_per_MWh_fuel": e_gas,
        "ccgt_co2_intensity_in_costs_t_per_MWh": e_ccgt_carrier,
        "expected_tCO2_per_MWh_el_if_fuel_based": expected_el,
        "costs_assign_gas_intensity_to_ccgt_unchanged": abs(e_ccgt_carrier - e_gas) < 1e-9,
    }


def network_co2_checks(n: pypsa.Network) -> dict:
    gens = n.generators.query("carrier == 'CCGT'")
    if gens.empty:
        return {"warning": "No CCGT generators in network"}

    carrier_co2 = float(n.carriers.at["CCGT", "co2_emissions"])
    eff = float(gens.efficiency.iloc[0])

    # PyPSA GlobalConstraint uses carrier co2_emissions × electrical output p (MW)
    # Post-processing in compare_scenarios uses the same (no /efficiency).
    fuel_per_mwh_el = 1.0 / eff
    implied_if_carrier_is_fuel_intensity = carrier_co2 * fuel_per_mwh_el

    weight = n.snapshot_weightings.objective.reindex(n.snapshots).fillna(1.0)
    gen = gens.index[0]
    one_hour_idx = n.snapshots[:1]
    p_set = 1000.0  # 1 GW for one snapshot

    # Build minimal emission tally matching compare_scenarios._co2_emissions_t
    postprocess_tco2 = carrier_co2 * p_set * float(weight.iloc[0]) / 1e6

    return {
        "carrier_co2_emissions": carrier_co2,
        "generator_efficiency": eff,
        "implied_tCO2_per_MWh_el_if_carrier_is_fuel_based": implied_if_carrier_is_fuel_intensity,
        "postprocess_tco2_for_1GWh_el_snapshot": postprocess_tco2,
        "global_constraint_type": (
            n.global_constraints.loc["CO2Limit", "type"]
            if "CO2Limit" in n.global_constraints.index
            else None
        ),
        "global_constraint_constant": (
            float(n.global_constraints.loc["CO2Limit", "constant"])
            if "CO2Limit" in n.global_constraints.index
            else None
        ),
    }


def gamspy_check() -> dict:
    tech_path = REPO_ROOT / "gamspy-de/inputs/technologies.csv"
    if not tech_path.exists():
        return {"warning": "GAMSPy technologies.csv not found"}
    tech = pd.read_csv(tech_path)
    ccgt = tech.query("tech == 'ccgt'").iloc[0]
    return {
        "gamspy_ccgt_co2_t_per_MWh": float(ccgt["co2_t_per_MWh"]),
        "gamspy_ccgt_efficiency_not_stored": "efficiency not in technologies.csv",
        "note": "PyPSA processed CCGT CO2 intensity is 0.198 (gas); GAMSPy uses 0.25",
    }


def summarise(checks: dict) -> str:
    phys = checks["physical"]
    lines = [
        "CO2 accounting verification summary",
        "================================",
        f"CCGT efficiency: {phys['ccgt_efficiency']}",
        f"Gas CO2 intensity (costs): {phys['gas_co2_intensity_t_per_MWh_fuel']} t/MWh_fuel",
        f"CCGT CO2 intensity (costs): {phys['ccgt_co2_intensity_in_costs_t_per_MWh']} t/MWh",
        f"Expected if fuel-based ÷ eta: {phys['expected_tCO2_per_MWh_el_if_fuel_based']:.4f} t/MWh_el",
        "",
    ]
    if "carrier_co2_emissions" in checks.get("network", {}):
        net = checks["network"]
        lines.extend(
            [
                f"Network carrier co2_emissions: {net['carrier_co2_emissions']}",
                f"Implied tCO2/MWh_el (if fuel-based): "
                f"{net['implied_tCO2_per_MWh_el_if_carrier_is_fuel_based']:.4f}",
                f"GlobalConstraint CO2Limit constant: {net.get('global_constraint_constant')}",
            ]
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "- PyPSA-Eur assigns gas CO2 intensity directly to CCGT carrier (fuel MWh basis).",
            "- PyPSA GlobalConstraint and compare_scenarios multiply by electrical output p.",
            "- If carrier value is fuel-based, emissions are UNDERCOUNTED by factor eta.",
            "- Do not classify CO2 cap as binding/non-binding until corrected and re-solved.",
            "- GAMSPy CCGT co2_t_per_MWh differs from PyPSA; align after verification.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify INRE CO2 accounting units")
    parser.add_argument(
        "--costs",
        default="results/dunkelflaute-smr/costs/costs_2050_processed.csv",
        help="Processed costs CSV",
    )
    parser.add_argument(
        "--network",
        default="results/base/networks/base_s_10_elec_.nc",
        help="Solved or prepared network for carrier checks",
    )
    parser.add_argument(
        "--output",
        default="results/inre-comparison-v3/co2_verification.json",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    costs_path = REPO_ROOT / args.costs
    costs = _load_processed_costs(costs_path)

    checks: dict = {"physical": physical_check_ccgt(costs), "gamspy": gamspy_check()}

    net_path = REPO_ROOT / args.network
    if net_path.exists():
        n = pypsa.Network(net_path)
        checks["network"] = network_co2_checks(n)
    else:
        checks["network"] = {"warning": f"Network not found: {net_path}"}

    out_path = REPO_ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(checks, indent=2))
    print(summarise(checks))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
