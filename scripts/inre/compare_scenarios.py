# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Compare solved INRE scenario networks and export KPI tables and charts.

Usage (from repository root)::

    python scripts/inre/compare_scenarios.py \\
        --scenarios base:inre-de-base dunkelflaute:inre-de-dunkelflaute \\
        --clusters 10 --opts "" \\
        --output-dir results/inre-comparison
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


def _network_path(run_name: str, clusters: str, opts: str) -> Path:
    opts_token = opts if opts else ""
    return (
        REPO_ROOT
        / "results"
        / run_name
        / "networks"
        / f"base_s_{clusters}_elec_{opts_token}.nc"
    )


def _snapshot_weight(n: pypsa.Network) -> float:
    if len(n.snapshots) == 0:
        return 1.0
    return n.snapshot_weightings.objective.sum() / len(n.snapshots)


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


def extract_kpis(n: pypsa.Network, label: str) -> dict:
    supply = n.statistics.supply().dropna()
    if isinstance(supply.index, pd.MultiIndex):
        supply_by_carrier = supply.groupby(level="carrier").sum()
    else:
        supply_by_carrier = supply.groupby(supply.index).sum()

    cap = n.statistics.optimal_capacity().dropna()
    if isinstance(cap.index, pd.MultiIndex):
        cap_by_carrier = cap.groupby(level="carrier").sum()
    else:
        cap_by_carrier = cap.groupby(cap.index).sum()

    capex = float(n.statistics.capex().sum())
    opex = float(n.statistics.opex().sum())
    weight = _snapshot_weight(n)
    hours_per_year = 8760.0

    supply_twh = supply_by_carrier.sum() * weight * hours_per_year / 1e6
    cap_gw = cap_by_carrier.sum() / 1e3

    return {
        "scenario": label,
        "objective_eur": float(n.objective),
        "capex_eur": capex,
        "opex_eur": opex,
        "total_cost_eur": capex + opex,
        "co2_t": _co2_emissions_t(n),
        "supply_by_carrier_twh": supply_twh,
        "capacity_by_carrier_gw": cap_gw,
    }


def build_summary_table(kpis: list[dict]) -> pd.DataFrame:
    rows = []
    for k in kpis:
        rows.append(
            {
                "scenario": k["scenario"],
                "objective_eur": k["objective_eur"],
                "capex_eur": k["capex_eur"],
                "opex_eur": k["opex_eur"],
                "total_cost_eur": k["total_cost_eur"],
                "co2_kt": k["co2_t"] / 1e3,
                "total_supply_twh": k["supply_by_carrier_twh"].sum(),
                "total_capacity_gw": k["capacity_by_carrier_gw"].sum(),
            }
        )
    return pd.DataFrame(rows).set_index("scenario")


def _plot_stacked_bar(
    kpis: list[dict],
    key: str,
    ylabel: str,
    path: Path,
    scale: float = 1.0,
) -> None:
    data = pd.DataFrame({k["scenario"]: k[key] for k in kpis}).fillna(0.0)
    data = data * scale
    if data.empty:
        return
    ax = data.T.plot(kind="bar", stacked=True, figsize=(10, 6), colormap="tab20")
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Scenario")
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
                "CAPEX": k["capex_eur"] / 1e9,
                "OPEX": k["opex_eur"] / 1e9,
            }
            for k in kpis
        ]
    ).set_index("scenario")
    ax = df.plot(kind="bar", figsize=(8, 5), colormap="Set2")
    ax.set_ylabel("Cost (bn EUR)")
    ax.set_xlabel("Scenario")
    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = ax.get_figure()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_co2(kpis: list[dict], path: Path) -> None:
    df = pd.Series({k["scenario"]: k["co2_t"] / 1e6 for k in kpis})
    ax = df.plot(kind="bar", figsize=(8, 4), color="slategray")
    ax.set_ylabel("CO2 emissions (Mt)")
    ax.set_xlabel("Scenario")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare INRE PyPSA-Eur scenarios")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=[
            "base:base",
            "dunkelflaute:dunkelflaute",
            "dunkelflaute-smr:dunkelflaute-smr",
            "dunkelflaute-msr:dunkelflaute-msr",
            "dunkelflaute-lfr:dunkelflaute-lfr",
        ],
        help="label:run_name pairs pointing to results/<run_name>/networks/",
    )
    parser.add_argument("--clusters", default="10")
    parser.add_argument("--opts", default="")
    parser.add_argument(
        "--output-dir",
        default="results/inre-comparison",
        help="Directory for CSV/XLSX and PNG outputs",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir

    kpis = []
    for label, run_name in parse_scenarios(args.scenarios):
        path = _network_path(run_name, args.clusters, args.opts)
        if not path.exists():
            logger.warning("Skipping %s: network not found at %s", label, path)
            continue
        logger.info("Loading %s from %s", label, path)
        n = pypsa.Network(path)
        kpis.append(extract_kpis(n, label))

    if not kpis:
        raise SystemExit("No solved networks found. Run scenarios first.")

    summary = build_summary_table(kpis)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "comparison_table.csv")
    try:
        summary.to_excel(output_dir / "comparison_table.xlsx")
    except ImportError:
        logger.warning("openpyxl not installed; skipping XLSX export")

    _plot_stacked_bar(
        kpis,
        "supply_by_carrier_twh",
        "Annualised supply (TWh)",
        output_dir / "production_mix.png",
    )
    _plot_stacked_bar(
        kpis,
        "capacity_by_carrier_gw",
        "Optimal capacity (GW)",
        output_dir / "capacity.png",
    )
    _plot_costs(kpis, output_dir / "costs_breakdown.png")
    _plot_co2(kpis, output_dir / "co2_emissions.png")

    logger.info("Wrote comparison outputs to %s", output_dir)


if __name__ == "__main__":
    main()
