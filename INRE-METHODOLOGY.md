# INRE Project — Modelling Methodology

**Document type:** Methodology (input data, sources, mathematical formulation, data processing)  
**Model:** PyPSA-Eur with INRE extension layer  
**Geographic scope:** Germany (`DE`), electricity-only  
**Planning horizon:** 2050 technology costs, 2024 renewable fleet, January 2021 weather window

---

## 1. Purpose and scope

This document describes the methodology used in the **INRE** (Integrated Nuclear & Renewable Energy) study. The model simulates the German electricity system under normal winter conditions and under **Dunkelflaute** stress — extended periods of simultaneously low wind and solar output — with optional investment in advanced nuclear technologies (SMR, MSR, LFR).

The workflow builds on [PyPSA-Eur](https://github.com/PyPSA/pypsa-eur), an open-source European energy system model, and adds a custom pre-solve layer that:

1. Derates variable renewable energy (VRE) availability profiles for Dunkelflaute scenarios.
2. Adds extendable advanced nuclear generators at candidate sites with technology-specific costs and operational parameters.

**In scope:** transmission-constrained dispatch, capacity expansion, storage, CO₂ cap, 2-week winter snapshot optimisation.  
**Out of scope:** sector coupling (heat, transport, industry), cross-border trade, unit commitment, existing German nuclear (all shut down).

---

## 2. Modelling framework

### 2.1 Software stack

| Component | Role |
|-----------|------|
| [PyPSA](https://pypsa.readthedocs.io/) | Linear optimal power flow and capacity expansion |
| [PyPSA-Eur](https://pypsa-eur.readthedocs.io/) | European grid build, clustering, data retrieval |
| [Snakemake](https://snakemake.github.io/) | Reproducible workflow orchestration |
| [Atlite](https://github.com/PyPSA/atlite) | Weather-to-renewable profile conversion |
| [HiGHS](https://highs.dev/) | LP solver (free, no commercial licence required) |

### 2.2 Workflow

```
retrieve data → build base network → cluster (10 nodes) → renewable profiles
    → add_electricity → prepare_network
        → [INRE: apply_inre_network]   ← Dunkelflaute and/or nuclear modifications
            → solve_network (LP)
                → results and comparison
```

The INRE step (`scripts/inre/apply_inre_network.py`) runs **after** `prepare_network` and **before** `solve_network` when Dunkelflaute stress and/or new nuclear carriers are enabled. The base scenario skips this step and passes the prepared network directly to the solver.

### 2.3 Spatial and temporal resolution

| Setting | Value | Rationale |
|---------|-------|-----------|
| Country | Germany only (`DE`) | Focused national adequacy study |
| Spatial clusters | 10 nodes | Balance between north–south heterogeneity and runtime |
| Snapshot window | 2021-01-25 → 2021-02-08 | Documented Jan 2021 winter Dunkelflaute episode |
| Temporal resolution | 3 hours (112 snapshots) | Target ≤ 15 min solve per scenario |
| Weather cutout | `europe-2021-sarah3-era5` | ERA5 + SARAH-3 for 2021 |
| Cost year | 2050 | PyPSA technology-data planning horizon |
| Renewable fleet year | 2024 | powerplantmatching capacity estimate |

---

## 3. Input data and sources

### 3.1 Summary table

| Data category | Primary source | Access | INRE override |
|---------------|----------------|--------|---------------|
| Transmission grid topology | OpenStreetMap (via PyPSA archive) | Free (`data.pypsa.org`) | No |
| Power plant database | [powerplantmatching](https://github.com/PyPSA/powerplantmatching) | Free | Filter for DE, retirement dates |
| Renewable installed capacities (2024) | powerplantmatching estimate | Free | No |
| Electricity demand | ENTSO-E Transparency Platform | Free | No |
| Weather (wind, irradiance, temperature) | ERA5 + SARAH-3 via Atlite | Free (`data.pypsa.org`) | Dunkelflaute derating applied in stress scenarios |
| Technology costs (2050) | [PyPSA technology-data](https://github.com/PyPSA/technology-data) | Free | Nuclear carriers overridden |
| Advanced nuclear techno-economics | OECD/NEA, IEA + INRE assumptions | Literature | **Yes** — `data/inre/custom_costs_nuclear.csv` |
| Dunkelflaute severity | INRE scenario parameters | Manual | **Yes** — `data/inre/dunkelflaute.yaml` |
| Nuclear candidate sites | Former German NPP locations | Manual | **Yes** — `data/inre/custom_powerplants_nuclear_DE.csv` |

### 3.2 Grid and topology

The base network is retrieved from the PyPSA-Eur archive (OpenStreetMap-derived transmission lines and substations). Germany is isolated (`countries: [DE]`) and clustered to **10 zones** using PyPSA-Eur's `cluster_network` rule. Each zone aggregates:

- Nodal electricity demand (ENTSO-E, distributed to buses),
- Conventional generators from powerplantmatching,
- Renewable generators with Atlite-derived availability profiles,
- Inter-zonal AC transmission lines (22 lines after clustering).

### 3.3 Conventional and renewable fleet

**Power plant filter** (config):

```text
(DateOut > 2025 or DateOut != DateOut) and (DateIn < 2026 or DateIn != DateIn)
```

This retains plants without a recorded shutdown date or with shutdown after 2025, and excludes plants commissioned from 2026 onward. Existing German nuclear is **not** included (all commercial plants shut down by April 2023).

**Renewable capacities** are estimated from powerplantmatching for year **2024** with technology mapping:

| powerplantmatching | PyPSA carrier |
|--------------------|---------------|
| Onshore | `onwind` |
| Offshore | `offwind-ac` |
| PV | `solar` |

**Extendable technologies** (base case): solar, solar-hsat, onwind, offwind-ac, offwind-dc, offwind-float, OCGT, CCGT, battery, H₂ store, H₂ pipeline.

### 3.4 Weather and renewable profiles

Weather data are taken from the `europe-2021-sarah3-era5` cutout:

- **ERA5:** wind speed, temperature, and related meteorological fields.
- **SARAH-3:** satellite-derived surface solar irradiance.

Atlite converts weather to per-generator availability time series `p_max_pu` (per-unit maximum output). Offshore depth constraints are disabled (`max_depth: false`) to allow unrestricted offshore siting in the model.

### 3.5 Technology costs

Default costs come from PyPSA technology-data for planning year **2050**, including:

- Overnight investment (EUR/kW),
- Fixed O&M (FOM, %/year),
- Variable O&M (VOM, EUR/MWh),
- Fuel costs,
- Electrical efficiency,
- Component lifetime,
- CO₂ intensity.

Nuclear new-build costs are **overridden** via `costs.custom_cost_fn: data/inre/custom_costs_nuclear.csv`, which is merged into the standard cost database during the build phase.

### 3.6 Advanced nuclear technology parameters

Techno-economic parameters for SMR, MSR, and LFR are documented in `nuclear-reactor-datasheet.md` and implemented in `data/inre/custom_costs_nuclear.csv`. Investment costs include **+15% decommissioning** on top of overnight CAPEX.

| Parameter | SMR | MSR | LFR | Unit | Source |
|-----------|----:|----:|----:|------|--------|
| CAPEX (overnight) | 5,000 | 5,800 | 5,400 | EUR/kW | OECD/NEA, IEA |
| Decommissioning | +15% | +15% | +15% | of CAPEX | OECD/NEA, IEA |
| **Total investment** | **5,750** | **6,670** | **6,210** | EUR/kW | Computed |
| Fixed O&M | 40 | 45 | 42 | EUR/kW-year | OECD/NEA, IEA |
| Variable O&M | 3.0 | 3.5 | 3.2 | EUR/MWh | OECD/NEA, IEA |
| Fuel cost | 3.0 | 2.5 | 2.8 | EUR/MWh_th | INRE uranium estimate |
| Electrical efficiency | 0.33 | 0.35 | 0.34 | p.u. | INRE assumption |
| Lifetime | 60 | 50 | 55 | years | INRE assumption |
| CO₂ intensity | 0 | 0 | 0 | t/MWh | INRE assumption |
| Ramp rate limit | 0.50 | 0.50 | 0.50 | p.u./hour | INRE assumption |
| Site capacity limit | 1,500 | 1,500 | 1,500 | MW | Config default |

Operational parameters applied in `scripts/inre/add_nuclear_technologies.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `p_max_pu` | 0.90 | Availability factor (90%) |
| `p_min_pu` | 0.30 | Minimum stable load (30% of rated capacity) |
| `ramp_limit_up/down` | 0.50 | Maximum ramp rate (per unit per hour) |
| `p_nom_max` | 1,500 MW | Maximum build per candidate site |

### 3.7 Nuclear candidate sites

Candidate locations are former German nuclear power plant sites in `data/inre/custom_powerplants_nuclear_DE.csv`:

| Site | Latitude | Longitude | SMR | MSR | LFR |
|------|----------|-----------|:---:|:---:|:---:|
| Grohnde | 51.906 | 9.401 | ✓ | ✓ | ✓ |
| Brokdorf | 53.851 | 9.345 | ✓ | ✓ | ✓ |
| Isar | 48.617 | 12.293 | ✓ | ✓ | — |
| Emsland | 52.471 | 7.321 | ✓ | — | ✓ |
| Neckarwestheim | 49.040 | 9.175 | ✓ | — | — |

Each site is mapped to the nearest network bus by Euclidean distance in geographic coordinates. Generators are added with zero initial capacity (`p_nom = 0`) and `p_nom_extendable = True`.

---

## 4. Mathematical model

The model is a **linear programming (LP)** formulation: linear optimal power flow combined with capacity expansion. PyPSA constructs the optimisation problem; INRE modifies input time series and adds generators before the solve step.

### 4.1 Sets and indices

| Symbol | Description |
|--------|-------------|
| $\mathcal{N}$ | Set of network buses (10 clustered zones) |
| $\mathcal{T}$ | Set of snapshots (112 timesteps, 3-hour resolution) |
| $\mathcal{G}$ | Set of generators |
| $\mathcal{L}$ | Set of transmission lines |
| $\mathcal{S}$ | Set of storage units and stores |
| $\mathcal{K}$ | Set of energy carriers (solar, onwind, CCGT, nuclear-smr, …) |

### 4.2 Decision variables

| Variable | Domain | Description |
|----------|--------|-------------|
| $p_{g,t}$ | $\mathbb{R}_+$ | Active power dispatch of generator $g$ at time $t$ (MW) |
| $p\_nom_g$ | $\mathbb{R}_+$ | Installed capacity of extendable generator $g$ (MW) |
| $f_{\ell,t}$ | $\mathbb{R}$ | Power flow on line $\ell$ at time $t$ (MW) |
| $e_{s,t}$ | $\mathbb{R}_+$ | State of charge of storage $s$ at time $t$ (MWh) |
| $h_{s,t}$ | $\mathbb{R}$ | Charge/discharge power of storage $s$ at time $t$ (MW) |

For non-extendable generators, $p\_nom_g$ is fixed to the installed capacity from the power plant database.

### 4.3 Parameters

| Parameter | Description | Source |
|-----------|-------------|--------|
| $d_{n,t}$ | Electricity demand at bus $n$, time $t$ | ENTSO-E |
| $\overline{p}_{g,t}$ | Per-unit availability: $p\_max\_pu_{g,t}$ | Atlite (modified by INRE for Dunkelflaute) |
| $c\_cap_g$ | Annuitised capital cost (EUR/MW/year) | technology-data + custom nuclear costs |
| $c\_marg_g$ | Marginal operating cost (EUR/MWh) | technology-data + custom nuclear costs |
| $\eta_g$ | Electrical efficiency | technology-data / custom costs |
| $r_g$ | Ramp limit (p.u./hour) | Generator attributes |
| $\underline{p}_g$ | Minimum stable load ($p\_min\_pu$) | Generator attributes |
| $e\_co2_g$ | CO₂ emissions intensity (t/MWh) | Carrier attributes |
| $w_t$ | Snapshot weighting for objective (hours) | PyPSA snapshot weightings |
| $\overline{f}_\ell$ | Line thermal capacity (MW) | PyPSA base network |
| $\overline{P}_g$ | Maximum build limit ($p\_nom\_max$, MW) | Config / INRE script |

**Marginal cost** for thermal generators combines variable O&M, fuel cost, and fixed O&M contribution:

$$\text{marginal\_cost}_g = \frac{\text{VOM}_g + \text{fuel}_g}{\eta_g} + \text{FOM contribution}$$

**Annuitised capital cost** converts overnight investment to annual EUR/MW using the technology-data discount rate and component lifetime.

### 4.4 Objective function

The optimiser minimises **total system cost** over all snapshots, weighted by snapshot duration:

$$\min \sum_{t \in \mathcal{T}} w_t \left[ \sum_{g \in \mathcal{G}} c\_marg_g \cdot p_{g,t} + \sum_{s \in \mathcal{S}} c\_marg_s \cdot |h_{s,t}| \right] + \sum_{g \in \mathcal{G}^{ext}} c\_cap_g \cdot p\_nom_g + \sum_{s \in \mathcal{S}^{ext}} c\_cap_s \cdot e\_nom_s$$

where $\mathcal{G}^{ext}$ and $\mathcal{S}^{ext}$ are sets of extendable generators and storage. The first term is operating expenditure (OPEX); the second and third terms are annuitised capital expenditure (CAPEX) for new capacity.

Snapshot weightings ensure that costs integrated over the simulation window are scaled consistently with the configured planning period. For a 2-week window at 3-hour resolution, the simulated period represents approximately **3.8%** of a full year; investment decisions are therefore based on limited operational exposure (see Section 6).

### 4.5 Constraints

#### 4.5.1 Nodal power balance (Kirchhoff's current law)

For each bus $n$ and time $t$:

$$\sum_{g: \text{bus}(g)=n} p_{g,t} + \sum_{\ell: \text{to}(\ell)=n} f_{\ell,t} - \sum_{\ell: \text{from}(\ell)=n} f_{\ell,t} + \sum_{s: \text{bus}(s)=n} h_{s,t} = d_{n,t}$$

#### 4.5.2 Generator dispatch limits

For each generator $g$ and time $t$:

$$\underline{p}_g \cdot p\_nom_g \leq p_{g,t} \leq \overline{p}_{g,t} \cdot p\_nom_g$$

where $\overline{p}_{g,t}$ is the time-varying availability (`p_max_pu`), and $\underline{p}_g$ is the minimum stable load fraction (`p_min_pu`).

#### 4.5.3 Ramp rate limits

For consecutive snapshots $t$ and $t+1$:

$$p_{g,t+1} - p_{g,t} \leq r_g \cdot p\_nom_g$$
$$p_{g,t} - p_{g,t+1} \leq r_g \cdot p\_nom_g$$

#### 4.5.4 Capacity expansion bounds

For extendable generators:

$$0 \leq p\_nom_g \leq \overline{P}_g$$

Nuclear generators receive $\overline{P}_g = 1{,}500$ MW per site from configuration.

#### 4.5.5 Transmission line limits

$$|f_{\ell,t}| \leq \overline{f}_\ell$$

#### 4.5.6 Storage dynamics

State-of-charge evolves with charge/discharge efficiency and standing losses (PyPSA standard storage formulation).

#### 4.5.7 CO₂ emission cap

A global constraint limits total CO₂ emissions over the simulation period:

$$\sum_{t \in \mathcal{T}} w_t \sum_{g \in \mathcal{G}} e\_co2_g \cdot p_{g,t} \leq \text{CO2Limit} \cdot \frac{\sum_t w_t}{8760}$$

Configured annual cap: **500 Mt CO₂/year** (`electricity.co2limit: 500.e+6`). PyPSA scales this to the snapshot window duration.

#### 4.5.8 Renewable resource limits

For VRE generators, dispatch is bounded by weather-derived availability profiles; no explicit energy budget constraint beyond the per-timestep $p\_max\_pu$ limit.

---

## 5. INRE data processing and scenario modifications

PyPSA-Eur has no built-in Dunkelflaute or advanced nuclear logic. INRE applies modifications in `scripts/inre/apply_inre_network.py` before the LP solve.

### 5.1 Dunkelflaute stress model

**Purpose:** Represent extended periods of low wind and solar output characteristic of Central European winter anticyclones ("Dunkelflaute").

**Implementation:** `scripts/inre/apply_dunkelflaute.py` modifies `generators_t.p_max_pu` in place.

**Parameters** (`data/inre/dunkelflaute.yaml`):

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `wind_factor` | 0.15 | Scalar fallback: retain 15% of normal wind availability during stress |
| `solar_factor` | 0.10 | Scalar fallback: retain 10% of normal solar availability during stress |
| `wind_factor_profile` | — (see `profiles/*.example.csv`) | Optional per-snapshot wind derating (overrides scalar inside stress mask) |
| `solar_factor_profile` | — (see `profiles/*.example.csv`) | Optional per-snapshot solar derating (overrides scalar inside stress mask) |
| `auto_worst_days` | 5 | Auto-select 5 lowest-VRE days in the simulation window |
| `ramp_hours` | 6 | Smooth transition over 6 snapshots (18 h) at window edges |
| `time_start` / `time_end` | 2021-01-28 → 2021-02-03 | Fallback fixed window (used when `auto_worst_days` is null) |

**Stress day selection (auto mode):**

For each day $d$ in the simulation window, compute a capacity-weighted VRE score:

$$\text{score}_d = \frac{1}{|T_d|} \sum_{t \in T_d} \left[ \sum_{g \in \text{wind}} p\_max\_pu_{g,t} \cdot p\_nom_g + \sum_{g \in \text{solar}} p\_max\_pu_{g,t} \cdot p\_nom_g \right]$$

The $N$ days with the lowest score are selected as the stress window. Lower score indicates worse Dunkelflaute conditions.

**Availability derating:**

Inside the stress mask, availability is scaled by a per-carrier factor $f_t$ (scalar or time-varying):

$$p\_max\_pu_{g,t} \leftarrow p\_max\_pu_{g,t} \times f_t$$

By default $f_t = 0.15$ for wind carriers (`onwind`, `offwind-ac`, `offwind-dc`, `offwind-float`) and $f_t = 0.10$ for solar carriers (`solar`, `solar-hsat`). Alternatively, `wind_factor_profile` and `solar_factor_profile` point to CSV files with columns `timestamp` and `factor` (values in $[0, 1]$), aligned to the 3-hourly snapshot index; these override the scalar factors inside the stress window.

**Edge ramping:** At the boundaries of the stress window, a linear ramp over `ramp_hours` snapshots blends between full and stressed availability to avoid discontinuous step changes.

**Spatial treatment:** Derating is applied **uniformly across all nodes** (national correlation assumption).

### 5.2 Advanced nuclear technology addition

**Implementation:** `scripts/inre/add_nuclear_technologies.py`

For each row in the sites CSV matching the scenario carrier:

1. Find the nearest network bus by geographic distance.
2. Add an extendable `Generator` component with:
   - `p_nom = 0`, `p_nom_extendable = True`
   - `p_nom_max` from config (default 1,500 MW)
   - `capital_cost` and `marginal_cost` from processed 2050 costs
   - `p_max_pu = 0.9`, `p_min_pu = 0.3`, `ramp_limit = 0.5`
3. Register the carrier in the network if not already present.

The LP optimiser then decides optimal installed capacity $p\_nom_g$ balancing annuitised CAPEX against dispatch value over the snapshot window.

### 5.3 Cost data integration

Custom nuclear costs in `data/inre/custom_costs_nuclear.csv` follow the PyPSA technology-data format:

```text
planning_horizon, technology, parameter, value, unit, source, further description
```

During the build phase, this file is merged via `costs.custom_cost_fn`. The processed output (`costs_2050_processed.csv`) provides `capital_cost` (EUR/MW/year) and `marginal_cost` (EUR/MWh) used when adding nuclear generators.

Investment values in the CSV include decommissioning:

$$\text{investment}_\text{total} = \text{CAPEX} \times 1.15$$

### 5.4 Scenario matrix

Five scenarios are defined in `config/inre/scenarios.yaml`:

| Scenario | Dunkelflaute | New nuclear carrier | Purpose |
|----------|:------------:|---------------------|---------|
| `base` | Off | None | Reference winter dispatch |
| `dunkelflaute` | On | None | Quantify adequacy gap under stress |
| `dunkelflaute-smr` | On | `nuclear-smr` (5 sites) | SMR contribution under stress |
| `dunkelflaute-msr` | On | `nuclear-msr` (3 sites) | MSR contribution under stress |
| `dunkelflaute-lfr` | On | `nuclear-lfr` (3 sites) | LFR contribution under stress |

Shared build resources (`run.shared_resources.policy: true`) mean grid topology, clustering, weather profiles, and the prepared network are built once. Only the INRE modification step and LP solve differ per scenario.

---

## 6. Solution method and output metrics

### 6.1 Solver

The LP is solved with **HiGHS** (interior-point method). Typical solve time: 5–7 minutes per scenario (10 clusters, 112 snapshots).

### 6.2 Key performance indicators

| KPI | Calculation |
|-----|-------------|
| Operating cost (OPEX) | `n.statistics.opex()` — variable + fixed O&M over weighted snapshots |
| Investment (CAPEX) | `n.statistics.capex()` — annuitised capital for optimal capacity |
| Total objective | `n.objective` — LP objective value |
| Generation by carrier | `n.generators_t.p` × snapshot weights, summed |
| Optimal capacity | `n.generators.p_nom_opt` for extendable units |
| CO₂ emissions | $\sum_{g,t} p_{g,t} \cdot w_t \cdot e\_co2_g$ |

---

## 7. Assumptions and limitations

### 7.1 Key assumptions

| ID | Assumption | Value | Sensitivity |
|----|------------|-------|-------------|
| T1 | Modelled country | Germany only | High — no imports |
| T2 | Spatial resolution | 10 clusters | Medium |
| T3 | Simulation window | 2 weeks (Jan 2021) | High — limits investment signal |
| T4 | Temporal resolution | 3 hours | Medium |
| T5 | Cost year | 2050 | High |
| D1 | Wind derating factor | 0.15 | Very high |
| D2 | Solar derating factor | 0.10 | Very high |
| D3 | Stress duration | 5 auto-selected days | High |
| P1 | CO₂ cap | 500 Mt/year | High — non-binding in current results |
| P2 | Existing nuclear | 0 MW | Correct for post-2023 Germany |

### 7.2 Known limitations

1. **Short snapshot window:** Investment decisions are based on ~3.8% of a year; nuclear and storage economics are not representative of full annual or lifetime utilisation.
2. **Linear programming:** No unit commitment, start-up costs, or integer build decisions.
3. **National Dunkelflaute:** Uniform derating ignores spatial variation in cloud cover and wind patterns.
4. **No cross-border flows:** Germany-only; neighbouring countries not modelled.
5. **CO₂ cap:** Current 500 Mt/year limit is non-binding; coal and lignite remain in the dispatch stack.
6. **Placeholder elements:** Fuel costs for nuclear and some operational parameters are INRE assumptions pending full literature review.

---

## 8. Reproducibility

### 8.1 Run commands

```bash
# Environment
pixi install && pixi shell

# All five scenarios
snakemake -call solve_elec_networks \
  --configfile config/inre/config.base.yaml \
  --configfile config/inre/config.scenarios.yaml

# Cross-scenario comparison
python scripts/inre/compare_scenarios.py --output-dir results/inre-comparison
```

### 8.2 Key configuration files

| File | Role |
|------|------|
| `config/inre/config.base.yaml` | Base case parameters |
| `config/inre/config.scenarios.yaml` | Multi-scenario driver |
| `config/inre/scenarios.yaml` | Per-scenario overrides |
| `data/inre/dunkelflaute.yaml` | Dunkelflaute stress parameters |
| `data/inre/custom_costs_nuclear.csv` | Nuclear techno-economic data |
| `data/inre/custom_powerplants_nuclear_DE.csv` | Candidate reactor sites |

### 8.3 INRE scripts

| Script | Function |
|--------|----------|
| `scripts/inre/apply_inre_network.py` | Orchestrator (Snakemake entry point) |
| `scripts/inre/apply_dunkelflaute.py` | Legacy synthetic VRE profile derating |
| `scripts/inre/apply_historical_dunkelflaute.py` | Direct historical / matched-reference CF import |
| `scripts/inre/historical_event_selection.py` | High-residual-load event ranking |
| `scripts/inre/freeze_transmission.py` | Freeze AC/DC transmission expansion |
| `scripts/inre/verify_co2_accounting.py` | CO₂ unit verification |
| `scripts/inre/run_v3_operational_stress.py` | v3 fixed-capacity re-solve helper |
| `scripts/inre/add_nuclear_technologies.py` | Extendable nuclear generator addition |
| `scripts/inre/compare_scenarios.py` | Cross-scenario KPI comparison |

---

## 8. Severe Dunkelflaute Event Construction (v3)

Three stress types are distinguished:

1. **Legacy synthetic Dunkelflaute** — a synthetic low-renewable profile generated using parameterised stochastic draws with a fixed random seed, applied as multipliers on the simulation-year Atlite baseline. Retained for backward comparison only (`data/inre/dunkelflaute.yaml`).

2. **Historical severe Dunkelflaute** — the main evidence-based scenario. Actual event-year Atlite capacity factors are imported directly into `p_max_pu` at cluster and carrier resolution:

\[
\bar{p}^{Historical}_{n,k,t}=CF^{event}_{n,k,t}
\]

No synthetic edge ramp. Simulation includes historical buffer days before/after the 14-day core event. Config: `data/inre/dunkelflaute.historical.yaml`.

3. **Extreme stress sensitivity** — optional anomaly-transfer transform, labelled separately from historical replay (`data/inre/dunkelflaute.extreme-sensitivity.yaml`).

**Event-selection criterion** (ranking across candidate years with fixed 2024 brownfield capacities):

\[
RL_t^{+}=\max(D_t-W_t-S_t,0),\quad I_\tau=\frac{\sum_{t=\tau}^{\tau+H-1}RL_t^{+}}{\sum_{t=\tau}^{\tau+H-1}D_t},\quad H=336\ \text{h}
\]

Main severe scenario definition: **worst observed non-overlapping 14-day high-residual-load scarcity event** in the analysed dataset (see `data/inre/dunkelflaute.historical.metadata.yaml`).

**Matched reference** shares the same demand, fixed fleet, transmission, and storage; renewable availability uses multi-year median CF at the event calendar position (`data/inre/dunkelflaute.matched-reference.yaml`).

\[
\Delta X = X_{\mathrm{Historical\ Severe}} - X_{\mathrm{Matched\ Reference}}
\]

**Operational adequacy defaults (v3):** fixed generation/storage capacities, `electricity.transmission_limit: v0`, load shedding enabled at VOLL = 100,000 EUR/MWh.

**Nuclear comparison:** equal-site technology comparison uses Grohnde, Brokdorf, Isar at 1.5 GW each (4.5 GW total). Main operational analysis uses `generic-advanced-nuclear`; SMR/MSR/LFR are cost/technical sensitivities.

**Data sources:** ERA5/SARAH via Atlite; ENTSO-E demand via PyPSA-Eur; event methodology informed by Kaspar et al. (2019), Mockert et al. (2023), Otero et al. (2022), Biewald et al. (2024).

**Limitations:** Pilot event ranking currently uses 2021 hourly CF proxy until multi-year Atlite cluster CF is built; CO₂ cap binding status requires post-patch re-solve (`scripts/inre/verify_co2_accounting.py`).

---

## 9. References

- PyPSA documentation: [Linear optimal power flow](https://pypsa.readthedocs.io/en/latest/optimal_power_flow.html)
- PyPSA-Eur: [https://pypsa-eur.readthedocs.io/](https://pypsa-eur.readthedocs.io/)
- PyPSA technology-data: [https://github.com/PyPSA/technology-data](https://github.com/PyPSA/technology-data)
- OECD/NEA, IEA: *Projected Costs of Generating Electricity* (nuclear cost basis)
- INRE project documentation: `INRE-README.md`, `INRE-PROGRESS-REPORT.md`

---

## Document history

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-07-01 | Initial methodology document for report preparation |
| 3.0 | 2026-07-10 | v3 historical severe Dunkelflaute, matched-reference, fixed-capacity defaults |
