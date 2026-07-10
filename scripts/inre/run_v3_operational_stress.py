# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Re-solve v3 operational stress scenarios from an existing solved base network.

Applies v3 INRE corrections (fixed capacities, frozen transmission, historical CF
profiles, CO2 patch) without requiring a full Snakemake rebuild when resources/ is absent.

Usage::

    python scripts/inre/run_v3_operational_stress.py --all
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pypsa

from scripts.inre.apply_historical_dunkelflaute import apply_historical_dunkelflaute, load_params
from scripts.inre.freeze_transmission import freeze_transmission
from scripts.inre.resolve_fixedcap import _fix_component_capacity


def _patch_co2_emissions_for_thermal(n: pypsa.Network) -> None:
    thermal = {"CCGT", "OCGT", "coal", "lignite", "oil"}
    for carrier in thermal:
        if carrier not in n.carriers.index:
            continue
        gens = n.generators.query("carrier == @carrier")
        if gens.empty:
            continue
        eff = float(gens.efficiency.iloc[0])
        if eff <= 0:
            continue
        raw = float(n.carriers.at[carrier, "co2_emissions"])
        n.carriers.at[carrier, "co2_emissions"] = raw / eff

logger = logging.getLogger(__name__)

V3_SCENARIOS = {
    "matched-reference": ("inre-de-matched-reference", "data/inre/dunkelflaute.matched-reference.yaml"),
    "historical-severe": ("inre-de-historical-severe", "data/inre/dunkelflaute.historical.yaml"),
    "extreme-stress-sensitivity": (
        "inre-de-extreme-stress",
        "data/inre/dunkelflaute.extreme-sensitivity.yaml",
    ),
}


def _freeze_all_capacities(n: pypsa.Network) -> None:
    _fix_component_capacity(n, fix_generator_carriers=set(n.generators.carrier.unique()), fix_all_components=True)


def _disable_expansion(n: pypsa.Network) -> None:
    if len(n.generators):
        n.generators["p_nom_extendable"] = False
    if hasattr(n, "storage_units") and len(n.storage_units):
        n.storage_units["p_nom_extendable"] = False
        if "e_nom_extendable" in n.storage_units.columns:
            n.storage_units["e_nom_extendable"] = False
    if hasattr(n, "links") and len(n.links):
        n.links["p_nom_extendable"] = False
    if hasattr(n, "stores") and len(n.stores):
        n.stores["e_nom_extendable"] = False


def _enable_load_shedding(n: pypsa.Network, voll: float = 100_000.0) -> None:
    if "load_shed" not in n.carriers.index:
        n.add("Carrier", "load_shed", co2_emissions=0.0)
    for bus in n.buses.index:
        name = f"load_shed_{bus}"
        if name in n.generators.index:
            continue
        n.add(
            "Generator",
            name,
            bus=bus,
            carrier="load_shed",
            p_nom=1e6,
            p_nom_extendable=False,
            marginal_cost=voll,
        )


def run_scenario(
    base_network: Path,
    scenario_name: str,
    config_path: str,
    output_path: Path,
) -> None:
    n = pypsa.Network(base_network)
    _freeze_all_capacities(n)
    _disable_expansion(n)
    freeze_transmission(n)
    _enable_load_shedding(n)
    _patch_co2_emissions_for_thermal(n)

    params = load_params(REPO_ROOT / config_path)
    params["enabled"] = True
    if "matched" in scenario_name:
        params["mode"] = "matched_reference"
    elif "extreme" in scenario_name:
        params["mode"] = "extreme_sensitivity"
    else:
        params["mode"] = "historical"

    apply_historical_dunkelflaute(n, params=params, config_path=REPO_ROOT / config_path)

    logger.info("Solving %s ...", scenario_name)
    n.optimize(solver_name="highs")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(output_path)
    logger.info("Wrote %s (objective=%.2e)", output_path, n.objective)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run v3 operational stress re-solves")
    parser.add_argument(
        "--base-network",
        default="results/base/networks/base_s_10_elec_.nc",
    )
    parser.add_argument(
        "--scenario",
        choices=[*V3_SCENARIOS.keys(), "all"],
        default="all",
    )
    parser.add_argument("--output-root", default="results")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    base = REPO_ROOT / args.base_network
    if not base.exists():
        raise SystemExit(f"Base network not found: {base}")

    scenarios = (
        V3_SCENARIOS
        if args.scenario == "all"
        else {args.scenario: V3_SCENARIOS[args.scenario]}
    )
    for name, (run_name, cfg) in scenarios.items():
        out = REPO_ROOT / args.output_root / run_name / "networks" / "base_s_10_elec_.nc"
        run_scenario(base, name, cfg, out)


if __name__ == "__main__":
    main()
