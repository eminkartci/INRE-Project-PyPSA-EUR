# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Create dispatch-only networks with fixed capacities, overriding solar capacity.

Use-case (Option 1):
- Compare base vs dunkelflaute dispatch with comparable solar capacity
- Prevent solar p_nom_opt from exploding in stress scenario

Method:
1) Load a solved scenario network (e.g. dunkelflaute)
2) Freeze *all* capacities to the scenario's own p_nom_opt/s_nom_opt
3) Override solar/solar-hsat p_nom with values taken from a reference network (e.g. base)
4) Disable all expansion and re-solve dispatch only
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pypsa


SOLAR_CARRIERS = {"solar", "solar-hsat"}
KEEP_EXTENDABLE_CARRIERS = {"CCGT"}


def freeze_to_opt(n: pypsa.Network) -> None:
    if len(n.generators):
        if "p_nom_opt" in n.generators.columns:
            n.generators["p_nom"] = n.generators["p_nom_opt"]
        n.generators["p_nom_extendable"] = False
        if "p_nom_opt" in n.generators.columns:
            n.generators["p_nom_opt"] = n.generators["p_nom"]

    if hasattr(n, "storage_units") and len(n.storage_units):
        if "p_nom_opt" in n.storage_units.columns:
            n.storage_units["p_nom"] = n.storage_units["p_nom_opt"]
        n.storage_units["p_nom_extendable"] = False
        if "p_nom_opt" in n.storage_units.columns:
            n.storage_units["p_nom_opt"] = n.storage_units["p_nom"]

    if hasattr(n, "links") and len(n.links):
        if "p_nom_opt" in n.links.columns:
            n.links["p_nom"] = n.links["p_nom_opt"]
        n.links["p_nom_extendable"] = False
        if "p_nom_opt" in n.links.columns:
            n.links["p_nom_opt"] = n.links["p_nom"]

    if hasattr(n, "lines") and len(n.lines):
        if "s_nom_opt" in n.lines.columns:
            n.lines["s_nom"] = n.lines["s_nom_opt"]
        if "s_nom_extendable" in n.lines.columns:
            n.lines["s_nom_extendable"] = False
        if "s_nom_opt" in n.lines.columns:
            n.lines["s_nom_opt"] = n.lines["s_nom"]


def override_solar_from(n: pypsa.Network, solar_ref: pypsa.Network) -> None:
    if not len(n.generators) or not len(solar_ref.generators):
        return
    ref = solar_ref.generators
    ref_cap = ref["p_nom_opt"] if "p_nom_opt" in ref.columns else ref["p_nom"]

    mask = n.generators.carrier.isin(SOLAR_CARRIERS)
    if not mask.any():
        return

    aligned = ref_cap.reindex(n.generators.index)
    idx = aligned.dropna().index.intersection(n.generators.index[mask])
    n.generators.loc[idx, "p_nom"] = aligned.loc[idx]
    if "p_nom_opt" in n.generators.columns:
        n.generators.loc[idx, "p_nom_opt"] = n.generators.loc[idx, "p_nom"]

    # Ensure feasibility under fixed solar by allowing slack supply (load shedding) at high cost.
    # This keeps comparisons meaningful: any non-zero shedding flags insufficient fixed capacity.
    if "load_shed" not in n.carriers.index:
        n.add("Carrier", "load_shed", co2_emissions=0.0)
    for bus in n.buses.index:
        name = f"load_shed_{bus}"
        if name in n.generators.index:
            continue
        n.add(
            "Generator",
            name,
            bus=bus,
            carrier="load_shed",
            p_nom=0.0,
            p_nom_extendable=True,
            p_nom_max=1e6,
            marginal_cost=1e5,  # VOLL aligned with config solving.options.load_shedding.default_cost
        )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--solar-ref", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--solver", default="highs")
    args = p.parse_args()

    n = pypsa.Network(args.input)
    ref = pypsa.Network(args.solar_ref)

    freeze_to_opt(n)
    override_solar_from(n, ref)

    n.optimize(solver_name=args.solver)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(out))


if __name__ == "__main__":
    main()

