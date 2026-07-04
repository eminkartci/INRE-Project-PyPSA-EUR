# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Apply INRE scenario modifications (Dunkelflaute stress, new nuclear technologies)
to a prepared electricity network before solving.
"""

import logging
import shutil

import pandas as pd
import pypsa

from scripts._helpers import configure_logging, load_costs, set_scenario_config
from scripts.inre.add_nuclear_technologies import add_nuclear_technologies
from scripts.inre.apply_dunkelflaute import apply_dunkelflaute, load_params

logger = logging.getLogger(__name__)


def _needs_inre_pass(inre: dict) -> bool:
    if not inre.get("enabled", False):
        return False
    dunkel = inre.get("dunkelflaute", {})
    nuclear = inre.get("nuclear", {})
    return bool(dunkel.get("enabled")) or bool(nuclear.get("extendable_carriers"))


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "apply_inre_network",
            clusters="10",
            opts="",
            run="inre-de-base",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    inre = snakemake.params.inre or {}
    if not _needs_inre_pass(inre):
        shutil.copyfile(snakemake.input.network, snakemake.output.network)
        logger.info("No INRE modifications requested; copied prepared network.")
    else:
        n = pypsa.Network(snakemake.input.network)

        dunkel_cfg = inre.get("dunkelflaute", {})
        if dunkel_cfg.get("enabled"):
            dunkel_config_path = dunkel_cfg.get("config")
            params = load_params(dunkel_config_path)
            params["enabled"] = True
            apply_dunkelflaute(n, params=params, config_path=dunkel_config_path)

        nuclear_cfg = inre.get("nuclear", {})
        carriers = nuclear_cfg.get("extendable_carriers") or []
        if carriers:
            costs = load_costs(snakemake.input.costs)
            add_nuclear_technologies(
                n,
                carriers=carriers,
                costs=costs,
                sites_file=nuclear_cfg.get("sites_file"),
                p_nom_max_per_site=float(nuclear_cfg.get("p_nom_max_per_site", 1500)),
                p_max_pu=float(nuclear_cfg.get("p_max_pu", 0.9)),
            )

        n.export_to_netcdf(snakemake.output.network)
        logger.info("Wrote INRE-modified network to %s", snakemake.output.network)
