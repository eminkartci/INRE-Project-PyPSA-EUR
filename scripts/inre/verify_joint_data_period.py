# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Verify joint availability of hourly weather CF proxies and German electricity demand.

Reports per-year coverage for ranking eligibility. Only years with consistent
hourly demand and weather may enter the main residual-load ranking.

Run::

    python scripts/inre/verify_joint_data_period.py \\
        --output output/historical_event_selection_v4/joint_data_period.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_weather_years(hourly_cf_path: Path) -> dict[int, pd.DatetimeIndex]:
    cf = pd.read_csv(hourly_cf_path, parse_dates=["timestamp"]).set_index("timestamp")
    cf.index = pd.DatetimeIndex(cf.index).tz_localize(None)
    years: dict[int, pd.DatetimeIndex] = {}
    for year in sorted(cf.index.year.unique()):
        sl = cf.index[cf.index.year == year]
        years[int(year)] = sl
    return years


def _load_demand_years(demand_csv: Path, demand_column: str = "DE") -> dict[int, pd.Series]:
    df = pd.read_csv(demand_csv, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    if demand_column not in df.columns:
        raise ValueError(f"Column {demand_column} not in {demand_csv}")
    de = df[demand_column].astype(float)
    years: dict[int, pd.Series] = {}
    for year in sorted(de.index.year.unique()):
        sl = de[de.index.year == year]
        years[int(year)] = sl
    return years


def _expected_hours(year: int) -> int:
    return 8784 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 8760


def build_joint_period_table(
    hourly_cf_path: Path,
    demand_csv: Path,
    demand_column: str = "DE",
    demand_type: str = "ENTSO-E observed (DE)",
) -> pd.DataFrame:
    weather = _load_weather_years(hourly_cf_path)
    demand = _load_demand_years(demand_csv, demand_column)
    all_years = sorted(set(weather) | set(demand))
    rows = []
    for year in all_years:
        w_idx = weather.get(year, pd.DatetimeIndex([]))
        d_ser = demand.get(year, pd.Series(dtype=float))
        w_avail = len(w_idx) > 0
        d_avail = len(d_ser) > 0
        if w_avail and d_avail:
            aligned = d_ser.reindex(w_idx)
            missing = int(aligned.isna().sum())
            dup_w = int(w_idx.duplicated().sum())
            dup_d = int(d_ser.index.duplicated().sum())
            missing += dup_w + dup_d
            included = missing == 0 and len(w_idx) >= _expected_hours(year) - 24
        else:
            missing = _expected_hours(year)
            included = False
        rows.append(
            {
                "year": year,
                "weather_available": w_avail,
                "demand_available": d_avail,
                "missing_hours": missing,
                "demand_type": demand_type if d_avail else "n/a",
                "included_in_ranking": included,
                "weather_hours": len(w_idx),
                "demand_hours": len(d_ser),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify joint weather+demand period (V4)")
    parser.add_argument(
        "--hourly-cf",
        default="output/dunkelflaute/hourly_capacity_factors.csv",
    )
    parser.add_argument(
        "--demand-csv",
        default="data/entsoe_electricity_demand/archive/2026-02-02/electricity_demand_entsoe_raw.csv",
    )
    parser.add_argument("--demand-column", default="DE")
    parser.add_argument(
        "--output",
        default="output/historical_event_selection_v4/joint_data_period.csv",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    table = build_joint_period_table(
        REPO_ROOT / args.hourly_cf,
        REPO_ROOT / args.demand_csv,
        demand_column=args.demand_column,
    )
    out = REPO_ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False)
    eligible = table.loc[table["included_in_ranking"], "year"].tolist()
    logger.info("Joint ranking-eligible years: %s", eligible)
    logger.info("Wrote %s", out)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
