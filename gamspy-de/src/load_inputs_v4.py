"""Load V4 CSV/YAML inputs for the Germany GAMSPy dispatch validation model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class ModelInputsV4:
    root: Path
    config: dict
    buses: pd.DataFrame
    lines: pd.DataFrame
    demand: pd.DataFrame
    technologies: pd.DataFrame
    capacity_existing: pd.DataFrame
    availability: pd.DataFrame
    nuclear_sites: pd.DataFrame
    snapshots: pd.DataFrame


def _read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")
    return pd.read_csv(path, **kwargs)


def load_config_v4(root: Path) -> dict:
    config_path = root / "config" / "model_v4.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def load_scenario_v4(root: Path, scenario_name: str) -> dict:
    scenario_path = root / "scenarios" / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        raise FileNotFoundError(f"Unknown scenario: {scenario_name} ({scenario_path})")
    with open(scenario_path) as f:
        return yaml.safe_load(f) or {}


def load_inputs_v4(root: Path | None = None, inputs_subdir: str = "inputs_v4") -> ModelInputsV4:
    root = Path(root or Path(__file__).resolve().parent.parent)
    inputs_dir = root / inputs_subdir

    config = load_config_v4(root)
    snapshots = _read_csv(inputs_dir / "snapshots.csv", parse_dates=["timestamp"])
    expected_count = int(config["snapshots"]["count"])
    if len(snapshots) != expected_count:
        raise ValueError(
            f"snapshots.csv has {len(snapshots)} rows; expected {expected_count} for V4"
        )

    weight_hours = float(config["snapshots"]["weight_hours"])
    snap_weights = snapshots["weight_hours"].astype(float)
    if not snap_weights.eq(weight_hours).all():
        raise ValueError(f"All snapshot weights must equal {weight_hours} h")

    demand = _read_csv(inputs_dir / "demand.csv", parse_dates=["timestamp"])
    availability = _read_csv(inputs_dir / "availability.csv", parse_dates=["timestamp"])

    return ModelInputsV4(
        root=root,
        config=config,
        buses=_read_csv(inputs_dir / "buses.csv"),
        lines=_read_csv(inputs_dir / "lines.csv"),
        demand=demand,
        technologies=_read_csv(inputs_dir / "technologies.csv"),
        capacity_existing=_read_csv(inputs_dir / "capacity_existing.csv"),
        availability=availability,
        nuclear_sites=_read_csv(inputs_dir / "nuclear_sites.csv"),
        snapshots=snapshots,
    )


def validate_inputs_v4(inputs: ModelInputsV4) -> list[str]:
    issues: list[str] = []
    bus_ids = set(inputs.buses["bus_id"])

    for label, df, cols in [
        ("demand", inputs.demand, ["bus", "timestamp", "demand_MW"]),
        ("availability", inputs.availability, ["bus", "tech", "timestamp", "p_max_pu"]),
        ("capacity_existing", inputs.capacity_existing, ["bus", "tech", "p_nom_MW"]),
    ]:
        missing = set(cols) - set(df.columns)
        if missing:
            issues.append(f"{label}.csv missing columns: {missing}")
        unknown = set(df["bus"]) - bus_ids
        if unknown:
            issues.append(f"{label}.csv references unknown buses: {sorted(unknown)}")

    if inputs.demand["demand_MW"].min() < 0:
        issues.append("demand_MW contains negative values")

    line_buses = set(inputs.lines["bus0"]) | set(inputs.lines["bus1"])
    unknown_lines = line_buses - bus_ids
    if unknown_lines:
        issues.append(f"lines.csv references unknown buses: {sorted(unknown_lines)}")

    return issues
