# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""
Build an interactive HTML dashboard bundle (HTML + CSS + JS + JSON) plus XLSX
from a solved PyPSA-Eur electricity network (.nc).

Usage (from repository root, ``pypsa-eur`` conda env active)::

    python scripts/export_results_dashboard.py \\
        --network results/germany-elec/networks/base_s_10_elec_.nc \\
        --output-dir results/germany-elec/dashboard

Preview (recommended: avoids ``file://`` blocking JSON fetches)::

    cd results/germany-elec
    python -m http.server 8765
    # Plotly bundle: http://localhost:8765/dashboard/
    # Chart.js explorer (live): http://localhost:8765/dashboard.html

Optional: embed payload in ``index.html`` (smaller runs only; large time series
inflate the file)::

    python scripts/export_results_dashboard.py --network PATH.nc --output-dir OUT --inline-data
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _static_dir() -> Path:
    return _script_dir() / "dashboard_static"


def _snap_len(n: pypsa.Network) -> int:
    try:
        return len(n.snapshots)
    except Exception:
        return 0


def _series_to_carrier_df(s: pd.Series) -> pd.DataFrame:
    if s.empty:
        return pd.DataFrame(columns=["value"])
    idx = s.index
    if isinstance(idx, pd.MultiIndex) and idx.nlevels >= 2:
        carriers = idx.get_level_values(-1)
    else:
        carriers = idx.astype(str)
    out = pd.DataFrame({"value": s.values}, index=carriers.astype(str))
    return out.groupby(level=0).sum()


def _carrier_colors(n: pypsa.Network) -> dict[str, str]:
    if n.carriers is None or n.carriers.empty:
        return {}
    out: dict[str, str] = {}
    for i in n.carriers.index:
        nice = n.carriers.loc[i, "nice_name"]
        if pd.isna(nice) or str(nice).strip() == "":
            nice = str(i)
        col = n.carriers.loc[i, "color"]
        if pd.isna(col) or str(col).strip() == "":
            col = "#94a3b8"
        else:
            col = str(col)
        out[str(i)] = col
        out[str(nice)] = col
    return out


def _dispatch_by_carrier_mw(n: pypsa.Network) -> tuple[pd.DatetimeIndex, list[str], np.ndarray]:
    if not hasattr(n, "generators_t") or "p" not in n.generators_t:
        return pd.DatetimeIndex([]), [], np.array([])
    p = n.generators_t.p.fillna(0.0)
    if p.empty:
        return pd.DatetimeIndex([]), [], np.array([])
    carriers = n.generators.carrier.reindex(p.columns).fillna("unknown")
    cols = [str(c) for c in carriers.unique()]
    parts = []
    for c in carriers.unique():
        mask = carriers == c
        parts.append(p.loc[:, mask].sum(axis=1))
    mat = pd.concat(parts, axis=1)
    mat.columns = cols
    idx = pd.DatetimeIndex(pd.to_datetime(mat.index, utc=True))
    return idx, cols, mat.to_numpy(dtype=float)


def _load_mw_series(n: pypsa.Network) -> list[float] | None:
    if not hasattr(n, "loads_t") or "p_set" not in n.loads_t:
        return None
    s = n.loads_t.p_set.sum(axis=1)
    if s.empty:
        return None
    return [float(x) if pd.notna(x) else 0.0 for x in s.tolist()]


def _map_payload(n: pypsa.Network, max_lines: int = 800) -> dict | None:
    buses = n.buses
    if buses is None or buses.empty or "x" not in buses.columns or "y" not in buses.columns:
        return None
    bus_list = []
    for bid, row in buses.iterrows():
        try:
            lon = float(row["x"])
            lat = float(row["y"])
        except (TypeError, ValueError):
            continue
        if np.isnan(lon) or np.isnan(lat):
            continue
        bus_list.append(
            {
                "id": str(bid),
                "name": str(row.get("location", bid)),
                "lon": lon,
                "lat": lat,
                "carrier": str(row.get("carrier", "")),
            }
        )
    if not bus_list:
        return None

    pos = {b["id"]: (b["lon"], b["lat"]) for b in bus_list}
    lines_out: list[list[dict[str, float]]] = []
    if n.lines is not None and not n.lines.empty and "s_nom" in n.lines.columns:
        sub = n.lines.sort_values("s_nom", ascending=False).head(max_lines)
    elif n.lines is not None and not n.lines.empty:
        sub = n.lines.head(max_lines)
    else:
        sub = None

    if sub is not None:
        for _, row in sub.iterrows():
            b0 = str(row.get("bus0", ""))
            b1 = str(row.get("bus1", ""))
            if b0 not in pos or b1 not in pos:
                continue
            lines_out.append(
                [
                    {"lon": pos[b0][0], "lat": pos[b0][1]},
                    {"lon": pos[b1][0], "lat": pos[b1][1]},
                ]
            )

    return {"buses": bus_list, "lines": lines_out}


_RENEWABLE_SUBSTR = (
    "solar",
    "wind",
    "hydro",
    "ror",
    "biomass",
    "geothermal",
    "marine",
    "wave",
    "tidal",
)


def _carrier_is_renewable(name: str) -> bool:
    u = str(name).lower()
    return any(tok in u for tok in _RENEWABLE_SUBSTR)


def _lines_twkm(n: pypsa.Network) -> float | None:
    if n.lines is None or n.lines.empty:
        return None
    if "length" not in n.lines.columns or "s_nom" not in n.lines.columns:
        return None
    try:
        prod = (n.lines["length"].astype(float) * n.lines["s_nom"].astype(float)).sum()
        return float(prod) / 1e6
    except (TypeError, ValueError):
        return None


def _explorer_buses_peak_mw(n: pypsa.Network) -> list[dict]:
    if n.loads is None or n.loads.empty:
        return []
    if not hasattr(n, "loads_t") or "p_set" not in n.loads_t:
        return []
    p_set = n.loads_t.p_set
    if p_set is None or p_set.empty:
        return []
    peaks: dict[str, float] = {}
    for load_name in p_set.columns:
        ln = str(load_name)
        if ln not in n.loads.index:
            continue
        bus = str(n.loads.loc[ln, "bus"])
        ser = pd.to_numeric(p_set[load_name], errors="coerce")
        mx = float(ser.max()) if len(ser) else 0.0
        if pd.isna(mx):
            mx = 0.0
        peaks[bus] = peaks.get(bus, 0.0) + mx
    locs: dict[str, str] = {}
    if n.buses is not None and not n.buses.empty and "location" in n.buses.columns:
        for bid, row in n.buses.iterrows():
            v = row.get("location", bid)
            locs[str(bid)] = str(v) if pd.notna(v) else str(bid)
    out: list[dict] = []
    for bid, load_mw in sorted(peaks.items(), key=lambda x: -x[1]):
        reg = locs.get(bid, bid)
        out.append({"id": bid, "load_mw": round(load_mw, 4), "region": str(reg)})
    return out


def build_explorer_payload(n: pypsa.Network, safe: dict) -> dict:
    """Shape compatible with scripts/dashboard_static/explorer.html (Chart.js viewer)."""
    sup = safe.get("supply_twh") or {}
    total = sum(float(v) for v in sup.values())
    ren = sum(float(v) for k, v in sup.items() if _carrier_is_renewable(k))
    ren_pct = 100.0 * ren / total if total > 0 else None

    kpi = safe.get("kpi") or {}
    obj = kpi.get("objective_1e9")
    load_mw = safe.get("load_mw") or []
    peak_gw = None
    if load_mw:
        peak_gw = max(float(x) for x in load_mw) / 1e3

    other_twh = max(0.0, total - ren)

    kpis = {
        "total_cost_bn_eur": obj,
        "co2_mt": None,
        "renewable_share_pct": ren_pct,
        "peak_load_gw": peak_gw,
        "lines_total_twkm": _lines_twkm(n),
    }

    scatter: list[dict] = []
    if ren_pct is not None and obj is not None:
        scatter.append(
            {"ren": round(float(ren_pct), 2), "cost": round(float(obj), 4)}
        )

    gen: dict[str, float] = {}
    for k, v in sorted(sup.items(), key=lambda kv: -kv[1]):
        fv = float(v)
        if fv <= 1e-12:
            continue
        rnd = round(fv, 6)
        if rnd <= 0:
            continue
        gen[str(k)] = rnd

    split: dict[str, float] = {}
    if total > 0:
        split["Renewables"] = round(ren, 4)
        split["Other"] = round(other_twh, 4)

    return {
        "live": True,
        "kpis": kpis,
        "generation_twh": gen,
        "emissions_kg_per_mwh": [],
        "emissions_split_mt": split,
        "buses": _explorer_buses_peak_mw(n),
        "scatter": scatter,
    }


def _json_safe(obj):
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def build_payload(
    n: pypsa.Network,
    network_path: Path,
    max_snapshots: int | None = None,
) -> dict:
    obj = getattr(n, "objective", None)
    obj_1e9 = float(obj) / 1e9 if obj is not None and pd.notna(obj) else None

    cap = n.statistics.optimal_capacity().dropna()
    cap = cap.drop("Line", errors="ignore")
    cap_df = _series_to_carrier_df(cap) / 1e3

    sup = n.statistics.supply().dropna()
    sup = sup.drop("Line", errors="ignore")
    sup_df = _series_to_carrier_df(sup) / 1e6

    idx, cols, data = _dispatch_by_carrier_mw(n)
    load_mw = _load_mw_series(n)
    if max_snapshots is not None and len(idx) > max_snapshots:
        idx = idx[:max_snapshots]
        data = data[:max_snapshots, :]
        if load_mw is not None:
            load_mw = load_mw[:max_snapshots]

    idx_iso = [t.isoformat() for t in idx]

    colors = _carrier_colors(n)

    return {
        "meta": {
            "network_path": str(network_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "kpi": {
            "objective_1e9": obj_1e9,
            "n_snapshots": len(idx_iso) if idx_iso else _snap_len(n),
            "n_buses": int(n.buses.shape[0]),
            "n_generators": int(n.generators.shape[0]),
            "n_lines": int(n.lines.shape[0]),
            "n_links": int(n.links.shape[0]),
        },
        "carrier_colors": colors,
        "capacities_gw": {str(k): float(v) for k, v in cap_df["value"].items() if v > 0},
        "supply_twh": {str(k): float(v) for k, v in sup_df["value"].items() if v > 0},
        "dispatch": {
            "index": idx_iso,
            "columns": cols,
            "data": data.tolist() if data.size else [],
        },
        "load_mw": load_mw,
        "map": _map_payload(n),
    }


def write_xlsx(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(
        [
            {"metric": "objective_1e9", "value": payload["kpi"].get("objective_1e9")},
            {"metric": "n_snapshots", "value": payload["kpi"].get("n_snapshots")},
            {"metric": "n_buses", "value": payload["kpi"].get("n_buses")},
            {"metric": "n_generators", "value": payload["kpi"].get("n_generators")},
            {"metric": "n_lines", "value": payload["kpi"].get("n_lines")},
            {"metric": "n_links", "value": payload["kpi"].get("n_links")},
        ]
    )
    cap = pd.Series(payload["capacities_gw"], name="GW").sort_values(ascending=False)
    sup = pd.Series(payload["supply_twh"], name="TWh").sort_values(ascending=False)
    d = payload["dispatch"]
    ts = pd.DataFrame(d["data"], columns=d["columns"], index=d["index"])

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        cap.to_frame().to_excel(writer, sheet_name="Capacities_GW")
        sup.to_frame().to_excel(writer, sheet_name="Supply_TWh")
        ts.to_excel(writer, sheet_name="Dispatch_MW")
        if payload.get("map") and payload["map"].get("buses"):
            pd.DataFrame(payload["map"]["buses"]).to_excel(
                writer, sheet_name="Buses_geo", index=False
            )


def copy_static_bundle(output_dir: Path) -> None:
    src = _static_dir()
    if not src.is_dir():
        raise FileNotFoundError(f"Missing dashboard static dir: {src}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js"):
        shutil.copy2(src / name, output_dir / name)


def stamp_dashboard_asset_urls(output_dir: Path) -> None:
    """Append a version query to CSS/JS so browsers reload after each export."""
    idx = output_dir / "index.html"
    if not idx.is_file():
        return
    v = int(time.time())
    text = idx.read_text(encoding="utf-8")
    text = text.replace('href="styles.css"', f'href="styles.css?v={v}"')
    text = text.replace('src="app.js"', f'src="app.js?v={v}"')
    idx.write_text(text, encoding="utf-8")


def inject_inline_payload(html: str, payload: dict) -> str:
    blob = json.dumps(_json_safe(payload), ensure_ascii=False)
    script = (
        f'<script type="application/json" id="dashboard-payload">{blob}</script>'
    )
    if "</head>" in html:
        return html.replace("</head>", f"{script}\n</head>", 1)
    return script + "\n" + html


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        type=Path,
        default=Path("results/germany-elec/networks/base_s_10_elec_.nc"),
        help="Path to solved network NetCDF",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/germany-elec/dashboard"),
        help="Write index.html, assets, data.json, summary.xlsx here",
    )
    parser.add_argument(
        "--inline-data",
        action="store_true",
        help="Embed data.json into index.html (large files; prefer http.server without this)",
    )
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=None,
        help="Trim time series to first N snapshots (optional)",
    )
    args = parser.parse_args()

    if not args.network.is_file():
        raise SystemExit(f"Network file not found: {args.network.resolve()}")

    n = pypsa.Network(args.network)
    payload = build_payload(n, args.network.resolve(), max_snapshots=args.max_snapshots)
    safe = _json_safe(payload)

    out = args.output_dir.resolve()
    copy_static_bundle(out)
    stamp_dashboard_asset_urls(out)

    data_json = out / "data.json"
    data_json.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")

    explorer = build_explorer_payload(n, safe)
    (out / "explorer.json").write_text(
        json.dumps(_json_safe(explorer), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    explorer_html = _static_dir() / "explorer.html"
    if explorer_html.is_file():
        shutil.copy2(explorer_html, out.parent / "dashboard.html")

    write_xlsx(safe, out / "summary.xlsx")

    if args.inline_data:
        index_path = out / "index.html"
        html = index_path.read_text(encoding="utf-8")
        index_path.write_text(inject_inline_payload(html, safe), encoding="utf-8")

    print(f"Wrote dashboard bundle under {out}")
    print("Preview Plotly: cd {0} && python -m http.server 8765".format(out))
    print(
        "Preview explorer: cd {0} && python -m http.server 8765".format(out.parent)
        + "  → http://localhost:8765/dashboard.html"
    )
    print("Tip: hard-refresh the browser (Ctrl+Shift+R) if an older UI is cached.")


if __name__ == "__main__":
    main()
