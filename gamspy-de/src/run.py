#!/usr/bin/env python3
"""Run Germany GAMSPy scenarios."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from apply_scenario import load_and_prepare
from build_model import build_model
from export_results import export_results

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCENARIO_CORE = [
    "base",
    "dunkelflaute",
    "dunkelflaute-smr",
    "dunkelflaute-msr",
    "dunkelflaute-lfr",
]

SCENARIO_CAPEX = [
    "dunkelflaute-smr-capex70",
    "dunkelflaute-smr-capex85",
    "dunkelflaute-smr-capex115",
]

SCENARIOS = SCENARIO_CORE + SCENARIO_CAPEX


def run_scenario(scenario_name: str, root: Path) -> dict:
    logger.info("Preparing scenario: %s", scenario_name)
    data = load_and_prepare(root, scenario_name)

    logger.info("Building GAMSPy model (%d buses, %d snapshots)", len(data.buses), len(data.times))
    built = build_model(data)

    solver = data.config.get("solver", "highs")
    logger.info("Solving with %s ...", solver)
    summary = built.model.solve(solver=solver)

    solve_info = {
        "status": str(summary),
        "objective": float(built.model.objective_value) if built.model.objective_value is not None else None,
    }
    logger.info("Solve finished: %s", solve_info)

    out_dir = root / "results" / scenario_name
    export_results(built, scenario_name, out_dir, solve_info)
    logger.info("Results written to %s", out_dir)
    return solve_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Run INRE Germany GAMSPy model")
    parser.add_argument(
        "--scenario",
        default="base",
        help="Scenario name, or 'all' (8), 'core' (5), 'capex' (3 SMR sensitivity)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Path to gamspy-de project root",
    )
    args = parser.parse_args()

    if args.scenario == "all":
        names = SCENARIOS
    elif args.scenario == "core":
        names = SCENARIO_CORE
    elif args.scenario == "capex":
        names = SCENARIO_CAPEX
    else:
        names = None

    if names is not None:
        results = {}
        for name in names:
            results[name] = run_scenario(name, args.root)
        for name, info in results.items():
            logger.info("%s: objective=%s", name, info.get("objective"))
    else:
        if args.scenario not in SCENARIOS:
            raise SystemExit(
                f"Unknown scenario '{args.scenario}'. Choose from: {SCENARIOS}, all, core, capex"
            )
        run_scenario(args.scenario, args.root)


if __name__ == "__main__":
    main()
