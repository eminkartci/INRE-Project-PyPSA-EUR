"""Build and solve the V4 Germany GAMSPy fixed-capacity dispatch validation model."""

from __future__ import annotations

from dataclasses import dataclass

import gamspy as gp
import pandas as pd

from apply_scenario_v4 import PreparedDataV4


@dataclass
class BuiltModelV4:
    container: gp.Container
    model: gp.Model
    symbols: dict


def _time_labels(times: list[pd.Timestamp]) -> list[str]:
    return [ts.strftime("%Y-%m-%dT%H:%M:%S") for ts in times]


def _aggregate_copper_plate(data: PreparedDataV4) -> PreparedDataV4:
    """National copper-plate aggregation to reduce model size for GAMS demo license."""
    bus = "DE"
    times = data.times
    dispatch_techs = [t for t in data.techs if not t.startswith("nuclear-")]

    demand = (
        data.demand.groupby("timestamp", as_index=False)["demand_MW"]
        .sum()
        .assign(bus=bus)
    )

    avail_rows = []
    for tech in dispatch_techs:
        sub = data.availability[data.availability["tech"] == tech]
        for ts in times:
            ts_rows = sub[sub["timestamp"] == ts]
            cap = 0.0
            weighted = 0.0
            for _, row in ts_rows.iterrows():
                bus_cap = (
                    float(data.existing_cap.at[row["bus"], tech])
                    if row["bus"] in data.existing_cap.index and tech in data.existing_cap.columns
                    else 0.0
                )
                cap += bus_cap
                weighted += bus_cap * float(row["p_max_pu"])
            pu = weighted / cap if cap > 0 else 0.0
            avail_rows.append({"bus": bus, "tech": tech, "timestamp": ts, "p_max_pu": pu})
    availability = pd.DataFrame(avail_rows)

    cap_row = {
        tech: float(data.existing_cap[tech].sum()) if tech in data.existing_cap.columns else 0.0
        for tech in dispatch_techs
    }
    existing_cap = pd.DataFrame([cap_row], index=[bus])

    total_nuc = sum(float(v) for v in data.nuclear_fixed_cap.values())
    nuclear_sites = pd.DataFrame()
    nuclear_fixed_cap: dict[str, float] = {}
    if total_nuc > 0:
        nuclear_sites = pd.DataFrame(
            [
                {
                    "site_id": "AGG",
                    "tech": "nuclear-smr",
                    "bus_id": bus,
                    "p_nom_max_MW": total_nuc,
                    "p_min_pu": 0.0,
                    "p_max_pu": 0.9,
                    "ramp_pu_per_h": 0.5,
                }
            ]
        )
        nuclear_fixed_cap = {"AGG": total_nuc}

    tech_index = dispatch_techs + (["nuclear-smr"] if total_nuc > 0 else [])
    tech_params = data.tech_params.reindex(tech_index).dropna(how="all")

    return PreparedDataV4(
        scenario_name=data.scenario_name,
        buses=[bus],
        techs=dispatch_techs,
        lines=[],
        times=times,
        weights=data.weights,
        demand=demand,
        availability=availability,
        existing_cap=existing_cap,
        tech_params=tech_params,
        line_params=pd.DataFrame(),
        nuclear_sites=nuclear_sites,
        nuclear_fixed_cap=nuclear_fixed_cap,
        voll_eur_per_mwh=data.voll_eur_per_mwh,
        config=data.config,
    )


def build_model_v4(data: PreparedDataV4) -> BuiltModelV4:
    if data.config.get("copper_plate", False):
        data = _aggregate_copper_plate(data)

    m = gp.Container()

    bus_techs = [t for t in data.techs if not t.startswith("nuclear-")]
    time_labels = _time_labels(data.times)
    sites = data.nuclear_sites["site_id"].tolist() if len(data.nuclear_sites) else []
    has_nuclear = len(sites) > 0
    voll = float(data.voll_eur_per_mwh)

    n = gp.Set(m, name="n", records=[(b,) for b in data.buses], description="buses")
    t = gp.Set(m, name="t", records=[(ts,) for ts in time_labels], description="snapshots")
    k = gp.Set(m, name="k", records=[(tech,) for tech in bus_techs], description="technologies")

    w = gp.Parameter(
        m,
        name="w",
        domain=[t],
        records=[(ts, float(h)) for ts, h in zip(time_labels, data.weights.values())],
        description="snapshot weight hours",
    )

    demand = gp.Parameter(m, name="demand", domain=[n, t], description="load MW")
    demand.setRecords(
        [
            (row["bus"], pd.Timestamp(row["timestamp"]).strftime("%Y-%m-%dT%H:%M:%S"), float(row["demand_MW"]))
            for _, row in data.demand.iterrows()
        ]
    )

    existing = gp.Parameter(m, name="existing", domain=[n, k], description="installed MW")
    existing.setRecords(
        [
            (
                bus,
                tech,
                float(data.existing_cap.at[bus, tech])
                if bus in data.existing_cap.index and tech in data.existing_cap.columns
                else 0.0,
            )
            for bus in data.buses
            for tech in bus_techs
        ]
    )

    avail = gp.Parameter(m, name="avail", domain=[n, k, t], description="availability pu")
    avail.setRecords(
        [
            (row["bus"], row["tech"], pd.Timestamp(row["timestamp"]).strftime("%Y-%m-%dT%H:%M:%S"), float(row["p_max_pu"]))
            for _, row in data.availability.iterrows()
            if row["tech"] in bus_techs
        ]
    )

    marg = gp.Parameter(m, name="marg", domain=[k], description="marginal cost EUR/MWh")
    co2 = gp.Parameter(m, name="co2", domain=[k], description="CO2 t/MWh_el")
    co2_rel = gp.Parameter(m, name="co2_rel", domain=[k], description="CO2 counted")

    def _flag(val) -> float:
        return 1.0 if val in (True, "True", "true", 1, "1") else 0.0

    tech_records = []
    for tech in bus_techs:
        row = data.tech_params.loc[tech]
        tech_records.append(
            (
                tech,
                float(row["marginal_cost_EUR_per_MWh"]),
                float(row["co2_t_per_MWh"]),
                _flag(row["co2_relevant"]),
            )
        )
    marg.setRecords([(r[0], r[1]) for r in tech_records])
    co2.setRecords([(r[0], r[2]) for r in tech_records])
    co2_rel.setRecords([(r[0], r[3]) for r in tech_records])

    p = gp.Variable(m, name="p", domain=[n, k, t], type="positive", description="dispatch MW")
    ls = gp.Variable(m, name="ls", domain=[n, t], type="positive", description="load shedding MW")

    gen_upper = gp.Equation(m, name="gen_upper", domain=[n, k, t])
    gen_upper[n, k, t] = p[n, k, t] <= avail[n, k, t] * existing[n, k]

    symbols = {
        "p": p,
        "ls": ls,
        "w": w,
        "co2": co2,
        "co2_rel": co2_rel,
        "existing": existing,
        "demand": demand,
        "marg": marg,
        "voll": gp.Parameter(m, name="voll", records=voll),
    }

    opex = gp.Sum([n, k, t], w[t] * marg[k] * p[n, k, t]) + gp.Sum([n, t], w[t] * voll * ls[n, t])

    if has_nuclear:
        s = gp.Set(m, name="s", records=[(site,) for site in sites], description="nuclear sites")
        site_marg = gp.Parameter(m, name="site_marg", domain=[s], description="site marg cost")
        site_pmaxpu = gp.Parameter(m, name="site_pmaxpu", domain=[s], description="site avail pu")
        site_cap = gp.Parameter(m, name="site_cap", domain=[s], description="fixed site MW")

        site_records = []
        for _, row in data.nuclear_sites.iterrows():
            site = row["site_id"]
            tech = row["tech"]
            trow = data.tech_params.loc[tech]
            cap_mw = float(data.nuclear_fixed_cap.get(site, row["p_nom_max_MW"]))
            site_records.append((site, float(trow["marginal_cost_EUR_per_MWh"]), float(row["p_max_pu"]), cap_mw))

        site_marg.setRecords([(r[0], r[1]) for r in site_records])
        site_pmaxpu.setRecords([(r[0], r[2]) for r in site_records])
        site_cap.setRecords([(r[0], r[3]) for r in site_records])

        p_nuc = gp.Variable(m, name="p_nuc", domain=[s, t], type="positive", description="nuclear MW")

        nuc_upper = gp.Equation(m, name="nuc_upper", domain=[s, t])
        nuc_upper[s, t] = p_nuc[s, t] <= site_pmaxpu[s] * site_cap[s]

        opex = opex + gp.Sum([s, t], w[t] * site_marg[s] * p_nuc[s, t])
        symbols["p_nuc"] = p_nuc
        symbols["site_cap"] = site_cap
        symbols["site_marg"] = site_marg

        balance = gp.Equation(m, name="balance", domain=[n, t])
        balance[n, t] = gp.Sum(k, p[n, k, t]) + gp.Sum(s, p_nuc[s, t]) + ls[n, t] == demand[n, t]
    else:
        balance = gp.Equation(m, name="balance", domain=[n, t])
        balance[n, t] = gp.Sum(k, p[n, k, t]) + ls[n, t] == demand[n, t]

    model = gp.Model(
        m,
        name="inre_de_v4",
        equations=m.getEquations(),
        problem=gp.Problem.LP,
        sense=gp.Sense.MIN,
        objective=opex,
    )

    symbols["model"] = model
    symbols["balance"] = balance
    return BuiltModelV4(container=m, model=model, symbols=symbols)
