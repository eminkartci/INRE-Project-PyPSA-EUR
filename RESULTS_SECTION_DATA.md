# Results Section Data Package

> **Report-ready version:** See [RESULTS_FINAL.md](RESULTS_FINAL.md) for the latest corrected results. This file is retained as an audit trail.

**Project:** Integration of nuclear and renewables for Dunkelflaute resilience in the German electricity system  
**Simulation window:** 14 days, 112 snapshots, 3-hour resolution (336 hours) — **2021-01-25 to 2021-02-07**  
**Energy unit convention:** All TWh values below are **integrated over the 2-week simulation period** unless explicitly labelled as annualised extrapolations.

**Data source priority:** Period-correct values extracted from solved PyPSA-Eur networks (`results/*/networks/base_s_10_elec_.nc`) and GAMSPy CSV/YAML outputs. The older `results/inre-comparison/` tables (e.g. CO₂ ≈ 3,283 kt) used incorrect scaling and are **not** used here. Current `compare_scenarios.py` (v2) integrates energy over snapshot weights correctly.

---

## 1. Model Runs Included

| Model | Scenario name | Results folder / file path | Dunkelflaute enabled? | Nuclear option | Solver status | Objective value | Notes |
|-------|---------------|----------------------------|----------------------|----------------|---------------|-----------------|-------|
| PyPSA-Eur INRE | base | `results/base/networks/base_s_10_elec_.nc` | no | none | HiGHS, optimal (solved network) | 543.8 M EUR | Germany, 10 clusters, 2050 costs, CO₂ limit 50 Mt/yr (not binding over 2 weeks) |
| PyPSA-Eur INRE | dunkelflaute | `results/dunkelflaute/networks/base_s_10_elec_.nc` | yes | none | HiGHS, optimal | 3,937.5 M EUR | Wind/solar derating profiles applied over full 14-day window (`data/inre/dunkelflaute.yaml`) |
| PyPSA-Eur INRE | dunkelflaute-smr | `results/dunkelflaute-smr/networks/base_s_10_elec_.nc` | yes | SMR (5 sites × 1,500 MW max) | HiGHS, optimal | 3,176.4 M EUR | Builds 7,500 MW SMR (5 × 1,500 MW) |
| PyPSA-Eur INRE | dunkelflaute-msr | `results/dunkelflaute-msr/networks/base_s_10_elec_.nc` | yes | MSR (3 sites × 1,500 MW max) | HiGHS, optimal | 3,481.8 M EUR | Builds 4,500 MW MSR |
| PyPSA-Eur INRE | dunkelflaute-lfr | `results/dunkelflaute-lfr/networks/base_s_10_elec_.nc` | yes | LFR (3 sites × 1,500 MW max) | HiGHS, optimal | 3,474.8 M EUR | Builds 4,500 MW LFR |
| GAMSPy DE | base | `gamspy-de/results/base/` | no | none | HiGHS, OptimalGlobal | 4.17 bn EUR | 10-bus template; representative inputs |
| GAMSPy DE | dunkelflaute | `gamspy-de/results/dunkelflaute/` | yes | none | HiGHS, OptimalGlobal | 41.52 bn EUR | Same derating profiles as PyPSA |
| GAMSPy DE | dunkelflaute-smr | `gamspy-de/results/dunkelflaute-smr/` | yes | SMR | HiGHS, OptimalGlobal | 34.15 bn EUR | Builds 7,500 MW SMR (5 × 1,500 MW) |
| GAMSPy DE | dunkelflaute-msr | `gamspy-de/results/dunkelflaute-msr/` | yes | MSR | HiGHS, OptimalGlobal | 37.42 bn EUR | Builds 4,500 MW MSR |
| GAMSPy DE | dunkelflaute-lfr | `gamspy-de/results/dunkelflaute-lfr/` | yes | LFR | HiGHS, OptimalGlobal | 37.25 bn EUR | Builds 4,500 MW LFR |

**PyPSA KPI tables (CSV):** `results/inre-comparison-v2/comparison_table.csv`, `report_summary.csv`  
**GAMSPy summaries:** `gamspy-de/results/<scenario>/summary.yaml`

---

## 2. PyPSA-Eur System-Level KPI Table

**Formulas (2-week period):**

- LCOE [EUR/MWh] = (OPEX + annuitised CAPEX) / load served = `total_cost_meur / load_twh`
- LCO₂ [EUR/tCO₂] = (OPEX + annuitised CAPEX) / CO₂ emissions = `total_cost_meur / co2_kt × 1,000`
- LCOA_s|b [EUR/tCO₂ avoided] = (Cost_s − Cost_b) / (Emissions_b − Emissions_s), reference **b = dunkelflaute**

| Scenario | Load served (TWh) | Total generation (TWh) | OPEX (M EUR) | CAPEX (M EUR) | Objective / total cost (M EUR) | CO₂ emissions (ktCO₂) | LCOE (EUR/MWh) | LCO₂ emissions cost (EUR/tCO₂) | CO₂ abatement cost vs dunkelflaute reference (EUR/tCO₂ avoided) | Nuclear capacity built (MW) | Battery capacity built (MW) | Notes |
|----------|------------------:|-----------------------:|-------------:|--------------:|-------------------------------:|----------------------:|---------------:|-------------------------------:|----------------------------------------------------------------:|------------------------------:|------------------------------:|-------|
| base | 21.15 | 21.21 | 266.9 | 1,935.7 | 543.8 (obj) / 2,202.6 (OPEX+CAPEX) | 1,020 | 104.1 | 2,159 | −54,821 (more emissions than reference) | 0 | ~0 (no discharge) | Reference winter window without stress |
| dunkelflaute | 21.15 | 21.24 | 308.4 | 5,287.9 | 3,937.5 / 5,596.3 | 1,082 | 264.6 | 5,171 | reference | 0 | ~0 (numerical p_nom_opt only) | +15.5% OPEX vs base; CCGT-dominated stress response |
| dunkelflaute-smr | 21.15 | 21.22 | 335.8 | 4,499.5 | 3,176.4 / 4,835.2 | 1,077 | 228.6 | 4,489 | −150,069 | **7,500** | ~0 | SMR supplies 2.27 TWh (10.7% of generation); displaces some gas |
| dunkelflaute-msr | 21.15 | 21.23 | 322.9 | 4,817.8 | 3,481.8 / 5,140.6 | 1,080 | 243.0 | 4,758 | −239,732 | **4,500** | ~0 | MSR supplies 1.36 TWh |
| dunkelflaute-lfr | 21.15 | 21.23 | 323.9 | 4,809.7 | 3,474.8 / 5,133.6 | 1,082 | 242.7 | 4,745 | −1,498,575 | **4,500** | ~0 | LFR supplies 1.36 TWh; marginal CO₂ change vs dunkelflaute (+0.3 kt) |

**Interpretation notes:**

- **Objective** includes period OPEX plus annuitised investment costs; it is **not** equal to OPEX alone.
- **CAPEX** column is **annuitised EUR/year** for the entire optimised fleet (PyPSA `statistics.capex()`), not overnight new-build CAPEX.
- Nuclear scenarios show **small but positive** CO₂ abatement vs dunkelflaute (5–5.1 kt), hence **negative LCOA** (cost reduction co-occurring with abatement). Values are dominated by CAPEX accounting over a 2-week window and should be treated as **indicative**, not policy-grade abatement costs.
- Reported battery `p_nom_opt` values (hundreds of GW) are **not backed by storage dispatch** (0 MWh discharged); treat as **numerical artefact** (see §14).

**Approximate annualised extrapolation (× 8760/336 ≈ 26.07):**  
Example — dunkelflaute OPEX ≈ 308.4 M EUR × 26.07 ≈ **8,040 M EUR/yr** (rough extrapolation only; not used for LCOE above).

---

## 3. Delta Table vs Base

| Scenario | Δ OPEX (M EUR) | Δ OPEX (%) | Δ CO₂ emissions (ktCO₂) | Δ CO₂ emissions (%) | Δ wind generation (TWh) | Δ solar generation (TWh) | Δ fossil generation (TWh) | Short interpretation |
|----------|---------------:|-----------:|------------------------:|--------------------:|------------------------:|---------------------------:|--------------------------:|----------------------|
| dunkelflaute | +41.5 | +15.5% | +62.0 | +6.1% | −4.34 | +3.08 | +0.54 | Stress lowers wind output; CCGT fills the gap; coal output falls to near zero in dispatch |
| dunkelflaute-smr | +68.9 | +25.8% | +56.8 | +5.6% | −5.64 | +2.12 | +0.51 | Higher OPEX than base; SMR adds low-carbon supply but fossil gas remains dominant |
| dunkelflaute-msr | +56.0 | +21.0% | +60.0 | +5.9% | −5.23 | +2.61 | +0.53 | Similar to dunkelflaute with MSR providing 1.36 TWh nuclear |
| dunkelflaute-lfr | +57.0 | +21.4% | +61.6 | +6.0% | −5.24 | +2.61 | +0.54 | Comparable to MSR scenario; LFR does not materially change emissions vs dunkelflaute |

*Fossil = CCGT + OCGT + coal + lignite. Wind/solar are total across all wind/solar carriers.*

---

## 4. Delta Table vs Dunkelflaute

Reference: **dunkelflaute** (no nuclear).

| Scenario | Δ OPEX vs dunkelflaute (M EUR) | Δ CO₂ vs dunkelflaute (ktCO₂) | Δ nuclear capacity built (MW) | Δ fossil generation (TWh) | Δ LCOE (EUR/MWh) | Δ LCO₂ (EUR/tCO₂) | Meaningful CO₂ abatement? | Interpretation |
|----------|-------------------------------:|------------------------------:|------------------------------:|--------------------------:|-----------------:|------------------:|--------------------------|----------------|
| dunkelflaute-smr | +27.4 | −5.1 | +7,500 | −0.025 | −36.0 | −682 | yes (small) | SMR reduces CO₂ marginally by displacing CCGT; total cost (OPEX+CAPEX) actually **falls** vs dunkelflaute because of CAPEX accounting |
| dunkelflaute-msr | +14.5 | −1.9 | +4,500 | −0.009 | −21.5 | −413 | borderline | MSR builds 4.5 GW; emissions change <2 kt |
| dunkelflaute-lfr | +15.5 | −0.3 | +4,500 | −0.001 | −21.9 | −426 | no | Emissions essentially unchanged; nuclear provides 1.36 TWh but gas remains marginal emitter |

---

## 5. Generation Mix by Carrier

### 5.1 By carrier (TWh, 2-week period)

| Carrier | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|---------|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| Onshore wind | 12.18 | 8.22 | 7.62 | 8.03 | 8.02 |
| Offshore wind (AC) | 1.45 | 0.36 | 0.36 | 0.36 | 0.36 |
| Offshore wind (DC) | 0.00 | 0.71 | 0.01 | 0.01 | 0.01 |
| Offshore wind (floating) | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Solar | 0.70 | 3.78 | 2.82 | 3.31 | 3.31 |
| CCGT | 4.55 | 5.46 | 5.43 | 5.45 | 5.46 |
| OCGT | 0.05 | 0.00 | 0.01 | 0.00 | 0.00 |
| Coal | 0.32 | ~0 | ~0 | ~0 | ~0 |
| Lignite | ~0 | ~0 | ~0 | ~0 | ~0 |
| Biomass | 1.94 | 2.69 | 2.69 | 2.69 | 2.69 |
| Waste | ~0 | ~0 | ~0 | ~0 | ~0 |
| Geothermal | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 |
| Nuclear SMR | — | — | **2.27** | — | — |
| Nuclear MSR | — | — | — | **1.36** | — |
| Nuclear LFR | — | — | — | — | **1.36** |

*Source: `results/inre-comparison-v2/generation_mix_twh.csv`*

### 5.2 Aggregated mix (TWh, 2-week period)

| Group | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|-------|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| Wind total | 13.63 | 9.29 | 7.99 | 8.40 | 8.39 |
| Solar total | 0.70 | 3.78 | 2.82 | 3.31 | 3.31 |
| VRE total | 14.33 | 13.07 | 10.81 | 11.72 | 11.71 |
| Fossil total | 4.92 | 5.46 | 5.44 | 5.45 | 5.46 |
| Nuclear total | 0.00 | 0.00 | 2.27 | 1.36 | 1.36 |
| Low-carbon total (VRE + nuclear + biomass + geo) | 16.28 | 15.78 | 15.78 | 15.78 | 15.77 |
| **Total generation** | **21.21** | **21.24** | **21.22** | **21.23** | **21.23** |

**Notes:** Solar generation is higher in dunkelflaute scenarios than in base because the base case does not apply the Dunkelflaute profile; cross-scenario solar levels are **not** directly comparable as a pure weather effect. Wind reductions are the primary Dunkelflaute signal.

---

## 6. Capacity Results

### 6.1 Existing installed capacity (p_nom, base scenario)

| Carrier | Capacity | Unit | Notes |
|---------|----------|------|-------|
| Onshore wind | 73.3 | GW | 2024-estimated fleet |
| Offshore wind (AC) | 11.2 | GW | |
| Solar | 48.8 | GW | |
| CCGT | 30.8 | GW | Extendable |
| OCGT | 6.1 | GW | Fixed |
| Coal | 20.4 | GW | Fixed |
| Lignite | 19.5 | GW | Fixed |
| Biomass | 8.0 | GW | Fixed |
| Battery | ~0 | MW | Negligible existing |

### 6.2 Optimal capacity by scenario (GW unless noted)

| Carrier | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr | Unit | Notes |
|---------|-----:|-------------:|-----------------:|-----------------:|-----------------:|------|-------|
| Onshore wind | 131.0 | 488.2 | 444.6 | 474.4 | 473.7 | GW | **Phantom expansion** — not credible; existing fleet ~73 GW |
| Offshore wind (AC) | 11.2 | 11.5 | 11.5 | 11.5 | 11.5 | GW | ~existing |
| Solar | 48.8 | 915.7 | 642.8 | 779.8 | 779.5 | GW | **Phantom expansion** |
| CCGT | 30.8 | 36.9 | 35.2 | 35.8 | 36.6 | GW | Modest real expansion (+4–6 GW) |
| OCGT | 6.1 | 6.1 | 6.1 | 6.1 | 6.1 | GW | Fixed |
| Coal | 20.4 | 20.4 | 20.4 | 20.4 | 20.4 | GW | Fixed |
| Lignite | 19.5 | 19.5 | 19.5 | 19.5 | 19.5 | GW | Fixed |
| Biomass | 8.0 | 8.0 | 8.0 | 8.0 | 8.0 | GW | Fixed |
| Battery power | 35.4 | 413.5 | 339.5 | 426.8 | 426.1 | GW | **Numerical dust** (0 MWh discharged) |
| Battery energy | 0 | 0 | 0 | 0 | 0 | GWh | No stored energy built |
| H₂ store | 0.04 | 0.20 | 2.47 | 0.18 | 0.28 | GW | Negligible |
| SMR | 0 | 0 | **7.5** | 0 | 0 | GW | 5 sites × 1.5 GW (at p_nom_max) |
| MSR | 0 | 0 | 0 | **4.5** | 0 | GW | 3 sites × 1.5 GW |
| LFR | 0 | 0 | 0 | 0 | **4.5** | GW | 3 sites × 1.5 GW |

*Source: `results/inre-comparison-v2/capacity_gw.csv` with interpretation from `p_nom` vs `p_nom_opt` analysis.*

### 6.3 Credible new build only (extendable, Δp_nom)

| Technology | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr | Unit |
|------------|-----------------:|-----------------:|-----------------:|------|
| SMR | 7,500 | — | — | MW |
| MSR | — | 4,500 | — | MW |
| LFR | — | — | 4,500 | MW |
| CCGT | +4,449 | +5,035 | +5,852 | MW |
| VRE / battery | unreliable | unreliable | unreliable | MW |

---

## 7. Nuclear Investment and Dispatch Results

### 7.1 Nuclear capacity built per scenario (PyPSA-Eur)

| Scenario | Technology | Total built (MW) | Generation (TWh) | Average CF (if built) |
|----------|------------|----------------:|-----------------:|----------------------:|
| dunkelflaute-smr | SMR | 7,500 | 2.27 | ~90% |
| dunkelflaute-msr | MSR | 4,500 | 1.36 | ~90% |
| dunkelflaute-lfr | LFR | 4,500 | 1.36 | ~90% |

**Important:** Unlike earlier development runs that produced sub-kW “numerical dust”, the **current solved networks build nuclear at the per-site maximum (1,500 MW)**. This reflects the short optimisation horizon and annuitised-cost formulation: nuclear runs baseload and displaces ~1–2 TWh of gas over 2 weeks. Results are **model-structural**, not a deployment recommendation.

### 7.2 Nuclear capacity built per site (PyPSA-Eur)

| Site | dunkelflaute-smr (MW) | dunkelflaute-msr (MW) | dunkelflaute-lfr (MW) |
|------|----------------------:|----------------------:|----------------------:|
| Grohnde | 1,500 | 1,500 | 1,500 |
| Brokdorf | 1,500 | 1,500 | 1,500 |
| Isar | 1,500 | 1,500 | — |
| Emsland | 1,500 | — | 1,500 |
| Neckarwestheim | 1,500 | — | — |

Each active site generates ~0.454 TWh over the 2-week window (~90% capacity factor).

### 7.3 GAMSPy nuclear (consistent with PyPSA)

| Scenario | Built (MW) | Generation (TWh) | Sites |
|----------|----------:|-----------------:|-------|
| dunkelflaute-smr | 7,500 | 2.10 | Grohnde, Brokdorf, Isar, Emsland, Neckarwestheim |
| dunkelflaute-msr | 4,500 | 1.26 | Grohnde, Brokdorf, Isar |
| dunkelflaute-lfr | 4,500 | 1.26 | Grohnde, Brokdorf, Emsland |

*Source: `gamspy-de/results/<scenario>/nuclear_investment.csv`, `nuclear_dispatch.csv`*

### 7.4 Nuclear dispatch profile file paths

| Model | Scenario | Investment | Dispatch |
|-------|----------|------------|----------|
| PyPSA-Eur | nuclear scenarios | `generators.p_nom_opt` in `results/<scenario>/networks/base_s_10_elec_.nc` | `generators_t.p` in same network |
| GAMSPy | dunkelflaute-smr | `gamspy-de/results/dunkelflaute-smr/nuclear_investment.csv` | `gamspy-de/results/dunkelflaute-smr/nuclear_dispatch.csv` |
| GAMSPy | dunkelflaute-msr | `gamspy-de/results/dunkelflaute-msr/nuclear_investment.csv` | `gamspy-de/results/dunkelflaute-msr/nuclear_dispatch.csv` |
| GAMSPy | dunkelflaute-lfr | `gamspy-de/results/dunkelflaute-lfr/nuclear_investment.csv` | `gamspy-de/results/dunkelflaute-lfr/nuclear_dispatch.csv` |

### 7.5 Interpretation — why nuclear builds in current runs (but remains non-physical for policy)

The optimiser **does build nuclear** in Dunkelflaute + nuclear scenarios at the **site cap (1,500 MW)** because:

1. **Short 2-week window** — annuitised CAPEX is compared against 336 hours of dispatch; baseload nuclear achieves ~90% CF in the model.
2. **High VRE stress** — reduced wind increases net load; nuclear provides firm low-carbon energy.
3. **Non-binding CO₂ cap** (50 Mt/yr annual → ~191 kt over 2 weeks; emissions ~1,020–1,082 kt) — climate constraint does not limit gas.
4. **Gas and biomass remain available** — nuclear displaces only a portion of CCGT (~5 kt CO₂ in SMR case).
5. **No sector coupling** — no hydrogen or heat revenue streams that would alter nuclear economics in real deployments.

**For report text:** Present nuclear build as **endogenous LP outcome at site caps**, sensitive to horizon and cost assumptions — not as a validated deployment pathway. If reporting earlier dust-level builds, state: *"The nuclear build is numerical dust and should be interpreted as zero capacity."* — this applied to **older** runs, not the current networks documented here.

---

## 8. Dunkelflaute Impact Results

### 8.1 Stress event configuration

| Parameter | Value | Source |
|-----------|-------|--------|
| Stress window | 2021-01-25 → 2021-02-07 (entire simulation) | `data/inre/dunkelflaute.yaml` |
| Auto worst-days mode | `null` (fixed window, not auto-selected subset) | same |
| Wind derating profile | `data/inre/profiles/dunkelflaute_wind_factors.csv` | min factor ≈ **0.10** |
| Solar derating profile | `data/inre/profiles/dunkelflaute_solar_factors.csv` | min factor ≈ **0.00** |
| Ramp smoothing | 6 hours | same |

### 8.2 Quantified impact: base → dunkelflaute (PyPSA-Eur, 2-week period)

| Metric | base | dunkelflaute | Change |
|--------|-----:|-------------:|-------|
| Wind generation (TWh) | 13.63 | 9.29 | **−4.34 TWh (−32%)** |
| Solar generation (TWh) | 0.70 | 3.78 | +3.08 TWh* |
| Fossil generation (TWh) | 4.92 | 5.46 | **+0.54 TWh (+11%)** |
| CCGT generation (TWh) | 4.55 | 5.46 | **+0.91 TWh (+20%)** |
| CO₂ emissions (ktCO₂) | 1,020 | 1,082 | **+62 kt (+6.1%)** |
| OPEX (M EUR) | 266.9 | 308.4 | **+41.5 M EUR (+15.5%)** |

\*Solar increase is a scenario-configuration artefact (profile applied only in dunkelflaute runs); wind reduction is the primary interpretable Dunkelflaute signal.

### 8.3 VRE capacity factor indicators

| Indicator | base | dunkelflaute | Change |
|-----------|-----:|-------------:|-------|
| Wind generation / existing wind fleet (2-week) | 13.63 TWh / 84.5 GW | 9.29 TWh / 84.5 GW | −32% energy |
| Profile mean wind derating factor | 1.00 | 0.97 (profile mean) | min ≈ 0.10 during stress |
| Profile mean solar derating factor | 1.00 | 0.98 (profile mean) | min ≈ 0.00 during stress |

### 8.4 Interpretation

**Dunkelflaute mainly shifts the system from VRE toward fossil dispatch in the current model setup.** Wind output falls by roughly one-third over the 2-week window while CCGT generation rises by ~20%. CO₂ increases modestly (+6%) because the CO₂ cap is non-binding and coal/lignite remain on the system. Storage does not materially participate (zero discharge). Nuclear is not available in the dunkelflaute-only scenario.

---

## 9. Worst-Day Dispatch

**Selected day:** **2021-01-25** (lowest daily VRE generation in dunkelflaute-smr)  
**Scenario shown:** dunkelflaute-smr  
**Daily totals:** 1,294 GWh generation; 347 GWh VRE (26.8% of energy)

| Date | Carrier | Generation (GWh/day) | Share of daily generation (%) |
|------|---------|---------------------:|------------------------------:|
| 2021-01-25 | CCGT | 591.8 | 45.7 |
| 2021-01-25 | Solar | 196.5 | 15.2 |
| 2021-01-25 | Biomass | 192.5 | 14.9 |
| 2021-01-25 | Nuclear SMR | 162.0 | 12.5 |
| 2021-01-25 | Onshore wind | 136.6 | 10.6 |
| 2021-01-25 | Offshore wind (AC) | 13.2 | 1.0 |
| 2021-01-25 | OCGT | 0.8 | 0.1 |
| 2021-01-25 | Geothermal | 0.7 | 0.1 |

### Interpretation

- **Wind + solar** contribute **~347 GWh (26.8%)** on the worst VRE day — well below their annual-average share.
- **Fossil (CCGT + OCGT)** contribute **~593 GWh (45.8%)** — the dominant daily source.
- **Nuclear (SMR)** contributes **162 GWh (12.5%)** in the SMR scenario, running near baseload.
- **Biomass** contributes **192 GWh (14.9%)** as must-run low-carbon supply.
- **Storage** does not appear in dispatch (negligible contribution).

**Stacked dispatch plot:** Not yet generated. Suggested source: extract `generators_t.p` for 2021-01-25 from `results/dunkelflaute-smr/networks/base_s_10_elec_.nc`; suggested filename `figures/worst_day_dispatch_2021-01-25.png`.

---

## 10. GAMSPy Results

**GAMSPy results are used for transparency and sensitivity interpretation; PyPSA-Eur solved networks remain the main calibrated reference.**

### 10.1 Summary table (2-week period)

| Scenario | Objective (bn EUR) | Demand (TWh) | Generation (TWh) | CO₂ (kt) | Nuclear built (MW) | Nuclear gen (TWh) | Storage (MW / GWh) |
|----------|-------------------:|-------------:|-----------------:|---------:|---------------------:|------------------:|-------------------:|
| base | 4.17 | 20.83 | 20.90 | 1,918 | 0 | 0.00 | 8,661 / 35 |
| dunkelflaute | 41.52 | 20.83 | 21.68 | 1,918 | 0 | 0.00 | 105,243 / 421 |
| dunkelflaute-smr | 34.15 | 20.83 | 19.44 | 1,918 | 7,500 | 2.10 | 89,888 / 360 |
| dunkelflaute-msr | 37.42 | 20.83 | 20.33 | 1,918 | 4,500 | 1.26 | 96,720 / 387 |
| dunkelflaute-lfr | 37.25 | 20.83 | 20.33 | 1,918 | 4,500 | 1.26 | 96,720 / 387 |

### 10.2 Generation by carrier (TWh)

| Carrier | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|---------|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| Onwind | 6.97 | 2.57 | 1.39 | 1.86 | 1.86 |
| Offwind | 0.94 | 0.19 | 0.19 | 0.19 | 0.19 |
| Solar | 5.51 | 11.30 | 10.22 | 10.66 | 10.66 |
| CCGT | 7.25 | 7.59 | 7.59 | 7.59 | 7.59 |
| OCGT | 0.24 | 0.05 | 0.05 | 0.05 | 0.05 |
| Nuclear | — | — | 2.10 | 1.26 | 1.26 |

### 10.3 New capacity built (MW, GAMSPy)

| Scenario | onwind | solar | ccgt | nuclear |
|----------|-------:|------:|-----:|--------:|
| base | 6,893 | — | 22,399 | 0 |
| dunkelflaute | 56,001 | 275,996 | 24,441 | 0 |
| dunkelflaute-smr | 4,994 | 243,632 | 21,344 | 7,500 |
| dunkelflaute-msr | 24,737 | 256,569 | 22,630 | 4,500 |
| dunkelflaute-lfr | 24,737 | 256,569 | 22,630 | 4,500 |

### 10.4 Comparison to PyPSA-Eur trends

GAMSPy **confirms directional trends**: Dunkelflaute reduces wind generation sharply, increases reliance on CCGT, and enables large nuclear build when SMR/MSR/LFR are available (7.5 GW / 4.5 GW). **Differences:** GAMSPy CO₂ is flat at 1,918 kt (cap-saturated template), while PyPSA shows +6% CO₂ under stress; GAMSPy builds very large solar/storage capacity (template elasticity), whereas PyPSA phantom expansion is similarly unphysical but manifests differently. **Use GAMSPy for qualitative sensitivity only.**

---

## 11. PyPSA-Eur vs GAMSPy Comparison

| Result / trend | PyPSA-Eur result | GAMSPy result | Agreement? | Explanation |
|----------------|------------------|---------------|------------|-------------|
| Dunkelflaute increases fossil dispatch | CCGT +0.91 TWh (+20%) | CCGT +0.34 TWh; onwind −4.4 TWh | **yes** | Both shift from wind to gas |
| Dunkelflaute increases CO₂ | +62 kt (+6%) | 0 kt (1,918 kt flat) | **partial** | PyPSA cap non-binding but tracks marginal emissions; GAMSPy hits CO₂ template ceiling |
| Dunkelflaute increases OPEX / cost | +41.5 M EUR OPEX (+15.5%) | Objective 4.2 → 41.5 bn EUR | **yes** (direction) | Absolute levels not comparable (different cost accounting) |
| Nuclear is built when enabled | 7.5 GW SMR / 4.5 GW MSR/LFR | Same magnitudes | **yes** | Both models fill site caps |
| Storage is used | No discharge | Large power build, minor energy | **partial** | Neither shows meaningful storage **dispatch** |
| Main flexibility source | CCGT (+ biomass must-run) | CCGT | **yes** | Gas fills VRE gap |
| Sensitivity to simplifications | Spatially resolved DE network | 10-bus template | **partial** | GAMSPy exaggerates VRE/storage build |

---

## 12. Figures Needed for the Report

| # | Figure title | Source data file | Suggested filename | Suggested caption | Status |
|---|--------------|------------------|--------------------|-------------------|--------|
| 1 | Scenario OPEX / total cost comparison | `results/inre-comparison-v2/report_summary.csv` | `results/inre-comparison-v2/costs_breakdown.png` | System OPEX (period) and annuitised CAPEX by scenario, Germany 2-week window. | **Exists** |
| 2 | CO₂ emissions by scenario | `results/inre-comparison-v2/comparison_table.csv` | `results/inre-comparison-v2/co2_emissions.png` | CO₂ emissions integrated over the 2-week simulation period (ktCO₂). | **Exists** |
| 3 | Generation mix stacked bar chart | `results/inre-comparison-v2/generation_mix_groups_twh.csv` | `results/inre-comparison-v2/production_mix.png` | Electricity generation by carrier group (TWh, 2-week period). | **Exists** |
| 4 | Capacity mix by scenario | `results/inre-comparison-v2/capacity_gw.csv` | `results/inre-comparison-v2/capacity.png` | Optimiser capacity by carrier (note: VRE/battery values include phantom expansion). | **Exists** (needs caveat in caption) |
| 5 | Dunkelflaute wind and solar capacity-factor profile | `output/dunkelflaute/hourly_capacity_factors.csv`, `gamspy-de/profiles/dunkelflaute_*_factors.csv` | `figures/dunkelflaute_cf_profile.png` | Wind and solar derating factors, Jan–Feb 2021 stress window. | **Needs generation** |
| 6 | Worst-day dispatch stacked area chart | `results/dunkelflaute-smr/networks/base_s_10_elec_.nc` | `figures/worst_day_dispatch_2021-01-25.png` | Hourly (3-hourly) dispatch on 2021-01-25, lowest-VRE day. | **Needs generation** |
| 7 | Nuclear capacity built by scenario | `gamspy-de/results/*/nuclear_investment.csv`, PyPSA networks | `figures/nuclear_capacity_by_scenario.png` | New nuclear capacity (MW) at INRE sites. | **Needs generation** |
| 8 | PyPSA-Eur vs GAMSPy comparison | §10–11 tables | `figures/pypsa_gamspy_comparison.png` | Side-by-side normalised trends (wind, gas, nuclear). | **Needs generation** |

---

## 13. Key Result Statements for Report Text

1. The Dunkelflaute scenario increases operating cost by **41.5 M EUR** over the 2-week window, corresponding to **+15.5%** relative to the base case (266.9 → 308.4 M EUR OPEX).

2. CO₂ emissions increase from **1,020 ktCO₂** to **1,082 ktCO₂** (+6.1%) because reduced wind generation is primarily replaced by **CCGT** (+0.91 TWh, +20%), while coal dispatch falls to near zero.

3. Wind generation falls from **13.63 TWh** to **9.29 TWh** (−32%) under Dunkelflaute stress; this is the dominant generation shift across scenarios.

4. Total electricity load is **21.15 TWh** in all PyPSA scenarios, confirming full load served over the 336-hour window.

5. When SMR is available (dunkelflaute-smr), the optimiser builds **7,500 MW** across five sites (1,500 MW each), supplying **2.27 TWh** (~11% of generation) at ~90% capacity factor.

6. MSR and LFR scenarios build **4,500 MW** each (three sites), each supplying **1.36 TWh** over the 2-week period.

7. Nuclear scenarios reduce CO₂ only marginally vs dunkelflaute (**−5.1 kt** for SMR, **−1.9 kt** for MSR, **−0.3 kt** for LFR) because gas remains on the margin and the CO₂ cap is non-binding.

8. On the worst VRE day (**2021-01-25**), **CCGT supplies 45.7%** of daily energy, wind and solar combined **26.8%**, and nuclear SMR **12.5%** (in the SMR scenario).

9. Battery storage shows **zero discharge** in all PyPSA scenarios despite large optimiser capacity values — storage is **not** a meaningful flexibility provider in these runs.

10. GAMSPy reproduces the qualitative pattern — wind down, gas up, nuclear at site caps — but uses a **10-bus template** with saturated CO₂ (1,918 kt in all scenarios).

11. System LCOE rises from **104 EUR/MWh** (base) to **265 EUR/MWh** (dunkelflaute) when expressed as (OPEX + annuitised CAPEX) over load served for the 2-week period.

12. Dunkelflaute mainly shifts dispatch from **VRE to CCGT**; neither storage nor cross-border imports (not modelled) participate in covering the residual load.

---

## 14. Data Quality and Caveats

| Caveat | Detail |
|--------|--------|
| **2-week model window** | 336 hours (Jan 25 – Feb 7, 2021); LCOE/LCOA not annualised unless explicitly scaled. |
| **3-hour resolution** | Unit commitment not represented; CCGT can ramp freely. |
| **Non-binding CO₂ cap** | 50 Mt/yr → ~191 kt/2-week pro-rata; actual emissions ~1,020–1,082 kt. |
| **Coal/lignite still present** | ~40 GW combined; mostly must-run baseload though dispatch is low in stress scenarios. |
| **No cross-border trade** | Dunkelflaute shortfall cannot be met by imports (unlike real Germany). |
| **No sector coupling** | Electricity-only; no H₂ or heat revenues for nuclear. |
| **Phantom VRE/battery expansion** | `p_nom_opt` for wind/solar/battery can reach hundreds of GW with zero storage energy — **do not report as real build**. |
| **Nuclear at site cap** | Current runs build 1,500 MW/site (not dust), but economics are distorted by the short horizon. |
| **GAMSPy template inputs** | 10 buses, synthetic elastic VRE/storage; CO₂ flat at cap. |
| **compare_scenarios.py scaling** | Fixed in v2 (`results/inre-comparison-v2/`). **Do not use** `results/inre-comparison/` (old CO₂ ≈ 3,283 kt, wrong energy scaling). |
| **Solar cross-scenario comparison** | Base scenario does not apply Dunkelflaute profiles; solar TWh levels are not directly comparable as weather effects. |
| **Objective vs OPEX+CAPEX** | PyPSA objective (543.8–3,937.5 M EUR) differs from OPEX+CAPEX sum; both documented. |

---

## 15. Raw Source Files Used

### PyPSA-Eur

| File | Purpose |
|------|---------|
| `results/base/networks/base_s_10_elec_.nc` | Solved base network |
| `results/dunkelflaute/networks/base_s_10_elec_.nc` | Solved Dunkelflaute network |
| `results/dunkelflaute-smr/networks/base_s_10_elec_.nc` | Solved SMR network |
| `results/dunkelflaute-msr/networks/base_s_10_elec_.nc` | Solved MSR network |
| `results/dunkelflaute-lfr/networks/base_s_10_elec_.nc` | Solved LFR network |
| `results/inre-comparison-v2/comparison_table.csv` | KPI summary |
| `results/inre-comparison-v2/generation_mix_twh.csv` | Generation by carrier |
| `results/inre-comparison-v2/generation_mix_groups_twh.csv` | Aggregated generation |
| `results/inre-comparison-v2/capacity_gw.csv` | Capacity by carrier |
| `results/inre-comparison-v2/co2_by_carrier_kt.csv` | CO₂ by carrier |
| `results/inre-comparison-v2/report_summary.csv` | Report KPIs |
| `results/inre-comparison-v2/report_summary.txt` | Narrative summary |
| `results/inre-comparison-v2/report_tables.xlsx` | Combined tables |
| `results/inre-comparison-v2/costs_breakdown.png` | Cost figure |
| `results/inre-comparison-v2/co2_emissions.png` | CO₂ figure |
| `results/inre-comparison-v2/production_mix.png` | Generation mix figure |
| `results/inre-comparison-v2/capacity.png` | Capacity figure |
| `scripts/inre/compare_scenarios.py` | Extraction and plotting script |
| `config/inre/config.base.yaml` | Scenario configuration |
| `data/inre/dunkelflaute.yaml` | Dunkelflaute parameters |

### GAMSPy

| File | Purpose |
|------|---------|
| `gamspy-de/results/base/summary.yaml` | Objective, status |
| `gamspy-de/results/dunkelflaute/summary.yaml` | — |
| `gamspy-de/results/dunkelflaute-smr/summary.yaml` | — |
| `gamspy-de/results/dunkelflaute-msr/summary.yaml` | — |
| `gamspy-de/results/dunkelflaute-lfr/summary.yaml` | — |
| `gamspy-de/results/<scenario>/dispatch.csv` | Generation dispatch |
| `gamspy-de/results/<scenario>/investment.csv` | New capacity |
| `gamspy-de/results/<scenario>/storage_power.csv` | Storage power |
| `gamspy-de/results/<scenario>/storage_energy.csv` | Storage energy |
| `gamspy-de/results/<scenario>/nuclear_investment.csv` | Nuclear build (nuclear scenarios) |
| `gamspy-de/results/<scenario>/nuclear_dispatch.csv` | Nuclear dispatch |
| `gamspy-de/inputs/technologies.csv` | CO₂ factors |
| `gamspy-de/inputs/demand.csv` | Demand |
| `gamspy-de/profiles/dunkelflaute_wind_factors.csv` | Wind derating |
| `gamspy-de/profiles/dunkelflaute_solar_factors.csv` | Solar derating |

### Custom Dunkelflaute profiles

| File | Purpose |
|------|---------|
| `output/dunkelflaute/hourly_capacity_factors.csv` | Hourly CF and derating flags |
| `output/dunkelflaute/dunkelflaute_wind_factors.csv` | Wind derating (3-hourly) |
| `output/dunkelflaute/dunkelflaute_solar_factors.csv` | Solar derating (3-hourly) |
| `data/inre/profiles/dunkelflaute_wind_factors.csv` | Source profile (PyPSA) |
| `data/inre/profiles/dunkelflaute_solar_factors.csv` | Source profile (PyPSA) |

---

## 16. Recommended Results Section Structure

Proposed LaTeX structure for **Section 5: Results**:

```latex
\section{Results}
\label{sec:results}

\subsection{Simulation setup and scenario overview}
\label{sec:results:setup}
% Table: Model Runs Included (§1)
% 1 paragraph: 2-week Jan 2021 window, PyPSA-Eur vs GAMSPy tracks

\subsection{System-level performance indicators}
\label{sec:results:kpis}
% Table: PyPSA-Eur System-Level KPI Table (§2)
% Figure: costs_breakdown.png, co2_emissions.png

\subsection{Impact of the Dunkelflaute event}
\label{sec:results:dunkelflaute}
% Table: Dunkelflaute impact metrics (§8)
% Figure: dunkelflaute_cf_profile.png (to be generated)
% Key statements on VRE → gas shift

\subsection{Generation and capacity outcomes}
\label{sec:results:generation}
% Table: Generation mix by carrier (§5)
% Figure: production_mix.png
% Table: Existing vs new capacity (§6) — with phantom-expansion caveat

\subsection{Scenario comparisons}
\label{sec:results:deltas}
% Table: Delta vs base (§3)
% Table: Delta vs dunkelflaute (§4)

\subsection{Nuclear investment and dispatch}
\label{sec:results:nuclear}
% Tables: §7.1–7.3
% Figure: nuclear_capacity_by_scenario.png (to be generated)
% Discussion: site-cap builds, short-horizon artefact

\subsection{Worst-day system dispatch}
\label{sec:results:worstday}
% Table: §9
% Figure: worst_day_dispatch_2021-01-25.png (to be generated)

\subsection{GAMSPy sensitivity results}
\label{sec:results:gamspy}
% Table: §10
% Disclaimer on template model

\subsection{Cross-model comparison}
\label{sec:results:comparison}
% Table: PyPSA vs GAMSPy (§11)
% Figure: pypsa_gamspy_comparison.png (optional)

\subsection{Summary of key findings}
\label{sec:results:summary}
% Bullet list from §13

% Discussion of limitations → link to Data Quality caveats (§14)
```

**Suggested placement order in report:** KPI table and cost/CO₂ figures first → Dunkelflaute impact → generation mix → nuclear subsection → worst-day dispatch → GAMSPy appendix-style comparison → summary bullets.

---

*Generated: 2026-07-07. Values extracted from solved networks in `results/*/networks/base_s_10_elec_.nc` and `gamspy-de/results/` using period-correct integration (336 h, 3-hourly snapshots).*
