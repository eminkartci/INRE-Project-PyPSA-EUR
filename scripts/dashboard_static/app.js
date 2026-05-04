/**
 * PyPSA-Eur dashboard: loads payload from embedded script or data.json,
 * renders Plotly charts, date filter, Sankey, Scattergeo map.
 */

const PLOTLY_CONFIG = {
  responsive: true,
  displayModeBar: true,
  displaylogo: false,
};

/** Light plot theme for legible text on pale backgrounds */
const PLOT_FONT = {
  family: "system-ui, Segoe UI, sans-serif",
  color: "#0f172a",
  size: 13,
};

function parsePayload() {
  const el = document.getElementById("dashboard-payload");
  if (el && el.textContent.trim()) {
    return JSON.parse(el.textContent);
  }
  return null;
}

async function loadData() {
  const embedded = parsePayload();
  if (embedded) return embedded;
  const res = await fetch("data.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`data.json HTTP ${res.status}`);
  return res.json();
}

function toDate(s) {
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatLocalInput(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

function sliceDispatch(data, t0, t1) {
  const idx = data.dispatch.index;
  const cols = data.dispatch.columns;
  const rows = data.dispatch.data;
  const outIdx = [];
  const outRows = [];
  for (let i = 0; i < idx.length; i++) {
    const t = toDate(idx[i]);
    if (!t) continue;
    if (t >= t0 && t <= t1) {
      outIdx.push(idx[i]);
      outRows.push(rows[i]);
    }
  }
  return { index: outIdx, columns: cols, data: outRows };
}

/** Hourly MW → GWh: sum(MW) / 1000 (1 h timestep). */
function carrierEnergyGWhFromSlice(slice) {
  const out = {};
  slice.columns.forEach((c, j) => {
    let s = 0;
    for (let i = 0; i < slice.data.length; i++) {
      const v = slice.data[i][j];
      if (v != null && !Number.isNaN(v)) s += v;
    }
    out[c] = s / 1000;
  });
  return out;
}

function loadEnergyGWhFromSlice(data, slice) {
  if (!data.load_mw || !slice.index.length) return null;
  const t0 = toDate(slice.index[0]);
  const t1 = toDate(slice.index[slice.index.length - 1]);
  let s = 0;
  for (let i = 0; i < data.dispatch.index.length; i++) {
    const t = toDate(data.dispatch.index[i]);
    if (!t || !t0 || !t1) continue;
    if (t >= t0 && t <= t1) s += data.load_mw[i] || 0;
  }
  return s / 1000;
}

function buildSankeyFromSlice(data, slice) {
  const colorsMap = data.carrier_colors || {};
  const genGWh = carrierEnergyGWhFromSlice(slice);
  const loadGWh = loadEnergyGWhFromSlice(data, slice);

  const carriers = Object.keys(genGWh).filter((c) => genGWh[c] > 1e-12);
  if (!carriers.length) {
    return {
      labels: ["No data"],
      colors: ["#94a3b8"],
      sources: [],
      targets: [],
      values: [],
      loadGWh: null,
    };
  }
  const loadIdx = carriers.length;
  const labels = carriers.map(String).concat(["Load"]);
  const colors = carriers
    .map((c) => colorsMap[c] || "#64748b")
    .concat(["#dc2626"]);
  const sources = [];
  const targets = [];
  const values = [];
  carriers.forEach((c, i) => {
    sources.push(i);
    targets.push(loadIdx);
    values.push(genGWh[c]);
  });
  return { labels, colors, sources, targets, values, loadGWh };
}

function renderKpi(root, data) {
  const k = data.kpi;
  const cards = [
    ["Objective (1e9)", k.objective_1e9 != null ? k.objective_1e9.toFixed(4) : "—"],
    ["Snapshots", String(k.n_snapshots)],
    ["Bus", String(k.n_buses)],
    ["Generators", String(k.n_generators)],
    ["Lines", String(k.n_lines)],
    ["Links", String(k.n_links)],
  ];
  root.innerHTML = cards
    .map(
      ([label, val]) =>
        `<div class="kpi-card"><div class="label">${label}</div><div class="value">${val}</div></div>`
    )
    .join("");
}

/** Vertical column chart (Plotly `bar` with default orientation). */
function columnChartLayout(title, yAxisTitle) {
  return {
    template: "plotly_white",
    title: { text: title, font: { ...PLOT_FONT, size: 15 } },
    margin: { l: 56, r: 24, t: 52, b: 140 },
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#f8fafc",
    font: PLOT_FONT,
    xaxis: {
      title: { text: "Carrier", font: PLOT_FONT },
      tickangle: -40,
      automargin: true,
      tickfont: { color: "#334155", size: 12 },
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
    },
    yaxis: {
      title: { text: yAxisTitle, font: PLOT_FONT },
      automargin: true,
      tickfont: { color: "#334155", size: 12 },
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
    },
  };
}

function renderCapacitySupply(data) {
  const c = data.capacities_gw || {};
  const s = data.supply_twh || {};
  const colorsC = data.carrier_colors || {};
  const labelsC = Object.keys(c).sort((a, b) => c[b] - c[a]);
  const valsC = labelsC.map((k) => c[k]);
  const colC = labelsC.map((k) => colorsC[k] || "#64748b");
  const traceC = {
    type: "bar",
    x: labelsC,
    y: valsC,
    marker: { color: colC },
  };
  Plotly.newPlot(
    "chart-capacity",
    [traceC],
    columnChartLayout("Optimal capacity (GW)", "GW"),
    PLOTLY_CONFIG
  );

  const labelsS = Object.keys(s).sort((a, b) => s[b] - s[a]);
  const valsS = labelsS.map((k) => s[k]);
  const colS = labelsS.map((k) => colorsC[k] || "#64748b");
  const traceS = {
    type: "bar",
    x: labelsS,
    y: valsS,
    marker: { color: colS },
  };
  Plotly.newPlot(
    "chart-supply",
    [traceS],
    columnChartLayout("Energy supply (TWh)", "TWh"),
    PLOTLY_CONFIG
  );
}

function renderDispatch(divId, slice, colorsMap) {
  const traces = [];
  slice.columns.forEach((col, j) => {
    const y = slice.data.map((row) => (row[j] != null ? row[j] / 1000 : 0));
    traces.push({
      type: "scatter",
      mode: "lines",
      name: col,
      x: slice.index,
      y,
      stackgroup: "one",
      line: { width: 0.6, color: colorsMap[col] || "#64748b" },
    });
  });
  const layout = {
    template: "plotly_white",
    title: {
      text: "Hourly dispatch (GW) — selected window",
      font: { ...PLOT_FONT, size: 15 },
    },
    yaxis: {
      title: { text: "GW", font: PLOT_FONT },
      tickfont: { color: "#334155", size: 12 },
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
    },
    xaxis: {
      tickfont: { color: "#334155", size: 11 },
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
    },
    margin: { l: 56, r: 24, t: 52, b: 56 },
    legend: {
      orientation: "h",
      y: 1.12,
      font: { color: "#0f172a", size: 12 },
      bgcolor: "rgba(255,255,255,0.92)",
      bordercolor: "#e2e8f0",
      borderwidth: 1,
    },
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#f8fafc",
    font: PLOT_FONT,
  };
  Plotly.newPlot(divId, traces, layout, PLOTLY_CONFIG);
}

function renderSankey(divId, sk) {
  const el = document.getElementById(divId);
  el.innerHTML = "";
  if (!sk.values.length) {
    el.innerHTML = '<p class="hint">Not enough data for a Sankey diagram.</p>';
    return;
  }
  const data = [
    {
      type: "sankey",
      orientation: "h",
      node: {
        pad: 12,
        thickness: 14,
        line: { color: "#888", width: 0.4 },
        label: sk.labels,
        color: sk.colors,
      },
      link: {
        source: sk.sources,
        target: sk.targets,
        value: sk.values,
      },
    },
  ];
  const loadNote =
    sk.loadGWh != null ? ` — metered load ≈ ${sk.loadGWh.toFixed(2)} GWh` : "";
  const layout = {
    template: "plotly_white",
    title: {
      text: `Carrier to load (GWh)${loadNote}`,
      font: { ...PLOT_FONT, size: 15 },
    },
    margin: { l: 24, r: 24, t: 52, b: 24 },
    font: PLOT_FONT,
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#f8fafc",
  };
  Plotly.newPlot(el, data, layout, PLOTLY_CONFIG);
}

function renderMap(divId, mapData) {
  const section = document.getElementById("map-section");
  const hint = document.getElementById("map-hint");
  if (!mapData || !mapData.buses || !mapData.buses.length) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");
  hint.textContent =
    "Bus locations from coordinates (x/y). Europe projection; lines capped by highest s_nom.";

  const busLon = mapData.buses.map((b) => b.lon);
  const busLat = mapData.buses.map((b) => b.lat);
  const busText = mapData.buses.map((b) => `${b.name || b.id}<br>${b.carrier || ""}`);

  const traces = [
    {
      type: "scattergeo",
      mode: "markers",
      lon: busLon,
      lat: busLat,
      text: busText,
      marker: { size: 8, color: "#2563eb" },
      name: "Bus",
    },
  ];

  if (mapData.lines && mapData.lines.length) {
    const lons = [];
    const lats = [];
    mapData.lines.forEach((seg) => {
      if (seg.length === 2) {
        lons.push(seg[0].lon, seg[1].lon, null);
        lats.push(seg[0].lat, seg[1].lat, null);
      }
    });
    traces.push({
      type: "scattergeo",
      mode: "lines",
      lon: lons,
      lat: lats,
      line: { width: 1, color: "#64748b" },
      opacity: 0.7,
      name: "Lines",
    });
  }

  const layout = {
    template: "plotly_white",
    title: { text: "Network geography", font: { ...PLOT_FONT, size: 15 } },
    geo: {
      scope: "europe",
      projection: { type: "natural earth" },
      showland: true,
      landcolor: "#eef2f7",
      countrycolor: "#94a3b8",
      coastlinecolor: "#64748b",
      bgcolor: "#f8fafc",
      showocean: true,
      oceancolor: "#e8f0fa",
    },
    margin: { l: 0, r: 0, t: 52, b: 0 },
    paper_bgcolor: "#ffffff",
    font: PLOT_FONT,
    height: 480,
  };
  Plotly.newPlot(divId, traces, layout, PLOTLY_CONFIG);
}

function main(data) {
  const meta = data.meta || {};
  document.getElementById("meta-network").textContent = meta.network_path || "";
  document.getElementById("meta-generated").textContent = meta.generated_at
    ? `Generated: ${meta.generated_at}`
    : "";

  renderKpi(document.getElementById("kpi-root"), data);

  const colorsMap = data.carrier_colors || {};
  renderCapacitySupply(data);

  const idx0 = data.dispatch.index[0];
  const idx1 = data.dispatch.index[data.dispatch.index.length - 1];
  const d0 = toDate(idx0);
  const d1 = toDate(idx1);
  const inpS = document.getElementById("filter-start");
  const inpE = document.getElementById("filter-end");
  if (d0 && d1) {
    inpS.value = formatLocalInput(d0);
    inpE.value = formatLocalInput(d1);
  }

  function applyFilter() {
    const t0 = toDate(inpS.value);
    const t1 = toDate(inpE.value);
    if (!t0 || !t1 || t0 > t1) {
      document.getElementById("filter-status").textContent =
        "Invalid range: start must be before end.";
      return;
    }
    const slice = sliceDispatch(data, t0, t1);
    if (!slice.index.length) {
      document.getElementById("filter-status").textContent =
        "No data in the selected window.";
      return;
    }
    document.getElementById(
      "filter-status"
    ).textContent = `${slice.index.length} snapshots selected.`;
    renderDispatch("chart-dispatch", slice, colorsMap);
    const sk = buildSankeyFromSlice(data, slice);
    renderSankey("chart-sankey", sk);
  }

  function resetFilter() {
    if (d0 && d1) {
      inpS.value = formatLocalInput(d0);
      inpE.value = formatLocalInput(d1);
    }
    const slice = {
      index: data.dispatch.index,
      columns: data.dispatch.columns,
      data: data.dispatch.data,
    };
    document.getElementById("filter-status").textContent = "Full time horizon.";
    renderDispatch("chart-dispatch", slice, colorsMap);
    const sk = buildSankeyFromSlice(data, slice);
    renderSankey("chart-sankey", sk);
  }

  document.getElementById("btn-apply").addEventListener("click", applyFilter);
  document.getElementById("btn-reset").addEventListener("click", resetFilter);

  resetFilter();
  renderMap("chart-map", data.map);
}

window.addEventListener("DOMContentLoaded", async () => {
  const notice = document.getElementById("fetch-notice");
  try {
    const data = await loadData();
    notice.classList.add("hidden");
    main(data);
  } catch (e) {
    console.error(e);
    notice.innerHTML = `<strong>Could not load data:</strong> ${e.message}<br/>
      Run <code>python -m http.server 8765</code> in this folder and open
      <code>http://localhost:8765</code>, or re-run the export script with <code>--inline-data</code>.`;
    notice.style.borderColor = "#dc2626";
  }
});
