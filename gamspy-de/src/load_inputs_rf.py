"""Load reduced-form GAMSPy inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class ModelInputsRF:
    root: Path
    scenario_dir: Path
    config: dict
    demand: pd.DataFrame
    blocks: pd.DataFrame
    availability: pd.DataFrame
    block_validation: pd.DataFrame
    snapshots: pd.DataFrame


def load_config_v4(root: Path) -> dict:
    with open(root / "config" / "model_v4.yaml") as f:
        return yaml.safe_load(f) or {}


def load_scenario_v4(root: Path, scenario_name: str) -> dict:
    with open(root / "scenarios" / f"{scenario_name}.yaml") as f:
        return yaml.safe_load(f) or {}


def load_inputs_rf(scenario_dir: Path, root: Path) -> ModelInputsRF:
    config = load_config_v4(root)
    snapshots = pd.read_csv(scenario_dir / "snapshots.csv", parse_dates=["timestamp"])
    expected = int(config["snapshots"]["count"])
    if len(snapshots) != expected:
        raise ValueError(f"Expected {expected} snapshots, got {len(snapshots)}")

    return ModelInputsRF(
        root=root,
        scenario_dir=scenario_dir,
        config=config,
        demand=pd.read_csv(scenario_dir / "demand.csv", parse_dates=["timestamp"]),
        blocks=pd.read_csv(scenario_dir / "blocks.csv"),
        availability=pd.read_csv(scenario_dir / "availability.csv", parse_dates=["timestamp"]),
        block_validation=pd.read_csv(scenario_dir / "block_validation.csv"),
        snapshots=snapshots,
    )


def validate_inputs_rf(inputs: ModelInputsRF) -> list[str]:
    issues: list[str] = []
    required_blocks = {"vre", "coal", "lignite", "ccgt", "peaker", "other_firm", "nuclear"}
    found = set(inputs.blocks["block"])
    missing = required_blocks - found
    if missing:
        issues.append(f"Missing blocks: {sorted(missing)}")
    if inputs.demand["demand_MW"].min() < 0:
        issues.append("Negative demand")
    if (inputs.availability["available_MW"] < -1e-6).any():
        issues.append("Negative available_MW")
    return issues
