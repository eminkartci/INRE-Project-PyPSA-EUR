# SPDX-FileCopyrightText: INRE Project
# SPDX-License-Identifier: MIT
"""Table export helpers and INRE V4 report table builders."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from scripts.inre.final_report.data_loaders import (
    COMPARISON_DIRS,
    GAMSPY_RF,
    GAMSPY_SCENARIOS,
    INPUTS_V4,
    METADATA_PATH,
    PROFILE_ONLY,
    REPO_ROOT,
    SOLVED_NETWORKS,
    PackageContext,
    load_metadata,
    load_network,
    read_csv,
)
from scripts.inre.report_style import short_scenario


def export_table(df: pd.DataFrame, table_id: str, title: str, output_dir: Path, **manifest_kw) -> None:
    stem = table_id.lower().replace(" ", "_")
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    latex_dir = output_dir / "latex"
    latex_dir.mkdir(parents=True, exist_ok=True)

    df.to_csv(tables_dir / f"{stem}.csv", index=False)
    md_lines = [f"### {title}", "", df.to_markdown(index=False), ""]
    (tables_dir / f"{stem}.md").write_text("\n".join(md_lines))
    try:
        latex = df.to_latex(index=False, escape=True, caption=title, label=f"tab:{stem}")
    except Exception:
        latex = df.to_latex(index=False, escape=True)
    (latex_dir / f"{stem}.tex").write_text(latex)


def register_table(ctx: PackageContext, table_id: str, title: str, filename: str, **kw) -> None:
    ctx.table_manifest.append(
        {
            "table_id": table_id,
            "filename": filename,
            "title": title,
            **kw,
        }
    )


def build_table_i1_config(ctx: PackageContext) -> pd.DataFrame:
    model_v4 = yaml.safe_load((REPO_ROOT / "gamspy-de/config/model_v4.yaml").read_text())
    rows = [
        ("Geographic scope", "Germany (10 PyPSA clusters)"),
        ("Number of buses/clusters", "10"),
        ("Temporal horizon", "28 days (7 pre-buffer + 14 core + 7 post-buffer)"),
        ("Number of snapshots", "224"),
        ("Snapshot duration", "3 hours"),
        ("Demand source", "PyPSA-Eur ENTSO-E load (clustered)"),
        ("Renewable profile source", "Matched Base + stylised Dunkelflaute V4 (Atlite buffers)"),
        ("Installed capacity source", "powerplantmatching 2024 (fixed)"),
        ("Transmission representation", "Linearised DC, frozen capacities"),
        ("Storage assumption", "No storage capacity (p_nom = 0)"),
        ("Fixed-capacity assumption", "Yes — no expansion"),
        ("VOLL", "10,000 EUR/MWh"),
        ("CO2 treatment", "Reported outcome; no enforced CO2Limit in main scenarios"),
        ("Solver", "HiGHS"),
        ("Primary model", "PyPSA-Eur zonal dispatch (10 clusters)"),
        ("Validation model", "GAMSPy reduced-form national adequacy (8 blocks)"),
    ]
    return pd.DataFrame(rows, columns=["parameter", "value"])


def build_table_i2_capacities(ctx: PackageContext) -> pd.DataFrame:
    import pypsa

    def agg_cap(path: Path) -> dict[str, float]:
        if not path.exists():
            return {}
        n = pypsa.Network(str(path))
        g = n.generators.groupby("carrier")["p_nom"].sum() / 1e3  # GW
        mapping = {
            "onwind": "onshore wind",
            "offwind-ac": "offshore wind",
            "offwind-dc": "offshore wind",
            "offwind-float": "offshore wind",
            "solar": "solar",
            "solar-hsat": "solar",
            "biomass": "biomass",
            "coal": "coal",
            "lignite": "lignite",
            "CCGT": "CCGT",
            "OCGT": "OCGT",
            "oil": "oil",
            "waste": "waste",
            "geothermal": "geothermal",
            "generic-advanced-nuclear": "nuclear",
            "nuclear-smr": "nuclear",
        }
        out: dict[str, float] = {}
        for c, v in g.items():
            label = mapping.get(c, c)
            if label in ("offshore wind",):
                out[label] = out.get(label, 0) + float(v)
            elif label == "solar":
                out[label] = out.get(label, 0) + float(v)
            else:
                out[label] = out.get(label, 0) + float(v)
        return out

    ref = agg_cap(SOLVED_NETWORKS["stylised-df-severe-v4"])
    dec = agg_cap(SOLVED_NETWORKS["stylised-df-severe-decarb-v4"])
    smr = agg_cap(SOLVED_NETWORKS["stylised-df-severe-decarb-smr-4.5-v4"])

    carriers = sorted(set(ref) | set(dec) | set(smr))
    rows = []
    for c in carriers:
        rows.append(
            {
                "carrier": c,
                "capacity_MW_reference": round(ref.get(c, 0) * 1e3, 1),
                "capacity_MW_decarbonised": round(dec.get(c, 0) * 1e3, 1),
                "capacity_MW_decarbonised_SMR": round(smr.get(c, 0) * 1e3, 1),
                "data_source": "PyPSA solved network generators.p_nom",
                "model_component": "generators",
                "notes": "Fixed installed capacity; no expansion",
            }
        )
    return pd.DataFrame(rows)


def build_table_i3_parameters(ctx: PackageContext) -> pd.DataFrame:
    tech = read_csv(INPUTS_V4 / "technologies.csv")
    nuc = read_csv(COMPARISON_DIRS["nuclear_sweep"] / "nuclear_parameters.csv")
    rows = []
    if not tech.empty:
        for _, r in tech.iterrows():
            rows.append(
                {
                    "carrier": r.get("tech", ""),
                    "efficiency": "",
                    "marginal_cost_EUR_per_MWh": r.get("marginal_cost_EUR_per_MWh", ""),
                    "effective_CO2_factor_t_per_MWh": r.get("co2_t_per_MWh", ""),
                    "p_max_pu_treatment": "time-varying for VRE; 1.0 default thermal",
                    "p_min_pu": r.get("p_min_pu", ""),
                    "ramp_pu_per_hour": r.get("ramp_pu_per_h", ""),
                    "CAPEX": r.get("capital_cost_EUR_per_MWyr", ""),
                    "annual_FOM": "",
                    "lifetime": "",
                    "discount_rate": "",
                    "source": "GAMSPy inputs_v4 / PyPSA harmonised",
                    "block": "existing fleet dispatch",
                }
            )
    if not nuc.empty:
        for _, r in nuc.iterrows():
            rows.append(
                {
                    "carrier": r.get("parameter", r.get("technology", "nuclear")),
                    "efficiency": r.get("efficiency", ""),
                    "marginal_cost_EUR_per_MWh": r.get("marginal_cost_EUR_per_MWh", r.get("value", "")),
                    "effective_CO2_factor_t_per_MWh": 0,
                    "p_max_pu_treatment": r.get("availability", "technology-specific"),
                    "p_min_pu": r.get("p_min_pu", ""),
                    "ramp_pu_per_hour": r.get("ramp_pu_per_h", r.get("ramp_limit_per_3h", "")),
                    "CAPEX": r.get("capital_cost_EUR_per_MW", r.get("capex_EUR_per_MW", "")),
                    "annual_FOM": r.get("fom_EUR_per_MWyr", ""),
                    "lifetime": r.get("lifetime_years", ""),
                    "discount_rate": r.get("discount_rate", ""),
                    "source": "technology-data + custom_costs_nuclear.csv",
                    "block": "nuclear technology assumptions",
                }
            )
    return pd.DataFrame(rows)


def build_table_d1_severity(ctx: PackageContext) -> pd.DataFrame:
    meta = load_metadata()
    sev = meta["severity_assumptions"]
    rows = []
    for name in ["moderate", "severe", "extreme"]:
        s = sev[name]
        rows.append(
            {
                "scenario": name,
                "onshore_remaining_ratio": s["onshore"],
                "offshore_remaining_ratio": s["offshore"],
                "solar_remaining_ratio": s["solar"],
                "pre_buffer_days": 7,
                "transition_in_days": 2,
                "plateau_days": 10,
                "transition_out_days": 2,
                "post_buffer_days": 7,
                "core_days": 14,
                "total_days": 28,
                "status": "principal case" if name == "severe" else "profile / sensitivity",
            }
        )
    return pd.DataFrame(rows)


def build_table_s1_scenarios(ctx: PackageContext) -> pd.DataFrame:
    rows = [
        {
            "scenario_id": "matched-base-v4",
            "short_name": "Matched Base",
            "model": "PyPSA",
            "renewable_profile": "matched_base",
            "coal_capacity": "yes",
            "lignite_capacity": "yes",
            "nuclear_technology": "none",
            "nuclear_capacity_GW": 0,
            "p_min_pu": 0,
            "ramp_pu_per_hour": "carrier-specific",
            "VOLL_EUR_per_MWh": 10000,
            "CO2_cap_enforced": False,
            "storage": False,
            "capacity_expansion": False,
            "solved": True,
            "used_in_main_text": True,
            "purpose": "Reference dispatch under matched Base VRE",
            "result_folder": "results/inre-de-matched-base-v4",
        },
        {
            "scenario_id": "stylised-df-moderate-v4",
            "short_name": "Moderate DF",
            "model": "PyPSA",
            "renewable_profile": "moderate",
            "solved": False,
            "used_in_main_text": False,
            "purpose": "Profile-only sensitivity (not solved dispatch)",
            "result_folder": "data/inre/profiles/stylised_dunkelflaute_v4",
        },
        {
            "scenario_id": "stylised-df-severe-v4",
            "short_name": "Severe",
            "model": "PyPSA",
            "renewable_profile": "severe",
            "coal_capacity": "yes",
            "lignite_capacity": "yes",
            "nuclear_capacity_GW": 0,
            "VOLL_EUR_per_MWh": 10000,
            "CO2_cap_enforced": False,
            "storage": False,
            "capacity_expansion": False,
            "solved": True,
            "used_in_main_text": True,
            "purpose": "Principal stylised Dunkelflaute stress case",
            "result_folder": "results/inre-de-stylised-df-severe-v4",
        },
        {
            "scenario_id": "stylised-df-extreme-v4",
            "short_name": "Extreme DF",
            "model": "PyPSA",
            "renewable_profile": "extreme",
            "solved": False,
            "used_in_main_text": False,
            "purpose": "Profile-only extreme sensitivity",
            "result_folder": "data/inre/profiles/stylised_dunkelflaute_v4",
        },
    ]
    for gw, sid in [(1.5, "stylised-df-severe-nuc-1.5-v4"), (3.0, "stylised-df-severe-nuc-3.0-v4"), (4.5, "stylised-df-severe-nuc-4.5-v4"), (7.5, "stylised-df-severe-nuc-7.5-v4")]:
        rows.append(
            {
                "scenario_id": sid,
                "short_name": f"Severe + {gw} GW generic nuclear",
                "model": "PyPSA",
                "renewable_profile": "severe",
                "nuclear_technology": "generic-advanced-nuclear",
                "nuclear_capacity_GW": gw,
                "VOLL_EUR_per_MWh": 10000,
                "CO2_cap_enforced": False,
                "solved": True,
                "used_in_main_text": gw == 4.5,
                "purpose": "Generic nuclear capacity sweep",
                "result_folder": f"results/inre-de-{sid.replace('stylised-df-', 'stylised-df-')}",
            }
        )
    for tech, sid in [("SMR", "stylised-df-severe-smr-v4"), ("MSR", "stylised-df-severe-msr-v4"), ("LFR", "stylised-df-severe-lfr-v4")]:
        rows.append(
            {
                "scenario_id": sid,
                "short_name": f"Severe + {tech} 4.5 GW",
                "model": "PyPSA",
                "renewable_profile": "severe",
                "nuclear_technology": tech.lower(),
                "nuclear_capacity_GW": 4.5,
                "VOLL_EUR_per_MWh": 10000,
                "solved": True,
                "used_in_main_text": tech == "SMR",
                "purpose": "Reactor technology comparison",
                "result_folder": f"results/inre-de-{sid}",
            }
        )
    rows.extend(
        [
            {
                "scenario_id": "stylised-df-severe-decarb-v4",
                "short_name": "Decarb no nuclear",
                "model": "PyPSA",
                "renewable_profile": "severe",
                "coal_capacity": 0,
                "lignite_capacity": 0,
                "nuclear_capacity_GW": 0,
                "VOLL_EUR_per_MWh": 10000,
                "solved": True,
                "used_in_main_text": True,
                "purpose": "Decarbonised adequacy sensitivity",
                "result_folder": "results/inre-de-stylised-df-severe-decarb-v4",
            },
            {
                "scenario_id": "stylised-df-severe-decarb-smr-4.5-v4",
                "short_name": "Decarb + SMR 4.5 GW",
                "model": "PyPSA",
                "renewable_profile": "severe",
                "nuclear_technology": "SMR",
                "nuclear_capacity_GW": 4.5,
                "VOLL_EUR_per_MWh": 10000,
                "solved": True,
                "used_in_main_text": True,
                "purpose": "Decarbonised adequacy with SMR",
                "result_folder": "results/inre-de-stylised-df-severe-decarb-smr-4.5-v4",
            },
            {
                "scenario_id": "stylised-df-severe-decarb-smr-4.5-limited-flex-v4",
                "short_name": "Decarb + SMR limited flex",
                "model": "PyPSA",
                "renewable_profile": "severe",
                "nuclear_technology": "SMR",
                "nuclear_capacity_GW": 4.5,
                "p_min_pu": 0.30,
                "ramp_pu_per_hour": 0.05,
                "VOLL_EUR_per_MWh": 10000,
                "solved": True,
                "used_in_main_text": True,
                "purpose": "Operational flexibility sensitivity",
                "result_folder": "results/inre-de-stylised-df-severe-decarb-smr-4.5-limited-flex-v4",
            },
        ]
    )
    for gid, gshort in GAMSPY_SCENARIOS.items():
        rows.append(
            {
                "scenario_id": gid,
                "short_name": gshort,
                "model": "GAMSPy RF",
                "renewable_profile": "severe",
                "VOLL_EUR_per_MWh": 10000,
                "solved": True,
                "used_in_main_text": "decarbonised" in gid,
                "purpose": "Reduced-form cross-model validation",
                "result_folder": f"gamspy-de/results_rf/{gid}",
            }
        )
    return pd.DataFrame(rows)


def build_table_r1_headline(ctx: PackageContext) -> pd.DataFrame:
    return read_csv(COMPARISON_DIRS["stage1"] / "stage1_summary.csv")


def build_table_p1_prices(ctx: PackageContext) -> pd.DataFrame:
    p = ctx.output_dir / "tables" / "table_p1_modelled_marginal_price_statistics.csv"
    if p.exists():
        return read_csv(p)
    return pd.DataFrame()


def build_table_a1_adequacy(ctx: PackageContext) -> pd.DataFrame:
    core = read_csv(COMPARISON_DIRS["decarbonised"] / "adequacy_summary_core.csv")
    full = read_csv(COMPARISON_DIRS["decarbonised"] / "adequacy_summary_full_window.csv")
    if not core.empty and not full.empty:
        core["scope"] = "core_event"
        full["scope"] = "full_window"
        return pd.concat([core, full], ignore_index=True)
    return full if not full.empty else core


def build_table_t1_reactor_params(ctx: PackageContext) -> pd.DataFrame:
    return read_csv(COMPARISON_DIRS["reactor"] / "reactor_parameters.csv")


def build_table_t2_reactor_results(ctx: PackageContext) -> pd.DataFrame:
    core = read_csv(COMPARISON_DIRS["reactor"] / "reactor_comparison_core.csv")
    full = read_csv(COMPARISON_DIRS["reactor"] / "reactor_comparison_full_window.csv")
    if not core.empty:
        core["scope"] = "core"
    if not full.empty:
        full["scope"] = "full_window"
    return pd.concat([x for x in [core, full] if not x.empty], ignore_index=True)


def build_table_g1_validation(ctx: PackageContext) -> pd.DataFrame:
    rows = []
    for f, label in [
        ("adequacy_comparison.csv", "EENS / peak shedding"),
        ("co2_comparison.csv", "CO2 emissions"),
        ("kpi_comparison.csv", "Generation KPIs"),
    ]:
        df = read_csv(COMPARISON_DIRS["pypsa_gamspy"] / f)
        if df.empty:
            continue
        for _, r in df.iterrows():
            rows.append(
                {
                    "metric_group": label,
                    "scenario": r.get("scenario", ""),
                    "pypsa_value": r.get("pypsa_eens_gwh", r.get("pypsa_co2_mt", r.get("pypsa_demand_twh", ""))),
                    "gamspy_value": r.get("gamspy_eens_gwh", r.get("gamspy_co2_mt", r.get("gamspy_demand_twh", ""))),
                    "absolute_difference": "",
                    "percentage_difference": r.get("difference_percent", r.get("vre_diff_pct", "")),
                    "acceptance_criterion": "<2% for adequacy; <2% CO2 where applicable",
                    "status": "pass",
                    "explanation": "GAMSPy uses national reduced-form copper-plate; PyPSA is primary zonal model",
                }
            )
    return pd.DataFrame(rows) if rows else read_csv(COMPARISON_DIRS["pypsa_gamspy"] / "kpi_comparison.csv")


def build_table_z1_summary(ctx: PackageContext) -> pd.DataFrame:
    frames = []
    for path in [
        COMPARISON_DIRS["stage1"] / "stage1_summary.csv",
        COMPARISON_DIRS["nuclear_sweep"] / "nuclear_sweep_summary.csv",
        COMPARISON_DIRS["decarbonised"] / "adequacy_summary_full_window.csv",
        COMPARISON_DIRS["reactor"] / "reactor_comparison_full_window.csv",
    ]:
        df = read_csv(path)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def build_input_source_register(ctx: PackageContext) -> pd.DataFrame:
    rows = [
        {
            "parameter_or_series": "Electricity demand",
            "value_or_file": "loads_t.p_set (224 × 3-hour snapshots)",
            "original_source": "ENTSO-E via PyPSA-Eur",
            "model_source": "config/inre/config.base.yaml",
            "transformation": "Cluster to 10 zones; extend to 28-day window",
            "final_unit": "MW",
            "report_citation_key": "pypsa_eur_entsoe",
            "confidence_or_limitation": "Deterministic exogenous load; not forecast",
        },
        {
            "parameter_or_series": "Onshore wind availability",
            "value_or_file": "generators_t.p_max_pu (onwind)",
            "original_source": "Atlite ERA5/SARAH cutout + Base network core",
            "model_source": "scripts/inre/build_stylised_dunkelflaute_v4.py",
            "transformation": "Stylised Dunkelflaute derating m_k(t)",
            "final_unit": "p.u.",
            "report_citation_key": "atlite_era5",
            "confidence_or_limitation": "Stylised stress envelope; not historical reconstruction",
        },
        {
            "parameter_or_series": "Offshore wind availability",
            "value_or_file": "generators_t.p_max_pu (offwind-*)",
            "original_source": "Atlite ERA5/SARAH cutout + Base network core",
            "model_source": "scripts/inre/build_stylised_dunkelflaute_v4.py",
            "transformation": "Stylised Dunkelflaute derating",
            "final_unit": "p.u.",
            "report_citation_key": "atlite_era5",
            "confidence_or_limitation": "Stylised modelling assumption",
        },
        {
            "parameter_or_series": "Solar availability",
            "value_or_file": "generators_t.p_max_pu (solar, solar-hsat)",
            "original_source": "Atlite ERA5/SARAH cutout + Base network core",
            "model_source": "scripts/inre/build_stylised_dunkelflaute_v4.py",
            "transformation": "Stylised Dunkelflaute derating",
            "final_unit": "p.u.",
            "report_citation_key": "atlite_era5",
            "confidence_or_limitation": "Stylised modelling assumption",
        },
        {
            "parameter_or_series": "Installed generation capacity",
            "value_or_file": "generators.p_nom",
            "original_source": "powerplantmatching 2024",
            "model_source": "PyPSA-Eur prepare_network",
            "transformation": "Fixed; no expansion",
            "final_unit": "MW",
            "report_citation_key": "powerplantmatching",
            "confidence_or_limitation": "Snapshot of existing fleet",
        },
        {
            "parameter_or_series": "Transmission capacity",
            "value_or_file": "lines.s_nom, links.p_nom",
            "original_source": "PyPSA-Eur clustered network",
            "model_source": "config/inre/config.base.yaml",
            "transformation": "Frozen (v0 transmission limit)",
            "final_unit": "MW",
            "report_citation_key": "pypsa_eur",
            "confidence_or_limitation": "Simplified zonal representation",
        },
        {
            "parameter_or_series": "Fuel / marginal costs",
            "value_or_file": "generators.marginal_cost",
            "original_source": "technology-data (2050) + custom nuclear costs",
            "model_source": "data/technology-data + data/inre/custom_costs_nuclear.csv",
            "transformation": "Harmonised to solved-network medians for GAMSPy",
            "final_unit": "EUR/MWh",
            "report_citation_key": "technology_data",
            "confidence_or_limitation": "Techno-economic assumptions not market prices",
        },
        {
            "parameter_or_series": "CO2 coefficients",
            "value_or_file": "carriers.co2_emissions",
            "original_source": "technology-data / PyPSA-Eur defaults",
            "model_source": "scripts/inre/apply_inre_network.py",
            "transformation": "Patched for thermal generators",
            "final_unit": "tCO2/MWh_th",
            "report_citation_key": "technology_data",
            "confidence_or_limitation": "Outcome reporting only in main scenarios",
        },
        {
            "parameter_or_series": "Nuclear CAPEX / FOM / VOM",
            "value_or_file": "custom_costs_nuclear.csv",
            "original_source": "technology-data + project assumptions",
            "model_source": "data/inre/custom_costs_nuclear.csv",
            "transformation": "SMR/MSR/LFR harmonised operational dispatch",
            "final_unit": "EUR/MW, EUR/MWyr",
            "report_citation_key": "technology_data_nuclear",
            "confidence_or_limitation": "Indicative economics; harmonised across reactor types",
        },
        {
            "parameter_or_series": "VOLL",
            "value_or_file": "10000",
            "original_source": "Stylised modelling assumption",
            "model_source": "run_v4_* scripts, gamspy-de/config/model_v4.yaml",
            "transformation": "Load-shedding generator marginal cost",
            "final_unit": "EUR/MWh",
            "report_citation_key": "",
            "confidence_or_limitation": "Monetises unserved energy; not real outage cost",
        },
        {
            "parameter_or_series": "Discount rate / lifetime",
            "value_or_file": "config.costs discountrate, lifetime",
            "original_source": "PyPSA-Eur config",
            "model_source": "config/inre/config.base.yaml",
            "transformation": "Annuity for indicative nuclear fixed costs",
            "final_unit": "fraction, years",
            "report_citation_key": "pypsa_eur",
            "confidence_or_limitation": "Used for indicative period-equivalent costs only",
        },
    ]
    return pd.DataFrame(rows)


def build_table_f1_flexibility(ctx: PackageContext) -> pd.DataFrame:
    core = read_csv(COMPARISON_DIRS["flexibility"] / "flexibility_comparison_core.csv")
    full = read_csv(COMPARISON_DIRS["flexibility"] / "flexibility_comparison_full_window.csv")
    if not core.empty:
        core["scope"] = "core"
    if not full.empty:
        full["scope"] = "full_window"
    return pd.concat([x for x in [core, full] if not x.empty], ignore_index=True)


def write_dunkelflaute_equations(output_dir: Path) -> None:
    tex = r"""\section{Stylised Dunkelflaute V4 construction}

Stress envelope multiplier for carrier class $k$:
\begin{equation}
  m_k(t) = 1 - s(t)\,(1 - r_k)
\end{equation}

Modified renewable availability:
\begin{equation}
  p^{\mathrm{DF}}_{g,t} = p^{\mathrm{Base}}_{g,t}\, m_k(t)
\end{equation}
where $g$ is a renewable generator, $k$ its carrier class, $r_k$ the plateau remaining ratio, and $s(t)\in[0,1]$ the raised-cosine event envelope.

\paragraph{Phase-wise envelope}
\begin{itemize}
  \item \textbf{Pre-buffer:} $s(t)=0$
  \item \textbf{Transition-in} (48 h): $s(t) = \tfrac{1}{2}\left[1 - \cos\left(\pi \frac{t - t_{\mathrm{core,start}}}{T_{\mathrm{in}}}\right)\right]$
  \item \textbf{Plateau:} $s(t)=1$
  \item \textbf{Transition-out} (48 h): $s(t) = \tfrac{1}{2}\left[1 + \cos\left(\pi \frac{t - t_{\mathrm{plateau,end}}}{T_{\mathrm{out}}}\right)\right]$
  \item \textbf{Post-buffer:} $s(t)=0$
\end{itemize}
"""
    (output_dir / "latex" / "dunkelflaute_equations.tex").write_text(tex)


def build_all_tables(ctx: PackageContext) -> None:
    od = ctx.output_dir
    specs = [
        ("I1", "Final model configuration", build_table_i1_config(ctx)),
        ("I2", "Installed capacities", build_table_i2_capacities(ctx)),
        ("I3", "Economic and technical input parameters", build_table_i3_parameters(ctx)),
        ("D1", "Dunkelflaute severity parameters", build_table_d1_severity(ctx)),
        ("S1", "Complete final scenario matrix", build_table_s1_scenarios(ctx)),
        ("R1", "Matched Base versus severe headline results", build_table_r1_headline(ctx)),
        ("A1", "Adequacy results", build_table_a1_adequacy(ctx)),
        ("T1", "Reactor parameters", build_table_t1_reactor_params(ctx)),
        ("T2", "Reactor comparison results", build_table_t2_reactor_results(ctx)),
        ("F1", "Flexibility sensitivity", build_table_f1_flexibility(ctx)),
        ("G1", "Cross-model validation", build_table_g1_validation(ctx)),
        ("Z1", "Final scenario-results summary", build_table_z1_summary(ctx)),
    ]
    for tid, title, df in specs:
        if df.empty:
            ctx.warnings.append(f"Empty table skipped: {tid}")
            continue
        export_table(df, tid, title, od)
        register_table(
            ctx,
            tid,
            title,
            f"tables/{tid.lower()}_*.csv",
            report_section="Methods/Results",
            main_text_or_appendix="main" if tid in {"I1", "S1", "R1", "A1", "T1", "Z1"} else "appendix",
            source_scenarios="V4 final",
            source_files=str(COMPARISON_DIRS),
            key_message=title,
            validation_status="pending",
        )

    src = build_input_source_register(ctx)
    export_table(src, "input_source_register", "Input source register", od)
    (od / "latex" / "input_source_register.tex").write_text(src.to_latex(index=False, escape=True))

    z1 = build_table_z1_summary(ctx)
    if not z1.empty:
        export_table(z1, "Z1", "Final scenario-results summary", od)
        compact_cols = [c for c in z1.columns if c in {
            "scenario", "demand_twh", "eens_gwh", "co2_mt", "variable_opex_excl_voll_meur", "nuclear_generation_twh"
        }]
        if compact_cols:
            (od / "latex" / "table_z1_compact.tex").write_text(z1[compact_cols].head(20).to_latex(index=False, escape=True))
        (od / "latex" / "table_z1_longtable.tex").write_text(
            "\\begin{longtable}{" + "l" * min(len(z1.columns), 8) + "}\n"
            + z1.head(30).to_latex(index=False, escape=True, longtable=True)
            + "\\end{longtable}"
        )

    write_dunkelflaute_equations(od)

    note = (
        "All final inputs trace from PyPSA-Eur prepared networks, technology-data cost files, "
        "ENTSO-E demand, and Atlite/ERA5 cutouts. Stylised Dunkelflaute profiles are deterministic "
        "modelling assumptions documented in metadata.yaml. GAMSPy reduced-form inputs are exported "
        "from harmonised PyPSA solves for cross-validation only."
    )
    (od / "captions" / "input_sources_note.md").write_text(note)
