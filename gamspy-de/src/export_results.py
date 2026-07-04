"""Export GAMSPy model results to CSV/YAML."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from build_model import BuiltModel


def _var_to_df(var, value_col: str = "value") -> pd.DataFrame:
    df = var.records
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in df.columns if c not in ("marginal", "lower", "upper", "level")]
    if "level" in df.columns:
        out = df[cols + ["level"]].copy()
        out = out.rename(columns={"level": value_col})
        return out
    return df.copy()


def export_results(
    built: BuiltModel,
    scenario_name: str,
    output_dir: Path,
    solve_summary: dict | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = built.symbols

    dispatch = _var_to_df(symbols["p"], "MW")
    if not dispatch.empty:
        dispatch.to_csv(output_dir / "dispatch.csv", index=False)

    investment = _var_to_df(symbols["p_cap"], "new_MW")
    if not investment.empty:
        investment = investment[investment["new_MW"] > 1e-3]
        investment.to_csv(output_dir / "investment.csv", index=False)

    storage = _var_to_df(symbols["p_st_cap"], "power_MW")
    storage_e = _var_to_df(symbols["e_cap"], "energy_MWh")
    if not storage.empty:
        storage.to_csv(output_dir / "storage_power.csv", index=False)
    if not storage_e.empty:
        storage_e.to_csv(output_dir / "storage_energy.csv", index=False)

    if "cap_nuc" in symbols:
        nuclear = _var_to_df(symbols["cap_nuc"], "built_MW")
        if not nuclear.empty:
            nuclear = nuclear[nuclear["built_MW"] > 1e-3]
            nuclear.to_csv(output_dir / "nuclear_investment.csv", index=False)

    if "p_nuc" in symbols:
        nuc_dispatch = _var_to_df(symbols["p_nuc"], "MW")
        if not nuc_dispatch.empty:
            nuc_dispatch.to_csv(output_dir / "nuclear_dispatch.csv", index=False)

    summary = {
        "scenario": scenario_name,
        "status": solve_summary.get("status") if solve_summary else None,
        "objective": solve_summary.get("objective") if solve_summary else None,
    }

    if not dispatch.empty and "MW" in dispatch.columns:
        summary["total_dispatch_MWh"] = float(
            dispatch.groupby("t", observed=True)["MW"].sum().sum() * 3.0
        )

    with open(output_dir / "summary.yaml", "w") as f:
        yaml.safe_dump(summary, f, sort_keys=False)
