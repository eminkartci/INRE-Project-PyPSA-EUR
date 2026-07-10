"""Export reduced-form GAMSPy results."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from build_model_rf import BuiltModelRF


def _var_to_df(var, value_col: str = "value") -> pd.DataFrame:
    df = var.records
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in df.columns if c not in ("marginal", "lower", "upper", "level")]
    if "level" in df.columns:
        out = df[cols + ["level"]].copy()
        return out.rename(columns={"level": value_col})
    return df.copy()


def _param_map(param, key_col: str) -> dict:
    df = param.records
    if df is None or df.empty:
        return {}
    val_col = "value" if "value" in df.columns else [c for c in df.columns if c != key_col][-1]
    return dict(zip(df[key_col], df[val_col]))


def reconcile_objective_rf(
    built: BuiltModelRF,
    solver_objective: float | None,
    snapshot_hours: float = 3.0,
) -> dict:
    symbols = built.symbols
    w_df = _var_to_df(symbols["w"], "hours")
    weight_col = "hours" if "hours" in w_df.columns else "value"
    weight_map = dict(zip(w_df["t"], w_df[weight_col])) if not w_df.empty else {}

    marg_map = _param_map(symbols["marg"], "b")
    voll = 100_000.0
    if "voll" in symbols:
        vrec = symbols["voll"].records
        if vrec is not None and not vrec.empty:
            voll = float(vrec["value"].iloc[0])

    dispatch = _var_to_df(symbols["p"], "MW")
    load_shed = _var_to_df(symbols["ls"], "MW")

    generation_cost = 0.0
    gen_by_block: dict[str, float] = {}
    for _, row in dispatch.iterrows():
        hours = float(weight_map.get(row["t"], snapshot_hours))
        energy = float(row["MW"]) * hours
        block = row["b"]
        gen_by_block[block] = gen_by_block.get(block, 0.0) + energy
        generation_cost += energy * float(marg_map.get(block, 0.0))

    voll_cost = 0.0
    for _, row in load_shed.iterrows():
        hours = float(weight_map.get(row["t"], snapshot_hours))
        voll_cost += float(row["MW"]) * hours * voll

    expected = generation_cost + voll_cost
    solver_obj = float(solver_objective) if solver_objective is not None else float("nan")
    residual = solver_obj - expected if solver_objective is not None else float("nan")
    residual_pct = 100.0 * abs(residual) / abs(solver_obj) if solver_objective and abs(solver_obj) > 0 else 0.0

    return {
        "solver_objective_eur": solver_obj,
        "generation_cost_eur": generation_cost,
        "voll_cost_eur": voll_cost,
        "expected_objective_eur": expected,
        "residual_eur": residual,
        "residual_percent": residual_pct,
        "generation_by_block_mwh": gen_by_block,
    }


def compute_metrics_rf(built: BuiltModelRF, snapshot_hours: float = 3.0, solver_objective: float | None = None) -> dict:
    recon = reconcile_objective_rf(built, solver_objective, snapshot_hours)
    gen = recon["generation_by_block_mwh"]

    symbols = built.symbols
    w_df = _var_to_df(symbols["w"], "hours")
    weight_col = "hours" if "hours" in w_df.columns else "value"
    weight_map = dict(zip(w_df["t"], w_df[weight_col])) if not w_df.empty else {}

    demand_df = symbols["demand"].records
    demand_mwh = 0.0
    if demand_df is not None and not demand_df.empty:
        for _, row in demand_df.iterrows():
            hours = float(weight_map.get(row["t"], snapshot_hours))
            demand_mwh += float(row["value"]) * hours

    load_shed = _var_to_df(symbols["ls"], "MW")
    eens_mwh = sum(
        float(row["MW"]) * float(weight_map.get(row["t"], snapshot_hours))
        for _, row in load_shed.iterrows()
    ) if not load_shed.empty else 0.0
    peak_ls = float(load_shed["MW"].max()) if not load_shed.empty else 0.0

    co2_map = _param_map(symbols["co2"], "b")
    co2_rel = _param_map(symbols["co2_rel"], "b")
    co2_t = sum(
        mwh * float(co2_map.get(block, 0.0))
        for block, mwh in gen.items()
        if co2_rel.get(block, 0.0) > 0.5
    )

    vre_mwh = gen.get("vre", 0.0)
    nuc_mwh = gen.get("nuclear", 0.0)
    firm_mwh = sum(gen.get(b, 0.0) for b in ("coal", "lignite", "ccgt", "peaker", "other_firm"))

    return {
        "demand_twh": demand_mwh / 1e6,
        "vre_generation_twh": vre_mwh / 1e6,
        "nuclear_generation_twh": nuc_mwh / 1e6,
        "firm_thermal_generation_twh": firm_mwh / 1e6,
        "eens_gwh": eens_mwh / 1e3,
        "peak_load_shedding_gw": peak_ls / 1e3,
        "co2_mt": co2_t / 1e6,
        "variable_opex_excl_voll_meur": recon["generation_cost_eur"] / 1e6,
        "load_shedding_penalty_meur": recon["voll_cost_eur"] / 1e6,
        "total_operational_cost_meur": recon["expected_objective_eur"] / 1e6,
        "solver_objective_eur": recon["solver_objective_eur"],
        "objective_residual_percent": recon["residual_percent"],
        "generation_by_block_mwh": gen,
    }


def export_results_rf(
    built: BuiltModelRF,
    scenario_name: str,
    output_dir: Path,
    solve_summary: dict | None = None,
    snapshot_hours: float = 3.0,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    dispatch = _var_to_df(built.symbols["p"], "MW")
    if not dispatch.empty:
        dispatch.to_csv(output_dir / "dispatch.csv", index=False)
    load_shed = _var_to_df(built.symbols["ls"], "MW")
    if not load_shed.empty:
        load_shed.to_csv(output_dir / "load_shedding.csv", index=False)

    solver_objective = solve_summary.get("objective") if solve_summary else None
    summary = {
        "scenario": scenario_name,
        "status": solve_summary.get("status") if solve_summary else None,
        "objective": solver_objective,
    }
    summary.update(compute_metrics_rf(built, snapshot_hours, solver_objective))

    with open(output_dir / "summary.yaml", "w") as f:
        yaml.safe_dump(summary, f, sort_keys=False)
    return summary
