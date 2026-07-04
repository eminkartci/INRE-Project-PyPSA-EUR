"""Build and solve the Germany GAMSPy LP capacity expansion model."""

from __future__ import annotations

from dataclasses import dataclass

import gamspy as gp
import pandas as pd

from apply_scenario import PreparedData


@dataclass
class BuiltModel:
    container: gp.Container
    model: gp.Model
    symbols: dict


def _time_labels(times: list[pd.Timestamp]) -> list[str]:
    return [ts.strftime("%Y-%m-%dT%H:%M:%S") for ts in times]


def build_model(data: PreparedData) -> BuiltModel:
    m = gp.Container()

    bus_techs = [t for t in data.techs if not t.startswith("nuclear-")]
    time_labels = _time_labels(data.times)
    sites = data.nuclear_sites["site_id"].tolist() if len(data.nuclear_sites) else []
    has_nuclear = len(sites) > 0
    snapshot_hours = float(list(data.weights.values())[0])

    n = gp.Set(m, name="n", records=[(b,) for b in data.buses], description="buses")
    t = gp.Set(m, name="t", records=[(ts,) for ts in time_labels], description="snapshots")
    k = gp.Set(m, name="k", records=[(tech,) for tech in bus_techs], description="technologies")
    l = gp.Set(m, name="l", records=[(line,) for line in data.lines], description="lines")

    w = gp.Parameter(
        m,
        name="w",
        domain=[t],
        records=[(ts, float(h)) for ts, h in zip(time_labels, data.weights.values())],
        description="snapshot weight hours",
    )
    snap_h = gp.Parameter(m, name="snap_h", records=snapshot_hours)

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
                float(data.existing_cap.at[bus, tech]) if bus in data.existing_cap.index and tech in data.existing_cap.columns else 0.0,
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
    cap_cost = gp.Parameter(m, name="cap_cost", domain=[k], description="capital EUR/MWyr")
    p_min = gp.Parameter(m, name="p_min", domain=[k], description="min stable load pu")
    ramp = gp.Parameter(m, name="ramp", domain=[k], description="ramp pu per hour")
    co2 = gp.Parameter(m, name="co2", domain=[k], description="CO2 t/MWh")
    extendable = gp.Parameter(m, name="extendable", domain=[k], description="extendable flag")
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
                float(row["capital_cost_EUR_per_MWyr"]),
                float(row["p_min_pu"]),
                float(row["ramp_pu_per_h"]),
                float(row["co2_t_per_MWh"]),
                _flag(row["extendable"]),
                _flag(row["co2_relevant"]),
            )
        )
    marg.setRecords([(r[0], r[1]) for r in tech_records])
    cap_cost.setRecords([(r[0], r[2]) for r in tech_records])
    p_min.setRecords([(r[0], r[3]) for r in tech_records])
    ramp.setRecords([(r[0], r[4]) for r in tech_records])
    co2.setRecords([(r[0], r[5]) for r in tech_records])
    extendable.setRecords([(r[0], r[6]) for r in tech_records])
    co2_rel.setRecords([(r[0], r[7]) for r in tech_records])

    s_nom = gp.Parameter(m, name="s_nom", domain=[l], description="line capacity MW")
    line_in = gp.Parameter(m, name="line_in", domain=[l, n], description="flow into bus")
    line_out = gp.Parameter(m, name="line_out", domain=[l, n], description="flow out of bus")
    s_nom.setRecords([(line_id, float(data.line_params.at[line_id, "s_nom_MW"])) for line_id in data.lines])
    in_records = []
    out_records = []
    for line_id in data.lines:
        row = data.line_params.loc[line_id]
        for bus in data.buses:
            in_records.append((line_id, bus, 1.0 if row["bus1"] == bus else 0.0))
            out_records.append((line_id, bus, 1.0 if row["bus0"] == bus else 0.0))
    line_in.setRecords(in_records)
    line_out.setRecords(out_records)

    st_cap_p = gp.Parameter(m, name="st_cap_p", domain=[n], description="storage power capex")
    st_cap_e = gp.Parameter(m, name="st_cap_e", domain=[n], description="storage energy capex")
    st_marg = gp.Parameter(m, name="st_marg", domain=[n], description="storage marginal")
    st_eta = gp.Parameter(m, name="st_eta", domain=[n], description="storage roundtrip eff")
    st_loss = gp.Parameter(m, name="st_loss", domain=[n], description="storage hourly loss")
    st_hours = gp.Parameter(m, name="st_hours", domain=[n], description="max storage hours")
    st_records = []
    for bus in data.buses:
        row = data.storage_params.loc[bus]
        eta = float(row["efficiency_store"]) * float(row["efficiency_dispatch"])
        st_records.append(
            (
                bus,
                float(row["capital_cost_power_EUR_per_MWyr"]),
                float(row["capital_cost_energy_EUR_per_MWhyr"]),
                float(row["marginal_cost_EUR_per_MWh"]),
                eta,
                float(row["standing_loss_per_h"]),
                float(row["max_hours"]),
            )
        )
    st_cap_p.setRecords([(r[0], r[1]) for r in st_records])
    st_cap_e.setRecords([(r[0], r[2]) for r in st_records])
    st_marg.setRecords([(r[0], r[3]) for r in st_records])
    st_eta.setRecords([(r[0], r[4]) for r in st_records])
    st_loss.setRecords([(r[0], r[5]) for r in st_records])
    st_hours.setRecords([(r[0], r[6]) for r in st_records])

    p = gp.Variable(m, name="p", domain=[n, k, t], type="positive", description="dispatch MW")
    p_cap = gp.Variable(m, name="p_cap", domain=[n, k], type="positive", description="new gen MW")
    f = gp.Variable(m, name="f", domain=[l, t], type="free", description="line flow MW")
    p_dis = gp.Variable(m, name="p_dis", domain=[n, t], type="positive", description="storage discharge")
    p_ch = gp.Variable(m, name="p_ch", domain=[n, t], type="positive", description="storage charge")
    e_cap = gp.Variable(m, name="e_cap", domain=[n], type="positive", description="storage MWh")
    p_st_cap = gp.Variable(m, name="p_st_cap", domain=[n], type="positive", description="storage MW")
    soc = gp.Variable(m, name="soc", domain=[n, t], type="positive", description="storage MWh")

    gen_upper = gp.Equation(m, name="gen_upper", domain=[n, k, t])
    gen_upper[n, k, t] = p[n, k, t] <= avail[n, k, t] * (existing[n, k] + p_cap[n, k])

    gen_lower = gp.Equation(m, name="gen_lower", domain=[n, k, t])
    gen_lower[n, k, t] = p[n, k, t] >= p_min[k] * (existing[n, k] + p_cap[n, k])

    cap_limit = gp.Equation(m, name="cap_limit", domain=[n, k])
    cap_limit[n, k] = p_cap[n, k] <= extendable[k] * 1e6

    t_ramp = gp.Set(
        m,
        name="t_ramp",
        domain=[t],
        records=[(time_labels[i],) for i in range(1, len(time_labels))],
        description="snapshots after first",
    )

    co2_limit = gp.Parameter(m, name="co2_limit", records=data.co2_limit_window)

    ramp_up = gp.Equation(m, name="ramp_up", domain=[n, k, t_ramp])
    ramp_up[n, k, t_ramp] = (
        p[n, k, t_ramp] - p[n, k, t_ramp.lag(1)]
        <= ramp[k] * snap_h * (existing[n, k] + p_cap[n, k])
    )

    ramp_down = gp.Equation(m, name="ramp_down", domain=[n, k, t_ramp])
    ramp_down[n, k, t_ramp] = (
        p[n, k, t_ramp.lag(1)] - p[n, k, t_ramp]
        <= ramp[k] * snap_h * (existing[n, k] + p_cap[n, k])
    )

    flow_pos = gp.Equation(m, name="flow_pos", domain=[l, t])
    flow_pos[l, t] = f[l, t] <= s_nom[l]

    flow_neg = gp.Equation(m, name="flow_neg", domain=[l, t])
    flow_neg[l, t] = f[l, t] >= -s_nom[l]

    st_dis_limit = gp.Equation(m, name="st_dis_limit", domain=[n, t])
    st_dis_limit[n, t] = p_dis[n, t] <= p_st_cap[n]

    st_ch_limit = gp.Equation(m, name="st_ch_limit", domain=[n, t])
    st_ch_limit[n, t] = p_ch[n, t] <= p_st_cap[n]

    st_e_limit = gp.Equation(m, name="st_e_limit", domain=[n, t])
    st_e_limit[n, t] = soc[n, t] <= e_cap[n]

    st_e_link = gp.Equation(m, name="st_e_link", domain=[n])
    st_e_link[n] = e_cap[n] <= st_hours[n] * p_st_cap[n]

    st_dyn = gp.Equation(m, name="st_dyn", domain=[n, t_ramp])
    st_dyn[n, t_ramp] = (
        soc[n, t_ramp]
        == (1 - st_loss[n] * snap_h) * soc[n, t_ramp.lag(1)]
        + st_eta[n] * p_ch[n, t_ramp] * snap_h
        - p_dis[n, t_ramp] / st_eta[n] * snap_h
    )

    st_init = gp.Equation(m, name="st_init", domain=[n])
    st_init[n] = soc[n, time_labels[0]] == 0.5 * e_cap[n]

    symbols = {
        "p": p,
        "p_cap": p_cap,
        "f": f,
        "p_dis": p_dis,
        "p_ch": p_ch,
        "e_cap": e_cap,
        "p_st_cap": p_st_cap,
        "soc": soc,
        "w": w,
        "co2_limit": co2_limit,
    }

    opex = gp.Sum([n, k, t], w[t] * marg[k] * p[n, k, t]) + gp.Sum(
        [n, t], w[t] * st_marg[n] * (p_dis[n, t] + p_ch[n, t])
    )
    capex = gp.Sum([n, k], cap_cost[k] * p_cap[n, k]) + gp.Sum(
        n, st_cap_p[n] * p_st_cap[n] + st_cap_e[n] * e_cap[n]
    )

    if has_nuclear:
        s = gp.Set(m, name="s", records=[(site,) for site in sites], description="nuclear sites")
        site_at = gp.Parameter(m, name="site_at", domain=[s, n], description="site at bus")
        site_pmax = gp.Parameter(m, name="site_pmax", domain=[s], description="site cap MW")
        site_marg = gp.Parameter(m, name="site_marg", domain=[s], description="site marg cost")
        site_cap_cost = gp.Parameter(m, name="site_cap_cost", domain=[s], description="site capex")
        site_pmin = gp.Parameter(m, name="site_pmin", domain=[s], description="site min pu")
        site_pmaxpu = gp.Parameter(m, name="site_pmaxpu", domain=[s], description="site avail pu")
        site_ramp = gp.Parameter(m, name="site_ramp", domain=[s], description="site ramp pu/h")

        at_records = []
        site_records = []
        for _, row in data.nuclear_sites.iterrows():
            site = row["site_id"]
            tech = row["tech"]
            trow = data.tech_params.loc[tech]
            site_records.append(
                (
                    site,
                    float(row["p_nom_max_MW"]),
                    float(trow["marginal_cost_EUR_per_MWh"]),
                    float(trow["capital_cost_EUR_per_MWyr"]),
                    float(row["p_min_pu"]),
                    float(row["p_max_pu"]),
                    float(row["ramp_pu_per_h"]),
                    row["bus_id"],
                )
            )
            for bus in data.buses:
                at_records.append((site, bus, 1.0 if row["bus_id"] == bus else 0.0))

        site_pmax.setRecords([(r[0], r[1]) for r in site_records])
        site_marg.setRecords([(r[0], r[2]) for r in site_records])
        site_cap_cost.setRecords([(r[0], r[3]) for r in site_records])
        site_pmin.setRecords([(r[0], r[4]) for r in site_records])
        site_pmaxpu.setRecords([(r[0], r[5]) for r in site_records])
        site_ramp.setRecords([(r[0], r[6]) for r in site_records])
        site_at.setRecords(at_records)

        p_nuc = gp.Variable(m, name="p_nuc", domain=[s, t], type="positive", description="nuclear MW")
        cap_nuc = gp.Variable(m, name="cap_nuc", domain=[s], type="positive", description="nuclear build MW")

        nuc_upper = gp.Equation(m, name="nuc_upper", domain=[s, t])
        nuc_upper[s, t] = p_nuc[s, t] <= site_pmaxpu[s] * cap_nuc[s]

        nuc_lower = gp.Equation(m, name="nuc_lower", domain=[s, t])
        nuc_lower[s, t] = p_nuc[s, t] >= site_pmin[s] * cap_nuc[s]

        nuc_cap = gp.Equation(m, name="nuc_cap", domain=[s])
        nuc_cap[s] = cap_nuc[s] <= site_pmax[s]

        nuc_ramp_up = gp.Equation(m, name="nuc_ramp_up", domain=[s, t_ramp])
        nuc_ramp_up[s, t_ramp] = (
            p_nuc[s, t_ramp] - p_nuc[s, t_ramp.lag(1)] <= site_ramp[s] * snap_h * cap_nuc[s]
        )

        nuc_ramp_down = gp.Equation(m, name="nuc_ramp_down", domain=[s, t_ramp])
        nuc_ramp_down[s, t_ramp] = (
            p_nuc[s, t_ramp.lag(1)] - p_nuc[s, t_ramp] <= site_ramp[s] * snap_h * cap_nuc[s]
        )

        nuc_balance = gp.Sum([s, t], w[t] * site_marg[s] * p_nuc[s, t])
        nuc_capex = gp.Sum(s, site_cap_cost[s] * cap_nuc[s])
        opex = opex + nuc_balance
        capex = capex + nuc_capex

        symbols["p_nuc"] = p_nuc
        symbols["cap_nuc"] = cap_nuc

        balance = gp.Equation(m, name="balance", domain=[n, t])
        balance[n, t] = (
            gp.Sum(k, p[n, k, t])
            + gp.Sum(s, p_nuc[s, t] * site_at[s, n])
            + gp.Sum(l, f[l, t] * (line_in[l, n] - line_out[l, n]))
            + p_dis[n, t]
            - p_ch[n, t]
            == demand[n, t]
        )
    else:
        balance = gp.Equation(m, name="balance", domain=[n, t])
        balance[n, t] = (
            gp.Sum(k, p[n, k, t])
            + gp.Sum(l, f[l, t] * (line_in[l, n] - line_out[l, n]))
            + p_dis[n, t]
            - p_ch[n, t]
            == demand[n, t]
        )

    co2_cap = gp.Equation(m, name="co2_cap")
    co2_cap[...] = gp.Sum([n, k, t], w[t] * co2[k] * co2_rel[k] * p[n, k, t]) <= co2_limit

    model = gp.Model(
        m,
        name="inre_de",
        equations=m.getEquations(),
        problem=gp.Problem.LP,
        sense=gp.Sense.MIN,
        objective=opex + capex,
    )

    symbols["model"] = model
    return BuiltModel(container=m, model=model, symbols=symbols)
