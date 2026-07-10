# SPDX-FileCopyrightText: INRE Project
#
# SPDX-License-Identifier: MIT
"""
Export cluster × carrier capacity-factor profiles from a prepared PyPSA network.

Output CSV format: profiles/historical/{bus}_{carrier}.csv with columns timestamp, cf
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

CARRIERS = [
    "onwind",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
    "solar",
    "solar-hsat",
]


def export_profiles(n: pypsa.Network, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots = pd.DatetimeIndex(n.snapshots)
    written: list[Path] = []

    for carrier in CARRIERS:
        gens = n.generators.query("carrier == @carrier")
        if gens.empty:
            continue
        for bus in gens.bus.unique():
            cols = gens.query("bus == @bus").index
            cols = [c for c in cols if c in n.generators_t.p_max_pu.columns]
            if not cols:
                continue
            mean_cf = n.generators_t.p_max_pu[cols].mean(axis=1)
            out = pd.DataFrame({"timestamp": snapshots, "cf": mean_cf.values})
            path = output_dir / f"{bus}_{carrier}.csv"
            out.to_csv(path, index=False)
            written.append(path)
    logger.info("Wrote %d profile files to %s", len(written), output_dir)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Export cluster CF profiles from PyPSA network")
    parser.add_argument("--network", required=True)
    parser.add_argument(
        "--output-dir",
        default="data/inre/profiles/historical",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    n = pypsa.Network(args.network)
    export_profiles(n, Path(args.output_dir))


if __name__ == "__main__":
    main()
