# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Derate wind and solar availability profiles for Dunkelflaute stress scenarios.

Modifies ``n.generators_t.p_max_pu`` in place for selected carriers and time windows.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa
import yaml

logger = logging.getLogger(__name__)

DEFAULT_WIND_CARRIERS = {"onwind", "offwind-ac", "offwind-dc", "offwind-float"}
DEFAULT_SOLAR_CARRIERS = {"solar", "solar-hsat"}


def load_params(config_path: str | Path | None, overrides: dict | None = None) -> dict:
    params: dict = {}
    if config_path:
        with open(config_path) as f:
            params = yaml.safe_load(f) or {}
    if overrides:
        params.update(overrides)
    return params


def _carrier_sets(params: dict) -> tuple[set[str], set[str]]:
    carriers = params.get("carriers", {})
    wind = set(carriers.get("wind", list(DEFAULT_WIND_CARRIERS)))
    solar = set(carriers.get("solar", list(DEFAULT_SOLAR_CARRIERS)))
    return wind, solar


def _snapshot_index(n: pypsa.Network) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(n.snapshots))


def _daily_vre_score(
    n: pypsa.Network, wind_carriers: set[str], solar_carriers: set[str]
) -> pd.Series:
    """Lower score = worse Dunkelflaute (less VRE availability)."""
    p_max = n.generators_t.p_max_pu
    weights = n.generators.p_nom.reindex(p_max.columns).fillna(0.0)
    scores = []
    for carrier_set in (wind_carriers, solar_carriers):
        cols = n.generators.query("carrier in @carrier_set").index
        cols = [c for c in cols if c in p_max.columns]
        if not cols:
            continue
        weighted = p_max[cols].multiply(weights[cols], axis=1).sum(axis=1)
        scores.append(weighted)
    if not scores:
        return pd.Series(0.0, index=_snapshot_index(n))
    total = sum(scores)
    return total.groupby(total.index.normalize()).mean()


def build_time_mask(snapshots: pd.DatetimeIndex, params: dict, n: pypsa.Network) -> pd.Series:
    auto_days = params.get("auto_worst_days")
    if auto_days:
        wind_carriers, solar_carriers = _carrier_sets(params)
        daily = _daily_vre_score(n, wind_carriers, solar_carriers)
        worst_days = daily.nsmallest(int(auto_days)).index
        mask = pd.Series(False, index=snapshots)
        for day in worst_days:
            mask |= snapshots.normalize() == day.normalize()
        logger.info("Auto-selected worst VRE days: %s", [d.date() for d in worst_days])
        return mask

    start = pd.Timestamp(params.get("time_start"))
    end = pd.Timestamp(params.get("time_end"))
    mask = pd.Series(
        (snapshots >= start) & (snapshots < end + pd.Timedelta(days=1)),
        index=snapshots,
    )
    logger.info(
        "Dunkelflaute window %s to %s (%d snapshots)",
        start.date(),
        end.date(),
        int(mask.sum()),
    )
    return mask


def _ramp_weights(mask: pd.Series | np.ndarray, ramp_hours: int) -> pd.Series:
    if not ramp_hours or ramp_hours <= 0:
        if isinstance(mask, pd.Series):
            return mask.astype(float)
        return pd.Series(mask, dtype=float)

    if isinstance(mask, pd.Series):
        weights = mask.astype(float).copy()
    else:
        weights = pd.Series(mask, dtype=float)

    idx = np.arange(len(weights))
    active = idx[weights.to_numpy(dtype=bool)]
    if len(active) == 0:
        return weights

    start, end = active[0], active[-1]
    for i in range(len(weights)):
        if i < start:
            dist = start - i
            if dist < ramp_hours:
                weights.iloc[i] = max(weights.iloc[i], 1.0 - dist / ramp_hours)
        elif i > end:
            dist = i - end
            if dist < ramp_hours:
                weights.iloc[i] = max(weights.iloc[i], 1.0 - dist / ramp_hours)
    return weights


def _apply_factor(
    n: pypsa.Network,
    carriers: set[str],
    factor: float,
    mask: pd.Series,
    ramp_hours: int,
) -> None:
    if factor >= 1.0:
        return

    cols = n.generators.query("carrier in @carriers").index
    cols = [c for c in cols if c in n.generators_t.p_max_pu.columns]
    if not cols:
        logger.warning("No generators found for carriers %s", carriers)
        return

    ramp = _ramp_weights(mask, ramp_hours)
    # weight=1 inside stress window, ramps toward 1 outside; factor applied where weight>0
    multipliers = 1.0 - ramp * (1.0 - factor)
    for col in cols:
        n.generators_t.p_max_pu[col] = n.generators_t.p_max_pu[col].mul(multipliers)

    logger.info(
        "Applied factor %.2f to %d generators (%s)",
        factor,
        len(cols),
        ", ".join(sorted(carriers)),
    )


def apply_dunkelflaute(
    n: pypsa.Network,
    params: dict | None = None,
    config_path: str | Path | None = None,
) -> pypsa.Network:
    params = params or load_params(config_path)
    if not params.get("enabled", True):
        logger.info("Dunkelflaute stress disabled; network unchanged.")
        return n

    snapshots = _snapshot_index(n)
    mask = build_time_mask(snapshots, params, n)
    if not mask.any():
        logger.warning("Dunkelflaute mask is empty; no derating applied.")
        return n

    wind_carriers, solar_carriers = _carrier_sets(params)
    ramp_hours = int(params.get("ramp_hours", 0) or 0)
    _apply_factor(n, wind_carriers, float(params.get("wind_factor", 1.0)), mask, ramp_hours)
    _apply_factor(n, solar_carriers, float(params.get("solar_factor", 1.0)), mask, ramp_hours)
    return n
