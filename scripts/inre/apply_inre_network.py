# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Apply INRE scenario modifications (Dunkelflaute stress, new nuclear technologies)
to a prepared electricity network before solving.
"""

import logging
import shutil
from pathlib import Path

import pandas as pd
import pypsa

from scripts._helpers import configure_logging, load_costs, set_scenario_config
from scripts.inre.add_nuclear_technologies import add_nuclear_technologies
from scripts.inre.apply_dunkelflaute import apply_dunkelflaute, load_params
from scripts.inre.apply_historical_dunkelflaute import apply_historical_dunkelflaute
from scripts.inre.apply_stylised_dunkelflaute_v4 import (
    apply_profile_to_network,
    load_profile_csv,
    _extend_snapshots_and_demand,
)
from scripts.inre.freeze_transmission import freeze_transmission, verify_frozen

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _needs_inre_pass(inre: dict) -> bool:
    if not inre.get("enabled", False):
        return False
    dunkel = inre.get("dunkelflaute", {})
    nuclear = inre.get("nuclear", {})
    return bool(dunkel.get("enabled")) or bool(nuclear.get("extendable_carriers"))


def _apply_stylised_v4_layer(n: pypsa.Network, dunkel_cfg: dict) -> None:
    config_path = dunkel_cfg.get("config")
    params = load_params(config_path)
    severity = dunkel_cfg.get("severity", params.get("main_scenario", "severe"))
    profile_key = params.get("profiles", {}).get(severity, f"{severity}_p_max_pu.csv")
    profile_dir = Path(config_path).parent / params.get("profile_dir", "profiles/stylised_dunkelflaute_v4")
    if not profile_dir.exists():
        profile_dir = REPO_ROOT / "data/inre" / params.get("profile_dir", "profiles/stylised_dunkelflaute_v4")
    profile_path = profile_dir / profile_key
    demand_csv = REPO_ROOT / "data/entsoe_electricity_demand/archive/2026-02-02/electricity_demand_entsoe_raw.csv"
    profile = load_profile_csv(profile_path)
    _extend_snapshots_and_demand(n, profile, demand_csv)
    apply_profile_to_network(n, profile)
    logger.info("Applied stylised V4 profile severity=%s from %s", severity, profile_path)


def _apply_dunkelflaute_layer(n: pypsa.Network, dunkel_cfg: dict) -> None:
    dunkel_type = dunkel_cfg.get("type", "legacy")
    config_path = dunkel_cfg.get("config")
    if dunkel_type == "stylised_v4":
        _apply_stylised_v4_layer(n, dunkel_cfg)
        return
    if dunkel_type in ("historical", "matched_reference", "extreme_sensitivity", "historical_normal"):
        params = load_params(config_path)
        params["enabled"] = True
        if dunkel_type == "matched_reference":
            params["mode"] = "matched_reference"
        elif dunkel_type == "extreme_sensitivity":
            params["mode"] = "extreme_sensitivity"
        elif dunkel_type == "historical_normal":
            params["mode"] = "historical_normal"
        else:
            params["mode"] = "historical"
        apply_historical_dunkelflaute(n, params=params, config_path=config_path)
    else:
        params = load_params(config_path)
        params["enabled"] = True
        apply_dunkelflaute(n, params=params, config_path=config_path)


def _patch_co2_emissions_for_thermal(n: pypsa.Network) -> None:
    """Align carrier co2_emissions with fuel-input intensity ÷ efficiency (MWh_el basis)."""
    thermal = {"CCGT", "OCGT", "coal", "lignite", "oil"}
    for gen in n.generators.query("carrier in @thermal").index:
        carrier = n.generators.at[gen, "carrier"]
        eff = float(n.generators.at[gen, "efficiency"])
        if eff <= 0 or carrier not in n.carriers.index:
            continue
        raw = float(n.carriers.at[carrier, "co2_emissions"])
        n.carriers.at[carrier, "co2_emissions"] = raw / eff


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

        if inre.get("freeze_transmission", True):
            freeze_transmission(n)

        dunkel_cfg = inre.get("dunkelflaute", {})
        if dunkel_cfg.get("enabled"):
            _apply_dunkelflaute_layer(n, dunkel_cfg)

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
                p_min_pu=float(nuclear_cfg.get("p_min_pu", 0.0)),
                ramp_limit_per_hour=float(nuclear_cfg.get("ramp_limit_per_hour", 0.5)),
                site_names=nuclear_cfg.get("site_names"),
                total_cap_mw=nuclear_cfg.get("total_cap_mw"),
                compare_mode=nuclear_cfg.get("compare_mode", "site-potential"),
            )

        if inre.get("patch_co2_emissions", True):
            _patch_co2_emissions_for_thermal(n)

        if inre.get("freeze_transmission", True):
            verify_frozen(n)

        n.export_to_netcdf(snakemake.output.network)
        logger.info("Wrote INRE-modified network to %s", snakemake.output.network)
