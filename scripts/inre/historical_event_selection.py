# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Rank rolling 14-day high-residual-load scarcity windows and export event metadata.

Uses fixed renewable capacities (2024 brownfield) for all candidate years so ranking
reflects meteorology and demand, not historical deployment.

Primary metric:

    RL_t+ = max(D_t - W_t - S_t, 0)
    I_tau = sum(RL+) / sum(D)  over H=336 hours

Run::

    python scripts/inre/historical_event_selection.py \\
        --demand-csv data/entsoe_electricity_demand/archive/2026-02-02/electricity_demand_entsoe_raw.csv \\
        --output-dir output/historical_event_selection_v4
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

HOURS_EVENT = 336
HOURS_BUFFER_EACH_SIDE = 168  # 7 days
TOP_N = 10
OVERLAP_THRESHOLD = 0.5  # fraction of window overlap to flag

# VRE scarcity thresholds for duration metrics (national fixed-capacity potential, GW)
VRE_THRESHOLDS_GW = (5.0, 10.0, 15.0)

DEFAULT_CAPACITY_NETWORK = REPO_ROOT / "results/base/networks/base_s_10_elec_.nc"


@dataclass
class FixedCapacitiesGW:
    onwind: float
    offwind_ac: float
    offwind_dc: float
    offwind_float: float
    solar: float

    @property
    def offwind_total(self) -> float:
        return self.offwind_ac + self.offwind_dc + self.offwind_float


def load_fixed_capacities_gw(network_path: Path | None = None) -> FixedCapacitiesGW:
    """Load 2024 brownfield GW capacities from solved fixed-capacity network."""
    path = network_path or DEFAULT_CAPACITY_NETWORK
    if not path.exists():
        logger.warning("Capacity network missing (%s); using credible_capacity fallback", path)
        return FixedCapacitiesGW(
            onwind=73.3320659,
            offwind_ac=11.163743,
            offwind_dc=0.0,
            offwind_float=0.0,
            solar=48.77125402,
        )
    import pypsa

    n = pypsa.Network(path)
    return FixedCapacitiesGW(
        onwind=float(n.generators.query("carrier == 'onwind'").p_nom.sum() / 1e3),
        offwind_ac=float(n.generators.query("carrier == 'offwind-ac'").p_nom.sum() / 1e3),
        offwind_dc=float(n.generators.query("carrier == 'offwind-dc'").p_nom.sum() / 1e3),
        offwind_float=float(n.generators.query("carrier == 'offwind-float'").p_nom.sum() / 1e3),
        solar=float(
            n.generators.query("carrier in ['solar', 'solar-hsat']").p_nom.sum() / 1e3
        ),
    )


def _load_hourly_cf_proxy(csv_path: Path) -> pd.DataFrame:
    """Load national hourly CF proxies from dunkelflaute hourly export or similar."""
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    return df


def load_demand_series(
    demand_csv: Path,
    demand_column: str = "DE",
    index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Load observed hourly German demand (ENTSO-E / OPSD). No synthetic fallback."""
    df = pd.read_csv(demand_csv, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    if demand_column not in df.columns:
        candidates = [c for c in df.columns if c == "DE" or c.startswith("DE")]
        if not candidates:
            raise ValueError(f"No DE demand column in {demand_csv}")
        demand_column = candidates[0]
    demand = df[demand_column].astype(float).sort_index()
    if index is not None:
        demand = demand.reindex(index)
        missing = int(demand.isna().sum())
        if missing:
            raise ValueError(
                f"Demand missing {missing} hours overlapping CF index "
                f"({demand_csv}, column={demand_column})"
            )
    return demand


def compute_residual_metrics(
    demand_mw: pd.Series,
    wind_on_cf: pd.Series,
    wind_off_cf: pd.Series,
    solar_cf: pd.Series,
    capacities: FixedCapacitiesGW,
) -> pd.DataFrame:
    w_pot = (
        wind_on_cf * capacities.onwind + wind_off_cf * capacities.offwind_total
    ) * 1000.0
    s_pot = solar_cf * capacities.solar * 1000.0
    rl = demand_mw - w_pot - s_pot
    rl_pos = rl.clip(lower=0.0)
    vre = w_pot + s_pot
    return pd.DataFrame(
        {
            "demand_mw": demand_mw,
            "w_pot_mw": w_pot,
            "s_pot_mw": s_pot,
            "rl_mw": rl,
            "rl_pos_mw": rl_pos,
            "vre_mw": vre,
            "wind_on_cf": wind_on_cf,
            "wind_off_cf": wind_off_cf,
            "solar_cf": solar_cf,
        }
    )


def _overlap_fraction(
    start_a: pd.Timestamp,
    end_a: pd.Timestamp,
    start_b: pd.Timestamp,
    end_b: pd.Timestamp,
    window_hours: int = HOURS_EVENT,
) -> float:
    overlap = min(end_a, end_b) - max(start_a, start_b)
    if overlap.total_seconds() <= 0:
        return 0.0
    return overlap / pd.Timedelta(hours=window_hours)


def _duration_below_vre_thresholds(vre_mw: pd.Series, thresholds_gw: tuple[float, ...]) -> dict[str, int]:
    vre_gw = vre_mw / 1000.0
    return {f"hours_below_{int(t)}gw_vre": int((vre_gw < t).sum()) for t in thresholds_gw}


def rolling_windows(
    df: pd.DataFrame,
    hours: int = HOURS_EVENT,
    thresholds_gw: tuple[float, ...] = VRE_THRESHOLDS_GW,
) -> pd.DataFrame:
    records = []
    for start in range(len(df) - hours + 1):
        sl = df.iloc[start : start + hours]
        tau = sl.index[0]
        i_tau = sl["rl_pos_mw"].sum() / sl["demand_mw"].sum()
        di_tau = 1.0 - sl["vre_mw"].sum() / sl["demand_mw"].sum()
        roll48 = sl["vre_mw"].rolling(48, min_periods=48).mean().min() / 1000.0
        dur = _duration_below_vre_thresholds(sl["vre_mw"], thresholds_gw)
        records.append(
            {
                "start": tau,
                "end": sl.index[-1],
                "year": tau.year,
                "i_tau": float(i_tau),
                "di_tau": float(di_tau),
                "mean_rl_mw": float(sl["rl_mw"].mean()),
                "max_rl_mw": float(sl["rl_mw"].max()),
                "cumulative_rl_gwh": float(sl["rl_pos_mw"].sum() / 1000.0),
                "mean_onwind_cf": float(sl["wind_on_cf"].mean()),
                "mean_offwind_cf": float(sl["wind_off_cf"].mean()),
                "mean_solar_cf": float(sl["solar_cf"].mean()),
                "min_rolling_vre_gw": float(roll48) if pd.notna(roll48) else float("nan"),
                **dur,
            }
        )
    return pd.DataFrame(records).sort_values("i_tau", ascending=False).reset_index(drop=True)


def flag_overlaps(candidates: pd.DataFrame, threshold: float = OVERLAP_THRESHOLD) -> pd.DataFrame:
    """
    Group strongly overlapping windows and mark exactly one primary independent
    candidate per group (highest I_tau).
    """
    candidates = candidates.sort_values("i_tau", ascending=False).reset_index(drop=True)
    n = len(candidates)
    groups = np.full(n, -1, dtype=int)
    group_id = 0

    for i in range(n):
        if groups[i] >= 0:
            continue
        groups[i] = group_id
        start_i = candidates.at[i, "start"]
        end_i = candidates.at[i, "end"]
        for j in range(i + 1, n):
            if groups[j] >= 0:
                continue
            frac = _overlap_fraction(
                start_i,
                end_i,
                candidates.at[j, "start"],
                candidates.at[j, "end"],
            )
            if frac >= threshold:
                groups[j] = group_id
        group_id += 1

    candidates = candidates.copy()
    candidates["overlap_group"] = groups
    candidates["is_primary_independent"] = False
    for gid in range(group_id):
        idx = candidates.index[candidates["overlap_group"] == gid]
        best = candidates.loc[idx, "i_tau"].idxmax()
        candidates.at[best, "is_primary_independent"] = True
    # Legacy alias kept for downstream readers
    candidates["is_non_overlapping"] = candidates["is_primary_independent"]
    return candidates


def select_top_independent(
    windows: pd.DataFrame,
    top_n: int = TOP_N,
    threshold: float = OVERLAP_THRESHOLD,
) -> pd.DataFrame:
    """Greedy selection of top-N primary-independent windows with low mutual overlap."""
    flagged = flag_overlaps(windows, threshold=threshold)
    primaries = flagged[flagged["is_primary_independent"]].sort_values("i_tau", ascending=False)
    selected: list[pd.Series] = []
    for _, row in primaries.iterrows():
        if len(selected) >= top_n:
            break
        if all(
            _overlap_fraction(row["start"], row["end"], s["start"], s["end"]) < threshold
            for s in selected
        ):
            selected.append(row)
    if not selected:
        return primaries.head(top_n)
    return pd.DataFrame(selected).reset_index(drop=True)


def select_main_event(candidates: pd.DataFrame) -> pd.Series:
    top = select_top_independent(candidates, top_n=1)
    if top.empty:
        return candidates.iloc[0]
    return top.iloc[0]


def run_selection(
    hourly_cf_path: Path,
    demand_csv: Path,
    demand_column: str = "DE",
    capacity_network: Path | None = None,
    ranking_years: list[int] | None = None,
) -> dict:
    capacities = load_fixed_capacities_gw(capacity_network)
    cf = _load_hourly_cf_proxy(hourly_cf_path)

    if ranking_years:
        cf = cf[cf.index.year.isin(ranking_years)]
        if cf.empty:
            raise ValueError(f"No CF data for ranking years {ranking_years}")

    demand = load_demand_series(demand_csv, demand_column=demand_column, index=cf.index)

    metrics = compute_residual_metrics(
        demand,
        cf["wind_onshore_cf"],
        cf["wind_offshore_cf"],
        cf["solar_pv_cf"],
        capacities,
    )
    windows = rolling_windows(metrics)
    flagged = flag_overlaps(windows)
    top = select_top_independent(windows, top_n=TOP_N)
    main = select_main_event(windows)

    core_start = main["start"]
    sim_start = core_start - pd.Timedelta(hours=HOURS_BUFFER_EACH_SIDE)
    sim_end = main["end"] + pd.Timedelta(hours=HOURS_BUFFER_EACH_SIDE)

    return {
        "version": "v4",
        "fixed_capacities_gw": {
            "onwind": capacities.onwind,
            "offwind_ac": capacities.offwind_ac,
            "offwind_dc": capacities.offwind_dc,
            "offwind_float": capacities.offwind_float,
            "offwind_total": capacities.offwind_total,
            "solar": capacities.solar,
        },
        "demand_source": str(demand_csv),
        "demand_column": demand_column,
        "metric": "I_tau = sum(RL+)/sum(D), H=336h",
        "overlap_threshold": OVERLAP_THRESHOLD,
        "main_event": {
            "definition": "worst observed non-overlapping 14-day high-residual-load event",
            "core_start": core_start.isoformat(),
            "core_end": main["end"].isoformat(),
            "simulation_start": sim_start.isoformat(),
            "simulation_end": sim_end.isoformat(),
            "buffer_days_each_side": HOURS_BUFFER_EACH_SIDE / 24,
            "simulation_days": (HOURS_EVENT + 2 * HOURS_BUFFER_EACH_SIDE) / 24,
            "i_tau": float(main["i_tau"]),
            "di_tau": float(main["di_tau"]),
            "year": int(main["year"]),
        },
        "top_candidates": top.assign(
            start=top["start"].astype(str), end=top["end"].astype(str)
        ).to_dict(orient="records"),
        "all_windows_flagged_count": int(len(flagged)),
        "independent_primary_count": int(flagged["is_primary_independent"].sum()),
        "percentiles": {
            "p95_i_tau": float(windows["i_tau"].quantile(0.95)),
            "p99_i_tau": float(windows["i_tau"].quantile(0.99)),
        },
        "note": (
            "V4 ranking uses observed demand (no synthetic fallback). "
            "Restrict ranking_years to joint weather+demand coverage."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical Dunkelflaute event selection (V4)")
    parser.add_argument(
        "--hourly-cf",
        default="output/dunkelflaute/hourly_capacity_factors.csv",
    )
    parser.add_argument(
        "--demand-csv",
        default="data/entsoe_electricity_demand/archive/2026-02-02/electricity_demand_entsoe_raw.csv",
        help="Observed hourly DE demand (ENTSO-E or OPSD); required",
    )
    parser.add_argument("--demand-column", default="DE")
    parser.add_argument("--capacity-network", default=str(DEFAULT_CAPACITY_NETWORK))
    parser.add_argument(
        "--ranking-years",
        nargs="*",
        type=int,
        default=None,
        help="Limit ranking to years with joint weather+demand (e.g. 2021)",
    )
    parser.add_argument(
        "--output-dir",
        default="output/historical_event_selection_v4",
    )
    parser.add_argument(
        "--metadata-path",
        default="data/inre/dunkelflaute.historical.metadata.v4.yaml",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    out_dir = REPO_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_selection(
        REPO_ROOT / args.hourly_cf,
        REPO_ROOT / args.demand_csv,
        demand_column=args.demand_column,
        capacity_network=REPO_ROOT / args.capacity_network,
        ranking_years=args.ranking_years,
    )

    meta_path = REPO_ROOT / args.metadata_path
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(yaml.safe_dump(result, sort_keys=False))

    json_path = out_dir / "event_selection.json"
    json_path.write_text(json.dumps(result, indent=2))

    pd.DataFrame(result["top_candidates"]).to_csv(out_dir / "top_candidates.csv", index=False)
    logger.info("Main event: %s to %s", result["main_event"]["core_start"], result["main_event"]["core_end"])
    logger.info("Wrote %s and %s", meta_path, json_path)


if __name__ == "__main__":
    main()
