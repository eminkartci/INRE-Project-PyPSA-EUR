# Appendices — Riding out the Dunkelflaute

**Project:** Riding out the Dunkelflaute: A Techno-Economic Assessment of SMR and Gen-IV Nuclear Coupling with High-Share Renewables in the German Power System  
**Status:** Extracted from project files (2026-07-10)  
**Authoritative results reference:** `RESULTS_FINAL.md`; KPI tables in `results/inre-comparison-v2/`

---

# Appendix A — Additional Data Tables

## A.1 Software Environment and Model Versions

| Item | Version or value | Source |
|---|---:|---|
| Python version | ≥3.10 (`pixi.toml`); lock file resolves **3.13.12** (default conda env) | `pixi.toml`, `pixi.lock` |
| PyPSA version | **1.1.2** (default env lock); doc feature pins 1.0.3 | `pixi.lock`, `pixi.toml` [feature.doc] |
| PyPSA-Eur version or Git commit | Workspace **2025.07.0**; upstream default **v2026.02.0**; repository commit **32c2240002d262e8ae47760d8ce3b8fec3c2683e** | `pixi.toml`, `config/config.default.yaml`, `git rev-parse HEAD` |
| GAMSPy version | **≥1.4.0** (not pinned in parent `pixi.lock`) | `gamspy-de/requirements.txt` |
| Solver used | **HiGHS** | `config/inre/config.base.yaml`, `gamspy-de/config/model.yaml` |
| Solver version | **highspy 1.13.1** (lock file, platform-specific) | `pixi.lock` |
| Operating system | **Not pinned in repository files** (development environment: macOS darwin 24.6.0) | User execution environment |
| Main configuration file | `config/inre/config.base.yaml` (+ `config/config.default.yaml` chain) | `Snakefile`, `INRE-README.md` |
| Main scenario files | `config/inre/scenarios.yaml` (driver: `config/inre/config.scenarios.yaml`) | `config/inre/scenarios.yaml` |

**Environment reproducibility:** Yes, in principle. The repository provides `pixi.toml`, `pixi.lock`, and exported `envs/environment.yaml` with platform pin files (`envs/default_*.pin.txt`). GAMSPy uses a separate `gamspy-de/requirements.txt` and requires an external GAMS licence. Solved PyPSA network files (`*.nc`) are gitignored and are not part of the committed repository.

---

## A.2 Temporal and Spatial Model Resolution

| Parameter | Value | Source |
|---|---|---|
| Simulated start date | **2021-01-25** | `config/inre/config.base.yaml` → `snapshots.start` |
| Simulated end date | **2021-02-08** (exclusive; PyPSA default `inclusive: left`) | `config/inre/config.base.yaml` → `snapshots.end` |
| Total simulated hours | **336 h** | `results/inre-comparison-v2/report_summary.csv` → `period_hours` |
| Snapshot frequency | **3 h** | `config/inre/config.base.yaml` → `clustering.temporal.resolution_elec` |
| Number of snapshots | **112** | `RESULTS_FINAL.md`; `gamspy-de/inputs/snapshots.csv` (112 data rows) |
| Snapshot weighting | **3 h per snapshot** (objective weight = snapshot duration) | `gamspy-de/inputs/snapshots.csv`; PyPSA `prepare_network.py` weighting logic |
| Equivalent year fraction \(N_y\) | **0.038356** (= 336/8760) | `results/inre-comparison-v2/report_summary.csv` → `nyears` |
| Number of German nodes/clusters | **10** | `config/inre/config.base.yaml` → `scenario.clusters` |
| Clustering method | **k-means busmap** (default inherited) | `config/config.default.yaml` → `clustering.cluster_network.algorithm` |
| Countries included | **Germany only (`DE`)** | `config/inre/config.base.yaml` → `countries` |
| Cross-border connections | **Excluded** (single-country model) | `INRE-METHODOLOGY.md` §1; `countries: [DE]` |
| Germany treated as isolated system | **Yes** | `INRE-METHODOLOGY.md` §3.2 |
| Weather year | **2021** (ERA5 + SARAH-3 cutout `europe-2021-sarah3-era5`) | `config/inre/config.base.yaml` → `atlite` |
| Demand year | **2021** (same snapshot window as weather) | Snapshot dates; ENTSO-E demand via PyPSA-Eur |
| Installed renewable capacity year | **2024** | `config/inre/config.base.yaml` → `estimate_renewable_capacities.year` |
| Technology cost year | **2050** | `config/inre/config.base.yaml` → `costs.year` |

**Year inconsistencies (explicit):**

| Aspect | Year used | Note |
|---|---|---|
| Weather / demand window | 2021 | 14-day January 2021 simulation |
| Renewable installed capacity | 2024 | Brownfield VRE fleet newer than weather year |
| Technology costs | 2050 | Forward-looking cost assumptions |
| Fossil plant filter | Plants with `DateIn < 2026` | `electricity.powerplants_filter` in `config/inre/config.base.yaml` |

---

## A.3 Scenario Definition

### Scenario matrix

| Scenario | Wind stress | Solar stress | Nuclear option | Extendable technologies | CO₂ constraint | Imports | Notes |
|---|---:|---:|---|---:|---|---|
| **base** | No | No | None | VRE, CCGT, battery | 50 Mt/y | No | Reference winter window |
| **dunkelflaute** | Yes (profile) | Yes (profile) | None | VRE, CCGT, battery | 50 Mt/y | No | 14-day profile stress |
| **dunkelflaute-smr** | Yes | Yes | nuclear-smr | VRE, CCGT, battery, nuclear-smr | 50 Mt/y | No | 5 sites × 1.5 GW max |
| **dunkelflaute-msr** | Yes | Yes | nuclear-msr | VRE, CCGT, battery, nuclear-msr | 50 Mt/y | No | 3 sites × 1.5 GW max |
| **dunkelflaute-lfr** | Yes | Yes | nuclear-lfr | VRE, CCGT, battery, nuclear-lfr | 50 Mt/y | No | 3 sites × 1.5 GW max |
| **base-fixedcap** | No | No | None | **None** (all fixed) | 50 Mt/y | No | Dispatch-only sensitivity |
| **dunkelflaute-fixedcap** | Yes | Yes | None | **None** | 50 Mt/y | No | Fixed-capacity adequacy test |
| **dunkelflaute-smr-capex{70,85,115}** | Yes | Yes | nuclear-smr | As SMR | 50 Mt/y | No | SMR investment ±15/30% |

*Source: `config/inre/scenarios.yaml`, `config/inre/config.base.yaml`*

**Not extendable in Phase 2 INRE:** OCGT, H₂ storage chain, conventional nuclear rebuild. OCGT and coal are additionally listed in `clustering.exclude_carriers`.

### Dunkelflaute profile construction

**Method (verified from code and notebooks):**

1. **Synthetic baseline capacity factors** are generated in `dunkenflaute_capacity_factor_calculations.ipynb` for calendar year 2021 (8,760 hourly steps; seed 42).
2. **Stress-window derating factors** are computed as ratios of stressed to baseline CFs inside the event window, clipped to \([0,1]\), and resampled to **3-hourly** resolution.
3. Outputs are written to `output/dunkelflaute/dunkelflaute_wind_factors.csv` and `output/dunkelflaute/dunkelflaute_solar_factors.csv` (also copied to `gamspy-de/profiles/`).
4. PyPSA applies them via `scripts/inre/apply_dunkelflaute.py` using `data/inre/dunkelflaute.yaml`.

**Profile parameters (`data/inre/dunkelflaute.yaml`):**

| Parameter | Value |
|---|---|
| Stress window | 2021-01-25 → 2021-02-07 |
| `auto_worst_days` | `null` (fixed window, not auto-selected) |
| Wind carriers modified | `onwind`, `offwind-ac`, `offwind-dc`, `offwind-float` |
| Solar carriers modified | `solar`, `solar-hsat` |
| Wind profile | `profiles/dunkelflaute_wind_factors.csv` |
| Solar profile | `profiles/dunkelflaute_solar_factors.csv` |
| Scalar fallbacks | Commented out (`wind_factor: 0.15`, `solar_factor: 0.10`) — **not active** |
| Edge ramp | `ramp_hours: 6` (6 snapshots = 18 h at 3-hourly resolution) |

**Transformation applied to availability** (`scripts/inre/apply_dunkelflaute.py`):

\[
\text{multiplier}_t = 1 - w_t^{\mathrm{ramp}}\,(1 - f_t)
\]
\[
\bar{p}_{g,t}^{\mathrm{DF}} = \bar{p}_{g,t}^{\mathrm{Base}} \times \text{multiplier}_t
\]

where \(f_t\) is the profile factor from CSV and \(w_t^{\mathrm{ramp}}\) is a 0–1 edge-ramp weight.

**Profile statistics inside stress window** (112 snapshots, derived from `output/dunkelflaute/*_factors.csv`):

| Profile | Min | Max | Mean |
|---|---:|---:|---:|
| Wind factor | 0.103 | 0.370 | 0.177 |
| Solar factor | 0.000 | 1.000 | 0.509 |

**Spatial coverage:** Derating applies to **all German generators** of the listed carriers (national uniform treatment).

**Wind vs. solar:** **Not modified equally** — separate profiles and carrier sets.

**Operations on profiles:** Clipping to \([0,1]\) in notebook; nearest-neighbour alignment to snapshots in `apply_dunkelflaute.py`; edge ramping; no replacement of baseline profiles outside the stress mask (multiplier = 1).

---

## A.4 Existing Generation and Storage Capacities

Values below are from the **base** scenario. Wind and solar use brownfield `p_nom` (credible); thermal capacities use optimiser-reported totals for the base run. *Classification: values directly extracted from model outputs via `scripts/inre/compare_scenarios.py`.*

### Main scenarios (base run)

| Carrier | Existing / base capacity [GW] | Extendable? | Maximum additional capacity [GW] | Source |
|---|---:|---|---:|---|
| Onshore + offshore wind | 84.50 | Yes | **Not capped in config** | `results/inre-comparison-v2/credible_capacity.csv` |
| Solar PV (+ hsat) | 48.77 | Yes | **Not capped in config** | `credible_capacity.csv` |
| CCGT | 30.78 | Yes | **Not capped in config** | `credible_capacity.csv` |
| OCGT | 6.11 | No | 0 | `results/inre-comparison-v2/capacity_gw.csv` → base |
| Coal | 20.35 | No | 0 | `capacity_gw.csv` (excluded from clustering) |
| Lignite | 19.46 | No | 0 | `capacity_gw.csv` |
| Biomass | 8.02 | No | 0 | `capacity_gw.csv` |
| Geothermal | 0.027 | No | 0 | `capacity_gw.csv` |
| Oil | 5.68 | No | 0 | `capacity_gw.csv` |
| Waste | 3.13 | No | 0 | `capacity_gw.csv` |
| Run-of-river / hydro | **Not available in current project files** (not extracted in KPI tables) | No | — | KPI extraction scope |
| Pumped hydro (PHS) | **Not available in current project files** | No | — | KPI extraction scope |
| Battery (StorageUnit) | 0.035 GW power / 0.211 GWh energy | Yes | **Not capped in config** | `credible_capacity.csv` |
| Nuclear (SMR/MSR/LFR) | 0 | Scenario-dependent | 7.5 (SMR) / 4.5 (MSR, LFR) | `config/inre/config.base.yaml`; site file |

**Fixed-capacity scenarios:** `base-fixedcap` and `dunkelflaute-fixedcap` set `electricity.extendable_carriers.Generator: []` and `StorageUnit: []` — all capacities frozen to the solved base capacities (`config/inre/scenarios.yaml`).

---

## A.5 Nuclear Technology Assumptions

| Parameter | SMR | MSR | LFR | Unit | Source |
|---|---:|---:|---:|---|---|
| Representative technology family | Light-water SMR | Molten-salt reactor | Lead-cooled fast reactor | — | `nuclear-reactor-datasheet.md` |
| Efficiency | 0.33 | 0.35 | 0.34 | p.u. | `data/inre/custom_costs_nuclear.csv` |
| Overnight CAPEX | 5,000 | 5,800 | 5,400 | EUR/kW | `custom_costs_nuclear.csv` |
| Decommissioning adder | +15% | +15% | +15% | of CAPEX | `custom_costs_nuclear.csv` |
| Total investment | 5,750 | 6,670 | 6,210 | EUR/kW | `custom_costs_nuclear.csv` |
| Fixed O&M (input) | 40 (0.8 %/yr) | 45 (0.776 %/yr) | 42 (0.778 %/yr) | EUR/kW-yr / %/yr | `custom_costs_nuclear.csv` |
| Variable O&M | 3.0 | 3.5 | 3.2 | EUR/MWh | `custom_costs_nuclear.csv` |
| Fuel cost (thermal) | 3.0 | 2.5 | 2.8 | EUR/MWh | `custom_costs_nuclear.csv` |
| Marginal cost (processed) | 12.09 | 10.64 | 11.44 | EUR/MWh | `results/dunkelflaute-smr/costs/costs_2050_processed.csv` |
| Lifetime | 60 | 50 | 55 | years | `custom_costs_nuclear.csv` |
| Discount rate | 0.07 | 0.07 | 0.07 | p.u. | `costs_2050_processed.csv` |
| Annuity factor \(a\) | 0.0712 | 0.0725 | 0.0717 | p.u. | Derived from `scripts/add_electricity.py` → `calculate_annuity` |
| Annualised capital cost | 17,474 | 20,523 | 18,940 | EUR/MW/yr | `costs_2050_processed.csv` |
| Maximum availability (`p_max_pu`) | 0.9 | 0.9 | 0.9 | p.u. | `scripts/inre/add_nuclear_technologies.py` |
| Minimum stable load (`p_min_pu`) | 0.3 | 0.3 | 0.3 | p.u. | `add_nuclear_technologies.py` |
| Ramp-up / ramp-down limit | 0.5 | 0.5 | 0.5 | p.u./h | `add_nuclear_technologies.py` |
| Module / site size limit | 1,500 | 1,500 | 1,500 | MW | `config/inre/config.base.yaml` → `p_nom_max_per_site` |
| Site capacity limit | 1,500 | 1,500 | 1,500 | MW | Same |
| Number of available sites | 5 | 3 | 3 | — | `data/inre/custom_powerplants_nuclear_DE.csv` |
| Total maximum buildable capacity | 7.5 | 4.5 | 4.5 | GW | \(N_{\text{sites}} \times P_{\text{site,max}}\) |
| CO₂ emission factor | 0 | 0 | 0 | t/MWh | `custom_costs_nuclear.csv` |
| Committable status | **Non-committable** (LP, no binaries) | — | — | Model formulation |
| Minimum up time | **Not available in current project files** | — | — | — |
| Minimum down time | **Not available in current project files** | — | — | — |
| Start-up cost | 0 | 0 | 0 | EUR | `nuclear-reactor-datasheet.md` |
| Shut-down cost | **Not available in current project files** | — | — | — |

**Shared operational parameters:** `p_max_pu`, `p_min_pu`, and ramp limits are **identical for all three technologies** and are set as generic INRE defaults in `add_nuclear_technologies.py`, not differentiated by reactor type in the PyPSA implementation.

**Marginal cost equation used in code** (`scripts/process_cost_data.py`):

\[
c_g^{\mathrm{marginal}} = \mathrm{VOM}_g + \frac{\mathrm{fuel}_g}{\eta_g}
\]

*Carbon price is not included in `marginal_cost`; CO₂ is constrained globally.*

---

## A.6 Nuclear Site Mapping

| Site | Model node or bus | Nuclear technology allowed | Maximum capacity [GW] | Selection rationale | Source |
|---|---|---|---:|---|---|
| Grohnde | Nearest PyPSA bus by (lon, lat) | SMR, MSR, LFR | 1.5 | Former German NPP site | `data/inre/custom_powerplants_nuclear_DE.csv`; `add_nuclear_technologies.py` |
| Brokdorf | Nearest bus | SMR, MSR, LFR | 1.5 | Former German NPP site | Same |
| Isar | Nearest bus | SMR, MSR | 1.5 | Former German NPP site | Same |
| Emsland | Nearest bus | SMR, LFR | 1.5 | Former German NPP site | Same |
| Neckarwestheim | Nearest bus | SMR only | 1.5 | Former German NPP site | Same |

**GAMSPy bus assignments** (`gamspy-de/inputs/nuclear_sites.csv`):

| Site | Bus | Technologies |
|---|---|---|
| Grohnde | DE2 | SMR, MSR, LFR |
| Brokdorf | DE0 | SMR, MSR, LFR |
| Isar | DE8 | SMR, MSR |
| Emsland | DE2 | SMR, LFR |
| Neckarwestheim | DE7 | SMR |

**Why site counts differ:** Each scenario enables only one carrier (`inre.nuclear.extendable_carriers` in `config/inre/scenarios.yaml`). The sites CSV contains rows per technology; the script filters by carrier. MSR and LFR exclude Isar and Neckarwestheim respectively.

**Maximum total capacity:**

| Technology | Calculation | Result |
|---|---|---:|
| SMR | \(5 \times 1.5\,\text{GW}\) | **7.5 GW** |
| MSR | \(3 \times 1.5\,\text{GW}\) | **4.5 GW** |
| LFR | \(3 \times 1.5\,\text{GW}\) | **4.5 GW** |

**Observed builds (model output):** SMR 7,500 MW; MSR 4,500 MW; LFR 4,500 MW (`results/inre-comparison-v2/credible_capacity.csv`) — all sites filled to cap.

*Source: `results/inre-comparison-v2/credible_capacity.csv`; `gamspy-de/results/dunkelflaute-smr/nuclear_investment.csv` (5 × 1,500 MW).*

---

## A.7 Fuel, Carbon, and Emission Assumptions

*Values from `results/dunkelflaute-smr/costs/costs_2050_processed.csv` (2050 technology-data + INRE nuclear overrides). Carbon price is **not** applied exogenously in `marginal_cost`; CO₂ is limited by a global cap.*

| Carrier | Fuel cost [EUR/MWh] | Efficiency | Variable O&M [EUR/MWh] | CO₂ factor [t/MWh] | Carbon price [EUR/t] | Final marginal cost [EUR/MWh] | Source |
|---|---:|---:|---:|---:|---:|---:|---|
| Gas (fuel) | 22.76 | 1.0 | 0 | 0.198 | **Not applied in marginal cost** | 22.76 | `costs_2050_processed.csv` → `gas` |
| CCGT | (via gas) | 0.60 | 5.34 | 0.198 | — | 43.27 | `costs_2050_processed.csv` → `CCGT` |
| OCGT | (via gas) | 0.43 | 6.01 | 0.198 | — | 58.94 | `costs_2050_processed.csv` → `OCGT` |
| Coal | 6.72 | 0.356 | 4.10 | 0.336 | — | 22.98 | `costs_2050_processed.csv` → `coal` |
| Lignite | 7.94 | 0.330 | 4.10 | 0.407 | — | 28.17 | `costs_2050_processed.csv` → `lignite` |
| Biomass | 9.35 | 0.468 | 0 | 0 | — | 19.98 | `costs_2050_processed.csv` → `biomass` |
| Nuclear SMR | 3.0 (thermal) | 0.33 | 3.0 | 0 | — | 12.09 | `costs_2050_processed.csv` → `nuclear-smr` |
| Nuclear MSR | 2.5 | 0.35 | 3.5 | 0 | — | 10.64 | → `nuclear-msr` |
| Nuclear LFR | 2.8 | 0.34 | 3.2 | 0 | — | 11.44 | → `nuclear-lfr` |
| Onshore wind | 0 | 1.0 | 0.015 | 0 | — | 0.015 | → `onwind` |
| Solar | 0 | 1.0 | 0.01 | 0 | — | 0.01 | → `solar` |

**Marginal-cost equation implemented in code:**

\[
c_g^{\mathrm{marginal}} = \mathrm{VOM}_g + \frac{\mathrm{fuel}_g}{\eta_g}
\]

*Source: `scripts/process_cost_data.py` (line 181). This does **not** include an explicit carbon-price term; CO₂ pricing arises only through the shadow value of the global cap constraint (shadow price not exported in committed results).*

---

## A.8 CO₂ Constraint Derivation

| Item | Value | Source |
|---|---:|---|
| Annual CO₂ cap | **50 Mt CO₂/y** (= 50×10⁶ t/y) | `config/inre/config.base.yaml` → `electricity.co2limit` |
| Simulated period duration | **336 h** | `report_summary.csv` |
| Scaling factor \(N_y\) | **0.038356** (= 336/8760) | `report_summary.csv` → `nyears` |
| Period cap | **1,918 kt CO₂** (= 50×10⁶ × 0.038356) | Derived; stated in `RESULTS_FINAL.md` |
| Snapshot weighting included | **Yes** — PyPSA uses `Nyears = snapshot_weightings.objective.sum()/8760` | `scripts/prepare_network.py` |
| Emissions accounting | \(\sum_{g,t} w_t \cdot p_{g,t} \cdot e_g\) where \(e_g\) is carrier `co2_emissions` | `scripts/inre/compare_scenarios.py` |

**Constraint implementation (PyPSA):**

\[
\sum_{g,t} w_t \, e_g \, p_{g,t} \leq \text{CO2Limit} \times N_y
\]

with `CO2Limit = 50×10⁶` t/y (`scripts/prepare_network.py` → `add_co2limit`).

| Scenario | Emissions [ktCO₂] | Period cap [ktCO₂] | Constraint binding? | Slack [ktCO₂] | Shadow price |
|---|---:|---:|---|---:|---|
| base | 1,020 | 1,918 | **No** | 898 | **Not available in current project files** |
| dunkelflaute | 1,082 | 1,918 | **No** | 836 | Not available |
| dunkelflaute-smr | 1,077 | 1,918 | **No** | 841 | Not available |
| dunkelflaute-msr | 1,080 | 1,918 | **No** | 838 | Not available |
| dunkelflaute-lfr | 1,082 | 1,918 | **No** | 836 | Not available |

*Emissions source: `results/inre-comparison-v2/report_summary.csv`. GAMSPy runs saturate at the cap (qualitative; see §A.15 and `RESULTS_FINAL.md` §12).*

---

## A.9 Storage Assumptions

### PyPSA-Eur (extendable battery StorageUnit)

| Parameter | Value | Source |
|---|---|---|
| Extendable carrier | `battery` (StorageUnit) | `config/inre/config.base.yaml` |
| Maximum hours (`max_hours`) | **6 h** | `config/config.default.yaml` → `electricity.max_hours.battery` |
| Battery capital cost (processed) | **2,325.56 EUR/MW/yr** (combined storage unit) | `costs_2050_processed.csv` → `battery` |
| Marginal cost | **0 EUR/MWh** | `costs_2050_processed.csv` |
| Cyclic SOC / standing loss | PyPSA defaults (not overridden in INRE config) | PyPSA-Eur defaults |

### GAMSPy template (`gamspy-de/inputs/storage.csv`, all buses)

| Parameter | Value |
|---|---:|
| Charging efficiency | 0.95 |
| Discharging efficiency | 0.95 |
| Round-trip efficiency (model) | \(\eta = 0.95 \times 0.95 = 0.9025\) |
| Standing loss | 0.0001 per hour |
| Max hours | 4.0 h |
| Capital cost (power) | 35,000 EUR/MW/yr |
| Capital cost (energy) | 15,000 EUR/MWh/yr |
| Initial SOC | \(0.5 \times e\_cap\) | `gamspy-de/src/build_model.py` → `st_init` |

### Observed storage outcomes (PyPSA, StorageUnit carrier `battery`)

| Scenario | Power [MW] | Energy [MWh] | Implied hours |
|---|---:|---:|---:|
| base | 35.2 | 211.2 | 6.0 |
| dunkelflaute | 29,316.0 | 175,895.8 | 6.0 |
| dunkelflaute-smr | 15,187.9 | 91,127.5 | 6.0 |
| dunkelflaute-msr | 12,717.4 | 76,304.3 | 6.0 |
| dunkelflaute-lfr | 12,129.4 | 72,776.2 | 6.0 |

*Source: `results/inre-comparison-v2/credible_capacity.csv`.*

### Model artefacts (documented)

| Artefact | Evidence | Assessment |
|---|---|---|
| Link-based “Battery Storage” up to **414 GW** | `capacity_gw.csv` → `Battery Storage` | Phantom link-chain capacity; **excluded** from credible results |
| Large StorageUnit builds under stress (up to 29.3 GW) | `credible_capacity.csv` | Short-horizon LP artefact; flagged in `RESULTS_FINAL.md` |
| Zero-energy battery | **Not observed** for StorageUnit (energy ∝ power × 6 h) | — |
| Inconsistent power-to-energy ratio | **Not observed** (ratio fixed at 6 h) | — |

---

## A.10 Transmission and Interconnection Assumptions

| Network element | Included? | Fixed or extendable | Capacity treatment | Source |
|---|---|---|---|---|
| Internal AC lines (10-cluster) | Yes | **Extendable** (`transmission_limit: vopt`) | `s_max_pu = 0.7`; `s_nom_max = ∞`; `max_extension = 20,000 MW` | `config/config.default.yaml`; `config/inre/config.base.yaml` |
| DC links | Yes | Extendable (default) | `max_extension = 30,000 MW` | `config/config.default.yaml` |
| Cross-border interconnectors | **No** (DE-only model) | — | Excluded with `countries: [DE]` | `INRE-METHODOLOGY.md` |
| Imports / exports | **No external trade** | — | Single-country isolation | `INRE-METHODOLOGY.md` |
| Transmission losses | **Not explicitly modelled** (transport-style limits) | — | `\|f_\ell\| \leq \bar{f}_\ell` | `INRE-METHODOLOGY.md`; GAMSPy `build_model.py` |
| Dynamic line rating | Disabled | Fixed | `lines.dynamic_line_rating.activate: false` | `config/inre/config.base.yaml` |

**GAMSPy:** 10 buses, 22 lines, transport model \(|f_{\ell,t}| \leq s_\ell^{\mathrm{nom}}\) (`gamspy-de/inputs/lines.csv`; `build_model.py`).

---

## A.11 Load Shedding and Adequacy Assumptions

| Parameter | Value | Source |
|---|---|---|
| Load shedding enabled (main scenarios) | **No** | `config/config.default.yaml` → `solving.options.load_shedding.enable: false` |
| Penalty if enabled | **100,000 EUR/MWh** | `config/config.default.yaml` |
| Main scenarios — energy not served | **0 TWh** (load = 21.15 TWh fully served) | `report_summary.csv` |

### Main five scenarios

| Scenario | Energy not served [GWh] | Share of demand [%] | Maximum load shedding [GW] | Affected snapshots |
|---|---:|---:|---:|---:|
| base | 0 | 0 | 0 | 0 |
| dunkelflaute | 0 | 0 | 0 | 0 |
| dunkelflaute-smr | 0 | 0 | 0 | 0 |
| dunkelflaute-msr | 0 | 0 | 0 | 0 |
| dunkelflaute-lfr | 0 | 0 | 0 | 0 |

*Derived: load served equals 21.15 TWh in all main scenarios (`report_summary.csv`). Detailed snapshot-level load-shedding time series **not available in committed CSV files**.*

### Fixed-capacity sensitivity (`dunkelflaute-fixedcap`)

| Metric | base-fixedcap | dunkelflaute-fixedcap | Source |
|---|---:|---:|---|
| Energy not served | 0 TWh | **3.51 TWh** | `RESULTS_FINAL.md` §10 |
| Solar generation | 0.705 TWh | 0.203 TWh | `RESULTS_FINAL.md` §10 |
| OPEX / objective | — | **~35,450 M EUR** (penalty-dominated) | `RESULTS_FINAL.md` §10 |

*Fixed-cap run uses high-cost load shedding for feasibility; costs are **not comparable** to main scenarios.*

---

## A.12 Complete Scenario Results

*Primary source: `results/inre-comparison-v2/`. Generation from `generation_mix_groups_twh.csv` and `generation_mix_twh.csv`. Units: TWh (energy, 14-day period), M EUR (costs), ktCO₂, GW/MW (capacity).*

| Indicator | Base | Dunkelflaute | SMR | MSR | LFR | Unit |
|---|---:|---:|---:|---:|---:|---|
| Electricity demand | 21.15 | 21.15 | 21.15 | 21.15 | 21.15 | TWh |
| Total generation | 21.21 | 21.24 | 21.22 | 21.23 | 21.23 | TWh |
| Wind generation | 13.63 | 9.29 | 7.99 | 8.40 | 8.39 | TWh |
| Solar generation* | 0.70 | 3.78 | 2.82 | 3.31 | 3.31 | TWh |
| Nuclear generation | 0 | 0 | 2.27 | 1.36 | 1.36 | TWh |
| CCGT generation | 4.55 | 5.46 | 5.43 | 5.45 | 5.46 | TWh |
| OCGT generation | 0.050 | 0.0009 | 0.0097 | 0.0008 | 0.0012 | TWh |
| Coal generation | 0.323 | ~0 | ~0 | ~0 | ~0 | TWh |
| Lignite generation | ~0 | ~0 | ~0 | ~0 | ~0 | TWh |
| Biomass generation | 1.94 | 2.69 | 2.69 | 2.69 | 2.69 | TWh |
| Hydro generation | **Not available** | — | — | — | — | TWh |
| Storage charging | **Not available in committed CSV files** | — | — | — | — | TWh |
| Storage discharging | **Not available** | — | — | — | — | TWh |
| Curtailment | **Not available** | — | — | — | — | TWh |
| Imports | **0 (isolated DE model)** | 0 | 0 | 0 | 0 | TWh |
| Exports | **0** | 0 | 0 | 0 | 0 | TWh |
| Load shedding | 0 | 0 | 0 | 0 | 0 | TWh |
| Period operating cost | 266.9 | 308.4 | 335.8 | 322.9 | 323.9 | M EUR |
| Annuitised investment cost | 1,935.7 | 5,287.9 | 4,499.5 | 4,817.8 | 4,809.7 | M EUR/yr |
| Period-scaled investment cost | 74.2 | 202.8 | 172.6 | 184.8 | 184.5 | M EUR |
| Solver objective | 543.8 | 3,937.5 | 3,176.4 | 3,481.8 | 3,474.8 | M EUR |
| CO₂ emissions | 1,020 | 1,082 | 1,077 | 1,080 | 1,082 | ktCO₂ |
| Nuclear capacity built | 0 | 0 | 7,500 | 4,500 | 4,500 | MW |
| Renewable capacity built (credible) | 0† | 0† | 0† | 0† | 0† | GW |
| Fossil capacity built (CCGT, credible) | — | +6.16 vs base | +4.45 vs base | +5.04 vs base | +5.85 vs base | GW |
| Storage power built (StorageUnit) | 0.035 | 29.32 | 15.19 | 12.72 | 12.13 | GW |
| Storage energy built (StorageUnit) | 0.211 | 175.9 | 91.1 | 76.3 | 72.8 | GWh |

\*Solar cross-scenario comparison flagged as **not interpretable** (`RESULTS_FINAL.md` §9).  
†Brownfield wind/solar `p_nom` unchanged in credible capacity table (84.5 GW wind, 48.8 GW solar). Phantom optimiser VRE expansion (up to 488 GW onshore wind, 916 GW solar) exists in raw outputs but is excluded.

*Sources: `report_summary.csv`, `generation_mix_groups_twh.csv`, `credible_capacity.csv`, `capacity_gw.csv`.*

---

## A.13 Cost Decomposition

**Available committed decomposition** (from `report_summary.csv`):

| Cost component | Base | Dunkelflaute | SMR | MSR | LFR | Unit |
|---|---:|---:|---:|---:|---:|---|
| Period operating cost (OPEX) | 266.9 | 308.4 | 335.8 | 322.9 | 323.9 | M EUR |
| Annuitised generator/storage investment (CAPEX) | 1,935.7 | 5,287.9 | 4,499.5 | 4,817.8 | 4,809.7 | M EUR/yr |
| Period-scaled CAPEX (= CAPEX × \(N_y\)) | 74.2 | 202.8 | 172.6 | 184.8 | 184.5 | M EUR |
| Solver objective | 543.8 | 3,937.5 | 3,176.4 | 3,481.8 | 3,474.8 | M EUR |
| OPEX + period-scaled CAPEX | 341.1 | 511.2 | 508.4 | 507.7 | 508.4 | M EUR |

**Not available in committed result files:** separate fuel cost, VOM, CO₂ cost, nuclear-only investment, renewable-only investment, transmission investment, and load-shedding cost breakdowns by scenario.

### Accounting basis

| Metric | Definition | Comparable across scenarios? |
|---|---|---|
| **Period OPEX** | `n.statistics.opex()` integrated over 336 h | **Yes** — headline operational metric |
| **Annuitised CAPEX** | `n.statistics.capex()` in **EUR/year** | Context only; do not add to period OPEX |
| **Period-scaled CAPEX** | CAPEX × \(N_y\) where \(N_y = 336/8760\) | Bridge metric |
| **Solver objective** | `n.objective` (LP optimum over same window) | **Caveated** — inflated in stress runs by phantom link/H₂/VRE CAPEX |

**Annualisation:** Investment terms enter the objective as **annualised EUR/MW·yr** multiplied by installed capacity, while operational terms are weighted by \(w_t\) (hours). Over a 14-day window, \(N_y = 0.03836\) of a year.

**Period OPEX is not equal to the solver objective** in stress scenarios (e.g. dunkelflaute: OPEX 308.4 M EUR vs objective 3,937.5 M EUR) because the objective includes large phantom capital costs (`RESULTS_FINAL.md` §2).

---

## A.14 Cleaned Results and Excluded Artefacts

| Variable | Raw model value | Reported value | Adjustment applied | Reason | Source |
|---|---:|---:|---|---|---|
| Onshore wind capacity | up to **488 GW** (dunkelflaute) | **84.5 GW** existing | Use brownfield `p_nom`; exclude `p_nom_opt` phantom | Short-horizon uncapped VRE expansion | `capacity_gw.csv`; `credible_capacity.csv` |
| Solar capacity | up to **916 GW** (dunkelflaute) | **48.8 GW** existing | Same | Phantom expansion + profile artefacts | Same |
| Solar generation (main scenarios) | 0.70 → 3.78 TWh (base → DF) | **Excluded from headline interpretation** | Not adjusted — flagged only | Profile mismatch + phantom capacity | `RESULTS_FINAL.md` §9–10 |
| Battery power (link chain) | up to **414 GW** | **0.035–29.3 GW** (StorageUnit only) | Exclude `Battery Storage` link component | Link-based storage artefact | `capacity_gw.csv`; `credible_capacity.csv` |
| Wind generation | 9.29 TWh (dunkelflaute) | **9.29 TWh** (reported) | None — treated as credible | Consistent with fixed-cap sensitivity | `generation_mix_groups_twh.csv` |
| CCGT capacity | 36.9 GW (dunkelflaute) | **36.9 GW** | None | Physically interpretable build | `credible_capacity.csv` |
| Fixed-cap solar | 3.78 TWh (main DF) | **0.203 TWh** | Re-solve with frozen capacities | `dispatch_fixed_solar.py` / `resolve_fixedcap.py` | `RESULTS_FINAL.md` §10 |
| Fixed-cap load shedding | 0 TWh (main) | **3.51 TWh** | Separate fixed-cap re-solve | Adequacy gap when investment frozen | `RESULTS_FINAL.md` §10 |

**Processing scope:** Cleaning is **post-processing only** for tables and figures; main scenarios were **not re-run** after artefact identification. Fixed-cap scenarios are **separate re-solves** with capacities frozen.

**Excluded capacities in optimisation:** Phantom capacities **did affect** the original LP solutions (they are part of solved networks). They are excluded only from **interpretation and reporting**.

---

## A.15 PyPSA-Eur and GAMSPy Input Harmonisation

| Parameter | PyPSA-Eur | GAMSPy | Same input? | Explanation |
|---|---|---|---|---|
| Demand | ENTSO-E, 10-cluster DE, 336 h | Template `demand.csv`, 10 buses | **No** | GAMSPy uses representative template (~21 MWh scale) |
| Wind profile | Atlite 2021 + optional DF derating | `availability.csv` + profile CSVs | **Partial** | Same DF factor files; different spatial aggregation |
| Solar profile | Atlite 2021 + DF derating | Aggregated `solar` tech | **Partial** | PyPSA has `solar` + `solar-hsat`; GAMSPy one solar type |
| Installed capacity | powerplantmatching 2024 | `capacity_existing.csv` template | **No** | GAMSPy template ~65 GW wind, ~55 GW solar nationally |
| Generator efficiency | technology-data 2050 | Simplified tech table | **Partial** | Nuclear efficiencies harmonised; fossil simplified |
| Marginal cost | Processed technology-data | `technologies.csv` | **Partial** | Nuclear MC aligned; CCGT 43.27 vs 52.0 EUR/MWh |
| Capital cost | Annuitised technology-data | `technologies.csv` EUR/MW/yr | **Partial** | Nuclear CAPEX harmonised via same investment data |
| CO₂ cap | 50 Mt/y → 1,918 kt/period | 50 Mt/y → same scaling | **Yes (policy level)** | Same annual cap and window scaling |
| Emission factors | Carrier `co2_emissions` | `co2_t_per_MWh` in tech table | **Partial** | CCGT 0.198 vs 0.25 t/MWh in GAMSPy |
| Transmission | Extendable AC/DC (vopt) | 22 fixed transport lines | **No** | Different topology and expansion rules |
| Storage | StorageUnit battery (6 h max) | Nodal battery 4 h max | **No** | Different hours and cost structure |
| Nuclear site limits | 1,500 MW × {5,3,3} sites | Same site table | **Yes** | `nuclear_sites.csv` aligned with PyPSA site file |
| Temporal resolution | 112 × 3 h | 112 × 3 h | **Yes** | Same window 2021-01-25 – 2021-02-07 |
| VRE carriers | 6 types | 3 aggregated types | **No** | GAMSPy aggregates offwind variants |
| H₂ chain | Present in PyPSA default build | **Not included** | **No** | GAMSPy electricity-only simplified |
| Load shedding | Disabled (main scenarios) | **Not included** | **Yes (main)** | Fixed-cap PyPSA uses shedding; GAMSPy does not |

**Role of GAMSPy:** **Qualitative mechanism check / directional sensitivity model**, not a numerically calibrated validation of PyPSA-Eur (`gamspy-de/GAMSPY-MODEL-DOCUMENTATION.md`; `RESULTS_FINAL.md` §12; `figures/captions.tex` fig. 10).

**Directional agreement (verified trends):**

| Trend | PyPSA-Eur | GAMSPy |
|---|---|---|
| Wind down under stress | −32% (13.63 → 9.29 TWh) | Sharp reduction |
| Gas fills gap | CCGT +20% | CCGT dispatch increases |
| Nuclear at site caps | 7.5 / 4.5 GW | 7.5 GW SMR (5 × 1,500 MW) |
| CO₂ | 1,020–1,082 kt (below cap) | Cap-saturated (~1,918 kt in report narrative) |

---

# Appendix B — Additional Model Equations

## Nomenclature

| Symbol | Definition | Unit |
|---|---|---|
| \(\mathcal{N}\) | Set of buses (nodes) | — |
| \(\mathcal{G}\) | Set of generators | — |
| \(\mathcal{S}\) | Set of storage units | — |
| \(\mathcal{L}\) | Set of transmission lines/links | — |
| \(\mathcal{T}\) | Set of snapshots | — |
| \(\mathcal{K}\) | Set of energy carriers | — |
| \(\mathcal{R}\) | Set of nuclear reactor sites | — |
| \(n\) | Bus index | — |
| \(g\) | Generator index | — |
| \(s\) | Storage index | — |
| \(\ell\) | Line index | — |
| \(t\) | Snapshot index | — |
| \(r\) | Nuclear site index | — |
| \(p_{g,t}\) | Generator dispatch | MW |
| \(P_g\) | Installed generator capacity (`p_nom`) | MW |
| \(\bar{p}_{g,t}\) | Availability factor (`p_max_pu`) | p.u. |
| \(\underline{p}_g\) | Minimum stable load (`p_min_pu`) | p.u. |
| \(f_{\ell,t}\) | Line flow | MW |
| \(h_{s,t}\) | Storage power (charge +, discharge −) | MW |
| \(e_{s,t}\) | Storage state of charge | MWh |
| \(d_{n,t}\) | Electricity demand | MW |
| \(w_t\) | Snapshot weight (duration) | h |
| \(c_g^{\mathrm{marg}}\) | Marginal cost | EUR/MWh |
| \(c_g^{\mathrm{cap}}\) | Annuitised capital cost | EUR/MW/yr |
| \(e_g\) | CO₂ intensity | t/MWh |
| \(N_y\) | Year-equivalent fraction of snapshots | p.u. |

---

## B.1 Sets and Indices

### PyPSA-Eur / INRE

| Set | Description | INRE instance |
|---|---|---|
| \(\mathcal{N}\) | Electrical buses | 10 DE clusters |
| \(\mathcal{G}\) | Generators (VRE, thermal, nuclear, etc.) | Country fleet + optional INRE nuclear |
| \(\mathcal{S}\) | StorageUnits (battery, PHS, hydro) | Battery extendable |
| \(\mathcal{L}\) | Lines and DC links | Internal DE transmission |
| \(\mathcal{T}\) | Snapshots | 112 × 3 h |
| \(\mathcal{K}\) | Carriers | solar, onwind, offwind-*, CCGT, nuclear-smr/msr/lfr, … |
| \(\mathcal{R}\) | Nuclear sites | 5 (SMR), 3 (MSR/LFR) candidate locations |

### GAMSPy

| Set | GAMSPy name | Description |
|---|---|---|
| \(\mathcal{N}\) | `n` | Buses DE0–DE9 |
| \(\mathcal{K}\) | `k` | `{onwind, offwind, solar, ocgt, ccgt}` |
| \(\mathcal{L}\) | `l` | 22 lines |
| \(\mathcal{T}\) | `t` | 112 snapshots |
| \(\mathcal{R}\) | `s` | Nuclear sites (scenario-dependent) |

---

## B.2 Decision Variables

### PyPSA-Eur (continuous LP)

| Variable | Description | Type |
|---|---|---|
| \(p_{g,t}\) | Generator dispatch | Continuous ≥ 0 |
| \(P_g\) | Installed capacity (if extendable) | Continuous ≥ 0 |
| \(f_{\ell,t}\) | Line/link flow | Continuous |
| \(h_{s,t}\), \(e_{s,t}\) | Storage power and SOC | Continuous ≥ 0 |
| Line/link expanded capacity | Transmission expansion | Continuous ≥ 0 |

**No integer or binary variables** — unit commitment is **not** modelled.

### GAMSPy

| Variable | GAMSPy name | Type |
|---|---|---|
| \(p_{n,k,t}\) | `p` | Continuous ≥ 0 |
| \(P_{n,k}^{\mathrm{cap}}\) | `p_cap` | Continuous ≥ 0 |
| \(f_{\ell,t}\) | `f` | Continuous |
| \(p_{s,t}^{\mathrm{nuc}}\) | `p_nuc` | Continuous ≥ 0 |
| \(P_s^{\mathrm{nuc}}\) | `cap_nuc` | Continuous ≥ 0 |
| \(p_{n,t}^{\mathrm{ch}}, p_{n,t}^{\mathrm{dis}}, e_{n,t}^{\mathrm{cap}}, p_{n,t}^{\mathrm{st}}\) | `p_ch`, `p_dis`, `e_cap`, `p_st_cap`, `soc` | Continuous ≥ 0 |

---

## B.3 Objective Function

### PyPSA-Eur

\[
\min \sum_{t \in \mathcal{T}} w_t \left[ \sum_{g} c_g^{\mathrm{marg}} p_{g,t} + \sum_{s} c_s^{\mathrm{marg}} |h_{s,t}| \right] + \sum_{g \in \mathcal{G}^{\mathrm{ext}}} c_g^{\mathrm{cap}} P_g + \sum_{s \in \mathcal{S}^{\mathrm{ext}}} c_s^{\mathrm{cap}} E_s
\]

Capital costs \(c^{\mathrm{cap}}\) are **annualised** (EUR/MW·yr). Operational terms are integrated over snapshot hours via \(w_t\).

*Source: PyPSA linopy backend; `INRE-METHODOLOGY.md` §4.4.*

### GAMSPy

\[
\min \underbrace{\sum_{n,k,t} w_t \, c_k^{\mathrm{marg}} \, p_{n,k,t} + \sum_{n,t} w_t \, c_n^{\mathrm{st,marg}} (p_{n,t}^{\mathrm{dis}} + p_{n,t}^{\mathrm{ch}})}_{\text{opex}} + \underbrace{\sum_{n,k} c_k^{\mathrm{cap}} P_{n,k}^{\mathrm{cap}} + \sum_n (c_n^{\mathrm{st,p}} p_{n}^{\mathrm{st}} + c_n^{\mathrm{st,e}} e_{n}^{\mathrm{cap}})}_{\text{capex}}
\]

(+ nuclear OPEX/CAPEX terms when enabled)

*GAMSPy symbols: `opex`, `capex`; `build_model.py` lines 235–240, 303–306.*

---

## B.4 Nodal Electricity Balance

### PyPSA-Eur

\[
\sum_{g: \mathrm{bus}(g)=n} p_{g,t} + \sum_{\ell \to n} f_{\ell,t} - \sum_{\ell \leftarrow n} f_{\ell,t} + \sum_{s: \mathrm{bus}(s)=n} h_{s,t} = d_{n,t}
\]

(Load shedding not active in main INRE scenarios.)

### GAMSPy (`balance`)

\[
\sum_k p_{n,k,t} + \sum_s p_{n,s,t}^{\mathrm{nuc}} \cdot \mathrm{site\_at}_{s,n} + \sum_\ell f_{\ell,t}(\mathrm{line\_in}_{\ell,n} - \mathrm{line\_out}_{\ell,n}) + p_{n,t}^{\mathrm{dis}} - p_{n,t}^{\mathrm{ch}} = d_{n,t}
\]

---

## B.5 Generator Dispatch Limits

\[
\underline{p}_g \, P_g \leq p_{g,t} \leq \bar{p}_{g,t} \, P_g
\]

- \(\bar{p}_{g,t}\) = `generators_t.p_max_pu` (Atlite baseline × Dunkelflaute multiplier if stressed).
- \(\underline{p}_g\) = `p_min_pu` (0.3 for CCGT and nuclear in INRE).

*GAMSPy equivalents: `gen_upper`, `gen_lower`.*

---

## B.6 Renewable Availability and Dunkelflaute Modification

**Baseline:** \(\bar{p}_{g,t}^{\mathrm{Base}}\) from Atlite conversion.

**Under Dunkelflaute** (`apply_dunkelflaute.py`):

\[
\bar{p}_{g,t}^{\mathrm{DF}} = \bar{p}_{g,t}^{\mathrm{Base}} \times \underbrace{\left[1 - w_t^{\mathrm{ramp}}(1 - f_t)\right]}_{\text{multiplier}_t}
\]

- \(f_t\) = wind or solar factor profile (CSV) or scalar fallback.
- \(w_t^{\mathrm{ramp}}\) = edge-ramp weight over `ramp_hours` snapshots.
- Applied separately to wind carriers `{onwind, offwind-ac, offwind-dc, offwind-float}` and solar carriers `{solar, solar-hsat}`.

---

## B.7 Capacity Expansion Constraints

\[
0 \leq P_g \leq \bar{P}_g
\]

| Technology | \(\bar{P}_g\) | Source |
|---|---|---|
| Nuclear at site | 1,500 MW | `p_nom_max_per_site` |
| VRE, CCGT, battery | **No explicit upper bound** (→ phantom expansion) | Config |
| Fixed-cap scenarios | \(P_g\) fixed | `extendable_carriers: []` |

---

## B.8 Nuclear Site Capacity Constraints

For each site \(r \in \mathcal{R}\):

\[
0 \leq P_r \leq 1{,}500\ \text{MW}
\]

Total nuclear capacity of a technology is \(\sum_r P_r\).

**Module discreteness:** **Not represented** — capacity is continuous.

*GAMSPy: `cap_nuc[s] <= site_pmax[s]` (`nuc_cap`).*

---

## B.9 Nuclear Operational Constraints

| Constraint | PyPSA implementation | Value |
|---|---|---|
| Maximum availability | `p_max_pu` | 0.9 |
| Minimum stable load | `p_min_pu` | 0.3 |
| Ramps | `ramp_limit_up/down` | 0.5 p.u./h |

**Unit commitment:** **Not implemented.** Positive \(p_{min}\) creates **continuous must-run** behaviour between 30% and 90% of installed capacity.

*GAMSPy: `nuc_upper`, `nuc_lower`, `nuc_ramp_up`, `nuc_ramp_down`.*

---

## B.10 Ramping Constraints

### PyPSA-Eur

\[
|p_{g,t} - p_{g,t-1}| \leq r_g \cdot P_g
\]

PyPSA applies ramp limits **per snapshot interval** (3 h), not explicitly multiplied by snapshot duration in `add_nuclear_technologies.py`.

### GAMSPy

\[
|p_{n,k,t} - p_{n,k,t-1}| \leq r_k \cdot \Delta t \cdot (P_{n,k}^{\mathrm{existing}} + P_{n,k}^{\mathrm{cap}})
\]

with \(\Delta t =\) `snap_h` = **3 h** (`ramp_up`, `ramp_down`).

**Interpretation note:** GAMSPy explicitly multiplies ramp limit by snapshot hours; PyPSA uses per-snapshot limits. This is a **formulation difference** between models.

---

## B.11 Storage Equations

### GAMSPy (`st_dyn`)

\[
e_{n,t} = (1 - \lambda_n \Delta t)\, e_{n,t-1} + \eta_n^{\mathrm{rt}} \, p_{n,t}^{\mathrm{ch}} \Delta t - \frac{p_{n,t}^{\mathrm{dis}}}{\eta_n^{\mathrm{rt}}} \Delta t
\]

\[
0 \leq p_{n,t}^{\mathrm{ch}}, p_{n,t}^{\mathrm{dis}} \leq p_n^{\mathrm{st}}; \quad 0 \leq e_{n,t} \leq e_n^{\mathrm{cap}}; \quad e_n^{\mathrm{cap}} \leq h_n^{\max} p_n^{\mathrm{st}}
\]

\[
e_{n,t_0} = 0.5 \, e_n^{\mathrm{cap}}
\]

### PyPSA-Eur

Standard PyPSA `StorageUnit` formulation (efficiency, standing losses, cyclic SOC per PyPSA defaults). Battery `max_hours = 6`.

---

## B.12 Transmission Constraints

**PyPSA-Eur:** Transport-style thermal limits on lines/links; **DC power flow** with linearised constraints; expansion permitted under `transmission_limit: vopt`.

\[
|f_{\ell,t}| \leq \bar{f}_\ell
\]

**GAMSPy:** Transport model only (`flow_pos`, `flow_neg`).

**10-cluster network:** **Transport / capacity limits** — not full AC load flow.

---

## B.13 CO₂ Constraint

\[
\sum_{t \in \mathcal{T}} w_t \sum_{g \in \mathcal{G}} e_g \, p_{g,t} \leq \text{CO2Limit} \cdot N_y
\]

Emissions are calculated from **electrical output** \(p_{g,t}\) and carrier emission intensity \(e_g\) (`compare_scenarios.py`; PyPSA `GlobalConstraint` with `carrier_attribute="co2_emissions"`).

*GAMSPy: `co2_cap` — \(\sum_{n,k,t} w_t \, e_k \, \mathbb{1}_k^{\mathrm{CO2}} \, p_{n,k,t} \leq \text{co2\_limit}\).*

---

## B.14 Load Shedding Constraint

**Main scenarios:** Load shedding **disabled** (`load_shedding.enable: false`).

If enabled (`solve_network.py`):

\[
\sum_{g: \mathrm{bus}(g)=n} p_{g,t} + \ldots = d_{n,t} - \ell_{n,t}; \quad \ell_{n,t} \geq 0
\]

with penalty **100,000 EUR/MWh** (`default_cost`).

---

## B.15 GAMSPy Formulation Summary

| Equation | GAMSPy name | Description |
|---|---|---|
| Dispatch upper bound | `gen_upper` | \(p \leq \mathrm{avail} \cdot \mathrm{cap}\) |
| Dispatch lower bound | `gen_lower` | \(p \geq p_{\min} \cdot \mathrm{cap}\) |
| Expansion limit | `cap_limit` | New capacity only if extendable |
| Ramps | `ramp_up`, `ramp_down` | Thermal ramping |
| Nuclear bounds | `nuc_upper`, `nuc_lower` | Site-level nuclear |
| Nuclear capacity | `nuc_cap` | Site max 1,500 MW |
| Nuclear ramps | `nuc_ramp_up`, `nuc_ramp_down` | Site ramping |
| Nodal balance | `balance` | Demand balance |
| Storage dynamics | `st_dyn` | SOC evolution |
| CO₂ cap | `co2_cap` | Global emission limit |
| Objective | `model` | minimise `opex + capex` |

---

## B.16 Differences Between the Two Models

| Model feature | PyPSA-Eur | GAMSPy |
|---|---|---|
| Network representation | 10-cluster AC/DC grid, extendable | 10-bus transport grid, fixed lines |
| Temporal resolution | 112 × 3 h | 112 × 3 h |
| Capacity expansion | VRE, CCGT, battery, lines (vopt) | Wind, solar, CCGT, battery |
| Unit commitment | No (LP) | No (LP) |
| Storage | StorageUnit 6 h + link artefacts | Nodal 4 h battery |
| CO₂ constraint | Output-based, non-binding in results | Same cap; **binding in GAMSPy results** |
| Renewable profiles | 6 VRE carriers, Atlite 2021 | 3 aggregated techs, template availabilities |
| Nuclear sites | 5/3/3 sites, continuous capacity | Same site table |
| Investment accounting | technology-data annuities | Simplified EUR/MW/yr table |
| Load shedding | Off (main); on in fixed-cap | Not included |
| H₂ chain | Present in network build | Excluded |

---

# Appendix C — Additional Figures

All figures below are **committed** in `figures/` (PDF + PNG) with LaTeX captions in `figures/captions.tex`. They were built from `results/inre-comparison-v2/` and `output/dunkelflaute/` per `RESULTS_FINAL.md`.

---

## C.1 Demand and Renewable Availability Profiles

| Item | Specification |
|---|---|
| **Figure title** | Wind and solar availability derating during the Dunkelflaute stress window |
| **File** | `figures/fig02_dunkelflaute_derating_profile.pdf` |
| **Scenarios** | Stress input profile (applies to Base vs Dunkelflaute transformation) |
| **Source files** | `output/dunkelflaute/hourly_capacity_factors.csv`; `output/dunkelflaute/dunkelflaute_wind_factors.csv`; `output/dunkelflaute/dunkelflaute_solar_factors.csv` |
| **Variables** | Wind derating factor; solar derating factor; timestamp |
| **Purpose** | Document the **scenario input** stress profile (not model output) |

**Demand time-series figure:** **Not available as a committed figure file.** Demand can be reconstructed from solved networks (`*.nc`, gitignored) or `gamspy-de/inputs/demand.csv` (GAMSPy template only).

---

## C.2 Residual Load

| Item | Specification |
|---|---|
| **Figure title** | Residual load under Base and Dunkelflaute conditions |
| **Status** | **Not available as a committed figure file** |
| **Approximate period-mean residual load** (derived) | Base: \(21.15 - 13.63 - 0.70 = 6.82\) TWh; Dunkelflaute: \(21.15 - 9.29 - 3.78 = 8.08\) TWh |
| **Formula** | \(\text{ResidualLoad}_t = D_t - P_t^{\mathrm{wind}} - P_t^{\mathrm{solar}}\) |
| **Source for approximation** | `report_summary.csv` (load); `generation_mix_groups_twh.csv` (wind, solar) |
| **Note** | Snapshot-level max/average/threshold-duration statistics require network time series **not in committed CSV files** |

---

## C.3 Generation Dispatch Time Series

| Item | Specification |
|---|---|
| **Figure title** | Daily generation dispatch on the lowest-wind day (Dunkelflaute–SMR) |
| **File** | `figures/fig09_worst_day_dispatch.pdf` |
| **Scenarios** | Dunkelflaute + SMR (daily totals for 2021-01-25) |
| **Source** | Daily GWh fallback values documented in `figures/captions.tex` (CCGT 591.8 GWh/day; SMR 162.0 GWh/day) |
| **Limitation** | **Not** a full 3-hourly stacked dispatch — network `generators_t.p` was unavailable when figure was built |

**Full 3-hourly stacked dispatch for all five scenarios:** **Not available as committed figures.**

---

## C.4 Nuclear Dispatch and Load-Following

| Item | Specification |
|---|---|
| **Figure title** | Nuclear generation and CO₂ effect of nuclear-enabled scenarios |
| **File** | `figures/fig07_nuclear_generation_and_co2_effect.pdf` |
| **Scenarios** | Dunkelflaute + SMR, MSR, LFR (vs Dunkelflaute without nuclear) |
| **Source files** | `generation_mix_twh.csv`; `report_summary.csv`; `co2_by_carrier_kt.csv` |
| **Nuclear generation** | SMR 2.27 TWh; MSR 1.36 TWh; LFR 1.36 TWh |
| **Implied capacity factor** (derived: gen / (capacity × 336 h)) | **~90%** for all three (2.27 TWh / (7.5 GW × 336 h) ≈ 0.90) |
| **Purpose** | Show firm nuclear output and marginal CO₂ change |

**Nuclear dispatch as fraction of capacity (time series):** **Not available in committed CSV files.**

---

## C.5 Generation Mix Comparison

| Item | Specification |
|---|---|
| **Figure title** | Generation mix across scenarios |
| **File** | `figures/fig05_generation_mix_by_scenario.pdf` |
| **Scenarios** | Base, Dunkelflaute, SMR, MSR, LFR |
| **Source** | `generation_mix_groups_twh.csv` |
| **Caveat** | Solar marked as non-interpretable for Dunkelflaute inference (`RESULTS_FINAL.md` §9) |

---

## C.6 Installed Capacity Comparison

| Item | Specification |
|---|---|
| **Figure title** | Credible capacity outcomes |
| **File** | `figures/fig06_credible_capacity_outcomes.pdf` |
| **Scenarios** | All five main scenarios |
| **Source** | `credible_capacity.csv` |
| **Variables** | CCGT (GW); nuclear (MW); excludes phantom VRE and link-battery |
| **Purpose** | Report interpretable capacity builds only |

---

## C.7 Operating Cost and Objective Comparison

| Item | Specification |
|---|---|
| **Figure title** | Dunkelflaute impact on period OPEX and CO₂ emissions |
| **File** | `figures/fig04_opex_co2_impact.pdf` |
| **Scenarios** | Base vs Dunkelflaute |
| **Source** | `report_summary.csv` |
| **Accounting** | **Period OPEX only** — not solver objective; annuitised CAPEX shown separately in `compare_scenarios.py` → `costs_breakdown.png` (not committed in `inre-comparison-v2/`) |

---

## C.8 CO₂ Emissions

| Item | Specification |
|---|---|
| **Figure title** | Nuclear generation and CO₂ effect (Panel B shows ΔCO₂ vs no-nuclear Dunkelflaute) |
| **File** | `figures/fig07_nuclear_generation_and_co2_effect.pdf` |
| **Source** | `report_summary.csv`; `co2_by_carrier_kt.csv` |
| **Values** | 1,020–1,082 ktCO₂ (PyPSA); cap 1,918 ktCO₂ |

---

## C.9 Fossil Generation Displacement

| Item | Specification |
|---|---|
| **Figure title** | Dunkelflaute operational response (wind and CCGT) |
| **File** | `figures/fig03_dunkelflaute_operational_response.pdf` |
| **Scenarios** | Base vs Dunkelflaute (fossil displacement); nuclear scenarios in `fig05` |
| **Source** | `generation_mix_groups_twh.csv` |
| **CCGT change (DF vs base)** | +0.91 TWh (+20%) |
| **Coal** | 0.323 → ~0 TWh |

**Dedicated nuclear-vs-fossil displacement figure:** Use `fig05` and `fig07`; no separate committed figure.

---

## C.10 Renewable Curtailment or Displacement

| Item | Specification |
|---|---|
| **Status** | **No committed figure** for curtailment |
| **Wind change (DF → SMR)** | 9.29 → 7.99 TWh (−1.30 TWh) | `generation_mix_groups_twh.csv` |
| **Interpretation** | Nuclear primarily displaces **CCGT** (5.46 → 5.43 TWh), not wind, in SMR scenario |

---

## C.11 Fixed-Capacity Sensitivity

| Item | Specification |
|---|---|
| **Figure title** | Fixed-capacity solar and adequacy sensitivity |
| **File** | `figures/fig08_fixed_solar_sensitivity.pdf` |
| **Scenarios** | `base-fixedcap` vs `dunkelflaute-fixedcap` |
| **Source** | `RESULTS_FINAL.md` §10 (networks gitignored) |
| **Fixed capacities** | All generator and StorageUnit capacities frozen (`extendable_carriers: []`) |
| **Key results** | Solar 0.705 → 0.203 TWh; load shedding 0 → 3.51 TWh |

---

## C.12 PyPSA-Eur and GAMSPy Comparison

| Item | Specification |
|---|---|
| **Figure title** | Cross-model directional comparison |
| **File** | `figures/fig10_pypsa_gamspy_directional_comparison.pdf` |
| **Scenarios** | Base, Dunkelflaute, nuclear scenarios (normalised % changes) |
| **Source** | `results/inre-comparison-v2/`; `gamspy-de/results/*/summary.yaml` |
| **Purpose** | Qualitative comparison only — **not calibrated to the same absolute scale** |
| **Disclaimer** | Stated in `figures/captions.tex`: GAMSPy uses template inputs; CO₂ saturates at cap in GAMSPy |

---

# Appendix Verification Notes

## Verified directly from project files

- Software stack and configuration chain (`pixi.toml`, `pixi.lock`, `config/inre/config.base.yaml`, `config/inre/scenarios.yaml`)
- Temporal and spatial resolution (112 snapshots, 336 h, 10 clusters, DE-only)
- Dunkelflaute profile parameters and transformation equations (`data/inre/dunkelflaute.yaml`, `apply_dunkelflaute.py`, factor CSV statistics)
- Nuclear technology costs and site mapping (`custom_costs_nuclear.csv`, `custom_powerplants_nuclear_DE.csv`, `add_nuclear_technologies.py`)
- CO₂ cap derivation and period emissions (`prepare_network.py`, `report_summary.csv`)
- Main scenario KPIs, generation mix, credible capacity, CO₂ by carrier (`results/inre-comparison-v2/`)
- Fixed-capacity sensitivity headline results (`RESULTS_FINAL.md`)
- GAMSPy formulation and scenario summaries (`gamspy-de/src/build_model.py`, `gamspy-de/results/*/summary.yaml`)
- Committed figures and captions (`figures/`, `figures/captions.tex`)

## Derived during post-processing

| Quantity | Formula / method | Source script |
|---|---|---|
| Period CO₂ cap | \(50 \times 10^6 \times N_y\) kt | `prepare_network.py`; \(N_y = 336/8760\) |
| Period-scaled CAPEX | Annuitised CAPEX × \(N_y\) | `compare_scenarios.py` |
| Operational LCOE | Period OPEX / load | `compare_scenarios.py` |
| Wind reduction under stress | \((9.29 - 13.63)/13.63\) | `generation_mix_groups_twh.csv` |
| Nuclear capacity factor | Gen (MWh) / (\(P \times 336\) h) | `generation_mix_twh.csv`; `credible_capacity.csv` |
| Approximate mean residual load | Load − wind − solar (period totals) | `report_summary.csv`; `generation_mix_groups_twh.csv` |
| Annuity factors | \(r / (1 - (1+r)^{-n})\) | `scripts/add_electricity.py` |

## Missing or inconsistent information

| Item | Value in report / methodology doc | Value in model files | Recommended correction |
|---|---:|---:|---|
| CO₂ annual cap | 500 Mt/y in `INRE-METHODOLOGY.md` §4.5.7 | **50 Mt/y** in `config/inre/config.base.yaml` | Use **50 Mt/y** (1,918 kt/period) |
| Dunkelflaute window | 2021-01-28 – 2021-02-03; `auto_worst_days: 5` in methodology | **2021-01-25 – 2021-02-07**; `auto_worst_days: null` in `dunkelflaute.yaml` | Use **profile-based fixed 14-day window** per Phase 2 config |
| Marginal cost formula | VOM + fuel/η + FOM contribution (methodology) | **VOM + fuel/η only** (`process_cost_data.py`) | Use code equation in Appendix B |
| GAMSPy CO₂ emissions (absolute) | ~1,918 kt (saturated) in `RESULTS_FINAL.md` | Summary YAMLs give objectives only, not emissions totals | Export GAMSPy emissions to CSV or cite as qualitative |
| Shadow price of CO₂ cap | — | **Not exported** | Re-solve with fixed CO₂ or extract duals |
| Hydro / PHS capacity and generation | — | **Not in KPI tables** | Extend `compare_scenarios.py` extraction |
| Storage charge/discharge, curtailment, imports | — | **Not in committed CSVs** | Post-process from `*.nc` networks |
| Snapshot-level residual load maxima | — | **Not in committed CSVs** | Plot from networks or export time series |
| Solver logs | — | **No log files in repository** | Archive Snakemake logs with results |
| fig09 dispatch | Caption notes daily fallback | Full 3-hourly data in gitignored `.nc` | Regenerate from `generators_t.p` when networks available |

### Recommendations

**Essential appendix tables for final submission:** A.2 (resolution), A.3 (scenarios + Dunkelflaute method), A.5 (nuclear assumptions), A.6 (site mapping), A.8 (CO₂ cap), A.12 (main results), A.14 (cleaned artefacts), B.6 (derating equation), B.16 (model comparison).

**Most useful figures:** fig02 (derating input), fig03 (wind/CCGT response), fig04 (OPEX/CO₂), fig06 (credible capacity), fig07 (nuclear/CO₂), fig08 (fixed-cap sensitivity), fig10 (GAMSPy directional).

**Do not rely on for policy conclusions without caveats:** fig05 solar panels (artefact), fig06 excluded phantom VRE, any capacity from `capacity_gw.csv` without cleaning, fig09 (daily fallback only), GAMSPy absolute cost/emission levels, LCOA for nuclear scenarios (|ΔCO₂| < 10 kt), fixed-cap cost figures (~35,450 M EUR).

---

*Generated: 2026-07-10. Source: project configuration, input data, result files, and `RESULTS_FINAL.md`.*
