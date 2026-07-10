# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Load validated V4 inputs, solved networks, and comparison CSVs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pypsa
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

METADATA_PATH = REPO_ROOT / "data/inre/profiles/stylised_dunkelflaute_v4/metadata.yaml"
PROFILE_OUTPUT = REPO_ROOT / "output/stylised_dunkelflaute_v4"
GAMSPY_RF = REPO_ROOT / "gamspy-de/results_rf"
INPUTS_V4 = REPO_ROOT / "gamspy-de/inputs_v4"

COMPARISON_DIRS = {
    "stage1": REPO_ROOT / "results/inre-comparison-v4-stage1",
    "nuclear_sweep": REPO_ROOT / "results/inre-comparison-v4-nuclear-sweep",
    "reactor": REPO_ROOT / "results/inre-comparison-v4-reactor-comparison",
    "decarbonised": REPO_ROOT / "results/inre-comparison-v4-decarbonised-adequacy",
    "flexibility": REPO_ROOT / "results/inre-comparison-v4-smr-flexibility",
    "pypsa_gamspy": REPO_ROOT / "results/inre-comparison-v4-pypsa-gamspy",
}

SOLVED_NETWORKS: dict[str, Path] = {
    "matched-base-v4": REPO_ROOT / "results/inre-de-matched-base-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-nuc-1.5-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-1.5-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-nuc-3.0-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-3.0-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-nuc-4.5-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-4.5-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-nuc-7.5-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-nuc-7.5-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-smr-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-smr-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-msr-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-msr-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-lfr-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-lfr-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-decarb-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-decarb-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-decarb-smr-4.5-v4": REPO_ROOT / "results/inre-de-stylised-df-severe-decarb-smr-4.5-v4/networks/base_s_10_elec_.nc",
    "stylised-df-severe-decarb-smr-4.5-limited-flex-v4": REPO_ROOT
    / "results/inre-de-stylised-df-severe-decarb-smr-4.5-limited-flex-v4/networks/base_s_10_elec_.nc",
}

PROFILE_ONLY = {"stylised-df-moderate-v4", "stylised-df-extreme-v4"}

GAMSPY_SCENARIOS = {
    "v4-severe-no-nuclear": "severe-no-nuclear",
    "v4-severe-smr-4.5": "severe-smr-4.5",
    "v4-severe-decarbonised-no-nuclear": "severe-decarbonised-no-nuclear",
    "v4-severe-decarbonised-smr-4.5": "severe-decarbonised-smr-4.5",
}

VOLL = 10_000.0


@dataclass
class PackageContext:
    output_dir: Path
    meta: dict = field(default_factory=dict)
    networks: dict[str, pypsa.Network] = field(default_factory=dict)
    figure_manifest: list[dict] = field(default_factory=list)
    table_manifest: list[dict] = field(default_factory=list)
    captions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def load_metadata() -> dict:
    return yaml.safe_load(METADATA_PATH.read_text())


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def load_network(key: str, ctx: PackageContext, cache: bool = True) -> pypsa.Network | None:
    if cache and key in ctx.networks:
        return ctx.networks[key]
    path = SOLVED_NETWORKS.get(key)
    if path is None or not path.exists():
        ctx.warnings.append(f"Missing solved network: {key} ({path})")
        return None
    n = pypsa.Network(str(path))
    if cache:
        ctx.networks[key] = n
    return n


def slice_snapshots(n: pypsa.Network, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    snaps = pd.DatetimeIndex(n.snapshots)
    return snaps[(snaps >= start) & (snaps <= end)]


def full_window_snaps(n: pypsa.Network) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(n.snapshots)


def core_snaps(n: pypsa.Network, meta: dict) -> pd.DatetimeIndex:
    return slice_snapshots(n, pd.Timestamp(meta["core_start"]), pd.Timestamp(meta["core_end"]))


def snapshot_weight(n: pypsa.Network, snaps: pd.DatetimeIndex | None = None) -> pd.Series:
    snaps = snaps if snaps is not None else pd.DatetimeIndex(n.snapshots)
    return n.snapshot_weightings.objective.reindex(snaps).fillna(1.0)


def national_demand_gw(n: pypsa.Network, snaps: pd.DatetimeIndex | None = None) -> pd.Series:
    snaps = snaps if snaps is not None else pd.DatetimeIndex(n.snapshots)
    return n.loads_t.p_set.reindex(snaps).sum(axis=1) / 1e3


RENEWABLE_CARRIERS = [
    "onwind",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
    "solar",
    "solar-hsat",
]


def gen_energy_by_carrier(n: pypsa.Network, snaps: pd.DatetimeIndex) -> pd.Series:
    """Weighted generation by carrier [TWh]."""
    weight = snapshot_weight(n, snaps)
    p = n.generators_t.p.reindex(snaps).fillna(0.0)
    by_carrier: dict[str, float] = {}
    for gen in p.columns:
        carrier = n.generators.at[gen, "carrier"]
        by_carrier[carrier] = by_carrier.get(carrier, 0.0) + float((p[gen] * weight).sum())
    return pd.Series(by_carrier) / 1e6


def ensure_dirs(output_dir: Path) -> None:
    for sub in [
        "figures/pdf",
        "figures/svg",
        "figures/png",
        "tables",
        "latex",
        "data",
        "captions",
        "validation",
    ]:
        (output_dir / sub).mkdir(parents=True, exist_ok=True)
