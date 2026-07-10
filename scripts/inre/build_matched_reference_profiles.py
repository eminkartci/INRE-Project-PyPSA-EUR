# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Build matched-reference CF profiles (V4).

Method A — climatological matched reference:
    pointwise multi-year median by (cluster, carrier, day-of-year, hour)

Method B — historical normal reference:
  select a real non-event window in the same season with representative VRE and
  similar demand; preserve chronology and spatial correlation from that period.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _stem_parts(stem: str) -> tuple[str, str]:
    for key in (
        "offwind-float",
        "offwind-dc",
        "offwind-ac",
        "solar-hsat",
        "onwind",
        "solar",
    ):
        suffix = f"_{key}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)], key
    parts = stem.rsplit("_", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (stem, "unknown")


def build_climatological_matched_reference(
    historical_dir: Path,
    output_dir: Path,
    hourly_cf_path: Path,
) -> Path:
    """Method A: climatological matched reference (doy-hour median)."""
    hourly = pd.read_csv(hourly_cf_path, parse_dates=["timestamp"]).set_index("timestamp")
    hourly["doy"] = hourly.index.dayofyear
    hourly["hour"] = hourly.index.hour
    median = hourly.groupby(["doy", "hour"])[
        ["wind_onshore_cf", "wind_offshore_cf", "solar_pv_cf"]
    ].median()

    output_dir.mkdir(parents=True, exist_ok=True)
    for hist_file in historical_dir.glob("*_*.csv"):
        df = pd.read_csv(hist_file, parse_dates=["timestamp"])
        ts = pd.DatetimeIndex(df["timestamp"])
        doy = ts.dayofyear
        hour = ts.hour
        _, carrier = _stem_parts(hist_file.stem)
        if carrier == "onwind":
            med = [median.loc[(d, h), "wind_onshore_cf"] for d, h in zip(doy, hour, strict=True)]
        elif carrier.startswith("offwind"):
            med = [median.loc[(d, h), "wind_offshore_cf"] for d, h in zip(doy, hour, strict=True)]
        elif carrier.startswith("solar"):
            med = [median.loc[(d, h), "solar_pv_cf"] for d, h in zip(doy, hour, strict=True)]
        else:
            med = df["cf"].values
        out = pd.DataFrame({"timestamp": ts, "cf": np.clip(med, 0.0, 1.0)})
        out.to_csv(output_dir / hist_file.name, index=False)
    logger.info("Wrote climatological matched-reference profiles to %s", output_dir)
    return output_dir


def build_historical_normal_reference(
    historical_dir: Path,
    output_dir: Path,
    event_metadata_path: Path,
    hourly_cf_path: Path,
    demand_csv: Path,
    demand_column: str = "DE",
) -> tuple[Path, dict]:
    """Method B: historical normal reference from a real low-scarcity window.

    Cluster profiles apply the national reference-period CF trajectory while
    preserving cross-cluster relative shape from the severe-event export.
    Final publication requires cluster Atlite re-export for the selected window.
    """
    import yaml

    from scripts.inre.historical_event_selection import (
        compute_residual_metrics,
        load_demand_series,
        load_fixed_capacities_gw,
        rolling_windows,
    )

    meta = yaml.safe_load(event_metadata_path.read_text())
    core_start = pd.Timestamp(meta["main_event"]["core_start"])
    core_end = pd.Timestamp(meta["main_event"]["core_end"])
    core_doy = core_start.dayofyear

    hourly = pd.read_csv(hourly_cf_path, parse_dates=["timestamp"]).set_index("timestamp")
    demand = load_demand_series(demand_csv, demand_column=demand_column, index=hourly.index)
    caps = load_fixed_capacities_gw()
    metrics = compute_residual_metrics(
        demand,
        hourly["wind_onshore_cf"],
        hourly["wind_offshore_cf"],
        hourly["solar_pv_cf"],
        caps,
    )
    windows = rolling_windows(metrics)
    season = windows[
        (windows["start"].dt.dayofyear >= core_doy - 45)
        & (windows["start"].dt.dayofyear <= core_doy + 45)
    ]
    event_mean_demand = metrics.loc[core_start:core_end, "demand_mw"].mean()
    season = season[
        (season["mean_rl_mw"] < season["mean_rl_mw"].quantile(0.25))
        & (season["i_tau"] < season["i_tau"].quantile(0.25))
    ]
    if season.empty:
        season = windows.nsmallest(50, "i_tau")

    def demand_delta(row: pd.Series) -> float:
        sl = metrics.loc[row["start"] : row["end"], "demand_mw"]
        return abs(sl.mean() - event_mean_demand) / event_mean_demand

    season = season.assign(demand_delta=season.apply(demand_delta, axis=1))
    ref = season.sort_values(["demand_delta", "i_tau"]).iloc[0]

    ref_start = ref["start"]
    template = pd.read_csv(next(historical_dir.glob("*_*.csv")), parse_dates=["timestamp"])
    template_ts = pd.DatetimeIndex(template["timestamp"])
    ref_len = len(template_ts)
    ref_index = pd.date_range(ref_start, periods=ref_len, freq=pd.infer_freq(template_ts) or "3h")

    nat = metrics["vre_mw"] / (
        (caps.onwind + caps.offwind_total + caps.solar) * 1000.0
    )
    severe_nat = nat.reindex(template_ts, method="nearest").values
    ref_nat = nat.reindex(ref_index, method="nearest").values
    ratio = np.clip(ref_nat / np.maximum(severe_nat, 1e-6), 0.0, 2.0)

    output_dir.mkdir(parents=True, exist_ok=True)
    for hist_file in historical_dir.glob("*_*.csv"):
        df = pd.read_csv(hist_file, parse_dates=["timestamp"])
        substituted = np.clip(df["cf"].values * ratio[: len(df)], 0.0, 1.0)
        out = pd.DataFrame({"timestamp": template_ts, "cf": substituted})
        out.to_csv(output_dir / hist_file.name, index=False)

    info = {
        "method": "historical_normal_reference",
        "reference_window_start": ref_start.isoformat(),
        "reference_window_end": (ref_start + pd.Timedelta(hours=ref_len - 1)).isoformat(),
        "reference_i_tau": float(ref["i_tau"]),
        "reference_demand_delta_frac": float(ref["demand_delta"]),
        "label": "historical normal reference (real observed period, not climatological replay)",
        "note": "Cluster Atlite re-export for reference window required for final publication.",
    }
    (output_dir / "reference_selection.json").write_text(
        __import__("json").dumps(info, indent=2)
    )
    logger.info(
        "Wrote historical-normal reference profiles to %s (ref %s)",
        output_dir,
        ref_start,
    )
    return output_dir, info


def compare_reference_methods(
    clim_dir: Path,
    hist_norm_dir: Path,
    historical_dir: Path,
    output_path: Path,
) -> pd.DataFrame:
    rows = []
    for hist_file in historical_dir.glob("*_*.csv"):
        bus, carrier = _stem_parts(hist_file.stem)
        a = pd.read_csv(clim_dir / hist_file.name)["cf"].values
        b = pd.read_csv(hist_norm_dir / hist_file.name)["cf"].values
        h = pd.read_csv(hist_file)["cf"].values
        rows.append(
            {
                "bus": bus,
                "carrier": carrier,
                "mean_abs_diff_clim_vs_histnorm": float(np.mean(np.abs(a - b))),
                "mean_cf_climatological": float(np.mean(a)),
                "mean_cf_historical_normal": float(np.mean(b)),
                "mean_cf_historical_severe": float(np.mean(h)),
            }
        )
    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Build V4 matched-reference profile sets")
    parser.add_argument("--historical-dir", default="data/inre/profiles/historical")
    parser.add_argument(
        "--climatological-dir",
        default="data/inre/profiles/historical/matched_reference_climatological_v4",
    )
    parser.add_argument(
        "--historical-normal-dir",
        default="data/inre/profiles/historical/matched_reference_historical_normal_v4",
    )
    parser.add_argument(
        "--hourly-cf",
        default="output/dunkelflaute/hourly_capacity_factors.csv",
    )
    parser.add_argument(
        "--event-metadata",
        default="data/inre/dunkelflaute.historical.metadata.v4.yaml",
    )
    parser.add_argument(
        "--demand-csv",
        default="data/entsoe_electricity_demand/archive/2026-02-02/electricity_demand_entsoe_raw.csv",
    )
    parser.add_argument(
        "--comparison-csv",
        default="output/historical_event_selection_v4/reference_method_comparison.csv",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    hist_dir = REPO_ROOT / args.historical_dir
    build_climatological_matched_reference(
        hist_dir,
        REPO_ROOT / args.climatological_dir,
        REPO_ROOT / args.hourly_cf,
    )
    build_historical_normal_reference(
        hist_dir,
        REPO_ROOT / args.historical_normal_dir,
        REPO_ROOT / args.event_metadata,
        REPO_ROOT / args.hourly_cf,
        REPO_ROOT / args.demand_csv,
    )
    compare_reference_methods(
        REPO_ROOT / args.climatological_dir,
        REPO_ROOT / args.historical_normal_dir,
        hist_dir,
        REPO_ROOT / args.comparison_csv,
    )


if __name__ == "__main__":
    main()
