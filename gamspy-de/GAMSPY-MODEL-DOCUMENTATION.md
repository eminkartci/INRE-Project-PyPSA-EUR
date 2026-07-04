# INRE Germany — GAMSPy Model Documentation

**Document type:** Model description for reports and reproducibility  
**Model location:** `gamspy-de/` (standalone sub-project)  
**Geographic scope:** Germany (`DE`), electricity-only  
**Planning horizon:** 2050 technology costs; 2024-style renewable fleet (template inputs)  
**Simulation window:** 25 January – 7 February 2021 (112 snapshots, 3-hour resolution)

---

## 1. Purpose and motivation

The **INRE** (Integrated Nuclear & Renewable Energy) study examines whether advanced nuclear technologies (SMR, MSR, LFR) can improve electricity system adequacy during **Dunkelflaute** events — extended periods of simultaneously low wind and solar output in Central European winters.

The main PyPSA-Eur workflow in the parent repository is a full Snakemake pipeline with NetCDF networks. The **`gamspy-de`** sub-project provides a **parallel, transparent optimisation model** that:

1. Uses **human-editable CSV/YAML inputs** instead of opaque binary network files.
2. Implements the same high-level logic (dispatch, expansion, Dunkelflaute stress, optional nuclear build) in **GAMSPy/GAMS**.
3. Allows independent verification, teaching, and extension of the INRE scenario design without running the full PyPSA build chain.

**What we are trying to answer with this model:**

- Can the system meet demand when VRE availability is severely derated?
- How much additional flexible capacity (gas, storage) is dispatched under stress?
- Does new nuclear capacity at former NPP sites become economically attractive under Dunkelflaute conditions?
- How do costs and CO₂ emissions change between `base` and stress scenarios?

> **Important:** The bundled template inputs are **representative placeholders** (~Germany scale). For publication-grade results, replace them with ENTSO-E demand, Atlite weather profiles, and PyPSA-exported capacities. The **PyPSA-INRE solved networks** in `results/` remain the primary calibrated reference; `gamspy-de` is a complementary, fully controllable formulation.

---

## 2. Software stack

| Component | Role |
|-----------|------|
| [GAMSPy](https://gamspy.readthedocs.io/) | Python API for building and solving GAMS models |
| [GAMS](https://www.gams.com/) | Optimisation engine (license required) |
| [HiGHS](https://highs.dev/) | Default LP solver (`gamspy install solver highs`) |
| pandas / PyYAML | Input loading and scenario configuration |

---

## 3. Model scope

### 3.1 In scope

- 10-node transmission network (transport model)
- Dispatch and capacity expansion for wind, offshore wind, solar, OCGT, CCGT
- Battery storage (power + energy) at each node
- Optional site-level nuclear investment (SMR / MSR / LFR)
- Dunkelflaute VRE derating via time-varying availability profiles
- Global CO₂ emission cap (scaled to simulation window)
- Ramp limits on thermal generators and nuclear

### 3.2 Out of scope (simplifications vs PyPSA-INRE)

| Feature | PyPSA-INRE | GAMSPy model |
|---------|------------|--------------|
| Cross-border trade | Disabled (DE only) | Disabled (DE only) |
| Transmission physics | Linearised DC OPF | Transport limits (\|f\| ≤ s_nom) |
| H₂ storage chain | Included | **Not included** |
| VRE carrier detail | 6 types (onwind, offwind-ac/dc/float, solar, solar-hsat) | 3 aggregated types (onwind, offwind, solar) |
| Unit commitment | No (LP only) | No (LP only) |
| Existing nuclear | Shut down | Not modelled (new-build only) |
| Sector coupling | No | No |

---

## 4. Spatial and temporal setup

### 4.1 Network nodes

Ten buses (`DE0` … `DE9`) represent clustered German zones. Coordinates in `inputs/buses.csv` are used to map nuclear candidate sites to the nearest node.

| Bus | Latitude | Longitude | Role (template) |
|-----|----------|-----------|-----------------|
| DE0 | 54.0 | 10.0 | North / coastal |
| DE1 | 53.0 | 9.0 | North-west |
| DE2 | 52.0 | 8.0 | North (Grohnde, Emsland nuclear sites) |
| DE3 | 53.0 | 13.0 | North-east |
| DE4 | 51.0 | 7.0 | West (Brokdorf nuclear site) |
| DE5 | 51.0 | 10.0 | Central |
| DE6 | 51.0 | 13.0 | East |
| DE7 | 49.0 | 8.0 | South-west (Neckarwestheim) |
| DE8 | 48.0 | 11.0 | South (Isar nuclear site) |
| DE9 | 50.0 | 12.0 | South-east |

### 4.2 Transmission

- **22 AC lines** (`inputs/lines.csv`)
- **Total thermal limit:** 60.8 GW (sum of `s_nom_MW`)
- Flow model: transport (absolute flow bounded by line capacity; no voltage angles)

### 4.3 Time dimension

| Parameter | Value |
|-----------|-------|
| Start | 2021-01-25 00:00 |
| End | 2021-02-07 21:00 (112 snapshots) |
| Resolution | 3 hours |
| Period length | 336 hours (14 days) |
| Snapshot weight | 3 h per step (`inputs/snapshots.csv`) |

---

## 5. Input data catalogue

All inputs live under `gamspy-de/inputs/` and are loaded by `src/load_inputs.py`.

### 5.1 Summary table

| File | Description | Primary references |
|------|-------------|-------------------|
| `buses.csv` | Node IDs and coordinates | Template (align with PyPSA 10-cluster busmap when calibrating) |
| `lines.csv` | Line endpoints and capacities | Template (~22 lines, INRE methodology) |
| `demand.csv` | Nodal load time series (MW) | Template (~62 GW average); replace with **ENTSO-E** |
| `capacity_existing.csv` | Installed capacity per bus × technology | Template (~146 GW total); replace with **powerplantmatching 2024** |
| `availability.csv` | VRE availability `p_max_pu` | Template synthetic profiles; replace with **Atlite / ERA5+SARAH-3** |
| `technologies.csv` | Costs and operational parameters | PyPSA technology-data 2050 + INRE nuclear overrides |
| `storage.csv` | Battery parameters per node | PyPSA-style defaults |
| `nuclear_sites.csv` | Candidate reactor locations | INRE former NPP sites ([`data/inre/custom_powerplants_nuclear_DE.csv`](../data/inre/custom_powerplants_nuclear_DE.csv)) |
| `snapshots.csv` | Timestamps and weighting hours | INRE config ([`config/inre/config.base.yaml`](../config/inre/config.base.yaml)) |

### 5.2 Scenario configuration

| File | Description |
|------|-------------|
| `scenarios/*.yaml` | Dunkelflaute on/off, nuclear technology and site filters |
| `profiles/dunkelflaute_*_factors.csv` | Wind/solar derating factors (from INRE [`data/inre/profiles/`](../data/inre/profiles/)) |
| `config/model.yaml` | CO₂ cap, solver, snapshot window |

---

## 6. Installed capacity (template inputs)

National totals from `inputs/capacity_existing.csv` (before optimisation):

| Technology | Installed capacity | Extendable | Notes |
|------------|-------------------:|:----------:|-------|
| Onshore wind | **65.0 GW** | Yes | Per-bus shares by demand weight |
| Solar PV | **55.0 GW** | Yes | |
| Offshore wind | **8.0 GW** | Yes | Higher share at northern buses (DE0–DE2) |
| CCGT | **18.0 GW** | Yes | min stable load 30% |
| OCGT | **8.0 GW** | Yes | Peaking gas |
| **Total** | **~154 GW** | | Excludes storage and nuclear |

Battery starts at **zero**; power and energy capacity are optimisation variables at each bus.

---

## 7. Electricity demand (template inputs)

Derived from `inputs/demand.csv`:

| Metric | Value |
|--------|-------|
| Simulation period | 336 hours (112 × 3 h) |
| **Total energy** | **~20.8 TWh** |
| Peak national load | ~72.8 GW |
| Minimum national load | ~51.9 GW |
| Average load | ~62.0 GW |

Demand follows a synthetic diurnal/weekly pattern scaled to Germany winter levels. For report-quality alignment with PyPSA-INRE (~21.15 TWh load), replace with ENTSO-E nodal time series.

---

## 8. Technology parameters and references

From `inputs/technologies.csv`:

### 8.1 Conventional and renewable technologies

| Tech | CAPEX (EUR/MW/yr) | Marginal cost (EUR/MWh) | CO₂ (t/MWh) | p_min | Ramp (pu/h) |
|------|------------------:|------------------------:|------------:|------:|------------:|
| onwind | 120,000 | 0.015 | 0 | 0 | 1.0 |
| offwind | 180,000 | 0.015 | 0 | 0 | 1.0 |
| solar | 80,000 | 0.01 | 0 | 0 | 1.0 |
| ocgt | 50,000 | 85 | 0.45 | 0 | 1.0 |
| ccgt | 95,000 | 52 | 0.25 | 0.3 | 0.5 |

Renewable CAPEX values are illustrative 2050 annuitised costs. Gas costs include fuel and VOM implicitly in marginal cost.

### 8.2 Advanced nuclear (INRE)

Techno-economics from [`data/inre/custom_costs_nuclear.csv`](../data/inre/custom_costs_nuclear.csv) and [`nuclear-reactor-datasheet.md`](../nuclear-reactor-datasheet.md). Annuitised at 7% discount rate over component lifetime.

| Tech | Overnight CAPEX (EUR/kW) | CAPEX annuitised (EUR/MW/yr) | Marginal cost (EUR/MWh) | Efficiency | Lifetime (yr) |
|------|-------------------------:|-----------------------------:|------------------------:|---------:|--------------:|
| SMR | 5,750 | ~410,000 | ~12.1 | 0.33 | 60 |
| MSR | 6,670 | ~483,000 | ~10.6 | 0.35 | 50 |
| LFR | 6,210 | ~445,000 | ~11.4 | 0.34 | 55 |

Sources: OECD/NEA & IEA for CAPEX and O&M; INRE assumptions for fuel and efficiency.

### 8.3 Battery storage (per node)

| Parameter | Value |
|-----------|-------|
| Round-trip efficiency | 90.25% (0.95 × 0.95) |
| Standing loss | 0.01% / hour |
| Max duration | 4 hours (energy ≤ 4 × power) |
| Power CAPEX | 35,000 EUR/MW/yr |
| Energy CAPEX | 15,000 EUR/MWh/yr |

### 8.4 Nuclear candidate sites

| Site | Bus | Max build (MW) | p_min | Availability | Ramp (pu/h) |
|------|-----|---------------:|------:|-------------:|------------:|
| Grohnde | DE2 | 1,500 | 0.30 | 0.90 | 0.50 |
| Brokdorf | DE0 | 1,500 | 0.30 | 0.90 | 0.50 |
| Isar | DE8 | 1,500 | 0.30 | 0.90 | 0.50 |
| Emsland | DE2 | 1,500 | 0.30 | 0.90 | 0.50 |
| Neckarwestheim | DE7 | 1,500 | 0.30 | 0.90 | 0.50 |

MSR scenarios use Grohnde, Brokdorf, Isar. LFR scenarios use Grohnde, Brokdorf, Emsland. SMR scenarios use all five sites.

---

## 9. Scenarios

Defined in `scenarios/` (aligned with [`config/inre/scenarios.yaml`](../config/inre/scenarios.yaml)):

| Scenario | Dunkelflaute | Nuclear | Purpose |
|----------|:------------:|---------|---------|
| `base` | Off | — | Normal winter VRE profiles |
| `dunkelflaute` | On | — | Stress without new nuclear |
| `dunkelflaute-smr` | On | SMR (5 sites) | Stress + small modular reactors |
| `dunkelflaute-msr` | On | MSR (3 sites) | Stress + molten salt reactors |
| `dunkelflaute-lfr` | On | LFR (3 sites) | Stress + lead-cooled fast reactors |

**Dunkelflaute treatment:** Wind and solar availability in `inputs/availability.csv` are multiplied by per-snapshot factors from `profiles/dunkelflaute_wind_factors.csv` and `profiles/dunkelflaute_solar_factors.csv` (Jan 2021 INRE profiles). Minimum wind factor ≈ 0.10; minimum solar factor ≈ 0.03 during the stress window.

---

## 10. Constraints and policy limits

| Constraint | Setting | Source |
|------------|---------|--------|
| CO₂ cap (annual) | 500 Mt CO₂/year | INRE `electricity.co2limit` |
| CO₂ cap (336 h window) | ~19.3 Mt | Scaled: 500×10⁶ × (336/8760) |
| Cross-border flows | None | Germany isolated |
| Line flow | \|f_ℓ,t\| ≤ s_nom_ℓ | Transport model |
| Generator dispatch | p_min × capacity ≤ p ≤ availability × capacity | |
| Capacity expansion | 0 ≤ new build ≤ extendable limit | Unlimited except nuclear site cap |
| Nuclear site cap | ≤ 1,500 MW per site | INRE config |
| Storage SOC | Dynamics with efficiency and standing loss | |
| Ramps | \|Δp\| ≤ ramp × Δt × capacity | 3 h snapshots |

---

## 11. Mathematical formulation

The model is a **linear program (LP)**: linear optimal power flow with capacity expansion.

### 11.1 Sets and indices

| Symbol | Description |
|--------|-------------|
| 𝒩 | Buses (10 nodes) |
| 𝒯 | Snapshots (112 timesteps, 3 h) |
| 𝒦 | Technologies (onwind, offwind, solar, ocgt, ccgt) |
| ℒ | Transmission lines (22) |
| 𝒮 | Nuclear sites (scenario-dependent, up to 5) |

### 11.2 Decision variables

| Variable | Unit | Description |
|----------|------|-------------|
| p_{n,k,t} | MW | Dispatch of technology k at bus n, time t |
| P^cap_{n,k} | MW | **New** installed capacity (extendable tech) |
| f_{ℓ,t} | MW | Power flow on line ℓ |
| p^dis_{n,t}, p^ch_{n,t} | MW | Battery discharge / charge |
| E^cap_n | MWh | Battery energy capacity |
| P^st_n | MW | Battery power capacity |
| SOC_{n,t} | MWh | State of charge |
| p^nu_{s,t} | MW | Nuclear dispatch at site s |
| Cap^nu_s | MW | Nuclear capacity built at site s |

Existing capacity P^exist_{n,k} is a parameter; total available capacity = P^exist + P^cap.

### 11.3 Objective function

Minimise total system cost over the simulation window:

$$\min \sum_{t \in \mathcal{T}} w_t \left[ \sum_{n,k} c^{marg}_k \, p_{n,k,t} + \sum_{n} c^{st}_n \,(p^{dis}_{n,t} + p^{ch}_{n,t}) + \sum_{s} c^{nu}_s \, p^{nu}_{s,t} \right] + \sum_{n,k} c^{cap}_k \, P^{cap}_{n,k} + \sum_{s} c^{nu,cap}_s \, Cap^{nu}_s + \sum_{n} \left( c^{p}_n P^{st}_n + c^{e}_n E^{cap}_n \right)$$

where w_t is the snapshot weight (hours), c^marg marginal cost, c^cap annuitised CAPEX.

### 11.4 Key constraints

**Nodal balance** (each bus n, time t):

$$\sum_{k} p_{n,k,t} + \sum_{s: bus(s)=n} p^{nu}_{s,t} + \sum_{\ell} f_{\ell,t} \cdot (\text{in}_{\ell,n} - \text{out}_{\ell,n}) + p^{dis}_{n,t} - p^{ch}_{n,t} = d_{n,t}$$

**Generator bounds:**

$$p_{min,k} \,(P^{exist}_{n,k} + P^{cap}_{n,k}) \leq p_{n,k,t} \leq \overline{p}_{n,k,t} \,(P^{exist}_{n,k} + P^{cap}_{n,k})$$

**Line limits:** −s_nom_ℓ ≤ f_{ℓ,t} ≤ s_nom_ℓ

**Ramps:** |p_{n,k,t} − p_{n,k,t−1}| ≤ ramp_k × Δt × capacity

**Storage dynamics:**

$$SOC_{n,t} = (1 - \lambda_n \Delta t)\, SOC_{n,t-1} + \eta_n \, p^{ch}_{n,t} \Delta t - \frac{p^{dis}_{n,t}}{\eta_n} \Delta t$$

**CO₂ cap:**

$$\sum_{n,k,t} w_t \, e^{CO2}_k \, p_{n,k,t} \leq CO2_{limit}^{window}$$

(Only gas technologies have non-zero CO₂ intensity in the template.)

**Nuclear:**

$$p_{min,s} \, Cap^{nu}_s \leq p^{nu}_{s,t} \leq p_{max,s} \, Cap^{nu}_s, \quad 0 \leq Cap^{nu}_s \leq 1{,}500 \text{ MW}$$

---

## 12. Exported results

After running `python src/run.py --scenario <name>`, outputs are written to `results/<scenario>/`.

### 12.1 Output files

| File | Contents | Report use |
|------|----------|------------|
| `summary.yaml` | Scenario name, solver status, objective (EUR), total dispatch (MWh) | Executive summary box; verify optimality |
| `dispatch.csv` | Columns: `n`, `k`, `t`, `MW` — generation by bus, technology, hour | Time-series plots; peak-hour supply stack |
| `investment.csv` | New capacity by bus and technology (`new_MW` > 0 only) | Table of optimal VRE/gas expansion |
| `storage_power.csv` | Optimal battery power capacity (MW) per bus | Storage deployment map |
| `storage_energy.csv` | Optimal battery energy capacity (MWh) per bus | Storage sizing |
| `nuclear_investment.csv` | Built nuclear capacity (MW) per site | Nuclear build outcome (if scenario enables nuclear) |
| `nuclear_dispatch.csv` | Nuclear generation (MW) by site and time | Dispatch duration curves |

### 12.2 How to interpret results

**Objective value (`summary.yaml`):** Total cost = weighted OPEX over 336 h + annuitised CAPEX of **new** investments. Compare across scenarios:

| Scenario (template run) | Objective (bn EUR) | Interpretation |
|-------------------------|---------------------:|----------------|
| base | ~1.96 | Reference winter operation |
| dunkelflaute | ~2.86 | +46% cost under VRE stress (more gas dispatch) |

**`investment.csv`:** Lists only **incremental** build. With template inputs, the optimiser may add large OCGT capacity — a sign that placeholders are not calibrated to the PyPSA fleet. Cross-check against PyPSA `report_summary.csv` in the parent repo.

**`dispatch.csv`:** Filter by time and bus to build stacked area charts (wind / solar / gas / storage). Useful for showing the Dunkelflaute hour composition.

**Nuclear files:** If `nuclear_investment.csv` is empty or near-zero, nuclear was not economic under current costs and the short optimisation window — consistent with PyPSA-INRE findings.

### 12.3 Comparing multiple scenarios

Run all scenarios:

```bash
python src/run.py --scenario all
```

Then compare `summary.yaml` objective values and aggregate `investment.csv` / `dispatch.csv` externally (Excel, Python, or a future comparison script).

For **publication-quality KPI tables**, prefer the PyPSA comparison outputs in `results/inre-comparison/report_summary.csv` (period-correct TWh and kt CO₂). Use `gamspy-de` results to demonstrate model structure, sensitivity tests, or independent replication.

---

## 13. Workflow diagram

```
inputs/*.csv  ──►  load_inputs.py
                        │
scenarios/*.yaml ──►  apply_scenario.py  (Dunkelflaute derating, nuclear filter)
                        │
                        ▼
                  build_model.py  (GAMSPy LP)
                        │
                        ▼
                    run.py  (HiGHS/CPLEX)
                        │
                        ▼
              export_results.py  ──►  results/<scenario>/
```

---

## 14. Running the model

```bash
cd gamspy-de
pip install -r requirements.txt
gamspy install solver highs          # one-time
python src/run.py --scenario base
python src/run.py --scenario dunkelflaute-smr
python src/run.py --scenario all
```

Regenerate template inputs:

```bash
python tools/generate_templates.py
```

---

## 15. Limitations for report authors

1. **Template inputs:** Current CSVs are synthetic placeholders, not ENTSO-E/Atlite/PyPSA exports. Absolute numbers (GW built, EUR costs) should be labelled as illustrative unless inputs are recalibrated.
2. **Short window bias:** 336 hours is insufficient for realistic long-term investment signals; nuclear and VRE expansion should be interpreted cautiously (same caveat as PyPSA-INRE).
3. **Transport vs DC-OPF:** Line flows are not physics-accurate OPF; use for adequacy screening, not detailed grid analysis.
4. **No imports:** Real Dunkelflaute events involved cross-border flows; this model is intentionally isolated.
5. **CO₂ cap:** 500 Mt/year is often non-binding in practice; check dual values if emissions bind.
6. **Complementary to PyPSA:** For calibrated German system results, cite PyPSA outputs; use GAMSPy for methodology transparency and custom scenario experiments.

---

## 16. References

| Topic | Reference |
|-------|-----------|
| INRE methodology | [`INRE-METHODOLOGY.md`](../INRE-METHODOLOGY.md) |
| PyPSA-Eur base model | [PyPSA-Eur documentation](https://pypsa-eur.readthedocs.io/) |
| Dunkelflaute parameters | [`data/inre/dunkelflaute.yaml`](../data/inre/dunkelflaute.yaml) |
| Nuclear costs | [`data/inre/custom_costs_nuclear.csv`](../data/inre/custom_costs_nuclear.csv), OECD/NEA & IEA |
| Nuclear sites | Former German NPP locations (Grohnde, Brokdorf, Isar, Emsland, Neckarwestheim) |
| Weather window | Jan 2021 — documented Central European Dunkelflaute episode |
| GAMSPy | [GAMSPy documentation](https://gamspy.readthedocs.io/) |

---

## 17. Suggested report structure (using this model)

1. **Methods:** Sections 1–4, 10–11 of this document (purpose, scope, formulation).
2. **Data:** Sections 5–9 (inputs, capacities, demand, references).
3. **Scenarios:** Section 9 (scenario matrix).
4. **Results:** Section 12 — cite `summary.yaml` objectives and selected `dispatch.csv` / `investment.csv` figures.
5. **Limitations:** Section 15.
6. **Cross-validation:** Compare qualitative trends with PyPSA `results/inre-comparison/report_summary.csv` (Dunkelflaute → higher OPEX and gas share).

---

*Generated for the INRE project. Model version: initial `gamspy-de` release aligned with INRE Phase 2 (Jan 2021 window, 10 clusters, 3-hour resolution).*
