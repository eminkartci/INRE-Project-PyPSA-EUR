# INRE Project — Progress Report, Assumptions, Results & Next Steps

**Date:** 22 June 2026  
**Author context:** Energy systems modelling study on the Germany electricity grid using PyPSA-Eur with an INRE (Integrated Nuclear & Renewable Energy) extension layer.  
**Status:** Phase 2 pipeline **implemented and executed** — all five scenarios solved successfully on 22 June 2026.

---

## Executive Summary

This project builds a custom modelling layer on top of [PyPSA-Eur](https://github.com/PyPSA/pypsa-eur) to answer one question:

> **During a Dunkelflaute (extended low wind/solar) event in winter, can new nuclear technologies (SMR, MSR, LFR) cost-effectively complement a high-renewable German electricity system?**

**What has been completed:**

1. A full Snakemake-integrated INRE workflow (configs, data, Python scripts, rules).
2. A five-scenario matrix: base reference, Dunkelflaute stress, and three Dunkelflaute + nuclear technology variants.
3. Successful execution of all five linear programming (LP) optimisations using the HiGHS solver.
4. A cross-scenario comparison script producing KPI tables (`results/inre-comparison/`).

**Headline preliminary findings:**

| Finding | Engineering interpretation |
|---------|---------------------------|
| Dunkelflaute stress raises operating cost by **+69 M EUR (+25.6%)** over the 2-week window | VRE shortfall is met primarily by **CCGT (+247%)** and slightly more **coal/lignite**, not by storage or nuclear |
| Wind capacity factor drops **~19%**, solar **~37%** under stress | The stress model works as intended; worst days were auto-detected inside the simulation window |
| New nuclear builds **~0 MW** (numerical dust only: 0.0001–0.002 MW total) | At placeholder 2050 costs (~18–22 kEUR/MW/year annuitised CAPEX) and a **2-week optimisation window**, nuclear cannot recover investment; gas is cheaper |
| CO₂ limit is **not binding** (3.3 Mt emitted vs 19.2 Mt allowed over 2 weeks) | The 500 Mt/year cap is a loose placeholder; coal/lignite remain in the dispatch stack |
| Average load **~63 GW**, peak **~76 GW** | Consistent with a winter week in a 2050-horizon, electricity-only DE model |

**Critical caveat:** Results are **preliminary and exploratory**. Many inputs are explicit placeholders (`INRE assumption`). The 2-week / 3-hour snapshot design prioritises fast iteration over annual energy balance or investment realism.

---

## Table of Contents

1. [Project Objective & Scope](#1-project-objective--scope)
2. [What Was Built — Technical Inventory](#2-what-was-built--technical-inventory)
3. [Modelling Methodology & Calculation Logic](#3-modelling-methodology--calculation-logic)
4. [Complete List of Manual Assumptions](#4-complete-list-of-manual-assumptions)
5. [Input Data Sources vs Assumptions](#5-input-data-sources-vs-assumptions)
6. [Scenario Matrix & Cross-Scenario Comparison](#6-scenario-matrix--cross-scenario-comparison)
7. [Preliminary Results — Quantitative Analysis](#7-preliminary-results--quantitative-analysis)
8. [Energy Engineering Interpretation](#8-energy-engineering-interpretation)
9. [Known Limitations & Model Artefacts](#9-known-limitations--model-artefacts)
10. [How to Improve & Change Assumptions](#10-how-to-improve--change-assumptions)
11. [Recommended Next Steps (Prioritised)](#11-recommended-next-steps-prioritised)
12. [Appendix: File Reference & Commands](#12-appendix-file-reference--commands)

---

## 1. Project Objective & Scope

### 1.1 Research question

Germany has phased out commercial nuclear generation (last plants shut down in April 2023). As the share of wind and solar grows, **Dunkelflaute** periods — multi-day episodes of simultaneously low wind and solar output, typically in winter — create reliability and adequacy challenges.

The INRE project uses PyPSA-Eur to simulate:

- A **2050-technology-cost, 2024-renewable-capacity** vision of the German grid.
- A **deliberate VRE availability stress** representing Dunkelflaute.
- Optional **new build** of advanced nuclear at former reactor sites (SMR, MSR, LFR).

### 1.2 Scope boundaries (what the model does *not* include)

| Excluded | Implication |
|----------|-------------|
| Sector coupling (heat, transport, industry) | Electricity-only; no heat pumps, EV load, or H₂ demand from other sectors |
| Cross-border trading detail | Germany-only (`countries: [DE]`); neighbouring countries not modelled |
| Existing nuclear | Correctly zero — all German NPPs filtered out / shut down |
| Unit commitment / start-up costs | LP dispatch with ramp limits only; no binary on/off |
| Perfect foresight over full year | Single 2-week window; investment decisions based on partial year exposure |

---

## 2. What Was Built — Technical Inventory

### 2.1 Repository modifications

The INRE layer was added **without forking** PyPSA-Eur core logic. Changes:

| Component | Path | Purpose |
|-----------|------|---------|
| Base config | `config/inre/config.base.yaml` | Germany, Jan 2021 window, 10 clusters, 3h resolution |
| Multi-scenario driver | `config/inre/config.scenarios.yaml` | Runs all scenarios with shared build resources |
| Scenario overrides | `config/inre/scenarios.yaml` | Per-scenario Dunkelflaute / nuclear flags |
| Phase 1 fast-dev config | `config/inre/config.phase1-fast.yaml` | March 2013, tutorial mode, smoke tests |
| Dunkelflaute parameters | `data/inre/dunkelflaute.yaml` | Stress factors, auto worst-day selection |
| Nuclear costs (placeholder) | `data/inre/custom_costs_nuclear.csv` | SMR / MSR / LFR techno-economic data |
| Candidate sites | `data/inre/custom_powerplants_nuclear_DE.csv` | 5 former NPP locations |
| Dunkelflaute script | `scripts/inre/apply_dunkelflaute.py` | VRE profile derating |
| Nuclear script | `scripts/inre/add_nuclear_technologies.py` | Extendable generators at sites |
| Orchestrator | `scripts/inre/apply_inre_network.py` | Snakemake entry point |
| Comparison tool | `scripts/inre/compare_scenarios.py` | KPI tables and charts |
| Snakemake rules | `rules/inre.smk` | `apply_inre_network` rule; solve input routing |
| Snakefile include | `Snakefile` line 86 | `include: "rules/inre.smk"` |
| Solve routing patch | `rules/solve_electricity.smk` | `_input_solve_network` uses INRE network when needed |
| Documentation | `INRE-README.md` | Operational reference |

### 2.2 Workflow architecture

```
retrieve → build base network → cluster (10 nodes) → renewable profiles
    → add_electricity → prepare_network
        → [INRE: apply_inre_network]   ← only for Dunkelflaute / nuclear scenarios
            → solve_network (HiGHS LP)
                → results/<scenario>/networks/*.nc
                    → compare_scenarios.py
```

The INRE step sits **between** `prepare_network` and `solve_network`. For the `base` scenario (no Dunkelflaute, no nuclear), the prepared network is passed directly to the solver.

### 2.3 Execution record (22 June 2026)

Command executed (from terminal log):

```bash
snakemake -call solve_elec_networks \
  --configfile config/inre/config.base.yaml \
  --configfile config/inre/config.scenarios.yaml
```

| Metric | Value |
|--------|-------|
| Scenarios solved | 5 / 5 |
| Solver | HiGHS (interior-point) |
| Base case solve time | ~306 s (~5.1 min) |
| Dunkelflaute scenarios | ~375–382 s (~6.2–6.4 min) |
| Peak memory | ~1.9 GB |
| Snapshots per scenario | 112 (14 days × 8 blocks/day at 3h resolution) |
| Optimality | HiGHS reported "Unknown" status due to small primal-dual gap (~3×10⁻⁵ relative); solutions parsed successfully |

Output networks:

```
results/base/networks/base_s_10_elec_.nc
results/dunkelflaute/networks/base_s_10_elec_.nc
results/dunkelflaute-smr/networks/base_s_10_elec_.nc
results/dunkelflaute-msr/networks/base_s_10_elec_.nc
results/dunkelflaute-lfr/networks/base_s_10_elec_.nc
```

Comparison table written to `results/inre-comparison/comparison_table.csv`.

---

## 3. Modelling Methodology & Calculation Logic

### 3.1 PyPSA-Eur base model

PyPSA-Eur constructs a **linear optimal power flow / capacity expansion** model:

- **Sets:** buses (10 clustered regions), generators (~5,876 units), lines (22), loads, storage (battery, H₂).
- **Decision variables:** generator dispatch `p[g,t]`, extendable capacity `p_nom[g]`, storage operation, line flows.
- **Objective:** minimise total system cost = annuitised CAPEX + fixed O&M + variable O&M + fuel costs, weighted by snapshot duration.
- **Constraints:** nodal power balance (Kirchhoff), generator ramp limits, line capacities, CO₂ cap, renewable potentials.

The model is a **single-year LP** with snapshot weighting to represent annual costs from a subset of timesteps.

### 3.2 Spatial clustering — 10 nodes

Germany's transmission network is aggregated to **10 zones** using PyPSA-Eur's `cluster_network` rule. Each zone has:

- Aggregated demand (ENTSO-E load, distributed to buses).
- Renewable generators (potentials from Atlite weather × installable capacity).
- Conventional plants from powerplantmatching, mapped to nearest bus.
- Inter-zonal AC lines (22 remaining after clustering).

**Engineering note:** 10 clusters capture north–south wind/solar heterogeneity at coarse resolution. Dunkelflaute is applied **nationally** (same derating factor at all nodes simultaneously), which is conservative for a spatially correlated winter anticyclone but ignores regional differences in cloud cover.

### 3.3 Temporal setup — why 2 weeks at 3-hour resolution?

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `snapshots.start` | 2021-01-25 | Start of documented Jan 2021 cold/Dunkelflaute episode |
| `snapshots.end` | 2021-02-08 | 14-day window (end exclusive in PyPSA → 13 full days + partial) |
| `resolution_elec` | `3h` | 112 snapshots; target ≤ 15 min solve per scenario |
| Weather cutout | `europe-2021-sarah3-era5` | ERA5 + SARAH-3 satellite irradiance |

**Snapshot weighting:** Each snapshot represents 3 hours. PyPSA assigns `snapshot_weightings.objective` so that costs integrated over all snapshots correspond to an **annualised** objective. For a 2-week window:

$$\text{period fraction of year} = \frac{\sum w_t}{8760} \approx 0.0384 \;(3.84\%)$$

Therefore, the reported `objective` (~270 M EUR for base) is the **cost attributed to this 2-week slice**, not the full annual system cost. A rough annualisation (base case):

$$\text{Annualised OPEX} \approx \frac{269.7 \text{ M EUR}}{0.0384} \approx 7.0 \text{ bn EUR/year}$$

This annualisation is **not rigorous** for investment decisions because capacity expansion sees only 2 weeks of operational patterns.

### 3.4 Dunkelflaute implementation logic

Implemented in `scripts/inre/apply_dunkelflaute.py`. Operates on **`generators_t.p_max_pu`** (per-unit availability) before the solve.

**Step 1 — Identify stress window:**

Two modes (configured in `data/inre/dunkelflaute.yaml`):

| Mode | Config key | Behaviour |
|------|------------|-----------|
| Auto worst days | `auto_worst_days: 5` | Compute daily national VRE score; pick 5 lowest days |
| Fixed calendar | `time_start` / `time_end` | Use explicit date range |

**VRE score formula** (lower = worse Dunkelflaute):

For each snapshot $t$ and day $d$:

$$\text{score}_d = \frac{1}{|T_d|} \sum_{t \in T_d} \left[ \sum_{g \in \text{wind}} p\_max\_pu_{g,t} \cdot p\_nom_g + \sum_{g \in \text{solar}} p\_max\_pu_{g,t} \cdot p\_nom_g \right]$$

Capacity-weighted average availability. The 5 days with the lowest score are selected.

**Auto-selected worst days (this run):**

| Date | Notes |
|------|-------|
| 2021-01-25 | First day of simulation window; deep winter, low solar |
| 2021-01-28 | Mid-period low VRE |
| 2021-01-30 | Weekend low wind |
| 2021-01-31 | Continuation |
| 2021-02-02 | Late-window stress day |

**Step 2 — Apply derating factors:**

Inside the stress mask:

$$p\_max\_pu_{g,t} \leftarrow p\_max\_pu_{g,t} \times f\_\text{carrier}$$

| Carrier group | Factor | Retained availability |
|---------------|--------|----------------------|
| Wind (onshore, offshore AC/DC/float) | 0.15 | 15% |
| Solar (fixed, tracking) | 0.10 | 10% |

**Step 3 — Edge ramping:**

Over `ramp_hours: 6` snapshots (18 hours at 3h resolution), availability linearly ramps between full and stressed values at the window boundaries. This avoids a discontinuous step change that would create artificial ramping infeasibilities.

**Physical interpretation:** This is a **scenario stress test**, not a meteorological reanalysis product. Factors 0.15/0.10 represent an extreme but plausible simultaneous collapse of wind and solar capacity factors — consistent with a stagnant high-pressure system over Central Europe in January.

### 3.5 Nuclear technology addition logic

Implemented in `scripts/inre/add_nuclear_technologies.py`.

For each row in `custom_powerplants_nuclear_DE.csv` matching the scenario carrier:

1. Find **nearest network bus** by Euclidean distance in lat/lon.
2. Add an **extendable generator** with:
   - `p_nom = 0`, `p_nom_extendable = True`
   - `p_nom_max = 1500 MW` (config default)
   - Costs from processed `costs_2050_processed.csv` (annuitised from `custom_costs_nuclear.csv`)
   - `p_max_pu = 0.9` (90% availability factor)
   - `p_min_pu = 0.3` (30% minimum stable load)
   - `ramp_limit_up/down = 0.5` p.u./hour

The optimiser then decides `p_nom_opt` balancing CAPEX against dispatch savings over the snapshot window.

**Annuitised capital cost example (SMR):**

From processed costs: `capital_cost = 18,335 EUR/MW` (per MW of installed capacity, annualised over 60-year lifetime at 2050 discount rate from technology-data).

With marginal cost ~12 EUR/MWh (fuel + VOM + FOM), nuclear is **cheap to operate** but **expensive to build** — classic baseload economics.

### 3.6 CO₂ constraint

```yaml
electricity:
  co2limit_enable: true
  co2limit: 500.e+6   # tonnes CO₂ per year
```

PyPSA scales this to the snapshot period:

$$\text{CO2Limit}_\text{period} = 500 \times 10^6 \times \frac{336}{8760} \approx 19.18 \text{ Mt}$$

Actual emissions (2-week window):

| Scenario | CO₂ (Mt) | Limit (Mt) | Utilisation |
|----------|----------|------------|-------------|
| base | 3.28 | 19.18 | 17% |
| dunkelflaute | 3.85 | 19.18 | 20% |
| dunkelflaute-smr | 3.85 | 19.18 | 20% |

The constraint is **non-binding**. Coal and lignite dispatch freely up to their installed capacity. This is a major policy assumption gap for a 2050 decarbonisation study.

### 3.7 Key performance indicators (KPIs)

| KPI | Calculation in PyPSA |
|-----|---------------------|
| Operating cost (OPEX) | `n.statistics.opex()` — variable + fixed O&M over weighted snapshots |
| Investment (CAPEX) | `n.statistics.capex()` — annuitised capital for optimal capacity |
| Total objective | `n.objective` — LP objective value |
| Generation by carrier | `n.generators_t.p` × snapshot weights, summed |
| Optimal capacity | `n.generators.p_nom_opt` for extendable units |
| CO₂ emissions | $\sum_{g,t} p_{g,t} \cdot w_t \cdot \text{co2\_emissions}_g$ |

---

## 4. Complete List of Manual Assumptions

Every assumption below is either explicitly tagged `INRE assumption` in data files or implied by config choices. **None should be used for publication without review.**

### 4.1 Geographic & temporal scope

| # | Assumption | Value | Source / tag | Sensitivity |
|---|------------|-------|--------------|-------------|
| T1 | Modelled country | Germany only (`DE`) | Config choice | High — excludes imports |
| T2 | Spatial resolution | 10 clusters | Config choice | Medium |
| T3 | Simulation window | 2021-01-25 → 2021-02-08 | Historical Dunkelflaute event | High |
| T4 | Temporal resolution | 3 hours (112 snapshots) | Runtime constraint | Medium–High |
| T5 | Planning horizon for costs | 2050 | PyPSA technology-data | High |
| T6 | Renewable fleet year | 2024 capacities | powerplantmatching | Medium |

### 4.2 Dunkelflaute stress parameters

| # | Assumption | Value | Source / tag | Sensitivity |
|---|------------|-------|--------------|-------------|
| D1 | Wind availability during stress | 15% of normal (`wind_factor: 0.15`) | INRE manual | **Very high** |
| D2 | Solar availability during stress | 10% of normal (`solar_factor: 0.10`) | INRE manual | **Very high** |
| D3 | Stress duration | 5 auto-selected worst days | INRE manual | High |
| D4 | Edge ramp | 6 snapshots (18 h) | INRE manual | Low–Medium |
| D5 | Spatial correlation | Uniform national derating | INRE simplification | Medium |
| D6 | Fallback fixed window | 2021-01-28 → 2021-02-03 | Not used (auto mode active) | — |

### 4.3 Nuclear technology placeholders

| # | Parameter | SMR | MSR | LFR | Unit | Tag |
|---|-----------|-----|-----|-----|------|-----|
| N1 | Investment cost | 4500 | 5200 | 4800 | EUR/kW | INRE assumption |
| N2 | Fixed O&M | 3.5 | 4.0 | 3.8 | %/year | INRE assumption |
| N3 | Variable O&M | 3.0 | 3.5 | 3.2 | EUR/MWh | INRE assumption |
| N4 | Fuel cost | 3.0 | 2.5 | 2.8 | EUR/MWh_th | INRE uranium estimate |
| N5 | Electrical efficiency | 0.33 | 0.35 | 0.34 | p.u. | INRE assumption |
| N6 | Lifetime | 60 | 50 | 55 | years | INRE assumption |
| N7 | CO₂ intensity | 0 | 0 | 0 | t/MWh | INRE assumption |
| N8 | Availability (`p_max_pu`) | 0.90 | 0.90 | 0.90 | p.u. | Script default |
| N9 | Minimum load (`p_min_pu`) | 0.30 | 0.30 | 0.30 | p.u. | Script default |
| N10 | Ramp rate | 0.50 | 0.50 | 0.50 | p.u./hour | Script default |
| N11 | Max build per site | 1500 | 1500 | 1500 | MW | Config default |
| N12 | National build cap | None | None | None | GW | **Not implemented** |
| N13 | Candidate sites | 5 former NPP locations | Manual CSV | Medium |
| N14 | Commissioning year | 2045 (`DateIn`) | Manual CSV | Low (not enforced in LP) |

**Processed annuitised costs (from solver input):**

| Carrier | Capital cost (EUR/MW/a) | Marginal cost (EUR/MWh) |
|---------|-------------------------|-------------------------|
| nuclear-smr | 18,335 | 12.10 |
| nuclear-msr | 22,430 | 10.64 |
| nuclear-lfr | 20,204 | 11.44 |
| CCGT (reference) | 4,849 | 43.27 |
| onwind (reference) | 4,557 | 0.01 |
| solar (reference) | 1,415 | 0.01 |

### 4.4 Policy & fleet assumptions

| # | Assumption | Value | Implication |
|---|------------|-------|-------------|
| P1 | CO₂ cap | 500 Mt/year | Non-binding; coal/lignite remain economic |
| P2 | Existing nuclear | Zero capacity | Correct for post-2023 Germany |
| P3 | Coal/lignite retirement | Filter keeps plants with `DateOut > 2025` | **~40 GW coal still in fleet** |
| P4 | Extendable technologies | VRE, OCGT, CCGT, battery, H₂ | Gas and storage can expand |
| P5 | Sector coupling | Disabled | No flexibility from heat/transport |
| P6 | Dynamic line rating | Disabled | Fixed thermal limits |
| P7 | Offshore depth limits | Disabled (`max_depth: false`) | Unrestricted offshore siting |

### 4.5 Solver & numerical

| # | Assumption | Value |
|---|------------|-------|
| S1 | Solver | HiGHS (free LP) |
| S2 | Optimality tolerance | Default; P-D gap ~3×10⁻⁵ triggers "Unknown" status |
| S3 | Foresight | Perfect within 2-week window |
| S4 | Storage | Battery/H₂ nearly unused (see results) |

---

## 5. Input Data Sources vs Assumptions

| Data category | Source | Free? | INRE override? |
|---------------|--------|-------|----------------|
| Transmission grid topology | OpenStreetMap (PyPSA archive) | Yes | No |
| Power plant database | powerplantmatching | Yes | Filter for DE, retirement dates |
| Renewable capacities (2024) | powerplantmatching estimate | Yes | No |
| Electricity demand | ENTSO-E Transparency Platform | Yes | No |
| Weather (wind speed, irradiance) | ERA5 + SARAH-3 via Atlite | Yes | Dunkelflaute derating applied |
| Technology costs (2050) | PyPSA technology-data | Yes | Nuclear costs overridden |
| Nuclear availability (legacy) | IAEA PRIS | Yes | Not used (no existing nuclear) |
| Nuclear new-build costs | **Manual placeholder** | — | **Yes — must replace** |
| Dunkelflaute severity | **Manual scenario parameter** | — | **Yes — calibrate to events** |
| Reactor siting | **Manual CSV at former sites** | — | **Yes — policy-driven** |

---

## 6. Scenario Matrix & Cross-Scenario Comparison

This section is the **master reference** for what each scenario changes relative to the others: config overrides, data files, pipeline steps, active assumptions, and measured outcomes.

### 6.1 Scenario overview

| Scenario ID | Run name | Results folder | Purpose |
|-------------|----------|----------------|---------|
| `base` | `inre-de-base` | `results/base/` | Reference: normal Jan 2021 VRE profiles, no stress, no new nuclear |
| `dunkelflaute` | `inre-de-dunkelflaute` | `results/dunkelflaute/` | Dunkelflaute stress only — quantify adequacy gap |
| `dunkelflaute-smr` | `inre-de-df-smr` | `results/dunkelflaute-smr/` | Stress + Small Modular Reactor as extendable option |
| `dunkelflaute-msr` | `inre-de-df-msr` | `results/dunkelflaute-msr/` | Stress + Molten Salt Reactor as extendable option |
| `dunkelflaute-lfr` | `inre-de-df-lfr` | `results/dunkelflaute-lfr/` | Stress + Lead-cooled Fast Reactor as extendable option |

All scenarios inherit from `config/inre/config.base.yaml` + `config/inre/config.scenarios.yaml`, with per-scenario overrides in `config/inre/scenarios.yaml`.

Shared build resources (`shared_resources.policy: true`) mean grid topology, clustering, weather cutout, and the prepared network are built **once** and reused. Only the INRE modification step (`apply_inre_network`) and the LP solve differ per scenario.

---

### 6.2 Shared baseline — identical across all five scenarios

These settings are **not changed** between scenarios. They form the common modelling foundation.

| Category | Parameter | Value | Config / data source |
|----------|-----------|-------|----------------------|
| Geography | Country | Germany only (`DE`) | `config.base.yaml` |
| Spatial | Clusters | 10 nodes | `scenario.clusters: [10]` |
| Temporal | Snapshot window | 2021-01-25 → 2021-02-08 (14 days) | `snapshots` |
| Temporal | Resolution | 3-hour (112 snapshots) | `clustering.temporal.resolution_elec: 3h` |
| Weather | Cutout | `europe-2021-sarah3-era5` | `atlite.default_cutout` |
| Costs | Planning year | 2050 | `costs.year: 2050` |
| Fleet | Renewable capacity year | 2024 (powerplantmatching) | `estimate_renewable_capacities.year` |
| Fleet | Existing nuclear | **0 MW** (all shut down) | `powerplants_filter` |
| Fleet | Coal + lignite | ~40 GW (plants with `DateOut > 2025`) | `powerplants_filter` |
| Policy | CO₂ cap | 500 Mt/year (non-binding in results) | `electricity.co2limit: 500.e+6` |
| Extendable | Generators | solar, solar-hsat, onwind, offwind-*, OCGT, CCGT | `extendable_carriers.Generator` |
| Extendable | Storage | battery, H₂ store, H₂ pipeline | `extendable_carriers` |
| Solver | Engine | HiGHS (free LP) | `solving.solver.name: highs` |
| INRE | Master switch | `inre.enabled: true` | All scenarios |

---

### 6.3 Configuration delta matrix — what changes per scenario

Legend: ✅ = active / added · — = same as base · ❌ = off / not present

| Setting | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|---------|:----:|:------------:|:----------------:|:----------------:|:----------------:|
| **Dunkelflaute stress** | ❌ | ✅ | ✅ | ✅ | ✅ |
| `inre.dunkelflaute.enabled` | `false` | `true` | `true` | `true` | `true` |
| Dunkelflaute config file | — | `data/inre/dunkelflaute.yaml` | same | same | same |
| Wind derating factor | — | **0.15** (15%) | same | same | same |
| Solar derating factor | — | **0.10** (10%) | same | same | same |
| Stress day selection | — | `auto_worst_days: 5` | same | same | same |
| Edge ramp | — | `ramp_hours: 6` | same | same | same |
| **New nuclear build** | ❌ | ❌ | ✅ SMR | ✅ MSR | ✅ LFR |
| `inre.nuclear.extendable_carriers` | `[]` | `[]` | `[nuclear-smr]` | `[nuclear-msr]` | `[nuclear-lfr]` |
| Nuclear sites file | — | — | `custom_powerplants_nuclear_DE.csv` | same | same |
| Max build per site | — | — | 1500 MW | 1500 MW | 1500 MW |
| `costs.custom_cost_fn` (explicit) | inherited | inherited | ✅ explicit | ✅ explicit | ✅ explicit |
| `pypsa_eur.Generator` carrier list | default | default | + `nuclear-smr` | + `nuclear-msr` | + `nuclear-lfr` |
| **Pipeline: `apply_inre_network`** | Skipped (copy) | Dunkelflaute only | Dunkelflaute + nuclear | Dunkelflaute + nuclear | Dunkelflaute + nuclear |
| **Output network suffix** | `_elec_.nc` | `_elec_.nc` | `_elec_.nc` | `_elec_.nc` | `_elec_.nc` |
| INRE intermediate file | — | `*_inre.nc` | `*_inre.nc` | `*_inre.nc` | `*_inre.nc` |

---

### 6.4 Scenario-by-scenario — what was added or changed vs `base`

#### 6.4.1 `base` (reference)

| Aspect | Detail |
|--------|--------|
| **Changes vs PyPSA-Eur default** | Germany-only filter, Jan 2021 window, 10 clusters, 3h resolution, INRE config block present but inactive |
| **INRE modifications** | None — prepared network copied directly to solver |
| **Added generators** | None |
| **Modified time series** | None — raw Atlite VRE profiles |
| **Active INRE assumptions** | T1–T6, P1–P7, S1–S4 only (see Section 4) |
| **Purpose** | Baseline dispatch and cost under normal winter weather |

#### 6.4.2 `dunkelflaute` (+1 change vs base)

| Aspect | Detail |
|--------|--------|
| **Added vs base** | Dunkelflaute VRE derating via `apply_dunkelflaute.py` |
| **Modified time series** | `generators_t.p_max_pu` for all wind and solar generators on 5 worst VRE days |
| **Auto-selected stress days** | 2021-01-25, 2021-01-28, 2021-01-30, 2021-01-31, 2021-02-02 |
| **Added generators** | None |
| **Removed / disabled** | Nothing |
| **Active INRE assumptions** | Base assumptions + **D1–D6** (Dunkelflaute parameters) |
| **Script / rule invoked** | `rules/inre.smk` → `apply_inre_network` → `apply_dunkelflaute.py` |
| **Purpose** | Isolate the cost and dispatch impact of a Dunkelflaute event without nuclear |

#### 6.4.3 `dunkelflaute-smr` (+2 changes vs base)

| Aspect | Detail |
|--------|--------|
| **Added vs base** | (1) Dunkelflaute derating — same as `dunkelflaute`; (2) five extendable SMR generators |
| **Added generators** | 5 × `nuclear-smr` at former NPP sites (Grohnde, Brokdorf, Isar, Emsland, Neckarwestheim) |
| **Added carrier** | `nuclear-smr` registered in `pypsa_eur.Generator` and `custom_costs_nuclear.csv` |
| **Generator parameters** | `p_nom_extendable=True`, `p_nom_max=1500 MW`, `p_max_pu=0.9`, `p_min_pu=0.3`, ramp=0.5 p.u./h |
| **Cost assumptions used** | Investment 4500 EUR/kW, FOM 3.5%/a, VOM 3 EUR/MWh, fuel 3 EUR/MWh_th, η=0.33, lifetime 60 y |
| **Active INRE assumptions** | D1–D6 + **N1–N14 (SMR column)** |
| **Script / rule invoked** | `apply_dunkelflaute.py` then `add_nuclear_technologies.py` |
| **Purpose** | Test whether SMR can economically cover the Dunkelflaute gap |

#### 6.4.4 `dunkelflaute-msr` (+2 changes vs base)

| Aspect | Detail |
|--------|--------|
| **Added vs base** | (1) Dunkelflaute derating; (2) three extendable MSR generators |
| **Added generators** | 3 × `nuclear-msr` at Grohnde, Brokdorf, Isar |
| **Added carrier** | `nuclear-msr` |
| **Cost assumptions used** | Investment 5200 EUR/kW, FOM 4.0%/a, VOM 3.5 EUR/MWh, fuel 2.5 EUR/MWh_th, η=0.35, lifetime 50 y |
| **Annuitised CAPEX** | 22,430 EUR/MW/a (highest of three nuclear options) |
| **Marginal cost** | 10.64 EUR/MWh (lowest operating cost of three) |
| **Active INRE assumptions** | D1–D6 + **N1–N14 (MSR column)** |
| **Purpose** | Test molten salt reactor under same Dunkelflaute stress |

#### 6.4.5 `dunkelflaute-lfr` (+2 changes vs base)

| Aspect | Detail |
|--------|--------|
| **Added vs base** | (1) Dunkelflaute derating; (2) three extendable LFR generators |
| **Added generators** | 3 × `nuclear-lfr` at Grohnde, Brokdorf, Emsland |
| **Added carrier** | `nuclear-lfr` |
| **Cost assumptions used** | Investment 4800 EUR/kW, FOM 3.8%/a, VOM 3.2 EUR/MWh, fuel 2.8 EUR/MWh_th, η=0.34, lifetime 55 y |
| **Annuitised CAPEX** | 20,204 EUR/MW/a |
| **Marginal cost** | 11.44 EUR/MWh |
| **Active INRE assumptions** | D1–D6 + **N1–N14 (LFR column)** |
| **Purpose** | Test lead-cooled fast reactor under same Dunkelflaute stress |

---

### 6.5 Nuclear candidate sites added per scenario

Rows from `data/inre/custom_powerplants_nuclear_DE.csv`. Only sites matching the scenario carrier are instantiated.

| Site (former NPP) | Lat | Lon | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|-------------------|-----|-----|:----------------:|:----------------:|:----------------:|
| Grohnde | 51.906 | 9.401 | ✅ SMR | ✅ MSR | ✅ LFR |
| Brokdorf | 53.851 | 9.345 | ✅ SMR | ✅ MSR | ✅ LFR |
| Isar | 48.617 | 12.293 | ✅ SMR | ✅ MSR | ❌ |
| Emsland | 52.471 | 7.321 | ✅ SMR | ❌ | ✅ LFR |
| Neckarwestheim | 49.040 | 9.175 | ✅ SMR | ❌ | ❌ |
| **Total candidate generators** | | | **5** | **3** | **3** |
| **Max theoretical build** | | | 7.5 GW | 4.5 GW | 4.5 GW |

Each generator is mapped to the nearest PyPSA bus via Euclidean distance in geographic coordinates.

---

### 6.6 Assumptions active per scenario

Which assumption groups from Section 4 apply to each scenario:

| Assumption group | ID range | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|------------------|----------|:----:|:------------:|:----------------:|:----------------:|:----------------:|
| Geographic & temporal scope | T1–T6 | ✅ | ✅ | ✅ | ✅ | ✅ |
| Dunkelflaute stress | D1–D6 | ❌ | ✅ | ✅ | ✅ | ✅ |
| Nuclear SMR economics | N1–N14 (SMR) | ❌ | ❌ | ✅ | ❌ | ❌ |
| Nuclear MSR economics | N1–N14 (MSR) | ❌ | ❌ | ❌ | ✅ | ❌ |
| Nuclear LFR economics | N1–N14 (LFR) | ❌ | ❌ | ❌ | ❌ | ✅ |
| Policy & fleet | P1–P7 | ✅ | ✅ | ✅ | ✅ | ✅ |
| Solver & numerical | S1–S4 | ✅ | ✅ | ✅ | ✅ | ✅ |

**Nuclear technology cost comparison (assumptions only active in respective scenario):**

| Parameter | SMR | MSR | LFR | Unit |
|-----------|-----|-----|-----|------|
| Overnight investment | 4,500 | 5,200 | 4,800 | EUR/kW |
| Annuitised capital cost | 18,335 | 22,430 | 20,204 | EUR/MW/a |
| Marginal (operating) cost | 12.10 | **10.64** | 11.44 | EUR/MWh |
| Electrical efficiency | 0.33 | **0.35** | 0.34 | p.u. |
| Lifetime | **60** | 50 | 55 | years |
| Availability factor | 0.90 | 0.90 | 0.90 | p.u. |
| Min stable load | 0.30 | 0.30 | 0.30 | p.u. |
| Candidate sites | 5 | 3 | 3 | count |
| Source tag | INRE assumption | INRE assumption | INRE assumption | — |

---

### 6.7 Pipeline modification summary

What happens in the Snakemake workflow for each scenario after the shared build phase:

| Pipeline step | base | dunkelflaute | dunkelflaute-smr / msr / lfr |
|---------------|------|--------------|------------------------------|
| `prepare_network` | ✅ shared | ✅ shared | ✅ shared |
| `apply_inre_network` | ⏭ skipped (file copy) | ✅ `apply_dunkelflaute` | ✅ `apply_dunkelflaute` + `add_nuclear_technologies` |
| Input to `solve_network` | `resources/.../base_s_10_elec_.nc` | `results/.../base_s_10_elec__inre.nc` | `results/.../base_s_10_elec__inre.nc` |
| `solve_network` | ✅ | ✅ | ✅ |
| Output | `results/<scenario>/networks/base_s_10_elec_.nc` | same pattern | same pattern |

**Dunkelflaute modification detail (all stress scenarios):**

| Modified attribute | Carriers affected | Transformation |
|--------------------|-------------------|----------------|
| `generators_t.p_max_pu` | onwind, offwind-ac, offwind-dc, offwind-float | × 0.15 on 5 worst days (+ 6-snapshot ramp at edges) |
| `generators_t.p_max_pu` | solar, solar-hsat | × 0.10 on 5 worst days (+ 6-snapshot ramp at edges) |
| All other components | — | Unchanged |

**Nuclear modification detail (SMR / MSR / LFR scenarios):**

| Added attribute | Value |
|-----------------|-------|
| New `Generator` components | 3–5 per scenario (see Section 6.5) |
| `p_nom` (initial) | 0 MW |
| `p_nom_extendable` | True |
| `p_nom_max` | 1,500 MW per site |
| `capital_cost` | From processed 2050 costs (18–22 kEUR/MW/a) |
| `marginal_cost` | 10.6–12.1 EUR/MWh |
| `p_max_pu` | 0.90 (constant availability) |
| `p_min_pu` | 0.30 |
| `ramp_limit_up/down` | 0.50 per hour |

---

### 6.8 Cross-scenario findings comparison table

All values for the **2-week simulation period** (336 hours, 112 snapshots at 3h resolution).  
Δ columns show change relative to `base`. Δ vs `dunkelflaute` shows incremental effect of adding nuclear.

#### 6.8.1 System-level KPIs

| KPI | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|-----|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| **Load (TWh)** | 21.15 | 21.15 | 21.15 | 21.15 | 21.15 |
| **Generation (TWh)** | 21.21 | 21.21 | 21.21 | 21.21 | 21.21 |
| **OPEX (M EUR)** | 269.7 | 338.8 | 338.8 | 338.9 | 338.8 |
| **Objective (M EUR)** | 269.7 | 338.8 | 338.8 | 338.9 | 338.8 |
| **CAPEX (M EUR)** | 1,658.9 | 1,658.9 | 1,658.9 | 1,658.9 | 1,658.9 |
| **CO₂ (kt)** | 3,283 | 3,849 | 3,849 | 3,849 | 3,849 |
| **Solver time (s)** | ~306 | ~375–382 | ~382 | ~382 | ~379 |
| Δ OPEX vs base (M EUR) | — | **+69.1** | **+69.1** | **+69.2** | **+69.1** |
| Δ OPEX vs base (%) | — | **+25.6%** | **+25.6%** | **+25.6%** | **+25.6%** |
| Δ CO₂ vs base (kt) | — | **+566** | **+566** | **+566** | **+566** |
| Δ vs dunkelflaute (OPEX) | — | — | −0.001 M EUR | +0.019 M EUR | +0.007 M EUR |

#### 6.8.2 Generation mix (TWh, 2-week period)

| Carrier | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr | Δ base→dunkelflaute |
|---------|-----:|-------------:|-----------------:|-----------------:|-----------------:|--------------------:|
| CCGT | 0.34 | 1.18 | 1.18 | 1.18 | 1.18 | **+0.84 (+247%)** |
| Coal + lignite | 8.74 | 9.61 | 9.61 | 9.61 | 9.61 | +0.87 (+10%) |
| Wind (all) | 8.86 | 7.21 | 7.21 | 7.21 | 7.21 | −1.65 (−19%) |
| Solar (all) | 0.70 | 0.44 | 0.44 | 0.44 | 0.44 | −0.26 (−37%) |
| Biomass | 6.15 | 6.15 | 6.15 | 6.15 | 6.15 | ~0 |
| OCGT | 0.0003 | 0.0002 | 0.0001 | 0.0009 | 0.0004 | ~0 |
| SMR | — | — | ~0 | — | — | — |
| MSR | — | — | — | ~0 | — | — |
| LFR | — | — | — | — | ~0 | — |

#### 6.8.3 VRE capacity factors (2-week average)

| Carrier | base | dunkelflaute | All stress + nuclear scenarios | Δ base→stress |
|---------|-----:|-------------:|:--------------------------------:|--------------:|
| Onshore wind | 9.3% | 7.5% | 7.5% (unchanged) | −18.7% |
| Offshore wind (AC) | 17.8% | 14.5% | 14.5% (unchanged) | −18.3% |
| Solar PV | 1.4% | 0.9% | 0.9% (unchanged) | −37.0% |

VRE capacity factors are identical across all stress scenarios because Dunkelflaute parameters are the same; nuclear availability does not feed back into VRE profiles.

#### 6.8.4 New build outcomes (optimal capacity)

| Technology | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|------------|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| Onshore wind (GW) | 73.33 | 73.33 | 73.33 | 73.33 | 73.33 |
| Solar (GW) | 48.77 | 48.77 | 48.77 | 48.77 | 48.77 |
| CCGT (GW) | 30.78 | 30.78 | 30.78 | 30.78 | 30.78 |
| Coal (GW) | 20.35 | 20.35 | 20.35 | 20.35 | 20.35 |
| Lignite (GW) | 19.46 | 19.46 | 19.46 | 19.46 | 19.46 |
| Battery (MW) | 0.07 | 0.03 | 0.02 | 0.14 | 0.06 |
| **SMR (MW)** | — | — | **0.0007** | — | — |
| **MSR (MW)** | — | — | — | **0.0023** | — |
| **LFR (MW)** | — | — | — | — | **0.0012** |
| H₂ storage (MW) | ~0.008 | ~0.003 | ~0.002 | ~0.015 | ~0.007 |

Nuclear capacities are numerical dust (sub-kW); effectively **zero build** in all three nuclear scenarios.

#### 6.8.5 CO₂ emissions breakdown (kt, 2-week period)

| Emitter | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr | Δ base→dunkelflaute |
|---------|-----:|-------------:|-----------------:|-----------------:|-----------------:|--------------------:|
| Coal | 1,885 | 1,910 | 1,910 | 1,910 | 1,910 | +25 |
| Lignite | 1,275 | 1,597 | 1,597 | 1,597 | 1,597 | **+322** |
| CCGT | 67 | 234 | 234 | 234 | 234 | **+167** |
| Waste | 55 | 106 | 106 | 106 | 106 | +51 |
| **Total** | **3,283** | **3,849** | **3,849** | **3,849** | **3,849** | **+566 (+17%)** |
| CO₂ limit (period) | 19,178 | 19,178 | 19,178 | 19,178 | 19,178 | Not binding |

---

### 6.9 Key findings by scenario — summary matrix

| Finding | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|---------|------|--------------|------------------|------------------|------------------|
| Dunkelflaute stress applied | No | **Yes** | Yes | Yes | Yes |
| New nuclear option available | No | No | **SMR (5 sites)** | **MSR (3 sites)** | **LFR (3 sites)** |
| Nuclear built | — | — | ~0 MW | ~0 MW | ~0 MW |
| Primary flexibility response | CCGT baseload | **CCGT +247%** | CCGT (same) | CCGT (same) | CCGT (same) |
| VRE share of generation | ~45% | ~36% | ~36% | ~36% | ~36% |
| Fossil + biomass share | ~70% | ~78% | ~78% | ~78% | ~78% |
| CO₂ limit binding | No | No | No | No | No |
| Storage utilisation | Negligible | Negligible | Negligible | Negligible | Negligible |
| Cost impact vs base | Reference | **+25.6% OPEX** | +25.6% (no delta vs dunkelflaute) | +25.6% | +25.6% |
| Engineering conclusion | Winter baseline | Gas fills VRE gap | SMR not competitive at placeholder costs | MSR lowest marginal cost but still no build | LFR intermediate, no build |

**Central conclusion from cross-scenario comparison:** The only scenario change that materially affects system outcomes is **Dunkelflaute stress** (base → dunkelflaute). Adding SMR, MSR, or LFR on top of Dunkelflaute produces **no meaningful difference** in dispatch, cost, or emissions under current assumptions — because the optimiser builds effectively zero nuclear capacity.

---

## 7. Preliminary Results — Quantitative Analysis

### 7.1 Summary table (2-week simulation period — correct scaling)

Energy and costs integrated over the 336-hour simulation window with proper snapshot weights:

| Scenario | Load (TWh) | Generation (TWh) | OPEX (M EUR) | Objective (M EUR) | CO₂ (kt) |
|----------|------------|-------------------|--------------|-------------------|----------|
| **base** | 21.15 | 21.21 | 269.7 | 269.7 | 3,283 |
| **dunkelflaute** | 21.15 | 21.21 | 338.8 | 338.8 | 3,849 |
| **dunkelflaute-smr** | 21.15 | 21.21 | 338.8 | 338.8 | 3,849 |
| **dunkelflaute-msr** | 21.15 | 21.21 | 338.8 | 338.8 | 3,849 |
| **dunkelflaute-lfr** | 21.15 | 21.21 | 338.8 | 338.8 | 3,849 |

**Note:** CAPEX (~1,659 M EUR) is similar across scenarios because it reflects **annuitised cost of the entire installed fleet**, not incremental investment in this 2-week run. Incremental CAPEX from new nuclear is negligible (~0 MW built).

### 7.2 Generation mix shift — base vs Dunkelflaute (TWh, 2-week period)

| Carrier | base | dunkelflaute | Δ | Δ (%) |
|---------|------|--------------|---|-------|
| **CCGT** | 0.34 | 1.18 | +0.84 | **+247%** |
| **Coal + lignite** | 8.74 | 9.61 | +0.87 | +10% |
| **Wind (all)** | 8.86 | 7.21 | −1.65 | −19% |
| **Solar (all)** | 0.70 | 0.44 | −0.26 | −37% |
| **Biomass** | 6.15 | 6.15 | ~0 | 0% |
| **OCGT** | 0.0003 | 0.0002 | ~0 | — |
| **Nuclear (SMR/MSR/LFR)** | 0 | ~10⁻⁷ | ~0 | — |

### 7.3 Installed capacity (GW) — optimal expansion

Capacities are essentially **identical across all five scenarios** because the 2-week window does not justify large structural changes:

| Carrier | Capacity (GW) | Extendable? |
|---------|---------------|-------------|
| Onshore wind | 73.3 | Yes |
| Solar PV | 48.8 | Yes |
| CCGT | 30.8 | Yes |
| Coal | 20.4 | No (fixed) |
| Lignite | 19.5 | No (fixed) |
| Offshore wind (AC) | 11.2 | Yes |
| Biomass | 8.0 | No |
| OCGT | 6.1 | Yes |
| **SMR / MSR / LFR** | **~10⁻⁶** | Yes (but builds nothing) |
| Battery | ~10⁻⁴ | Yes (negligible) |

The model's 2024-estimated renewable fleet (~122 GW wind + solar) is retained; the optimiser does not expand VRE within this short window because existing capacity is sufficient except during Dunkelflaute hours.

### 7.4 VRE capacity factors (2-week average)

| Carrier | base CF | dunkelflaute CF | Change |
|---------|---------|-----------------|--------|
| Onshore wind | 9.3% | 7.5% | −18.7% |
| Offshore wind (AC) | 17.8% | 14.5% | −18.3% |
| Solar PV | 1.4% | 0.9% | −37.0% |

Winter capacity factors are low in absolute terms (January); the Dunkelflaute derating further suppresses them during the 5 worst days.

### 7.5 Dispatch on worst VRE day (2021-01-25) — Dunkelflaute-SMR scenario

| Carrier | Generation (GWh/day) |
|---------|---------------------|
| Coal | 163 |
| Lignite | 156 |
| CCGT | 100 |
| Biomass | 64 |
| Waste | 22 |
| Onshore wind | 7.7 |
| Offshore wind | 4.0 |
| Solar | 1.6 |
| SMR | ~0.000004 |

On the worst day, **~95% of electricity comes from fossil and biomass**; VRE contributes ~13 GWh (~6% of daily energy).

### 7.6 Nuclear build detail

| Scenario | Total nuclear built (MW) | Generators | Generation (TWh) |
|----------|--------------------------|------------|------------------|
| dunkelflaute-smr | 0.00066 | 5 × ~0.00013 MW | 1.5×10⁻⁷ |
| dunkelflaute-msr | 0.00225 | 5 × ~0.00045 MW | 5.0×10⁻⁷ |
| dunkelflaute-lfr | 0.00115 | 5 × ~0.00023 MW | 2.6×10⁻⁷ |

These are **numerical artefacts** (sub-kW capacities), not meaningful engineering outcomes. The LP assigns tiny capacities to avoid degeneracy; they have zero practical significance.

### 7.7 Comparison script caveat

`compare_scenarios.py` annualises supply by multiplying by `8760 / n_snapshots`, producing values like "911,266 TWh" — **physically meaningless**. The script's plotting function also fails on this data (`ValueError: If using all scalar values, you must pass an index`). **Use period-correct energy (Section 7.1–7.2) for interpretation.** Fix planned in next steps.

---

## 8. Energy Engineering Interpretation

### 8.1 What the Dunkelflaute scenario reveals

The Jan 2021 window captures a **winter high-pressure situation** typical of Central European Dunkelflaute:

1. **Low solar** — short days, low elevation angle; 1–2% capacity factor is realistic for January.
2. **Moderate but insufficient wind** — even before derating, 9–18% CF cannot cover ~63 GW average demand with ~122 GW installed VRE (need ~50%+ CF or storage/interconnection).
3. **Under stress**, the gap is filled by **flexible gas (CCGT)** first because:
   - Marginal cost ~43 EUR/MWh vs coal/lignite must-run baseload.
   - CCGT is extendable and already has 31 GW installed.
   - Ramp limits allow daily cycling.

4. **Coal/lignite increase modestly (+10%)** because they operate near minimum stable output already as baseload; they provide inertia and low-marginal-cost energy but cannot ramp fast enough to cover all peaks.

**Engineering conclusion:** In the current model setup, **Dunkelflaute is a gas-and-coal event**, not a storage or nuclear event. This aligns with real-world observations from Jan 2021 when Germany relied heavily on conventional generation and imports (imports not modelled here).

### 8.2 Why nuclear did not build

Three reinforcing reasons:

1. **Capital recovery period vs snapshot window:** Annuitised CAPEX ~18,000 EUR/MW/year must be recovered from dispatch savings over **336 hours**. Even if nuclear displaced CCGT at 43 EUR/MWh every hour, revenue ≈ 43 × 336 ≈ 14,500 EUR/MW — less than one year's capital cost alone.

2. **High absolute CAPEX:** At 4,500 EUR/kW (SMR), a 1 GW plant costs ~4.5 bn EUR overnight → ~18 kEUR/MW/year annuitised. Competing with CCGT at ~4.8 kEUR/MW/year annuitised CAPEX, gas wins on short horizons.

3. **No carbon price binding:** With CO₂ cap at 17–20% utilisation, coal/lignite remain cheap. Nuclear's zero-carbon advantage is not monetised.

4. **Baseload mismatch:** Nuclear with `p_min_pu = 0.3` wants to run continuously; a 2-week winter window with moderate total demand does not create enough **scarcity pricing** to justify 24/7 firm capacity investment.

**Engineering conclusion:** The model correctly rejects nuclear under current cost assumptions and short optimisation horizon. This is **not evidence that nuclear is useless for Dunkelflaute** — it indicates the **model configuration is not yet suited to capacity adequacy decisions**.

### 8.3 Technology ranking (if nuclear were forced to build)

At placeholder costs, marginal cost ranking for dispatch:

$$\text{MSR (10.6)} < \text{LFR (11.4)} < \text{SMR (12.1)} < \text{CCGT (43.3)} \text{ EUR/MWh}$$

MSR has lowest operating cost but highest CAPEX (5,200 EUR/kW). The optimiser's build decision depends on **utilisation hours** — classic baseload economics.

### 8.4 Storage and hydrogen

Battery optimal capacity: **~0.07 MW (base), ~0.03 MW (Dunkelflaute)** — effectively zero.

**Why:** With 2-week horizon, arbitrage between high-wind and low-wind hours within the window does not justify battery CAPEX. H₂ chain similarly unused. Over a full year with repeated Dunkelflaute events, seasonal storage economics would differ substantially.

### 8.5 CO₂ and policy

Emitting 3.3 Mt in 2 weeks → **~86 Mt/year** if extrapolated linearly (rough, not rigorous). The 500 Mt/year cap allows this easily. For a 2050 net-zero scenario, the cap should be **< 50 Mt/year** or coal/lignite must be retired via `powerplants_filter`.

Top emitters (base, kt over 2 weeks):

| Carrier | CO₂ (kt) | Share |
|---------|----------|-------|
| Coal | 1,885 | 57% |
| Lignite | 1,275 | 39% |
| CCGT | 67 | 2% |

---

## 9. Known Limitations & Model Artefacts

| Limitation | Severity | Description |
|------------|----------|-------------|
| Short snapshot window | **Critical** | Investment decisions not representative of annual/full-life economics |
| Non-binding CO₂ cap | **High** | Coal/lignite fleet inconsistent with 2050 policy narrative |
| National uniform Dunkelflaute | Medium | Real events have spatial structure |
| 10-cluster aggregation | Medium | Internal congestion within zones ignored |
| No imports/exports | Medium | Germany relied on neighbours during 2021 event |
| Placeholder nuclear costs | **High** | ±50% cost swing would change build decisions |
| No national nuclear cap | Medium | Unrealistic if 5×1500 MW all build in future configs |
| compare_scenarios annualisation bug | Low (reporting) | Misleading TWh figures in CSV |
| HiGHS "Unknown" status | Low | Solution usable; gap ~0.003% of objective |
| Linear programming (no UC) | Medium | CCGT can fractionally dispatch without start costs |
| Coal still in 2050 fleet | **High** | `powerplants_filter` keeps pre-2025 plants without phase-out schedule |

---

## 10. How to Improve & Change Assumptions

### 10.1 Dunkelflaute parameters

| Parameter | Current | Suggested range | How to change |
|-----------|---------|-----------------|---------------|
| `wind_factor` | 0.15 | 0.05 – 0.30 | `data/inre/dunkelflaute.yaml` |
| `solar_factor` | 0.10 | 0.02 – 0.20 | Same |
| `auto_worst_days` | 5 | 3 – 14 | Same; or set `null` and use fixed `time_start`/`time_end` |
| `ramp_hours` | 6 | 0 – 12 | Same |
| Spatial pattern | Uniform | Zone-varying factors | Extend `apply_dunkelflaute.py` |

**Calibration approach:** Compare derated profiles against ENTSO-E actual wind/solar generation during Jan 24 – Feb 8, 2021. Compute the ratio of actual to potential generation on each day; use the 5th percentile as `wind_factor`/`solar_factor`.

### 10.2 Nuclear techno-economics

Replace `data/inre/custom_costs_nuclear.csv` with literature values:

| Source type | Examples |
|-------------|----------|
| SMR | NEA/IEA "Projected Costs of Generating Electricity", NuScale/ Rolls-Royce SMR studies |
| MSR | EU SAMOFAR, Moltex, Terrestrial Energy public estimates |
| LFR | MYRRHA, BREST-OD-300 conceptual designs |

Recommended sensitivity band: **±40% on overnight capital cost**, **±10% on availability**, **±5% on efficiency**.

Also consider adding to `add_nuclear_technologies.py`:

- `GlobalConstraint` on total nuclear capacity (national cap, e.g. 10 GW).
- Scheduled `DateIn` enforcement (plants unavailable before 2045).
- Co-location with industrial heat offtake (future sector coupling).

### 10.3 Policy & fleet

| Change | Config key | Suggested value |
|--------|------------|-----------------|
| Binding CO₂ cap | `electricity.co2limit` | 50e+6 (50 Mt/year) for 2050 net-zero path |
| Coal phase-out | `electricity.powerplants_filter` | Exclude coal/lignite: `Fueltype != 'Hard coal' and Fueltype != 'Lignite'` |
| Carbon price | PyPSA `EmissionPrice` constraint | Alternative to hard cap |
| Renewable expansion limit | `estimate_renewable_capacities.expansion_limit` | `true` with cap if matching real pipeline |

### 10.4 Temporal & spatial resolution

| Goal | Change | Trade-off |
|------|--------|-----------|
| Better investment signal | Extend to full year or 4× seasonal weeks | Solve time ↑ (hours) |
| Faster iteration | `resolution_elec: 24h` or 6h | Lose ramp detail |
| More spatial detail | `clusters: [20]` or `[37]` | Memory and solve time ↑ |
| Adequacy focus | Switch to `solve_operations_network` with fixed capacities | Separates expansion from operation |

### 10.5 Model formulation upgrades

1. **Myopic or perfect foresight expansion** over multiple investment periods (`foresight: myopic`).
2. **Unit commitment** for CCGT/OCGT (requires MILP, e.g. Gurobi).
3. **Import/export** links to FR, NL, PL, CZ, AT, DK (PyPSA-Eur multi-country config).
4. **Demand-side response** as shiftable load.
5. **Fix `compare_scenarios.py`** to report period energy and optional annual extrapolation with explicit scaling factor.

---

## 11. Recommended Next Steps (Prioritised)

### Phase A — Fix & validate (1–2 days)

- [ ] **Fix `compare_scenarios.py`** — period-correct energy, working plots, delta table vs base.
- [ ] **Add coal/lignite phase-out scenario** — rerun Dunkelflaute without fossil baseload.
- [ ] **Tighten CO₂ cap** to binding level (e.g. 50 Mt/year); observe dispatch shift.
- [ ] Document solver runtime vs target (currently ~5–6 min ✅, within 15 min goal).

### Phase B — Nuclear relevance (3–5 days)

- [ ] **Literature review** → update `custom_costs_nuclear.csv` with cited values.
- [ ] **Operations-only mode:** Fix VRE + storage + gas capacities at 2030/2040/2050 levels; optimise dispatch and **marginal value of nuclear** during Dunkelflaute only.
- [ ] **Add national nuclear cap** (`GlobalConstraint`, e.g. 5–15 GW).
- [ ] **Sensitivity sweep:** wind_factor × solar_factor × nuclear CAPEX (3×3×3 = 27 runs with shared resources).

### Phase C — Temporal realism (1–2 weeks)

- [ ] **Extend snapshot window** to full year 2021 (hourly or 3h) — requires longer solves or cluster reduction.
- [ ] **Multi-period investment** with myopic foresight (2030, 2040, 2050).
- [ ] **Calibrate Dunkelflaute** against ENTSO-E actuals for Jan–Feb 2021.
- [ ] **Alternative events:** Dec 2016, Feb 2012 for robustness.

### Phase D — Reporting & policy (ongoing)

- [ ] Cross-border flows and EU context.
- [ ] Levelised cost of lost load (LOLP) / unserved energy metric during stress days.
- [ ] Publication-ready figures: duration curve, dispatch stack for worst day, price duration.
- [ ] Peer review of assumptions document.

---

## 12. Appendix: File Reference & Commands

### 12.1 Reproduce results

```bash
cd /path/to/INRE-Project-PyPSA-EUR
pixi install && pixi shell

# All five scenarios
snakemake -call solve_elec_networks \
  --configfile config/inre/config.base.yaml \
  --configfile config/inre/config.scenarios.yaml

# Comparison (after fixing script)
python scripts/inre/compare_scenarios.py --output-dir results/inre-comparison
```

### 12.2 Key result files

| Path | Content |
|------|---------|
| `results/base/networks/base_s_10_elec_.nc` | Solved base case network |
| `results/dunkelflaute*/networks/*.nc` | Stress and nuclear variants |
| `results/inre-comparison/comparison_table.csv` | KPI summary (note scaling caveat) |
| `results/*/logs/apply_inre_network/*.log` | Dunkelflaute day selection log |
| `results/*/logs/solve_network/*_solver.log` | HiGHS solver output |

### 12.3 Glossary

| Term | Definition |
|------|------------|
| **Dunkelflaute** | "Dark doldrums" — extended period of low wind and solar output |
| **SMR** | Small Modular Reactor (~50–300 MW modules) |
| **MSR** | Molten Salt Reactor (liquid fuel/coolant) |
| **LFR** | Lead-cooled Fast Reactor (fast neutron spectrum) |
| **p_max_pu** | Per-unit availability factor (0–1) for renewable generators |
| **CAPEX / OPEX** | Capital / operating expenditure |
| **CF** | Capacity factor = energy output / (capacity × time) |

---

## Document History

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-06-22 | Initial progress report after first full 5-scenario Phase 2 run |

---

*This report reflects the state of the INRE project as of the first successful multi-scenario solve. All numerical results should be treated as preliminary until assumptions P1–P3 (CO₂, coal fleet, snapshot window) are revised for 2050 policy consistency.*
