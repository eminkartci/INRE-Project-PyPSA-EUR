"""Export GAMSPy V4 model results to CSV/YAML."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from build_model_v4 import BuiltModelV4


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


def _param_map(param, key_col: str, val_col: str = "value") -> dict:
    df = param.records
    if df is None or df.empty:
        return {}
    if val_col not in df.columns:
        val_col = [c for c in df.columns if c not in (key_col,)][-1]
    return dict(zip(df[key_col], df[val_col]))


def reconcile_objective(
    built: BuiltModelV4,
    solver_objective: float | None,
    snapshot_hours: float = 3.0,
) -> dict:
    symbols = built.symbols
    w_df = _var_to_df(symbols["w"], "hours")
    weight_col = "hours" if "hours" in w_df.columns else "value"
    weight_map = dict(zip(w_df["t"], w_df[weight_col])) if not w_df.empty else {}

    marg_map = _param_map(symbols["marg"], "k")
    voll = 100_000.0
    if "voll" in symbols:
        vrec = symbols["voll"].records
        if vrec is not None and not vrec.empty and "value" in vrec.columns:
            voll = float(vrec["value"].iloc[0])

    dispatch = _var_to_df(symbols["p"], "MW")
    load_shed = _var_to_df(symbols["ls"], "MW")

    generation_cost = 0.0
    gen_by_tech: dict[str, float] = {}
    if not dispatch.empty:
        for _, row in dispatch.iterrows():
            hours = float(weight_map.get(row["t"], snapshot_hours))
            energy_mwh = float(row["MW"]) * hours
            tech = row["k"]
            gen_by_tech[tech] = gen_by_tech.get(tech, 0.0) + energy_mwh
            generation_cost += energy_mwh * float(marg_map.get(tech, 0.0))

    if "p_nuc" in symbols and "site_marg" in symbols:
        nuc_df = _var_to_df(symbols["p_nuc"], "MW")
        site_marg = _param_map(symbols["site_marg"], "s")
        for _, row in nuc_df.iterrows():
            hours = float(weight_map.get(row["t"], snapshot_hours))
            energy_mwh = float(row["MW"]) * hours
            site = row["s"]
            generation_cost += energy_mwh * float(site_marg.get(site, 0.0))
            gen_by_tech["nuclear-smr"] = gen_by_tech.get("nuclear-smr", 0.0) + energy_mwh

    voll_cost = 0.0
    if not load_shed.empty:
        for _, row in load_shed.iterrows():
            hours = float(weight_map.get(row["t"], snapshot_hours))
            voll_cost += float(row["MW"]) * hours * voll

    expected_objective = generation_cost + voll_cost
    solver_obj = float(solver_objective) if solver_objective is not None else float("nan")
    residual = solver_obj - expected_objective if solver_objective is not None else float("nan")
    residual_pct = (
        100.0 * abs(residual) / abs(solver_obj) if solver_objective is not None and abs(solver_obj) > 0 else 0.0
    )

    return {
        "solver_objective_eur": solver_obj,
        "reconstructed_generation_cost_eur": generation_cost,
        "reconstructed_voll_cost_eur": voll_cost,
        "expected_objective_eur": expected_objective,
        "residual_eur": residual,
        "residual_percent": residual_pct,
        "generation_by_tech_mwh": gen_by_tech,
    }


def compute_metrics_v4(
    built: BuiltModelV4,
    snapshot_hours: float = 3.0,
    solver_objective: float | None = None,
) -> dict:
    symbols = built.symbols
    recon = reconcile_objective(built, solver_objective, snapshot_hours)
    gen_by_tech = recon["generation_by_tech_mwh"]

    w_df = _var_to_df(symbols["w"], "hours")
    weight_col = "hours" if "hours" in w_df.columns else "value"
    weight_map = dict(zip(w_df["t"], w_df[weight_col])) if not w_df.empty else {}

    load_shed = _var_to_df(symbols["ls"], "MW")
    demand_df = symbols["demand"].records
    demand_mwh = 0.0
    if demand_df is not None and not demand_df.empty:
        for _, row in demand_df.iterrows():
            hours = float(weight_map.get(row["t"], snapshot_hours))
            demand_mwh += float(row["value"]) * hours

    eens_mwh = 0.0
    if not load_shed.empty:
        for _, row in load_shed.iterrows():
            hours = float(weight_map.get(row["t"], snapshot_hours))
            eens_mwh += float(row["MW"]) * hours
    peak_ls_mw = float(load_shed.groupby("t", observed=True)["MW"].sum().max()) if not load_shed.empty else 0.0

    co2_map = _param_map(symbols["co2"], "k")
    co2_rel_map = _param_map(symbols["co2_rel"], "k")
    co2_t = 0.0
    for tech, mwh in gen_by_tech.items():
        if tech == "nuclear-smr":
            continue
        if co2_rel_map.get(tech, 0.0) > 0.5:
            co2_t += mwh * float(co2_map.get(tech, 0.0))

    renewable_techs = {"onwind", "offshore", "solar"}
    renewable_mwh = sum(mwh for tech, mwh in gen_by_tech.items() if tech in renewable_techs)
    nuc_mwh = gen_by_tech.get("nuclear-smr", 0.0)

    return {
        "demand_mwh": demand_mwh,
        "demand_twh": demand_mwh / 1e6,
        "renewable_generation_mwh": renewable_mwh,
        "renewable_generation_twh": renewable_mwh / 1e6,
        "nuclear_generation_mwh": nuc_mwh,
        "nuclear_generation_twh": nuc_mwh / 1e6,
        "coal_generation_mwh": gen_by_tech.get("coal", 0.0),
        "coal_generation_twh": gen_by_tech.get("coal", 0.0) / 1e6,
        "lignite_generation_mwh": gen_by_tech.get("lignite", 0.0),
        "lignite_generation_twh": gen_by_tech.get("lignite", 0.0) / 1e6,
        "ccgt_generation_mwh": gen_by_tech.get("ccgt", 0.0),
        "ccgt_generation_twh": gen_by_tech.get("ccgt", 0.0) / 1e6,
        "biomass_generation_mwh": gen_by_tech.get("biomass", 0.0),
        "biomass_generation_twh": gen_by_tech.get("biomass", 0.0) / 1e6,
        "ocgt_generation_mwh": gen_by_tech.get("ocgt", 0.0),
        "ocgt_generation_twh": gen_by_tech.get("ocgt", 0.0) / 1e6,
        "oil_generation_mwh": gen_by_tech.get("oil", 0.0),
        "oil_generation_twh": gen_by_tech.get("oil", 0.0) / 1e6,
        "waste_generation_mwh": gen_by_tech.get("waste", 0.0),
        "waste_generation_twh": gen_by_tech.get("waste", 0.0) / 1e6,
        "eens_mwh": eens_mwh,
        "eens_gwh": eens_mwh / 1e3,
        "peak_load_shedding_mw": peak_ls_mw,
        "peak_load_shedding_gw": peak_ls_mw / 1e3,
        "co2_t": co2_t,
        "co2_mt": co2_t / 1e6,
        "variable_opex_excl_voll_eur": recon["reconstructed_generation_cost_eur"],
        "variable_opex_excl_voll_meur": recon["reconstructed_generation_cost_eur"] / 1e6,
        "load_shedding_penalty_eur": recon["reconstructed_voll_cost_eur"],
        "load_shedding_penalty_meur": recon["reconstructed_voll_cost_eur"] / 1e6,
        "total_operational_cost_eur": recon["expected_objective_eur"],
        "total_operational_cost_meur": recon["expected_objective_eur"] / 1e6,
        "solver_objective_eur": recon["solver_objective_eur"],
        "objective_residual_eur": recon["residual_eur"],
        "objective_residual_percent": recon["residual_percent"],
        "generation_by_tech_mwh": gen_by_tech,
    }


def export_results_v4(
    built: BuiltModelV4,
    scenario_name: str,
    output_dir: Path,
    solve_summary: dict | None = None,
    snapshot_hours: float = 3.0,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = built.symbols

    dispatch = _var_to_df(symbols["p"], "MW")
    if not dispatch.empty:
        dispatch.to_csv(output_dir / "dispatch.csv", index=False)

    load_shed = _var_to_df(symbols["ls"], "MW")
    if not load_shed.empty:
        load_shed.to_csv(output_dir / "load_shedding.csv", index=False)

    if "p_nuc" in symbols:
        nuc_dispatch = _var_to_df(symbols["p_nuc"], "MW")
        if not nuc_dispatch.empty:
            nuc_dispatch.to_csv(output_dir / "nuclear_dispatch.csv", index=False)

    solver_objective = solve_summary.get("objective") if solve_summary else None
    summary = {
        "scenario": scenario_name,
        "status": solve_summary.get("status") if solve_summary else None,
        "objective": solver_objective,
    }
    summary.update(compute_metrics_v4(built, snapshot_hours, solver_objective))

    with open(output_dir / "summary.yaml", "w") as f:
        yaml.safe_dump(summary, f, sort_keys=False)

    return summary
