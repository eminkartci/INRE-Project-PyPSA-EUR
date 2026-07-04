#!/usr/bin/env python3
"""Generate placeholder input CSVs for gamspy-de (run once from gamspy-de/)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "inputs"

BUSES = [
    ("DE0", 54.0, 10.0),
    ("DE1", 53.0, 9.0),
    ("DE2", 52.0, 8.0),
    ("DE3", 53.0, 13.0),
    ("DE4", 51.0, 7.0),
    ("DE5", 51.0, 10.0),
    ("DE6", 51.0, 13.0),
    ("DE7", 49.0, 8.0),
    ("DE8", 48.0, 11.0),
    ("DE9", 50.0, 12.0),
]

LINES = [
    ("L01", "DE0", "DE1", 3500),
    ("L02", "DE0", "DE3", 2800),
    ("L03", "DE1", "DE2", 3200),
    ("L04", "DE1", "DE5", 3000),
    ("L05", "DE2", "DE4", 2900),
    ("L06", "DE2", "DE5", 3100),
    ("L07", "DE3", "DE6", 2700),
    ("L08", "DE3", "DE5", 2600),
    ("L09", "DE4", "DE5", 3400),
    ("L10", "DE4", "DE7", 2500),
    ("L11", "DE5", "DE6", 3000),
    ("L12", "DE5", "DE9", 2800),
    ("L13", "DE6", "DE9", 2600),
    ("L14", "DE7", "DE8", 3200),
    ("L15", "DE7", "DE9", 2900),
    ("L16", "DE8", "DE9", 3100),
    ("L17", "DE0", "DE2", 2400),
    ("L18", "DE1", "DE3", 2300),
    ("L19", "DE4", "DE9", 2200),
    ("L20", "DE6", "DE8", 2100),
    ("L21", "DE2", "DE7", 2000),
    ("L22", "DE5", "DE8", 2500),
]

DEMAND_SHARE = {
    "DE0": 0.08,
    "DE1": 0.11,
    "DE2": 0.14,
    "DE3": 0.09,
    "DE4": 0.13,
    "DE5": 0.12,
    "DE6": 0.08,
    "DE7": 0.10,
    "DE8": 0.09,
    "DE7": 0.10,
    "DE9": 0.06,
}
# fix duplicate DE7
DEMAND_SHARE = {
    "DE0": 0.08,
    "DE1": 0.11,
    "DE2": 0.14,
    "DE3": 0.09,
    "DE4": 0.13,
    "DE5": 0.12,
    "DE6": 0.08,
    "DE7": 0.10,
    "DE8": 0.09,
    "DE9": 0.06,
}

NUCLEAR_SITES = [
    ("Grohnde", "nuclear-smr", 51.906, 9.401),
    ("Brokdorf", "nuclear-smr", 53.851, 9.345),
    ("Isar", "nuclear-smr", 48.617, 12.293),
    ("Emsland", "nuclear-smr", 52.471, 7.321),
    ("Neckarwestheim", "nuclear-smr", 49.040, 9.175),
    ("Grohnde", "nuclear-msr", 51.906, 9.401),
    ("Brokdorf", "nuclear-msr", 53.851, 9.345),
    ("Isar", "nuclear-msr", 48.617, 12.293),
    ("Grohnde", "nuclear-lfr", 51.906, 9.401),
    ("Brokdorf", "nuclear-lfr", 53.851, 9.345),
    ("Emsland", "nuclear-lfr", 52.471, 7.321),
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_bus(lat: float, lon: float) -> str:
    return min(BUSES, key=lambda b: haversine_km(lat, lon, b[1], b[2]))[0]


def annuity(investment_eur_per_kw: float, lifetime: int, rate: float = 0.07) -> float:
    if rate == 0:
        return investment_eur_per_kw * 1000 / lifetime
    factor = rate * (1 + rate) ** lifetime / ((1 + rate) ** lifetime - 1)
    return investment_eur_per_kw * 1000 * factor


def nuclear_marginal(vom: float, fuel: float, efficiency: float) -> float:
    return vom + fuel / efficiency


def main() -> None:
    INPUTS.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(BUSES, columns=["bus_id", "lat", "lon"]).to_csv(
        INPUTS / "buses.csv", index=False
    )
    pd.DataFrame(LINES, columns=["line_id", "bus0", "bus1", "s_nom_MW"]).to_csv(
        INPUTS / "lines.csv", index=False
    )

    snapshots = pd.date_range("2021-01-25", periods=112, freq="3h")
    pd.DataFrame({"timestamp": snapshots, "weight_hours": 3.0}).to_csv(
        INPUTS / "snapshots.csv", index=False
    )

    base_demand_gw = 62.0
    demand_rows = []
    for ts in snapshots:
        hour = ts.hour + ts.dayofyear * 0.01
        daily = 1.0 + 0.12 * math.sin(2 * math.pi * (hour - 6) / 24)
        weekly = 1.0 + 0.05 * math.sin(2 * math.pi * ts.dayofyear / 7)
        total = base_demand_gw * 1000 * daily * weekly
        for bus, share in DEMAND_SHARE.items():
            demand_rows.append(
                {"bus": bus, "timestamp": ts, "demand_MW": round(total * share, 2)}
            )
    pd.DataFrame(demand_rows).to_csv(INPUTS / "demand.csv", index=False)

    techs = [
        # tech, cap_eur_mw_yr, marg, co2, extendable, p_min, p_max_def, ramp, co2_rel
        ("onwind", 120000, 0.015, 0.0, True, 0.0, 1.0, 1.0, False),
        ("offwind", 180000, 0.015, 0.0, True, 0.0, 1.0, 1.0, False),
        ("solar", 80000, 0.01, 0.0, True, 0.0, 1.0, 1.0, False),
        ("ocgt", 50000, 85.0, 0.45, True, 0.0, 1.0, 1.0, True),
        ("ccgt", 95000, 52.0, 0.25, True, 0.3, 1.0, 0.5, True),
    ]
    for name, inv, lifetime, eff, vom, fuel in [
        ("nuclear-smr", 5750, 60, 0.33, 3.0, 3.0),
        ("nuclear-msr", 6670, 50, 0.35, 3.5, 2.5),
        ("nuclear-lfr", 6210, 55, 0.34, 3.2, 2.8),
    ]:
        techs.append(
            (
                name,
                annuity(inv, lifetime),
                nuclear_marginal(vom, fuel, eff),
                0.0,
                True,
                0.3,
                0.9,
                0.5,
                False,
            )
        )

    pd.DataFrame(
        techs,
        columns=[
            "tech",
            "capital_cost_EUR_per_MWyr",
            "marginal_cost_EUR_per_MWh",
            "co2_t_per_MWh",
            "extendable",
            "p_min_pu",
            "p_max_pu_default",
            "ramp_pu_per_h",
            "co2_relevant",
        ],
    ).to_csv(INPUTS / "technologies.csv", index=False)

    cap_rows = []
    for bus, share in DEMAND_SHARE.items():
        cap_rows.extend(
            [
                {"bus": bus, "tech": "onwind", "p_nom_MW": round(65000 * share, 1)},
                {"bus": bus, "tech": "offwind", "p_nom_MW": round(8000 * share * (2 if bus in ("DE0", "DE1", "DE2") else 0.5), 1)},
                {"bus": bus, "tech": "solar", "p_nom_MW": round(55000 * share, 1)},
                {"bus": bus, "tech": "ocgt", "p_nom_MW": round(3000 * share + 500, 1)},
                {"bus": bus, "tech": "ccgt", "p_nom_MW": round(8000 * share + 1000, 1)},
            ]
        )
    pd.DataFrame(cap_rows).to_csv(INPUTS / "capacity_existing.csv", index=False)

    avail_rows = []
    bus_ids = [b[0] for b in BUSES]
    for ts in snapshots:
        hour = ts.hour
        solar_base = max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.0
        wind_base = 0.35 + 0.25 * math.sin(2 * math.pi * ts.dayofyear / 5 + hour / 24)
        for bus in bus_ids:
            wind_factor = min(1.0, wind_base * (1.2 if bus in ("DE0", "DE1", "DE2") else 0.85))
            solar_factor = solar_base * (0.95 if bus in ("DE7", "DE8", "DE9") else 1.0)
            for tech, pu in [
                ("onwind", round(wind_factor, 4)),
                ("offwind", round(min(1.0, wind_factor * 1.1), 4)),
                ("solar", round(solar_factor, 4)),
                ("ocgt", 1.0),
                ("ccgt", 1.0),
            ]:
                avail_rows.append(
                    {"bus": bus, "tech": tech, "timestamp": ts, "p_max_pu": pu}
                )
    pd.DataFrame(avail_rows).to_csv(INPUTS / "availability.csv", index=False)

    pd.DataFrame(
        [
            {
                "bus": bus,
                "efficiency_store": 0.95,
                "efficiency_dispatch": 0.95,
                "standing_loss_per_h": 0.0001,
                "capital_cost_power_EUR_per_MWyr": 35000,
                "capital_cost_energy_EUR_per_MWhyr": 15000,
                "marginal_cost_EUR_per_MWh": 0.0,
                "max_hours": 4.0,
            }
            for bus in bus_ids
        ]
    ).to_csv(INPUTS / "storage.csv", index=False)

    nuc_rows = []
    for site_id, tech, lat, lon in NUCLEAR_SITES:
        nuc_rows.append(
            {
                "site_id": site_id,
                "tech": tech,
                "bus_id": nearest_bus(lat, lon),
                "lat": lat,
                "lon": lon,
                "p_nom_max_MW": 1500,
                "p_min_pu": 0.3,
                "p_max_pu": 0.9,
                "ramp_pu_per_h": 0.5,
            }
        )
    pd.DataFrame(nuc_rows).to_csv(INPUTS / "nuclear_sites.csv", index=False)

    print(f"Generated template inputs in {INPUTS}")


if __name__ == "__main__":
    main()
