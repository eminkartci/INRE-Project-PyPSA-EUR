# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT

"""
Snakemake rules for INRE Dunkelflaute stress tests and new nuclear technologies.
"""


def _inre_needs_modification(w):
    inre = config_provider("inre", default={})(w) or {}
    if not inre.get("enabled", False):
        return False
    dunkel = inre.get("dunkelflaute", {})
    nuclear = inre.get("nuclear", {})
    return bool(dunkel.get("enabled")) or bool(nuclear.get("extendable_carriers"))


def _inre_needs_nuclear(w):
    inre = config_provider("inre", default={})(w) or {}
    if not inre.get("enabled", False):
        return False
    return bool((inre.get("nuclear", {}) or {}).get("extendable_carriers"))


def _inre_scenario_costs_path(w):
    year = config_provider("costs", "year")(w)
    return RESULTS + f"costs/costs_{year}_processed.csv"


def _input_solve_network(w):
    if _inre_needs_modification(w):
        return RESULTS + "networks/base_s_{clusters}_elec_{opts}_inre.nc"
    return resources("networks/base_s_{clusters}_elec_{opts}.nc")


rule process_inre_scenario_costs:
    input:
        network=resources("networks/base_s.nc"),
        costs=rules.retrieve_cost_data.output["costs"],
        custom_costs=config_provider("costs", "custom_cost_fn"),
    output:
        RESULTS + "costs/costs_{planning_horizons}_processed.csv",
    log:
        RESULTS + "logs/process_inre_scenario_costs/costs_{planning_horizons}.log",
    benchmark:
        RESULTS + "benchmarks/process_inre_scenario_costs/costs_{planning_horizons}",
    threads: 1
    resources:
        mem_mb=2000,
    params:
        costs=config_provider("costs"),
        max_hours=config_provider("electricity", "max_hours"),
    message:
        "Processing scenario-specific INRE cost data ({wildcards.planning_horizons})"
    script:
        scripts("inre/process_scenario_costs.py")


rule apply_inre_network:
    input:
        network=resources("networks/base_s_{clusters}_elec_{opts}.nc"),
        costs=lambda w: (
            _inre_scenario_costs_path(w) if _inre_needs_nuclear(w) else []
        ),
    output:
        network=RESULTS + "networks/base_s_{clusters}_elec_{opts}_inre.nc",
    log:
        RESULTS + "logs/apply_inre_network/base_s_{clusters}_elec_{opts}.log",
    benchmark:
        RESULTS + "benchmarks/apply_inre_network/base_s_{clusters}_elec_{opts}"
    threads: 1
    resources:
        mem_mb=4000,
    params:
        inre=config_provider("inre", default={}),
    message:
        "Applying INRE Dunkelflaute / nuclear modifications for {wildcards.clusters} clusters"
    script:
        scripts("inre/apply_inre_network.py")
