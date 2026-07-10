"""Prepare reduced-form scenario data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from blocks import NUCLEAR_AVAILABILITY_PU
from load_inputs_rf import ModelInputsRF, load_inputs_rf, load_scenario_v4, validate_inputs_rf


@dataclass
class PreparedDataRF:
    scenario_name: str
    blocks: list[str]
    times: list[pd.Timestamp]
    weights: dict[str, float]
    demand: pd.DataFrame
    availability: pd.DataFrame
    blocks_df: pd.DataFrame
    block_validation: pd.DataFrame
    voll_eur_per_mwh: float
    config: dict


def _apply_block_capacity_overrides(blocks_df: pd.DataFrame, overrides: dict | None) -> pd.DataFrame:
    if not overrides:
        return blocks_df
    out = blocks_df.copy()
    for block, value in overrides.items():
        if block in out["block"].values:
            out.loc[out["block"] == block, "installed_capacity_MW"] = float(value)
    return out


def _zero_availability_when_no_capacity(availability: pd.DataFrame, blocks_df: pd.DataFrame) -> pd.DataFrame:
    out = availability.copy()
    cap_map = dict(zip(blocks_df["block"], blocks_df["installed_capacity_MW"]))
    for block, cap in cap_map.items():
        if cap <= 0:
            out.loc[out["block"] == block, "available_MW"] = 0.0
        elif block == "nuclear":
            out.loc[out["block"] == block, "available_MW"] = cap * NUCLEAR_AVAILABILITY_PU
    return out


def prepare_scenario_rf(inputs: ModelInputsRF, scenario: dict) -> PreparedDataRF:
    snapshots = pd.DatetimeIndex(inputs.snapshots["timestamp"])
    weights = {
        str(ts): float(w)
        for ts, w in zip(inputs.snapshots["timestamp"], inputs.snapshots["weight_hours"])
    }

    blocks_df = _apply_block_capacity_overrides(inputs.blocks, scenario.get("capacity_overrides"))
    availability = _zero_availability_when_no_capacity(inputs.availability, blocks_df)

    return PreparedDataRF(
        scenario_name=scenario.get("name", "unnamed"),
        blocks=sorted(blocks_df["block"].tolist()),
        times=list(snapshots),
        weights=weights,
        demand=inputs.demand.copy(),
        availability=availability,
        blocks_df=blocks_df,
        block_validation=inputs.block_validation.copy(),
        voll_eur_per_mwh=float(inputs.config.get("voll_eur_per_mwh", 100_000.0)),
        config=inputs.config,
    )


def load_and_prepare_rf(root: Path, scenario_name: str, inputs_subdir: str = "inputs_v4_rf") -> PreparedDataRF:
    scenario_path = root / "scenarios" / f"{scenario_name}.yaml"
    scenario_inputs = root / inputs_subdir / scenario_name
    inputs = load_inputs_rf(scenario_inputs, root)
    issues = validate_inputs_rf(inputs)
    if issues:
        raise ValueError("Input validation failed:\n" + "\n".join(f"  - {i}" for i in issues))
    with open(scenario_path) as f:
        import yaml

        scenario = yaml.safe_load(f) or {}
    return prepare_scenario_rf(inputs, scenario)
