# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Build scenario-specific processed cost tables for INRE nuclear scenarios.

The shared ``process_cost_data`` rule has no ``{run}`` wildcard, so with
``run.shared_resources.policy: true`` every scenario reuses one
``resources/costs_*_processed.csv`` built from the top-level config only.
This rule re-applies ``costs.custom_cost_fn`` per scenario (including CAPEX
sensitivity files) into ``results/<run>/costs/``.
"""

import logging

import pandas as pd
import pypsa

from scripts import process_cost_data
from scripts._helpers import configure_logging, set_scenario_config
from scripts.process_cost_data import prepare_costs

logger = logging.getLogger(__name__)


def _bind_process_cost_context(snakemake) -> str:
    """
    ``prepare_costs`` reads ``snakemake.input.custom_costs`` and ``planning_horizon``
    from the ``process_cost_data`` module namespace when invoked as a library.
    """
    planning_horizon = str(snakemake.wildcards.planning_horizons)
    process_cost_data.snakemake = snakemake
    process_cost_data.planning_horizon = planning_horizon
    return planning_horizon


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "process_inre_scenario_costs",
            run="dunkelflaute-smr-capex70",
            planning_horizons="2050",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    _bind_process_cost_context(snakemake)

    n = pypsa.Network(snakemake.input.network)
    nyears = n.snapshot_weightings.generators.sum() / 8760.0

    costs = pd.read_csv(snakemake.input.costs, index_col=["technology", "parameter"])
    costs_processed = prepare_costs(
        costs,
        snakemake.params.costs,
        snakemake.params.max_hours,
        nyears,
        snakemake.input.custom_costs,
    )
    costs_processed.to_csv(snakemake.output[0])
    logger.info(
        "Wrote scenario costs to %s (custom_cost_fn=%s)",
        snakemake.output[0],
        snakemake.config.get("costs", {}).get("custom_cost_fn"),
    )
