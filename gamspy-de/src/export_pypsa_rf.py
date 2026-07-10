"""Export PyPSA solved networks to reduced-form GAMSPy block inputs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

from blocks import BLOCK_CARRIERS, DISPATCH_BLOCKS, NUCLEAR_AVAILABILITY_PU

SNAPSHOT_HOURS = 3.0
NUCLEAR_CARRIER = "nuclear-smr"


def _effective_co2_t_per_mwh_el(n: pypsa.Network, carrier: str) -> float:
    if carrier not in n.carriers.index:
        return 0.0
    return float(n.carriers.at[carrier, "co2_emissions"])


def _generator_available_mw(n: pypsa.Network, gen: str, ts: pd.Timestamp) -> float:
    p_nom = float(n.generators.at[gen, "p_nom"])
    if p_nom <= 0:
        return 0.0
    if gen in n.generators_t.p_max_pu.columns:
        pu = float(n.generators_t.p_max_pu.at[ts, gen])
    else:
        pu = 1.0
    return p_nom * pu


def _block_generators(n: pypsa.Network, block: str) -> pd.DataFrame:
    carriers = BLOCK_CARRIERS[block]
    return n.generators[n.generators.carrier.isin(carriers)].copy()


def _capacity_weighted_mean(gens: pd.DataFrame, values: dict[str, float]) -> float:
    caps = gens["p_nom"].astype(float)
    total = float(caps.sum())
    if total <= 0:
        return 0.0
    weighted = sum(float(values.get(car, 0.0)) * float(gens.loc[gens.carrier == car, "p_nom"].sum()) for car in gens.carrier.unique())
    return weighted / total


def _block_installed_capacity_mw(gens: pd.DataFrame) -> float:
    return float(gens["p_nom"].sum())


def _block_marginal_cost(gens: pd.DataFrame, n: pypsa.Network, block: str) -> float:
    if block in ("peaker", "other_firm"):
        mc_by_carrier = {c: float(gens.loc[gens.carrier == c, "marginal_cost"].median()) for c in gens.carrier.unique()}
        return _capacity_weighted_mean(gens, mc_by_carrier)
    if len(gens) == 0:
        return 0.0
    return float(gens.marginal_cost.median())


def _block_co2(gens: pd.DataFrame, n: pypsa.Network, block: str) -> float:
    if block in ("peaker", "other_firm"):
        co2_by_carrier = {c: _effective_co2_t_per_mwh_el(n, c) for c in gens.carrier.unique()}
        return _capacity_weighted_mean(gens, co2_by_carrier)
    if block == "nuclear":
        return 0.0
    if len(gens) == 0:
        return 0.0
    carrier = gens.carrier.iloc[0]
    return _effective_co2_t_per_mwh_el(n, carrier)


def export_block_inputs_from_pypsa(network_path: Path, output_dir: Path) -> dict[str, pd.DataFrame]:
    n = pypsa.Network(str(network_path))
    snaps = pd.DatetimeIndex(n.snapshots)
    weight = float(n.snapshot_weightings.objective.iloc[0])

    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame({"timestamp": snaps, "weight_hours": weight}).to_csv(output_dir / "snapshots.csv", index=False)

    demand_mw = n.loads_t.p_set.reindex(snaps).sum(axis=1)
    pd.DataFrame({"timestamp": snaps, "demand_MW": demand_mw.values}).to_csv(output_dir / "demand.csv", index=False)

    block_rows = []
    avail_rows = []
    validation_rows = []

    for block in DISPATCH_BLOCKS:
        gens = _block_generators(n, block)
        installed = _block_installed_capacity_mw(gens)
        carriers = BLOCK_CARRIERS[block]
        included = ",".join(carriers)

        mc = _block_marginal_cost(gens, n, block)
        co2 = _block_co2(gens, n, block)

        block_rows.append(
            {
                "block": block,
                "included_carriers": included,
                "installed_capacity_MW": installed,
                "marginal_cost_EUR_per_MWh": mc,
                "co2_t_per_MWh_el": co2,
            }
        )

        max_avail_mw = 0.0
        max_energy_mwh = 0.0
        for ts in snaps:
            avail_mw = sum(_generator_available_mw(n, gen, ts) for gen in gens.index)
            avail_rows.append({"block": block, "timestamp": ts, "available_MW": avail_mw})
            max_avail_mw = max(max_avail_mw, avail_mw)
            max_energy_mwh += avail_mw * weight

        validation_rows.append(
            {
                "block": block,
                "included_carriers": included,
                "installed_capacity_MW": installed,
                "max_available_power_MW": max_avail_mw,
                "full_window_max_available_energy_TWh": max_energy_mwh / 1e6,
                "marginal_cost_EUR_per_MWh": mc,
                "co2_t_per_MWh_el": co2,
            }
        )

    blocks_df = pd.DataFrame(block_rows)
    avail_df = pd.DataFrame(avail_rows)
    validation_df = pd.DataFrame(validation_rows)

    blocks_df.to_csv(output_dir / "blocks.csv", index=False)
    avail_df.to_csv(output_dir / "availability.csv", index=False)
    validation_df.to_csv(output_dir / "block_validation.csv", index=False)

    return {
        "blocks": blocks_df,
        "availability": avail_df,
        "demand": pd.DataFrame({"timestamp": snaps, "demand_MW": demand_mw.values}),
        "block_validation": validation_df,
        "snapshots": pd.DataFrame({"timestamp": snaps, "weight_hours": weight}),
    }
