#!/usr/bin/env python3
"""Run reduced-form GAMSPy V4 validation scenarios."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from apply_scenario_rf import load_and_prepare_rf
from build_model_rf import build_model_rf
from export_results_rf import export_results_rf

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RF_SCENARIOS = [
    "v4-severe-no-nuclear",
    "v4-severe-smr-4.5",
    "v4-severe-decarbonised-no-nuclear",
    "v4-severe-decarbonised-smr-4.5",
]


def run_scenario_rf(scenario_name: str, root: Path, inputs_subdir: str = "inputs_v4_rf") -> dict:
    logger.info("Preparing reduced-form scenario: %s", scenario_name)
    data = load_and_prepare_rf(root, scenario_name, inputs_subdir=inputs_subdir)

    logger.info("Building reduced-form model (%d blocks, %d snapshots)", len(data.blocks), len(data.times))
    built = build_model_rf(data)

    solver = data.config.get("solver", "highs")
    logger.info("Solving with %s ...", solver)
    summary = built.model.solve(solver=solver)

    solve_info = {
        "status": str(summary),
        "objective": float(built.model.objective_value) if built.model.objective_value is not None else None,
    }
    logger.info("Solve finished: objective=%s", solve_info.get("objective"))

    out_dir = root / "results_rf" / scenario_name
    metrics = export_results_rf(
        built,
        scenario_name,
        out_dir,
        solve_info,
        snapshot_hours=float(data.config.get("snapshot_hours", 3.0)),
    )
    solve_info.update(metrics)
    return solve_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Run INRE reduced-form GAMSPy scenarios")
    parser.add_argument("--scenario", default="all")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--inputs-subdir", default="inputs_v4_rf")
    args = parser.parse_args()

    names = RF_SCENARIOS if args.scenario == "all" else [args.scenario]
    for name in names:
        if name not in RF_SCENARIOS:
            raise SystemExit(f"Unknown scenario: {name}")
        run_scenario_rf(name, args.root, inputs_subdir=args.inputs_subdir)


if __name__ == "__main__":
    main()
