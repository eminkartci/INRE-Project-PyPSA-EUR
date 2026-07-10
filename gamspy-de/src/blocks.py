"""Reduced-form dispatch block definitions for INRE V4 GAMSPy validation."""

from __future__ import annotations

DISPATCH_BLOCKS = [
    "vre",
    "coal",
    "lignite",
    "ccgt",
    "peaker",
    "other_firm",
    "nuclear",
]

BLOCK_CARRIERS: dict[str, list[str]] = {
    "vre": ["onwind", "offwind-ac", "offwind-dc", "offwind-float", "solar", "solar-hsat"],
    "coal": ["coal"],
    "lignite": ["lignite"],
    "ccgt": ["CCGT"],
    "peaker": ["OCGT", "oil"],
    "other_firm": ["biomass", "waste", "geothermal"],
    "nuclear": ["nuclear-smr"],
}

NUCLEAR_AVAILABILITY_PU = 0.9
SMR_CAPACITY_MW = 4500.0
