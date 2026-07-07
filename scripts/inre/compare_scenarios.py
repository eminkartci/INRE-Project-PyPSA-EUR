# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Compare solved INRE scenario networks and export report-ready KPI tables and charts.

Energy values are integrated over the simulation window (not annualised).
Outputs in ``results/inre-comparison/`` are suitable for direct use in reports.

Usage (from repository root)::

    python scripts/inre/compare_scenarios.py --output-dir results/inre-comparison
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

SCENARIO_PRESETS = {
    "core": [
        "base:base",
        "dunkelflaute:dunkelflaute",
        "dunkelflaute-smr:dunkelflaute-smr",
        "dunkelflaute-msr:dunkelflaute-msr",
        "dunkelflaute-lfr:dunkelflaute-lfr",
    ],
    "capex": [
        "smr-capex70:dunkelflaute-smr-capex70",
        "smr-capex85:dunkelflaute-smr-capex85",
        "smr-capex100:dunkelflaute-smr",
        "smr-capex115:dunkelflaute-smr-capex115",
    ],
    "full": None,
}

NUCLEAR_CARRIERS = {"nuclear-smr", "nuclear-msr", "nuclear-lfr", "nuclear", "SMR", "MSR", "LFR"}
NON_GENERATION_CARRIERS = {
    "AC",
    "DC",
    "Battery Storage",
    "Hydrogen Storage",
    "H2 Electrolysis",
    "H2 Fuel Cell",
}


def _is_wind(carrier: str) -> bool:
    return "wind" in carrier.lower()


def _is_solar(carrier: str) -> bool:
    return "solar" in carrier.lower()


def _network_path(run_name: str, clusters: str, opts: str) -> Path:
    opts_token = opts if opts else ""
    return (
        REPO_ROOT
        / "results"
        / run_name
        / "networks"
        / f"base_s_{clusters}_elec_{opts_token}.nc"
    )


def _period_hours(n: pypsa.Network) -> float:
    weight = n.snapshot_weightings.objective.reindex(n.snapshots).fillna(1.0)
    return float(weight.sum())


def _load_twh(n: pypsa.Network) -> float:
    weight = n.snapshot_weightings.objective.reindex(n.snapshots).fillna(1.0)
    return float(n.loads_t.p_set.mul(weight, axis=0).sum().sum()) / 1e6


def _co2_emissions_t(n: pypsa.Network) -> float:
    if not hasattr(n, "generators_t") or "p" not in n.generators_t:
        return 0.0
    weight = n.snapshot_weightings.objective.reindex(n.snapshots).fillna(1.0)
    emissions = n.generators.carrier.map(n.carriers.co2_emissions).fillna(0.0)
    gen_p = n.generators_t.p.fillna(0.0)
    total = 0.0
    for gen in gen_p.columns:
        if gen in emissions.index:
            total += (gen_p[gen] * weight * emissions[gen]).sum()
    return float(total)


def _co2_by_carrier_kt(n: pypsa.Network) -> pd.Series:
    weight = n.snapshot_weightings.objective.reindex(n.snapshots).fillna(1.0)
    emissions = n.generators.carrier.map(n.carriers.co2_emissions).fillna(0.0)
    gen_p = n.generators_t.p.fillna(0.0)
    by_carrier: dict[str, float] = {}
    for gen in gen_p.columns:
        carrier = n.generators.at[gen, "carrier"]
        co2 = emissions.get(gen, emissions.get(carrier, 0.0))
        by_carrier[carrier] = by_carrier.get(carrier, 0.0) + float(
            (gen_p[gen] * weight * co2).sum()
        )
    return pd.Series(by_carrier) / 1e3


def _group_by_carrier(series: pd.Series) -> pd.Series:
    if isinstance(series.index, pd.MultiIndex):
        grouped = series.groupby(level="carrier").sum()
    else:
        grouped = series.groupby(series.index).sum()
    return grouped


def _generator_capacity_mw(n: pypsa.Network, carrier: str) -> tuple[float, float]:
    gens = n.generators.query("carrier == @carrier")
    if gens.empty:
        return 0.0, 0.0
    p_nom = float(gens.p_nom.sum())
    p_nom_opt = float(gens.p_nom_opt.sum()) if "p_nom_opt" in gens.columns else p_nom
    return p_nom, p_nom_opt


def _wind_capacity_mw(n: pypsa.Network) -> tuple[float, float]:
    wind = n.generators[n.generators.carrier.str.contains("wind", case=False, na=False)]
    if wind.empty:
        return 0.0, 0.0
    return float(wind.p_nom.sum()), float(wind.p_nom_opt.sum())


def _solar_capacity_mw(n: pypsa.Network) -> tuple[float, float]:
    solar = n.generators[n.generators.carrier.str.contains("solar", case=False, na=False)]
    if solar.empty:
        return 0.0, 0.0
    return float(solar.p_nom.sum()), float(solar.p_nom_opt.sum())


def _credible_capacity(n: pypsa.Network) -> dict[str, float]:
    wind_nom, _ = _wind_capacity_mw(n)
    solar_nom, _ = _solar_capacity_mw(n)
    _, ccgt_opt = _generator_capacity_mw(n, "CCGT")
    nuclear_mw = float(
        n.generators.query("carrier in @NUCLEAR_CARRIERS").p_nom_opt.sum()
        if len(n.generators)
        else 0.0
    )
    battery_su = n.storage_units.query("carrier == 'battery'") if hasattr(n, "storage_units") else None
    battery_power_mw = float(battery_su.p_nom_opt.sum()) if battery_su is not None and len(battery_su) else 0.0
    battery_energy_mwh = (
        float((battery_su.p_nom_opt * battery_su.max_hours).sum())
        if battery_su is not None and len(battery_su)
        else 0.0
    )
    return {
        "existing_wind_gw": wind_nom / 1e3,
        "existing_solar_gw": solar_nom / 1e3,
        "ccgt_gw": ccgt_opt / 1e3,
        "nuclear_mw": nuclear_mw,
        "battery_storageunit_power_mw": battery_power_mw,
        "battery_storageunit_energy_mwh": battery_energy_mwh,
    }


def extract_kpis(n: pypsa.Network, label: str) -> dict:
    supply = n.statistics.supply(comps=["Generator"]).dropna()
    supply_by_carrier = _group_by_carrier(supply)
    supply_by_carrier = supply_by_carrier.drop(
        labels=[c for c in NON_GENERATION_CARRIERS if c in supply_by_carrier.index],
        errors="ignore",
    )
    supply_twh = supply_by_carrier / 1e6

    cap = n.statistics.optimal_capacity().dropna()
    cap_by_carrier = _group_by_carrier(cap)
    cap_gw = cap_by_carrier / 1e3

    capex = float(n.statistics.capex().sum())
    opex = float(n.statistics.opex().sum())

    weight = n.snapshot_weightings.objective.reindex(n.snapshots).fillna(1.0)
    nyears = float(weight.sum() / 8760.0)

    # statistics.optimal_capacity() returns MW by component; keep nuclear in MW (no extra scaling)
    nuclear_mw = float(cap_by_carrier.reindex(NUCLEAR_CARRIERS).fillna(0.0).sum())

    # Battery (StorageUnit carrier) is more credible than link-based charger/discharger capacities.
    battery_su = n.storage_units.query("carrier == 'battery'") if hasattr(n, "storage_units") else None
    battery_power_mw = float(battery_su.p_nom_opt.sum()) if battery_su is not None and len(battery_su) else 0.0
    battery_energy_mwh = (
        float((battery_su.p_nom_opt * battery_su.max_hours).sum())
        if battery_su is not None and len(battery_su)
        else 0.0
    )

    return {
        "scenario": label,
        "period_hours": _period_hours(n),
        "nyears": nyears,
        "load_twh": _load_twh(n),
        "objective_eur": float(n.objective),
        "capex_eur": capex,
        "capex_period_eur": capex * nyears,
        "opex_eur": opex,
        "co2_t": _co2_emissions_t(n),
        "co2_by_carrier_kt": _co2_by_carrier_kt(n),
        "supply_by_carrier_twh": supply_twh,
        "capacity_by_carrier_gw": cap_gw,
        "nuclear_build_mw": float(nuclear_mw),
        "battery_storageunit_power_mw": battery_power_mw,
        "battery_storageunit_energy_mwh": battery_energy_mwh,
        "credible_capacity": _credible_capacity(n),
    }


def build_report_summary(kpis: list[dict]) -> pd.DataFrame:
    rows = []
    base_opex = kpis[0]["opex_eur"] if kpis else 0.0
    base_co2 = kpis[0]["co2_t"] if kpis else 0.0

    for k in kpis:
        load_mwh = k["load_twh"] * 1e6
        opex_per_mwh = k["opex_eur"] / load_mwh if load_mwh else float("nan")
        objective_per_mwh = k["objective_eur"] / load_mwh if load_mwh else float("nan")
        co2_kt = k["co2_t"] / 1e3
        lco2_opex = (k["opex_eur"] / 1e3) / co2_kt if co2_kt else float("nan")
        lco2_objective = (k["objective_eur"] / 1e3) / co2_kt if co2_kt else float("nan")
        rows.append(
            {
                "scenario": k["scenario"],
                "period_hours": k["period_hours"],
                "nyears": round(k["nyears"], 6),
                "load_twh": round(k["load_twh"], 2),
                "generation_twh": round(k["supply_by_carrier_twh"].sum(), 2),
                "opex_meur": round(k["opex_eur"] / 1e6, 1),
                "capex_annuitised_meur": round(k["capex_eur"] / 1e6, 1),
                "capex_period_meur": round(k["capex_period_eur"] / 1e6, 1),
                "objective_meur": round(k["objective_eur"] / 1e6, 1),
                "co2_kt": round(co2_kt, 0),
                "nuclear_build_mw": round(k["nuclear_build_mw"], 4),
                "battery_storageunit_power_mw": round(k["battery_storageunit_power_mw"], 3),
                "battery_storageunit_energy_mwh": round(k["battery_storageunit_energy_mwh"], 3),
                "operational_lcoe_eur_per_mwh": round(opex_per_mwh, 1),
                "period_all_in_lcoe_eur_per_mwh": round(objective_per_mwh, 1),
                "operational_lco2_eur_per_tco2": round(lco2_opex, 0),
                "period_all_in_lco2_eur_per_tco2": round(lco2_objective, 0),
                "delta_opex_meur_vs_base": round((k["opex_eur"] - base_opex) / 1e6, 1),
                "delta_co2_kt_vs_base": round((k["co2_t"] - base_co2) / 1e3, 0),
            }
        )
    return pd.DataFrame(rows).set_index("scenario")


def build_generation_mix(kpis: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({k["scenario"]: k["supply_by_carrier_twh"] for k in kpis}).fillna(0.0)


def build_capacity_table(kpis: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({k["scenario"]: k["capacity_by_carrier_gw"] for k in kpis}).fillna(0.0)


def build_co2_table(kpis: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({k["scenario"]: k["co2_by_carrier_kt"] for k in kpis}).fillna(0.0)


def build_credible_capacity_table(kpis: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({k["scenario"]: pd.Series(k["credible_capacity"]) for k in kpis})


def build_lcoa_table(
    kpis: list[dict],
    reference: str = "dunkelflaute",
    unstable_threshold_kt: float = 10.0,
) -> pd.DataFrame:
    by_scenario = {k["scenario"]: k for k in kpis}
    if reference not in by_scenario:
        return pd.DataFrame()

    ref = by_scenario[reference]
    rows = []
    for scenario, k in by_scenario.items():
        if scenario == reference:
            continue
        delta_co2_kt = (k["co2_t"] - ref["co2_t"]) / 1e3
        delta_opex_meur = (k["opex_eur"] - ref["opex_eur"]) / 1e6
        delta_objective_meur = (k["objective_eur"] - ref["objective_eur"]) / 1e6
        unstable = abs(delta_co2_kt) < unstable_threshold_kt
        lcoa_opex = (
            (delta_opex_meur * 1e6) / (-delta_co2_kt * 1e3)
            if delta_co2_kt and not unstable
            else float("nan")
        )
        lcoa_objective = (
            (delta_objective_meur * 1e6) / (-delta_co2_kt * 1e3)
            if delta_co2_kt and not unstable
            else float("nan")
        )
        rows.append(
            {
                "scenario": scenario,
                "reference": reference,
                "delta_co2_kt_vs_reference": round(delta_co2_kt, 1),
                "delta_opex_meur_vs_reference": round(delta_opex_meur, 1),
                "delta_objective_meur_vs_reference": round(delta_objective_meur, 1),
                "lcoa_operational_eur_per_tco2": round(lcoa_opex, 0) if lcoa_opex == lcoa_opex else None,
                "lcoa_period_all_in_eur_per_tco2": round(lcoa_objective, 0)
                if lcoa_objective == lcoa_objective
                else None,
                "policy_grade": "no" if unstable else "borderline",
            }
        )
    return pd.DataFrame(rows).set_index("scenario")


def build_generation_groups(mix: pd.DataFrame) -> pd.DataFrame:
    """Aggregate carriers into report-friendly groups."""
    groups: dict[str, pd.Series] = {}
    wind = mix.loc[[c for c in mix.index if _is_wind(c)]].sum()
    solar = mix.loc[[c for c in mix.index if _is_solar(c)]].sum()
    groups["Wind (all)"] = wind
    groups["Solar (all)"] = solar
    for carrier in mix.index:
        if _is_wind(carrier) or _is_solar(carrier):
            continue
        if carrier in NUCLEAR_CARRIERS and mix.loc[carrier].max() < 1e-6:
            continue
        groups[carrier] = mix.loc[carrier]
    return pd.DataFrame(groups).T


def write_report_txt(summary: pd.DataFrame, groups: pd.DataFrame, path: Path) -> None:
    lines = [
        "INRE Germany — Scenario comparison (simulation period)",
        "=" * 60,
        "",
        "Window: Jan 2021 winter (112 snapshots, 3-hour resolution).",
        "Energy and OPEX are integrated over the simulation period.",
        "CAPEX is annuitised cost of the installed fleet (EUR/year).",
        "",
        "System summary",
        "-" * 40,
    ]
    for scenario, row in summary.iterrows():
        lines.append(
            f"{scenario}: load {row['load_twh']:.2f} TWh, "
            f"OPEX {row['opex_meur']:.1f} M EUR, "
            f"CO2 {row['co2_kt']:.0f} kt"
        )
    lines.extend(["", "Generation mix by group (TWh, simulation period)", "-" * 40])
    for group, row in groups.iterrows():
        vals = ", ".join(f"{col}={row[col]:.2f}" for col in groups.columns)
        lines.append(f"{group}: {vals}")

    if "base" in groups.columns and "dunkelflaute" in groups.columns:
        lines.extend(["", "Key shift base → dunkelflaute", "-" * 40])
        for group in groups.index:
            delta = groups.loc[group, "dunkelflaute"] - groups.loc[group, "base"]
            if abs(delta) > 0.001:
                pct = (
                    100 * delta / groups.loc[group, "base"]
                    if groups.loc[group, "base"] > 0.001
                    else float("nan")
                )
                pct_str = f" ({pct:+.0f}%)" if pct == pct else ""
                lines.append(f"  {group}: {delta:+.2f} TWh{pct_str}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plot_stacked_bar(
    data: pd.DataFrame,
    ylabel: str,
    path: Path,
    title: str | None = None,
) -> None:
    if data.empty:
        return
    plot_data = data.T
    ax = plot_data.plot(kind="bar", stacked=True, figsize=(10, 6), colormap="tab20")
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Scenario")
    if title:
        ax.set_title(title)
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = ax.get_figure()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_costs(kpis: list[dict], path: Path) -> None:
    df = pd.DataFrame(
        [
            {
                "scenario": k["scenario"],
                "CAPEX (bn EUR/yr)": k["capex_eur"] / 1e9,
                "OPEX (M EUR, period)": k["opex_eur"] / 1e6,
            }
            for k in kpis
        ]
    ).set_index("scenario")
    ax = df.plot(kind="bar", figsize=(8, 5), colormap="Set2")
    ax.set_ylabel("Cost")
    ax.set_xlabel("Scenario")
    ax.set_title("System cost by scenario")
    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = ax.get_figure()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_co2(kpis: list[dict], path: Path) -> None:
    df = pd.Series({k["scenario"]: k["co2_t"] / 1e3 for k in kpis})
    ax = df.plot(kind="bar", figsize=(8, 4), color="slategray")
    ax.set_ylabel("CO2 emissions (kt, simulation period)")
    ax.set_xlabel("Scenario")
    ax.set_title("CO2 emissions by scenario")
    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = ax.get_figure()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def parse_scenarios(specs: list[str]) -> list[tuple[str, str]]:
    out = []
    for spec in specs:
        if ":" in spec:
            label, run_name = spec.split(":", 1)
        else:
            label = run_name = spec
        out.append((label, run_name))
    return out


def export_report(kpis: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = build_report_summary(kpis)
    mix = build_generation_mix(kpis)
    capacity = build_capacity_table(kpis)
    credible_capacity = build_credible_capacity_table(kpis)
    co2 = build_co2_table(kpis)
    lcoa = build_lcoa_table(kpis)
    groups = build_generation_groups(mix)

    summary.to_csv(output_dir / "report_summary.csv")
    groups.to_csv(output_dir / "generation_mix_groups_twh.csv")
    mix.to_csv(output_dir / "generation_mix_twh.csv")
    capacity.to_csv(output_dir / "capacity_gw.csv")
    credible_capacity.to_csv(output_dir / "credible_capacity.csv")
    co2.to_csv(output_dir / "co2_by_carrier_kt.csv")
    if not lcoa.empty:
        lcoa.to_csv(output_dir / "lcoa_vs_dunkelflaute.csv")

    legacy = summary.rename(
        columns={
            "generation_twh": "total_supply_twh",
            "capex_annuitised_meur": "capex_meur",
        }
    )
    legacy["total_capacity_gw"] = [
        k["capacity_by_carrier_gw"].sum() for k in kpis
    ]
    legacy.to_csv(output_dir / "comparison_table.csv")

    write_report_txt(summary, groups, output_dir / "report_summary.txt")

    try:
        with pd.ExcelWriter(output_dir / "report_tables.xlsx") as writer:
            summary.to_excel(writer, sheet_name="summary")
            groups.to_excel(writer, sheet_name="generation_groups")
            mix.to_excel(writer, sheet_name="generation_detail")
            capacity.to_excel(writer, sheet_name="capacity")
            credible_capacity.to_excel(writer, sheet_name="credible_capacity")
            co2.to_excel(writer, sheet_name="co2")
            if not lcoa.empty:
                lcoa.to_excel(writer, sheet_name="lcoa")
    except ImportError:
        logger.warning("openpyxl not installed; skipping report_tables.xlsx")

    _plot_stacked_bar(
        groups,
        "Generation (TWh, simulation period)",
        output_dir / "production_mix.png",
        title="Generation mix by scenario",
    )
    _plot_stacked_bar(
        capacity,
        "Optimal capacity (GW)",
        output_dir / "capacity.png",
        title="Installed capacity by scenario",
    )
    _plot_costs(kpis, output_dir / "costs_breakdown.png")
    _plot_co2(kpis, output_dir / "co2_emissions.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare INRE PyPSA-Eur scenarios")
    parser.add_argument(
        "--preset",
        choices=["core", "capex", "full"],
        default="core",
        help="Scenario group: core (5), capex (SMR sensitivity), full (all 8)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        help="Override preset: label:run_name pairs (folder = run_name for multi-scenario runs)",
    )
    parser.add_argument("--clusters", default="10")
    parser.add_argument("--opts", default="")
    parser.add_argument(
        "--output-dir",
        default="results/inre-comparison",
        help="Directory for report CSV/XLSX/TXT and PNG outputs",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.scenarios:
        scenario_specs = args.scenarios
    elif args.preset == "full":
        scenario_specs = SCENARIO_PRESETS["core"] + SCENARIO_PRESETS["capex"]
    else:
        scenario_specs = SCENARIO_PRESETS[args.preset]

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir

    kpis = []
    for label, run_name in parse_scenarios(scenario_specs):
        path = _network_path(run_name, args.clusters, args.opts)
        if not path.exists():
            logger.warning("Skipping %s: network not found at %s", label, path)
            continue
        logger.info("Loading %s from %s", label, path)
        n = pypsa.Network(path)
        kpis.append(extract_kpis(n, label))

    if not kpis:
        raise SystemExit("No solved networks found. Run scenarios first.")

    export_report(kpis, output_dir)
    logger.info("Wrote report outputs to %s", output_dir)


if __name__ == "__main__":
    main()
