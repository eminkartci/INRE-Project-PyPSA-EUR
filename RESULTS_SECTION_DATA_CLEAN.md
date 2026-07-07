# Results Section Data Package (Report-Ready)

> **Superseded by:** [RESULTS_FINAL.md](RESULTS_FINAL.md) — use that file for report writing and AI handoff.

**Project:** Integration of nuclear and renewables for Dunkelflaute resilience in the German electricity system  
**Simulation window:** 14 days, 112 snapshots, 3-hour resolution (336 hours) — **2021-01-25 to 2021-02-07**  
**Energy unit convention:** All TWh values are **integrated over the 2-week simulation period** unless explicitly labelled as annualised extrapolations.

**Authoritative data source:** Solved PyPSA-Eur networks (`results/*/networks/base_s_10_elec_.nc`) extracted with period-correct integration via `scripts/inre/compare_scenarios.py` → `results/inre-comparison-v2/`.

**Superseded:** `results/inre-comparison/` (v1, wrong CO₂ scaling) and narrative in `INRE-PROGRESS-REPORT.md` §6.8–7.7 from earlier runs (zero nuclear, no phantom expansion). Audit trail preserved in [RESULTS_SECTION_DATA.md](RESULTS_SECTION_DATA.md).

---

## 1. Executive Summary — Robust Headline Findings

1. **Dunkelflaute reduces wind generation by 32%** (13.63 → 9.29 TWh) over the 2-week window; this is the primary interpretable stress signal.
2. **Period OPEX rises 15.5%** (266.9 → 308.4 M EUR) from base to dunkelflaute; use **period OPEX** for operational cost comparisons.
3. **CCGT fills the gap** (+0.91 TWh, +20%); coal dispatch falls to near zero in stress scenarios.
4. **CO₂ emissions rise 6.1%** (1,020 → 1,082 kt), remaining **below** the non-binding pro-rata cap of **1,918 kt** (50 Mt/yr × 336/8760).
5. When nuclear is enabled, the optimiser **builds to per-site caps** (SMR 7,500 MW; MSR/LFR 4,500 MW each) and supplies **1.36–2.27 TWh** baseload — an **endogenous LP outcome**, not a deployment recommendation.
6. **CO₂ abatement vs dunkelflaute-only is marginal** (≤5.1 kt for SMR); **LCOA is unstable / not policy-grade** at this scale.
7. **Large optimiser-reported VRE and link-based battery capacities are numerical artefacts** (short horizon + uncapped extendable carriers); exclude from capacity findings.
8. **Solar TWh changes across scenarios are not interpretable** for Dunkelflaute impact (different profiles + phantom solar expansion).

---

## 2. Metric Definitions — Which Number to Use

| Metric | Source | Units | Use for |
|--------|--------|-------|---------|
| **Solver objective (period)** | `n.objective` | EUR over 336 h | LP optimum; period all-in cost (distorted by phantom CAPEX in stress runs) |
| **Period OPEX** | `n.statistics.opex()` | EUR over 336 h | **Headline operational cost comparisons** |
| **Annuitised fleet CAPEX** | `n.statistics.capex()` | **EUR/year** | Context on optimal fleet; **never add directly to period OPEX** |
| **Period-scaled CAPEX** | `capex_annual × (336/8760)` | EUR over 336 h | Approximate capital charge for window; can diverge from objective when link/storage artefacts dominate |
| **Operational LCOE** | period OPEX / load served | EUR/MWh | **Headline** cost intensity |
| **Period all-in LCOE** | solver objective / load served | EUR/MWh | Secondary; caveated |
| **Operational LCO₂** | period OPEX / (CO₂ kt × 1,000) | EUR/tCO₂ | Headline emissions-cost proxy |
| **LCOA** | Δcost / ΔCO₂ vs reference | EUR/tCO₂ avoided | **Appendix only** if \|ΔCO₂\| < 10 kt |

**Do not use the label “total system cost” for both objective and OPEX+annual CAPEX.** They are different metrics with different units.

**Objective vs OPEX + period-scaled CAPEX:** For `base`, objective (543.8 M EUR) exceeds OPEX + scaled CAPEX (341.1 M EUR). For `dunkelflaute`, objective (3,937.5 M EUR) greatly exceeds OPEX + scaled CAPEX (511.2 M EUR) because phantom link/storage/VRE investment enters the LP objective. **Do not interpret objective differences as operational savings.**

---

## 3. PyPSA-Eur System-Level KPI Table (Cleaned)

| Scenario | Load (TWh) | Period OPEX (M EUR) | Annuitised CAPEX (M EUR/yr) | Period-scaled CAPEX (M EUR) | Solver objective (M EUR) | CO₂ (kt) | Operational LCOE (EUR/MWh) | Period all-in LCOE (EUR/MWh) | Nuclear built (MW) | Battery SU power (MW)\* |
|----------|----------:|--------------------:|----------------------------:|----------------------------:|-------------------------:|---------:|---------------------------:|-----------------------------:|-------------------:|------------------------:|
| base | 21.15 | 266.9 | 1,935.7 | 74.2 | 543.8 | 1,020 | 12.6 | 25.7 | 0 | 35 |
| dunkelflaute | 21.15 | 308.4 | 5,287.9 | 202.8 | 3,937.5 | 1,082 | 14.6 | 186.2 | 0 | 29,316 |
| dunkelflaute-smr | 21.15 | 335.8 | 4,499.5 | 172.6 | 3,176.4 | 1,077 | 15.9 | 150.2 | **7,500** | 15,188 |
| dunkelflaute-msr | 21.15 | 322.9 | 4,817.8 | 184.8 | 3,481.8 | 1,080 | 15.3 | 164.6 | **4,500** | 12,717 |
| dunkelflaute-lfr | 21.15 | 323.9 | 4,809.7 | 184.5 | 3,474.8 | 1,082 | 15.3 | 164.3 | **4,500** | 12,129 |

\*Battery SU = `StorageUnit` carrier `battery` (credible component); link-based “Battery Storage” capacities in Appendix A are artefacts.

**CO₂ cap (pro-rata):** 50 Mt/yr × 336/8760 ≈ **1,918 ktCO₂** — non-binding in all PyPSA scenarios (emissions 1,020–1,082 kt).

*Source: `results/inre-comparison-v2/report_summary.csv`*

---

## 4. Dunkelflaute Impact — base → dunkelflaute

| Metric | base | dunkelflaute | Change | Interpretable? |
|--------|-----:|-------------:|-------:|:--------------|
| Wind generation (TWh) | 13.63 | 9.29 | **−4.34 (−32%)** | **Yes** |
| CCGT generation (TWh) | 4.55 | 5.46 | **+0.91 (+20%)** | **Yes** |
| Fossil total (TWh) | 4.92 | 5.46 | +0.54 (+11%) | Yes |
| Period OPEX (M EUR) | 266.9 | 308.4 | **+41.5 (+15.5%)** | **Yes** |
| CO₂ (kt) | 1,020 | 1,082 | +62 (+6.1%) | Yes |
| Solar generation (TWh) | 0.70 | 3.78 | +3.08 (+438%) | **No** — see §10 |

---

## 5. Generation Mix by Carrier Group (TWh, 2-week period)

| Group | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|-------|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| Wind (all) | 13.63 | 9.29 | 7.99 | 8.40 | 8.39 |
| Solar (all)\* | 0.70 | 3.78 | 2.82 | 3.31 | 3.31 |
| CCGT | 4.55 | 5.46 | 5.43 | 5.45 | 5.46 |
| Biomass | 1.94 | 2.69 | 2.69 | 2.69 | 2.69 |
| Nuclear SMR | — | — | 2.27 | — | — |
| Nuclear MSR | — | — | — | 1.36 | — |
| Nuclear LFR | — | — | — | — | 1.36 |
| **Total generation** | **21.21** | **21.24** | **21.22** | **21.23** | **21.23** |

\*Solar cross-scenario levels are **not** interpretable as a pure Dunkelflaute weather effect (§10).

*Source: `results/inre-comparison-v2/generation_mix_groups_twh.csv`*

---

## 6. Credible Capacity Table

Initial fleet from `p_nom`; extendable outcomes from `p_nom_opt` for CCGT and nuclear only.

| Technology | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr | Notes |
|------------|-----:|-------------:|-----------------:|-----------------:|-----------------:|-------|
| Existing wind (GW) | 84.5 | 84.5 | 84.5 | 84.5 | 84.5 | Initial `p_nom` |
| Existing solar (GW) | 48.8 | 48.8 | 48.8 | 48.8 | 48.8 | Initial `p_nom` |
| CCGT (GW) | 30.8 | 36.9 | 35.2 | 35.8 | 36.6 | Credible extendable build |
| SMR (MW) | 0 | 0 | **7,500** | 0 | 0 | 5 × 1,500 MW site cap |
| MSR (MW) | 0 | 0 | 0 | **4,500** | 0 | 3 × 1,500 MW |
| LFR (MW) | 0 | 0 | 0 | 0 | **4,500** | 3 × 1,500 MW |
| Battery SU power (MW)\* | 35 | 29,316 | 15,188 | 12,717 | 12,129 | Short-horizon artefact; not policy-grade |
| Battery SU energy (GWh)\* | 0.2 | 176 | 91 | 76 | 73 | Implied from `p_nom_opt × max_hours` |

\*Battery StorageUnit values are reported for transparency but treated as **model artefacts** in headline capacity findings.

*Source: `results/inre-comparison-v2/credible_capacity.csv`*

---

## 7. Nuclear Investment and Dispatch

| Scenario | Technology | Built (MW) | Generation (TWh) | Avg CF (if built) |
|----------|------------|----------:|-----------------:|------------------:|
| dunkelflaute-smr | SMR | 7,500 | 2.27 | ~90% |
| dunkelflaute-msr | MSR | 4,500 | 1.36 | ~90% |
| dunkelflaute-lfr | LFR | 4,500 | 1.36 | ~90% |

**Per-site build (all active sites at 1,500 MW):**

| Site | SMR (MW) | MSR (MW) | LFR (MW) |
|------|--------:|---------:|---------:|
| Grohnde | 1,500 | 1,500 | 1,500 |
| Brokdorf | 1,500 | 1,500 | 1,500 |
| Isar | 1,500 | 1,500 | — |
| Emsland | 1,500 | — | 1,500 |
| Neckarwestheim | 1,500 | — | — |

**Interpretation:** Nuclear at site cap is a **model outcome** under the 2-week horizon, annuitised-cost formulation, and non-binding CO₂ cap. It is **not** a validated deployment pathway or policy recommendation. Earlier development runs with sub-kW “dust” builds are superseded by these v2 networks.

---

## 8. Scenario Deltas

### 8.1 vs base

| Scenario | Δ OPEX (M EUR) | Δ OPEX (%) | Δ CO₂ (kt) | Δ wind (TWh) | Δ CCGT (TWh) |
|----------|---------------:|-----------:|-----------:|-------------:|-------------:|
| dunkelflaute | +41.5 | +15.5% | +62 | −4.34 | +0.91 |
| dunkelflaute-smr | +68.9 | +25.8% | +57 | −5.64 | +0.87 |
| dunkelflaute-msr | +56.0 | +21.0% | +60 | −5.23 | +0.90 |
| dunkelflaute-lfr | +57.0 | +21.4% | +62 | −5.24 | +0.91 |

### 8.2 vs dunkelflaute (nuclear incremental)

| Scenario | Δ OPEX (M EUR) | Δ CO₂ (kt) | Δ nuclear (MW) | Δ CCGT (TWh) | Meaningful abatement? |
|----------|---------------:|-----------:|---------------:|-------------:|----------------------|
| dunkelflaute-smr | +27.4 | −5.1 | +7,500 | −0.03 | Borderline (small) |
| dunkelflaute-msr | +14.5 | −1.9 | +4,500 | −0.01 | No |
| dunkelflaute-lfr | +15.5 | −0.3 | +4,500 | ~0 | No |

---

## 9. LCOA — Unstable, Appendix Only

Reference: **dunkelflaute**. Threshold: \|ΔCO₂\| < 10 kt → **not policy-grade**.

| Scenario | Δ CO₂ (kt) | Δ OPEX (M EUR) | Δ objective (M EUR) | LCOA operational | LCOA all-in | Policy-grade? |
|----------|----------:|---------------:|--------------------:|-----------------:|------------:|:-------------|
| dunkelflaute-smr | −5.1 | +27.4 | −761.1 | — | — | **No** |
| dunkelflaute-msr | −1.9 | +14.5 | −455.7 | — | — | **No** |
| dunkelflaute-lfr | −0.3 | +15.5 | −462.7 | — | — | **No** |

**Do not headline negative abatement costs.** The SMR case shows lower solver objective than dunkelflaute despite higher OPEX because phantom VRE/link CAPEX differs between scenarios — not a real cost saving.

*Source: `results/inre-comparison-v2/lcoa_vs_dunkelflaute.csv`*

**Recommended wording:** *“SMR displaces ~5 kt CO₂ (−0.5%) vs dunkelflaute-only; abatement cost is not meaningful at this scale.”*

---

## 10. GAMSPy Sensitivity (Qualitative)

| Aspect | PyPSA-Eur | GAMSPy DE | Agreement |
|--------|-----------|-----------|-----------|
| Wind down under stress | −32% | Sharp reduction | Directional yes |
| Gas fills gap | CCGT +20% | CCGT up | Yes |
| Nuclear at site caps | 7.5 / 4.5 GW | Same magnitudes | Yes |
| CO₂ | 1,020–1,082 kt (below cap) | Flat 1,918 kt (cap-saturated) | Partial — different cap binding |
| VRE/storage build | Phantom in statistics | Very large template build | Both unphysical |

GAMSPy CO₂ flat at **1,918 kt** reflects **binding cap behaviour** in the 10-bus template, not comparable absolute emissions to PyPSA.

---

## 11. Data Quality Caveats

| Caveat | Detail |
|--------|--------|
| **2-week window** | 336 h; investment decisions distorted by short horizon |
| **CO₂ cap** | 50 Mt/yr → **1,918 kt** over 336 h (not 191 kt); non-binding in PyPSA |
| **Phantom VRE expansion** | `p_nom_opt` hundreds of GW for wind/solar; do not report as real build |
| **Link-based battery** | Hundreds of GW in `capacity_gw.csv`; artefact — use credible table §6 |
| **Solar cross-scenario** | Base has no Dunkelflaute profile; stress has profiles + phantom solar — **not comparable** |
| **Objective inflation** | Stress scenarios: objective dominated by phantom capital terms |
| **Nuclear at site cap** | Endogenous LP outcome; not a deployment recommendation |
| **LCOA** | Unstable when ΔCO₂ < 10 kt |

---

## 12. Recommended Report Wording (LaTeX §5)

> Over a 14-day January 2021 window, the Dunkelflaute stress scenario reduces wind generation by 32% (13.6 → 9.3 TWh) and increases period operating cost by 15.5% (267 → 308 M EUR), with combined-cycle gas filling most of the gap (+20%). CO₂ emissions rise by 6% to 1,082 kt, remaining below the non-binding 50 Mt/yr cap (1,918 kt pro-rata). When nuclear is enabled, the optimiser builds to per-site caps (7.5 GW SMR / 4.5 GW MSR or LFR) and supplies 1.4–2.3 TWh baseload, reducing emissions by at most 5 kt relative to stress-only — too small for meaningful abatement-cost interpretation. Large optimiser-reported VRE and link-based battery capacities are numerical artefacts of the short horizon and uncapped extendable carriers; they are excluded from capacity findings. Solar generation changes across scenarios are not interpreted as Dunkelflaute impacts because stress profiles are applied only in Dunkelflaute runs and phantom solar expansion is present.

---

## Appendix A — Optimiser Artefact Tables (Do Not Headline)

### A.1 Full optimal capacity (`capacity_gw.csv`)

Includes phantom onshore wind (up to 488 GW), solar (up to 916 GW), and link-based battery storage (up to 414 GW). See `results/inre-comparison-v2/capacity_gw.csv`.

### A.2 Deprecated mixed-unit LCOE (v1 document)

Do **not** use LCOE = (OPEX + annual CAPEX) / period load. Example of removed values: base 104 EUR/MWh, dunkelflaute 265 EUR/MWh — dimensionally inconsistent.

### A.3 CO₂ by carrier (kt, 2-week period)

| Emitter | base | dunkelflaute | dunkelflaute-smr |
|---------|-----:|-------------:|-----------------:|
| CCGT | 901 | 1,081 | 1,074 |
| Coal | 108 | ~0 | ~0 |
| OCGT | 10 | ~0 | ~2 |
| **Total** | **1,020** | **1,082** | **1,077** |

*Source: `results/inre-comparison-v2/co2_by_carrier_kt.csv`*

---

## Raw Source Files

| File | Purpose |
|------|---------|
| `results/inre-comparison-v2/report_summary.csv` | Cleaned KPIs |
| `results/inre-comparison-v2/credible_capacity.csv` | Credible capacity |
| `results/inre-comparison-v2/lcoa_vs_dunkelflaute.csv` | LCOA (unstable) |
| `results/inre-comparison-v2/generation_mix_groups_twh.csv` | Generation groups |
| `results/inre-comparison-v2/capacity_gw.csv` | Appendix artefact capacities |
| `scripts/inre/compare_scenarios.py` | Extraction script |

*Generated: 2026-07-07. Values from solved networks with period-correct integration (336 h, 3-hourly snapshots).*
