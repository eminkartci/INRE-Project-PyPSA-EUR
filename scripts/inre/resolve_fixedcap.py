# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Re-solve an existing solved PyPSA network with fixed capacities.

Purpose:
- Eliminate phantom capacity expansion (e.g., solar/wind/link battery p_nom_opt inflation)
- Enable apples-to-apples dispatch comparison across scenarios (e.g., base vs dunkelflaute)

This script loads a solved network, fixes all extendable assets to their initial p_nom/s_nom
values, disables expansion, and re-solves the dispatch for the same snapshots.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pypsa


def _fix_component_capacity(
    n: pypsa.Network,
    reference: pypsa.Network | None = None,
    fix_generator_carriers: set[str] | None = None,
    fix_all_components: bool = False,
) -> None:
    # Generators
    if len(n.generators):
        if fix_generator_carriers is None:
            fix_mask = n.generators.index.to_series().map(lambda _: False)
        else:
            fix_mask = n.generators.carrier.isin(fix_generator_carriers)

        if fix_mask.any():
            if reference is not None and len(reference.generators):
                ref = reference.generators
                ref_p = ref["p_nom_opt"] if "p_nom_opt" in ref.columns else ref["p_nom"]
                aligned = ref_p.reindex(n.generators.index)
                idx = aligned.dropna().index.intersection(n.generators.index)
                # Fix to reference capacities if provided, else keep current p_nom
                n.generators.loc[idx, "p_nom"] = aligned.loc[idx]

            n.generators.loc[fix_mask, "p_nom_extendable"] = False
            if "p_nom_opt" in n.generators.columns:
                n.generators.loc[fix_mask, "p_nom_opt"] = n.generators.loc[fix_mask, "p_nom"]

    if not fix_all_components:
        return

    # Storage units (battery etc.)
    if hasattr(n, "storage_units") and len(n.storage_units):
        if reference is not None and hasattr(reference, "storage_units") and len(reference.storage_units):
            ref = reference.storage_units
            ref_p = ref["p_nom_opt"] if "p_nom_opt" in ref.columns else ref["p_nom"]
            aligned = ref_p.reindex(n.storage_units.index)
            n.storage_units.loc[aligned.dropna().index, "p_nom"] = aligned.dropna()
        n.storage_units["p_nom_extendable"] = False
        if "p_nom_opt" in n.storage_units.columns:
            n.storage_units["p_nom_opt"] = n.storage_units["p_nom"]
        if "e_nom_extendable" in n.storage_units.columns:
            n.storage_units["e_nom_extendable"] = False
        if "e_nom_opt" in n.storage_units.columns and "e_nom" in n.storage_units.columns:
            n.storage_units["e_nom_opt"] = n.storage_units["e_nom"]

    # Links (includes battery charger/discharger style assets)
    if hasattr(n, "links") and len(n.links):
        if reference is not None and hasattr(reference, "links") and len(reference.links):
            ref = reference.links
            ref_p = ref["p_nom_opt"] if "p_nom_opt" in ref.columns else ref["p_nom"]
            aligned = ref_p.reindex(n.links.index)
            n.links.loc[aligned.dropna().index, "p_nom"] = aligned.dropna()
        n.links["p_nom_extendable"] = False
        if "p_nom_opt" in n.links.columns:
            n.links["p_nom_opt"] = n.links["p_nom"]

    # Lines
    if hasattr(n, "lines") and len(n.lines):
        if reference is not None and hasattr(reference, "lines") and len(reference.lines):
            ref = reference.lines
            ref_s = ref["s_nom_opt"] if "s_nom_opt" in ref.columns else ref["s_nom"]
            aligned = ref_s.reindex(n.lines.index)
            n.lines.loc[aligned.dropna().index, "s_nom"] = aligned.dropna()
        if "s_nom_extendable" in n.lines.columns:
            n.lines["s_nom_extendable"] = False
        if "s_nom_opt" in n.lines.columns:
            n.lines["s_nom_opt"] = n.lines["s_nom"]


def resolve_fixedcap(
    input_nc: Path,
    output_nc: Path,
    solver: str = "highs",
    reference_nc: Path | None = None,
    fix_generator_carriers: set[str] | None = None,
    fix_all_components: bool = False,
) -> None:
    n = pypsa.Network(str(input_nc))

    reference = pypsa.Network(str(reference_nc)) if reference_nc else None
    _fix_component_capacity(
        n,
        reference=reference,
        fix_generator_carriers=fix_generator_carriers,
        fix_all_components=fix_all_components,
    )

    # Re-solve with fixed capacities
    n.optimize(solver_name=solver)

    output_nc.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(output_nc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-solve network with fixed capacities")
    parser.add_argument("--input", required=True, help="Path to solved network .nc")
    parser.add_argument("--output", required=True, help="Output path for fixed-capacity .nc")
    parser.add_argument(
        "--reference",
        default=None,
        help="Optional reference .nc whose p_nom_opt/s_nom_opt are used as fixed capacities",
    )
    parser.add_argument(
        "--fix-generator-carriers",
        nargs="*",
        default=["solar", "solar-hsat"],
        help="Generator carriers to fix (default: solar, solar-hsat).",
    )
    parser.add_argument(
        "--fix-all-components",
        action="store_true",
        help="Also fix StorageUnits/Links/Lines to reference capacities (default: off).",
    )
    parser.add_argument("--solver", default="highs", help="Solver name (default: highs)")
    args = parser.parse_args()

    resolve_fixedcap(
        Path(args.input),
        Path(args.output),
        solver=args.solver,
        reference_nc=Path(args.reference) if args.reference else None,
        fix_generator_carriers=set(args.fix_generator_carriers) if args.fix_generator_carriers else None,
        fix_all_components=bool(args.fix_all_components),
    )


if __name__ == "__main__":
    main()

