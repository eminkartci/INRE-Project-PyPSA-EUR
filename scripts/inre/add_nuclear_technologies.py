# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Add extendable INRE nuclear technology generators at candidate sites.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

NUCLEAR_COLORS = {
    "nuclear-smr": "#ff8c00",
    "nuclear-msr": "#e65c00",
    "nuclear-lfr": "#cc4d00",
}


def _nearest_bus(n: pypsa.Network, lat: float, lon: float) -> str:
    buses = n.buses.dropna(subset=["x", "y"])
    dist = (buses.x - lon) ** 2 + (buses.y - lat) ** 2
    return dist.idxmin()


def _load_sites(sites_file: str | Path, carriers: list[str]) -> pd.DataFrame:
    df = pd.read_csv(sites_file)
    required = {"Name", "Technology", "Country", "Capacity", "lat", "lon"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Sites file missing columns: {missing}")

    df = df.query("Country == 'DE'")
    if carriers:
        df = df.query("Technology in @carriers")
    return df


def _cost_row(costs: pd.DataFrame, carrier: str) -> pd.Series:
    if carrier not in costs.index:
        raise KeyError(
            f"Carrier '{carrier}' not in processed costs. "
            f"Add rows to data/inre/custom_costs_nuclear.csv."
        )
    return costs.loc[carrier]


def add_nuclear_technologies(
    n: pypsa.Network,
    carriers: list[str],
    costs: pd.DataFrame,
    sites_file: str | Path | None = None,
    p_nom_max_per_site: float = 1500.0,
    p_max_pu: float = 0.9,
) -> pypsa.Network:
    if not carriers:
        return n

    for carrier in carriers:
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier, co2_emissions=0.0)
        if carrier in NUCLEAR_COLORS:
            n.carriers.at[carrier, "color"] = NUCLEAR_COLORS[carrier]
            n.carriers.at[carrier, "nice_name"] = carrier.replace("nuclear-", "").upper()

    if sites_file and Path(sites_file).exists():
        sites = _load_sites(sites_file, carriers)
    else:
        sites = pd.DataFrame(
            {
                "Name": [f"INRE {c} everywhere" for c in carriers],
                "Technology": carriers,
                "Country": ["DE"] * len(carriers),
                "Capacity": [0.0] * len(carriers),
                "lat": [51.0] * len(carriers),
                "lon": [10.0] * len(carriers),
            }
        )

    added = 0
    for _, row in sites.iterrows():
        carrier = row["Technology"]
        if carrier not in carriers:
            continue
        bus = _nearest_bus(n, row["lat"], row["lon"])
        gen_name = f"INRE {carrier} {row['Name']}"
        if gen_name in n.generators.index:
            continue

        cost = _cost_row(costs, carrier)
        n.add(
            "Generator",
            gen_name,
            bus=bus,
            carrier=carrier,
            p_nom=0.0,
            p_nom_extendable=True,
            p_nom_max=p_nom_max_per_site,
            capital_cost=cost.capital_cost,
            marginal_cost=cost.marginal_cost,
            efficiency=cost.efficiency,
            lifetime=cost.lifetime,
            p_max_pu=p_max_pu,
            ramp_limit_up=0.5,
            ramp_limit_down=0.5,
            p_min_pu=0.3,
        )
        added += 1

    logger.info("Added %d extendable INRE nuclear generators for %s", added, carriers)
    return n
