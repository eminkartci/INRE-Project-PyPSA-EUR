"""Load CSV/YAML inputs for the Germany GAMSPy model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class ModelInputs:
    root: Path
    config: dict
    buses: pd.DataFrame
    lines: pd.DataFrame
    demand: pd.DataFrame
    technologies: pd.DataFrame
    capacity_existing: pd.DataFrame
    availability: pd.DataFrame
    storage: pd.DataFrame
    nuclear_sites: pd.DataFrame
    snapshots: pd.DataFrame


def _read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")
    return pd.read_csv(path, **kwargs)


def load_config(root: Path) -> dict:
    config_path = root / "config" / "model.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def load_scenario(root: Path, scenario_name: str) -> dict:
    scenario_path = root / "scenarios" / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        raise FileNotFoundError(f"Unknown scenario: {scenario_name} ({scenario_path})")
    with open(scenario_path) as f:
        return yaml.safe_load(f) or {}


def load_inputs(root: Path | None = None) -> ModelInputs:
    root = Path(root or Path(__file__).resolve().parent.parent)
    inputs_dir = root / "inputs"

    config = load_config(root)
    snapshots = _read_csv(inputs_dir / "snapshots.csv", parse_dates=["timestamp"])
    expected = pd.date_range(
        config["snapshots"]["start"],
        periods=112,
        freq=config["snapshots"]["freq"],
    )
    snap_index = pd.DatetimeIndex(snapshots["timestamp"])
    if len(snap_index) != len(expected):
        raise ValueError(
            f"snapshots.csv has {len(snap_index)} rows; expected {len(expected)} "
            f"for {config['snapshots']['start']}–{config['snapshots']['end']} "
            f"at {config['snapshots']['freq']}"
        )

    demand = _read_csv(inputs_dir / "demand.csv", parse_dates=["timestamp"])
    availability = _read_csv(inputs_dir / "availability.csv", parse_dates=["timestamp"])

    return ModelInputs(
        root=root,
        config=config,
        buses=_read_csv(inputs_dir / "buses.csv"),
        lines=_read_csv(inputs_dir / "lines.csv"),
        demand=demand,
        technologies=_read_csv(inputs_dir / "technologies.csv"),
        capacity_existing=_read_csv(inputs_dir / "capacity_existing.csv"),
        availability=availability,
        storage=_read_csv(inputs_dir / "storage.csv"),
        nuclear_sites=_read_csv(inputs_dir / "nuclear_sites.csv"),
        snapshots=snapshots,
    )


def validate_inputs(inputs: ModelInputs) -> None:
    bus_ids = set(inputs.buses["bus_id"])
    for label, df, cols in [
        ("demand", inputs.demand, ["bus", "timestamp", "demand_MW"]),
        ("availability", inputs.availability, ["bus", "tech", "timestamp", "p_max_pu"]),
        ("capacity_existing", inputs.capacity_existing, ["bus", "tech", "p_nom_MW"]),
    ]:
        missing = set(cols) - set(df.columns)
        if missing:
            raise ValueError(f"{label}.csv missing columns: {missing}")
        unknown = set(df["bus"]) - bus_ids
        if unknown:
            raise ValueError(f"{label}.csv references unknown buses: {sorted(unknown)}")

    line_buses = set(inputs.lines["bus0"]) | set(inputs.lines["bus1"])
    unknown_lines = line_buses - bus_ids
    if unknown_lines:
        raise ValueError(f"lines.csv references unknown buses: {sorted(unknown_lines)}")
