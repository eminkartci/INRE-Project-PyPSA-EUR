"""Build reduced-form 8-variable copper-plate GAMSPy dispatch model."""

from __future__ import annotations

from dataclasses import dataclass

import gamspy as gp
import pandas as pd

from apply_scenario_rf import PreparedDataRF


@dataclass
class BuiltModelRF:
    container: gp.Container
    model: gp.Model
    symbols: dict


def _time_labels(times: list[pd.Timestamp]) -> list[str]:
    return [ts.strftime("%Y-%m-%dT%H:%M:%S") for ts in times]


def build_model_rf(data: PreparedDataRF) -> BuiltModelRF:
    m = gp.Container()
    blocks = list(data.blocks)
    time_labels = _time_labels(data.times)
    voll = float(data.voll_eur_per_mwh)

    b = gp.Set(m, name="b", records=[(blk,) for blk in blocks], description="dispatch blocks")
    t = gp.Set(m, name="t", records=[(ts,) for ts in time_labels], description="snapshots")

    w = gp.Parameter(
        m,
        name="w",
        domain=[t],
        records=[(ts, float(h)) for ts, h in zip(time_labels, data.weights.values())],
        description="snapshot weight hours",
    )

    demand = gp.Parameter(m, name="demand", domain=[t], description="national load MW")
    demand.setRecords(
        [
            (pd.Timestamp(row["timestamp"]).strftime("%Y-%m-%dT%H:%M:%S"), float(row["demand_MW"]))
            for _, row in data.demand.iterrows()
        ]
    )

    cap = gp.Parameter(m, name="cap", domain=[b], description="installed MW")
    cap.setRecords([(row["block"], float(row["installed_capacity_MW"])) for _, row in data.blocks_df.iterrows()])

    avail = gp.Parameter(m, name="avail", domain=[b, t], description="available MW")
    avail.setRecords(
        [
            (row["block"], pd.Timestamp(row["timestamp"]).strftime("%Y-%m-%dT%H:%M:%S"), float(row["available_MW"]))
            for _, row in data.availability.iterrows()
        ]
    )

    marg = gp.Parameter(m, name="marg", domain=[b], description="marginal cost EUR/MWh")
    co2 = gp.Parameter(m, name="co2", domain=[b], description="CO2 t/MWh_el")
    co2_rel = gp.Parameter(m, name="co2_rel", domain=[b], description="CO2 counted")

    marg.setRecords([(row["block"], float(row["marginal_cost_EUR_per_MWh"])) for _, row in data.blocks_df.iterrows()])
    co2.setRecords([(row["block"], float(row["co2_t_per_MWh_el"])) for _, row in data.blocks_df.iterrows()])
    co2_rel.setRecords(
        [
            (row["block"], 1.0 if float(row["co2_t_per_MWh_el"]) > 0.0 else 0.0)
            for _, row in data.blocks_df.iterrows()
        ]
    )

    p = gp.Variable(m, name="p", domain=[b, t], type="positive", description="dispatch MW")
    ls = gp.Variable(m, name="ls", domain=[t], type="positive", description="load shedding MW")

    gen_upper = gp.Equation(m, name="gen_upper", domain=[b, t])
    gen_upper[b, t] = p[b, t] <= avail[b, t]

    balance = gp.Equation(m, name="balance", domain=[t])
    balance[t] = gp.Sum(b, p[b, t]) + ls[t] == demand[t]

    opex = gp.Sum([b, t], w[t] * marg[b] * p[b, t]) + gp.Sum(t, w[t] * voll * ls[t])

    model = gp.Model(
        m,
        name="inre_de_rf",
        equations=m.getEquations(),
        problem=gp.Problem.LP,
        sense=gp.Sense.MIN,
        objective=opex,
    )

    symbols = {
        "p": p,
        "ls": ls,
        "w": w,
        "cap": cap,
        "avail": avail,
        "demand": demand,
        "marg": marg,
        "co2": co2,
        "co2_rel": co2_rel,
        "voll": gp.Parameter(m, name="voll", records=voll),
        "model": model,
        "balance": balance,
    }
    return BuiltModelRF(container=m, model=model, symbols=symbols)
