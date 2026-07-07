#!/usr/bin/env python3
"""Generate SMR CAPEX sensitivity cost files from the INRE nuclear baseline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = REPO_ROOT / "data" / "inre" / "custom_costs_nuclear.csv"

MULTIPLIERS = {
    "capex70": 0.70,
    "capex85": 0.85,
    "capex115": 1.15,
}


def main() -> None:
    df = pd.read_csv(BASE)
    mask = (df["technology"] == "nuclear-smr") & (df["parameter"] == "investment")
    if not mask.any():
        raise SystemExit("No nuclear-smr investment row in baseline cost file.")

    for label, mult in MULTIPLIERS.items():
        out = df.copy()
        out.loc[mask, "value"] = (out.loc[mask, "value"] * mult).round(1)
        out.loc[mask, "further description"] = (
            f"SMR CAPEX {int(mult * 100)}% of OECD/NEA baseline"
        )
        path = REPO_ROOT / "data" / "inre" / f"custom_costs_nuclear_smr_{label}.csv"
        out.to_csv(path, index=False)
        print(f"Wrote {path} (investment={out.loc[mask, 'value'].iloc[0]} EUR/kW)")


if __name__ == "__main__":
    main()
