#!/usr/bin/env python3
"""Run V4 Germany GAMSPy dispatch validation scenarios."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from apply_scenario_v4 import load_and_prepare_v4
from build_model_v4 import build_model_v4
from export_results_v4 import export_results_v4

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

V4_SCENARIOS = [
    "v4-severe-no-nuclear",
    "v4-severe-smr-4.5",
    "v4-severe-decarbonised-no-nuclear",
    "v4-severe-decarbonised-smr-4.5",
]


def run_scenario_v4(scenario_name: str, root: Path, inputs_subdir: str = "inputs_v4") -> dict:
    logger.info("Preparing V4 scenario: %s", scenario_name)
    data = load_and_prepare_v4(root, scenario_name, inputs_subdir=inputs_subdir)

    logger.info("Building GAMSPy V4 model (%d buses, %d snapshots)", len(data.buses), len(data.times))
    built = build_model_v4(data)

    solver = data.config.get("solver", "highs")
    logger.info("Solving with %s ...", solver)
    summary = built.model.solve(solver=solver)

    solve_info = {
        "status": str(summary),
        "objective": float(built.model.objective_value) if built.model.objective_value is not None else None,
    }
    logger.info("Solve finished: %s", solve_info)

    out_dir = root / "results_v4" / scenario_name
    metrics = export_results_v4(
        built,
        scenario_name,
        out_dir,
        solve_info,
        snapshot_hours=float(data.config.get("snapshot_hours", 3.0)),
    )
    solve_info.update(metrics)
    logger.info("Results written to %s", out_dir)
    return solve_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Run INRE Germany GAMSPy V4 validation scenarios")
    parser.add_argument(
        "--scenario",
        default="all",
        help=f"Scenario name or 'all' ({', '.join(V4_SCENARIOS)})",
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="Path to gamspy-de project root")
    parser.add_argument("--inputs-subdir", default="inputs_v4", help="Inputs subdirectory under root")
    args = parser.parse_args()

    if args.scenario == "all":
        names = V4_SCENARIOS
    else:
        names = [args.scenario]

    results = {}
    for name in names:
        if name not in V4_SCENARIOS:
            raise SystemExit(f"Unknown scenario '{name}'. Choose from: {V4_SCENARIOS}, all")
        results[name] = run_scenario_v4(name, args.root, inputs_subdir=args.inputs_subdir)

    for name, info in results.items():
        logger.info("%s: status=%s objective=%s", name, info.get("status"), info.get("objective"))


if __name__ == "__main__":
    main()
