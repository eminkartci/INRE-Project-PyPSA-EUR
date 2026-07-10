# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Freeze AC lines and DC links: no transmission expansion in operational stress tests.

Sets s_nom_extendable / p_nom_extendable to False and pins min capacities to current values.
"""

from __future__ import annotations

import logging

import pypsa

logger = logging.getLogger(__name__)


def freeze_transmission(n: pypsa.Network) -> pypsa.Network:
    if len(n.lines):
        n.lines["s_nom_min"] = n.lines["s_nom"]
        n.lines["s_nom_extendable"] = False
        if "s_nom_opt" in n.lines.columns:
            n.lines["s_nom_opt"] = n.lines["s_nom"]

    if len(n.links):
        dc = n.links.carrier == "DC"
        if dc.any():
            n.links.loc[dc, "p_nom_min"] = n.links.loc[dc, "p_nom"]
            n.links.loc[dc, "p_nom_extendable"] = False
            if "p_nom_opt" in n.links.columns:
                n.links.loc[dc, "p_nom_opt"] = n.links.loc[dc, "p_nom"]

    logger.info(
        "Froze transmission: %d lines, %d DC links",
        len(n.lines),
        int((n.links.carrier == "DC").sum()) if len(n.links) else 0,
    )
    return n


def verify_frozen(n: pypsa.Network) -> bool:
    ok = True
    if len(n.lines) and n.lines["s_nom_extendable"].any():
        logger.error("Lines still extendable: %s", n.lines.index[n.lines.s_nom_extendable].tolist())
        ok = False
    if len(n.links):
        dc = n.links.carrier == "DC"
        if dc.any() and n.links.loc[dc, "p_nom_extendable"].any():
            logger.error("DC links still extendable")
            ok = False
    return ok
