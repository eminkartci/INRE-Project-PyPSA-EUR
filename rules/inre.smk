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


def _input_solve_network(w):
    if _inre_needs_modification(w):
        return RESULTS + "networks/base_s_{clusters}_elec_{opts}_inre.nc"
    return resources("networks/base_s_{clusters}_elec_{opts}.nc")


rule apply_inre_network:
    input:
        network=resources("networks/base_s_{clusters}_elec_{opts}.nc"),
        costs=lambda w: (
            resources(f"costs_{config_provider('costs', 'year')(w)}_processed.csv")
            if _inre_needs_modification(w)
            else []
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
