# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Modelled marginal electricity price extraction and statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa

from scripts.inre.final_report.data_loaders import VOLL, national_demand_gw, snapshot_weight
from scripts.inre.report_style import short_scenario


def demand_weighted_system_price(n: pypsa.Network, snaps: pd.DatetimeIndex | None = None) -> pd.Series:
    snaps = snaps if snaps is not None else pd.DatetimeIndex(n.snapshots)
    loads = n.loads_t.p_set.reindex(snaps).fillna(0.0)
    mp = n.buses_t.marginal_price.reindex(snaps).fillna(0.0)
    demand = loads.sum(axis=1)
    num = (loads * mp).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = num / demand.replace(0, np.nan)
    return p.fillna(0.0)


def nodal_price_band(n: pypsa.Network, snaps: pd.DatetimeIndex | None = None) -> tuple[pd.Series, pd.Series]:
    snaps = snaps if snaps is not None else pd.DatetimeIndex(n.snapshots)
    mp = n.buses_t.marginal_price.reindex(snaps)
    return mp.min(axis=1), mp.max(axis=1)


def validate_prices(n: pypsa.Network, scenario_key: str) -> dict:
    mp = n.buses_t.marginal_price
    ls = n.generators[n.generators.carrier == "load_shed"]
    issues = []
    if mp.empty:
        issues.append("marginal_price missing")
    if mp.isna().any().any() or np.isinf(mp.values).any():
        issues.append("NaN or infinite marginal prices")
    voll_mc = float(ls.marginal_cost.iloc[0]) if len(ls) else np.nan
    if len(ls) and abs(voll_mc - VOLL) > 1:
        issues.append(f"load_shed marginal_cost={voll_mc}, expected {VOLL}")
    p_sys = demand_weighted_system_price(n)
    ls_p = n.generators_t.p[ls.index].sum(axis=1) if len(ls) else pd.Series(0, index=p_sys.index)
    near_voll = (p_sys >= 0.99 * VOLL) & (ls_p > 0)
    return {
        "scenario": scenario_key,
        "has_marginal_price": not mp.empty,
        "units": "EUR/MWh",
        "voll_mc": voll_mc,
        "snapshots_near_voll": int(near_voll.sum()),
        "max_system_price": float(p_sys.max()),
        "issues": issues,
        "ok": len(issues) == 0,
    }


def price_statistics(n: pypsa.Network, scenario_key: str, label: str | None = None) -> dict:
    p = demand_weighted_system_price(n)
    w = snapshot_weight(n, pd.DatetimeIndex(n.snapshots))
    w_norm = w / w.sum()
    ls = n.generators[n.generators.carrier == "load_shed"]
    ls_p = n.generators_t.p[ls.index].sum(axis=1) if len(ls) else pd.Series(0, index=p.index)
    near_voll = ((p >= 0.99 * VOLL) & (ls_p > 0)).sum()
    return {
        "scenario": label or short_scenario(scenario_key),
        "scenario_key": scenario_key,
        "mean_EUR_per_MWh": float((p * w_norm).sum()),
        "median": float(p.median()),
        "P90": float(p.quantile(0.90)),
        "P95": float(p.quantile(0.95)),
        "P99": float(p.quantile(0.99)),
        "maximum": float(p.max()),
        "snapshots_above_100_EUR_per_MWh": int((p > 100).sum()),
        "snapshots_above_500_EUR_per_MWh": int((p > 500).sum()),
        "snapshots_near_VOLL": int(near_voll),
        "price_definition": "Demand-weighted national average nodal marginal price (3-hourly)",
    }


def price_duration_curve(p: pd.Series) -> pd.Series:
    return p.sort_values(ascending=False).reset_index(drop=True)
