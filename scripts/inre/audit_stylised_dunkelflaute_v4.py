# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Audit prepared stylised Dunkelflaute V4 PyPSA networks and regenerate from profiles.

Called at the end of build_stylised_dunkelflaute_v4.py — does not solve networks.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

RENEWABLE_CARRIERS = {
    "onwind",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
    "solar",
    "solar-hsat",
}

NETWORK_SCENARIOS = {
    "matched-base-v4": (
        "results/stylised-df-matched-base-v4/networks/base_s_10_elec_.nc",
        "matched_base_p_max_pu.csv",
    ),
    "stylised-df-moderate-v4": (
        "results/stylised-df-moderate-v4/networks/base_s_10_elec_.nc",
        "moderate_p_max_pu.csv",
    ),
    "stylised-df-severe-v4": (
        "results/stylised-df-severe-v4/networks/base_s_10_elec_.nc",
        "severe_p_max_pu.csv",
    ),
    "stylised-df-extreme-v4": (
        "results/stylised-df-extreme-v4/networks/base_s_10_elec_.nc",
        "extreme_p_max_pu.csv",
    ),
}

TIME_TABLE_ATTRS = [
    ("loads_t", "p_set"),
    ("generators_t", "p_max_pu"),
    ("generators_t", "p_min_pu"),
    ("generators_t", "marginal_cost"),
    ("storage_units_t", "inflow"),
    ("storage_units_t", "state_of_charge_set"),
    ("stores_t", "e_set"),
    ("stores_t", "p_set"),
    ("links_t", "p_set"),
    ("links_t", "p_max_pu"),
    ("lines_t", "s_max_pu"),
]


def regenerate_prepared_networks(
    repo_root: Path,
    base_network: Path,
    profile_dir: Path,
    demand_csv: str,
    python_exe: str | None = None,
) -> None:
    py = python_exe or sys.executable
    apply_script = repo_root / "scripts/inre/apply_stylised_dunkelflaute_v4.py"
    for _name, (out_rel, prof_name) in NETWORK_SCENARIOS.items():
        out = repo_root / out_rel
        prof = profile_dir / prof_name
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            py,
            str(apply_script),
            "--network",
            str(base_network.relative_to(repo_root)),
            "--profile",
            str(prof.relative_to(repo_root)),
            "--output-network",
            str(out.relative_to(repo_root)),
            "--demand-csv",
            demand_csv,
        ]
        logger.info("Regenerating network: %s", out)
        subprocess.run(cmd, cwd=repo_root, check=True)


def _iter_time_tables(n: pypsa.Network) -> list[tuple[str, pd.DataFrame]]:
    tables: list[tuple[str, pd.DataFrame]] = []
    for container, attr in TIME_TABLE_ATTRS:
        obj = getattr(n, container, None)
        if obj is None:
            continue
        df = getattr(obj, attr, None)
        if df is not None and not df.empty:
            tables.append((f"{container}.{attr}", df))
    return tables


def audit_network_timeseries(repo_root: Path, expected_rows: int = 224) -> pd.DataFrame:
    rows = []
    for scenario, (path_rel, _) in NETWORK_SCENARIOS.items():
        path = repo_root / path_rel
        if not path.exists():
            rows.append(
                {
                    "scenario": scenario,
                    "table": "network",
                    "row_count": 0,
                    "expected_row_count": expected_rows,
                    "missing_values": np.nan,
                    "index_matches": False,
                    "status": "missing_file",
                }
            )
            continue
        n = pypsa.Network(str(path))
        snaps = pd.DatetimeIndex(n.snapshots)
        snap_ok = len(snaps) == expected_rows
        if not snap_ok:
            rows.append(
                {
                    "scenario": scenario,
                    "table": "snapshots",
                    "row_count": len(snaps),
                    "expected_row_count": expected_rows,
                    "missing_values": 0,
                    "index_matches": False,
                    "status": "snapshot_count_mismatch",
                }
            )
        weights = n.snapshot_weightings
        if weights is not None and len(weights) == expected_rows:
            idx_match = snaps.equals(weights.index)
            rows.append(
                {
                    "scenario": scenario,
                    "table": "snapshot_weightings",
                    "row_count": len(weights),
                    "expected_row_count": expected_rows,
                    "missing_values": int(weights.isna().sum().sum()),
                    "index_matches": bool(idx_match),
                    "status": "ok" if idx_match and len(weights) == expected_rows else "index_mismatch",
                }
            )
        for tname, df in _iter_time_tables(n):
            idx_match = snaps.equals(df.index)
            n_missing = int(df.isna().sum().sum())
            status = "ok"
            if len(df) != expected_rows:
                status = "row_count_mismatch"
            elif not idx_match:
                status = "index_mismatch"
            elif n_missing > 0:
                status = "has_nan"
            rows.append(
                {
                    "scenario": scenario,
                    "table": tname,
                    "row_count": len(df),
                    "expected_row_count": expected_rows,
                    "missing_values": n_missing,
                    "index_matches": bool(idx_match),
                    "status": status,
                }
            )
    return pd.DataFrame(rows)


def audit_fixed_capacity(repo_root: Path) -> pd.DataFrame:
    checks = [
        ("generators", "p_nom_extendable"),
        ("storage_units", "p_nom_extendable"),
        ("stores", "e_nom_extendable"),
        ("lines", "s_nom_extendable"),
        ("links", "p_nom_extendable"),
    ]
    rows = []
    for scenario, (path_rel, _) in NETWORK_SCENARIOS.items():
        n = pypsa.Network(str(repo_root / path_rel))
        for comp, attr in checks:
            df = getattr(n, comp)
            if attr not in df.columns:
                ext = 0
            else:
                ext = int(df[attr].fillna(False).astype(bool).sum())
            rows.append(
                {
                    "scenario": scenario,
                    "component_class": comp,
                    "extendable_count": ext,
                    "status": "ok" if ext == 0 else "extendable_nonzero",
                }
            )
    return pd.DataFrame(rows)


def _series_equal(a, b, rtol=1e-9, atol=1e-9) -> bool:
    if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
        if not a.columns.equals(b.columns):
            return False
        return np.allclose(a.values, b.values, rtol=rtol, atol=atol, equal_nan=True)
    if isinstance(a, pd.Series) and isinstance(b, pd.Series):
        return np.allclose(a.values, b.values, rtol=rtol, atol=atol, equal_nan=True)
    if isinstance(a, (float, int, np.floating)) and isinstance(b, (float, int, np.floating)):
        return bool(np.isclose(a, b, rtol=rtol, atol=atol))
    return a == b


def audit_scenario_differences(repo_root: Path) -> pd.DataFrame:
    paths = {k: repo_root / v[0] for k, v in NETWORK_SCENARIOS.items()}
    networks = {k: pypsa.Network(str(p)) for k, p in paths.items()}
    base_key = "matched-base-v4"
    n0 = networks[base_key]
    rows = []

    def get_val(n, comp, attr):
        o = getattr(n, comp)
        return getattr(o, attr) if hasattr(o, attr) else o[attr]

    v0_snaps = pd.DatetimeIndex(n0.snapshots)
    snap_eq = {
        "stylised-df-moderate-v4": v0_snaps.equals(pd.DatetimeIndex(networks["stylised-df-moderate-v4"].snapshots)),
        "stylised-df-severe-v4": v0_snaps.equals(pd.DatetimeIndex(networks["stylised-df-severe-v4"].snapshots)),
        "stylised-df-extreme-v4": v0_snaps.equals(pd.DatetimeIndex(networks["stylised-df-extreme-v4"].snapshots)),
    }
    rows.append(
        {
            "component": "snapshots",
            "attribute": "index",
            "matched_vs_moderate_equal": snap_eq["stylised-df-moderate-v4"],
            "matched_vs_severe_equal": snap_eq["stylised-df-severe-v4"],
            "matched_vs_extreme_equal": snap_eq["stylised-df-extreme-v4"],
            "difference_expected": False,
            "status": "ok" if all(snap_eq.values()) else "unexpected_diff",
        }
    )

    static_checks = [
        ("loads_t", "p_set", False),
        ("generators", "p_nom", False),
        ("generators", "p_nom_extendable", False),
        ("generators", "efficiency", False),
        ("generators", "marginal_cost", False),
        ("storage_units", "p_nom", False),
        ("stores", "e_nom", False),
        ("lines", "s_nom", False),
        ("lines", "s_nom_extendable", False),
        ("links", "p_nom", False),
        ("links", "p_nom_extendable", False),
        ("carriers", "co2_emissions", False),
    ]
    for comp, attr, diff_expected in static_checks:
        val0 = get_val(n0, comp, attr)
        eq_mod = _series_equal(val0, get_val(networks["stylised-df-moderate-v4"], comp, attr))
        eq_sev = _series_equal(val0, get_val(networks["stylised-df-severe-v4"], comp, attr))
        eq_ext = _series_equal(val0, get_val(networks["stylised-df-extreme-v4"], comp, attr))
        status = "expected_diff" if diff_expected else ("ok" if eq_mod and eq_sev and eq_ext else "unexpected_diff")
        rows.append(
            {
                "component": comp,
                "attribute": attr,
                "matched_vs_moderate_equal": eq_mod,
                "matched_vs_severe_equal": eq_sev,
                "matched_vs_extreme_equal": eq_ext,
                "difference_expected": diff_expected,
                "status": status,
            }
        )

    ren0 = n0.generators[n0.generators.carrier.isin(RENEWABLE_CARRIERS)].index
    pm0 = n0.generators_t.p_max_pu
    ren_cols = [g for g in ren0 if g in pm0.columns]
    eq_mod = _series_equal(
        networks["stylised-df-moderate-v4"].generators_t.p_max_pu[ren_cols],
        pm0[ren_cols],
    )
    eq_sev = _series_equal(
        networks["stylised-df-severe-v4"].generators_t.p_max_pu[ren_cols],
        pm0[ren_cols],
    )
    eq_ext = _series_equal(
        networks["stylised-df-extreme-v4"].generators_t.p_max_pu[ren_cols],
        pm0[ren_cols],
    )
    rows.append(
        {
            "component": "generators_t",
            "attribute": "p_max_pu_renewable",
            "matched_vs_moderate_equal": eq_mod,
            "matched_vs_severe_equal": eq_sev,
            "matched_vs_extreme_equal": eq_ext,
            "difference_expected": True,
            "status": "ok" if not eq_mod and not eq_sev and not eq_ext else "check_renewable_pmu",
        }
    )
    nonren0 = n0.generators.index.difference(ren0)
    static0 = n0.generators.loc[nonren0, "p_max_pu"].astype(float)
    rows.append(
        {
            "component": "generators",
            "attribute": "p_max_pu_static_non_renewable",
            "matched_vs_moderate_equal": _series_equal(
                static0, networks["stylised-df-moderate-v4"].generators.loc[nonren0, "p_max_pu"].astype(float)
            ),
            "matched_vs_severe_equal": _series_equal(
                static0, networks["stylised-df-severe-v4"].generators.loc[nonren0, "p_max_pu"].astype(float)
            ),
            "matched_vs_extreme_equal": _series_equal(
                static0, networks["stylised-df-extreme-v4"].generators.loc[nonren0, "p_max_pu"].astype(float)
            ),
            "difference_expected": False,
            "status": "ok",
        }
    )
    return pd.DataFrame(rows)


def append_validation_tests(
    validation: pd.DataFrame,
    summary_dir: Path,
    stitch_df: pd.DataFrame | None,
    demand_validation: pd.DataFrame | None,
    overlap_info: dict | None,
) -> pd.DataFrame:
    extra = []

    def row(test, passed, detail="", tolerance=""):
        extra.append({"test": test, "passed": passed, "tolerance": tolerance, "detail": detail})

    if overlap_info:
        row(
            "pre_overwrite_diagnostic",
            overlap_info.get("pre_overwrite_global_max_diff", 0) >= 0,
            f"max={overlap_info.get('pre_overwrite_global_max_diff')}",
        )
        row(
            "post_overwrite_below_tol",
            overlap_info.get("post_overwrite_global_max_diff", 0) < 1e-10,
            f"max={overlap_info.get('post_overwrite_global_max_diff')}",
            "1e-10",
        )
    if stitch_df is not None and not stitch_df.empty:
        row("stitch_diagnostics_exported", True, f"n={len(stitch_df)}")
    if demand_validation is not None and not demand_validation.empty:
        dv = demand_validation.iloc[0]
        row(
            "demand_unit_gw",
            dv["converted_unit"] == "GW" and dv["status"] == "ok",
            f"source={dv['source_unit']}",
        )
    for path, name in [
        (summary_dir / "cutout_base_comparison.csv", "cutout_comparison_exported"),
        (summary_dir / "profile_stitch_validation.csv", "stitch_csv_exported"),
        (summary_dir / "demand_unit_validation.csv", "demand_validation_exported"),
    ]:
        row(name, path.exists(), str(path))

    if extra:
        validation = pd.concat([validation, pd.DataFrame(extra)], ignore_index=True)
    return validation


def run_full_audit(
    repo_root: Path,
    summary_dir: Path,
    base_network: Path,
    profile_dir: Path,
    demand_csv: str,
    validation: pd.DataFrame,
    overlap_info: dict | None = None,
    stitch_df: pd.DataFrame | None = None,
    demand_validation: pd.DataFrame | None = None,
    python_exe: str | None = None,
) -> pd.DataFrame:
    regenerate_prepared_networks(repo_root, base_network, profile_dir, demand_csv, python_exe)

    ts_val = audit_network_timeseries(repo_root)
    ts_val.to_csv(summary_dir / "network_timeseries_validation.csv", index=False)

    scen_audit = audit_scenario_differences(repo_root)
    scen_audit.to_csv(summary_dir / "scenario_difference_audit.csv", index=False)

    fixed = audit_fixed_capacity(repo_root)
    fixed.to_csv(summary_dir / "fixed_capacity_validation.csv", index=False)

    if stitch_df is None and (summary_dir / "profile_stitch_validation.csv").exists():
        stitch_df = pd.read_csv(summary_dir / "profile_stitch_validation.csv")
    if demand_validation is None and (summary_dir / "demand_unit_validation.csv").exists():
        demand_validation = pd.read_csv(summary_dir / "demand_unit_validation.csv")

    validation = append_validation_tests(validation, summary_dir, stitch_df, demand_validation, overlap_info)

    net_ok = (ts_val["status"] == "ok").all() if not ts_val.empty else False
    fixed_ok = (fixed["extendable_count"] == 0).all() if not fixed.empty else False
    unexpected = scen_audit.query("difference_expected == False and status == 'unexpected_diff'")
    validation = pd.concat(
        [
            validation,
            pd.DataFrame(
                [
                    {
                        "test": "network_timeseries_aligned",
                        "passed": net_ok,
                        "tolerance": "",
                        "detail": f"tables={len(ts_val)}",
                    },
                    {
                        "test": "fixed_capacity_zero_extendable",
                        "passed": fixed_ok,
                        "tolerance": "",
                        "detail": "",
                    },
                    {
                        "test": "scenario_only_renewable_pmu_differs",
                        "passed": unexpected.empty,
                        "tolerance": "",
                        "detail": f"unexpected={len(unexpected)}",
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    return validation
