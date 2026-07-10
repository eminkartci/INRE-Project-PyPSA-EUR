# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Add extendable INRE nuclear technology generators at candidate sites.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

NUCLEAR_COLORS = {
    "nuclear-smr": "#ff8c00",
    "nuclear-msr": "#e65c00",
    "nuclear-lfr": "#cc4d00",
    "generic-advanced-nuclear": "#d97706",
}

EQUAL_SITE_NAMES = {"Grohnde", "Brokdorf", "Isar"}


def _snapshot_step_hours(n: pypsa.Network) -> float:
    snapshots = pd.DatetimeIndex(pd.to_datetime(n.snapshots))
    if len(snapshots) < 2:
        return 1.0
    return float((snapshots[1] - snapshots[0]) / pd.Timedelta(hours=1))


def _nearest_bus(n: pypsa.Network, lat: float, lon: float) -> str:
    buses = n.buses.dropna(subset=["x", "y"])
    dist = (buses.x - lon) ** 2 + (buses.y - lat) ** 2
    return dist.idxmin()


def _load_sites(
    sites_file: str | Path,
    carriers: list[str],
    site_names: set[str] | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(sites_file)
    required = {"Name", "Technology", "Country", "Capacity", "lat", "lon"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Sites file missing columns: {missing}")

    df = df.query("Country == 'DE'")
    if carriers:
        df = df.query("Technology in @carriers")
    if site_names:
        df = df.query("Name in @site_names")
    return df


def _cost_row(costs: pd.DataFrame, carrier: str) -> pd.Series:
    if carrier not in costs.index:
        raise KeyError(
            f"Carrier '{carrier}' not in processed costs. "
            f"Add rows to data/inre/custom_costs_nuclear.csv."
        )
    return costs.loc[carrier]


def _per_site_cap_mw(
    p_nom_max_per_site: float,
    total_cap_mw: float | None,
    n_sites: int,
) -> float:
    if total_cap_mw is not None and n_sites > 0:
        return total_cap_mw / n_sites
    return p_nom_max_per_site


def add_nuclear_technologies(
    n: pypsa.Network,
    carriers: list[str],
    costs: pd.DataFrame,
    sites_file: str | Path | None = None,
    p_nom_max_per_site: float = 1500.0,
    p_max_pu: float = 0.9,
    p_min_pu: float = 0.0,
    ramp_limit_per_hour: float = 0.5,
    site_names: list[str] | None = None,
    total_cap_mw: float | None = None,
    compare_mode: str = "site-potential",
) -> pypsa.Network:
    if not carriers:
        return n

    step_h = _snapshot_step_hours(n)
    ramp_per_snapshot = ramp_limit_per_hour * step_h

    site_filter: set[str] | None = None
    if compare_mode == "equal-site":
        site_filter = set(site_names) if site_names else EQUAL_SITE_NAMES

    for carrier in carriers:
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier, co2_emissions=0.0)
        if carrier in NUCLEAR_COLORS:
            n.carriers.at[carrier, "color"] = NUCLEAR_COLORS[carrier]
            nice = carrier.replace("nuclear-", "").replace("generic-advanced-", "").upper()
            n.carriers.at[carrier, "nice_name"] = nice

    if sites_file and Path(sites_file).exists():
        sites = _load_sites(sites_file, carriers, site_filter)
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

    n_sites = len(sites)
    site_cap = _per_site_cap_mw(p_nom_max_per_site, total_cap_mw, n_sites)

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
            p_nom_max=site_cap,
            capital_cost=cost.capital_cost,
            marginal_cost=cost.marginal_cost,
            efficiency=cost.efficiency,
            lifetime=cost.lifetime,
            p_max_pu=p_max_pu,
            ramp_limit_up=ramp_per_snapshot,
            ramp_limit_down=ramp_per_snapshot,
            p_min_pu=p_min_pu,
        )
        added += 1

    logger.info(
        "Added %d nuclear generators for %s (mode=%s, %.0f MW/site, total cap=%s)",
        added,
        carriers,
        compare_mode,
        site_cap,
        total_cap_mw,
    )
    return n
