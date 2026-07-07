# INRE Results — Final Report Package

**Status:** Authoritative, report-ready (2026-07-07)  
**Use this file** for Results section writing and handoff to other tools.  
**Project:** Integration of nuclear and renewables for Dunkelflaute resilience in the German electricity system

**Simulation window:** 14 days, 112 snapshots, 3-hour resolution (**336 hours**) — 2021-01-25 to 2021-02-07  
**Energy units:** TWh integrated over the 2-week period unless stated otherwise.

---

## Data sources (authoritative)

| What | Where |
|------|-------|
| Solved PyPSA networks | `results/{base,dunkelflaute,dunkelflaute-smr,dunkelflaute-msr,dunkelflaute-lfr}/networks/base_s_10_elec_.nc` |
| KPI tables (v2) | `results/inre-comparison-v2/` |
| Extraction script | `scripts/inre/compare_scenarios.py` |
| Solar fixed-cap sensitivity | `results/{base,dunkelflaute}-fixedcap/networks/base_s_10_elec_.nc` |

**Do not use:** `results/inre-comparison/` (v1 — wrong CO₂ scaling).  
**Audit trail only:** [RESULTS_SECTION_DATA.md](RESULTS_SECTION_DATA.md)

---

## 1. Executive summary (headline findings)

1. **Dunkelflaute reduces wind generation by 32%** (13.63 → 9.29 TWh) — primary interpretable stress signal.
2. **Period OPEX rises 15.5%** (266.9 → 308.4 M EUR) from base to dunkelflaute.
3. **CCGT fills the gap** (+0.91 TWh, +20%); coal dispatch falls to near zero under stress.
4. **CO₂ rises 6.1%** (1,020 → 1,082 kt), below the non-binding pro-rata cap of **1,918 kt** (50 Mt/yr × 336/8760).
5. **Nuclear builds to site caps** when enabled (SMR 7,500 MW; MSR/LFR 4,500 MW), supplying 1.36–2.27 TWh — **model outcome, not a deployment recommendation**.
6. **CO₂ abatement vs dunkelflaute-only is marginal** (≤5.1 kt for SMR); **LCOA is unstable / not policy-grade**.
7. **Phantom VRE and link-based battery capacities** (hundreds of GW) are numerical artefacts — exclude from capacity headlines.
8. **Solar TWh in main scenarios is not interpretable** for Dunkelflaute impact (profile mismatch + phantom solar expansion). See §10 for fixed-solar sensitivity.

---

## 2. Metric definitions — which number to use

| Metric | Source | Units | Use for |
|--------|--------|-------|---------|
| **Period OPEX** | `n.statistics.opex()` | EUR / 336 h | **Headline operational comparisons** |
| **Solver objective** | `n.objective` | EUR / 336 h | LP optimum; distorted by phantom CAPEX in stress runs |
| **Annuitised fleet CAPEX** | `n.statistics.capex()` | **EUR/year** | Context only — **never add to period OPEX** |
| **Period-scaled CAPEX** | annual CAPEX × (336/8760) | EUR / 336 h | Bridge metric; can diverge from objective |
| **Operational LCOE** | period OPEX / load | EUR/MWh | **Headline** cost intensity |
| **Period all-in LCOE** | objective / load | EUR/MWh | Secondary, caveated |
| **LCOA** | Δcost / ΔCO₂ | EUR/tCO₂ avoided | Appendix only if \|ΔCO₂\| < 10 kt |

**Never call both objective and (OPEX + annual CAPEX) “total system cost”.** They have different units and meanings.

---

## 3. Scenario overview

| Scenario | Dunkelflaute | Nuclear | Network path |
|----------|:------------:|---------|--------------|
| base | no | — | `results/base/networks/base_s_10_elec_.nc` |
| dunkelflaute | yes | — | `results/dunkelflaute/networks/base_s_10_elec_.nc` |
| dunkelflaute-smr | yes | SMR (5×1,500 MW) | `results/dunkelflaute-smr/networks/base_s_10_elec_.nc` |
| dunkelflaute-msr | yes | MSR (3×1,500 MW) | `results/dunkelflaute-msr/networks/base_s_10_elec_.nc` |
| dunkelflaute-lfr | yes | LFR (3×1,500 MW) | `results/dunkelflaute-lfr/networks/base_s_10_elec_.nc` |

CO₂ policy: **50 Mt/yr** → pro-rata window cap **1,918 ktCO₂** (non-binding in PyPSA; emissions 1,020–1,082 kt).

---

## 4. System-level KPIs (PyPSA-Eur, cleaned)

| Scenario | Load (TWh) | Period OPEX (M EUR) | Annuitised CAPEX (M EUR/yr) | Solver objective (M EUR) | CO₂ (kt) | Operational LCOE (EUR/MWh) | Nuclear (MW) |
|----------|----------:|--------------------:|----------------------------:|-------------------------:|---------:|---------------------------:|-------------:|
| base | 21.15 | 266.9 | 1,935.7 | 543.8 | 1,020 | 12.6 | 0 |
| dunkelflaute | 21.15 | 308.4 | 5,287.9 | 3,937.5 | 1,082 | 14.6 | 0 |
| dunkelflaute-smr | 21.15 | 335.8 | 4,499.5 | 3,176.4 | 1,077 | 15.9 | **7,500** |
| dunkelflaute-msr | 21.15 | 322.9 | 4,817.8 | 3,481.8 | 1,080 | 15.3 | **4,500** |
| dunkelflaute-lfr | 21.15 | 323.9 | 4,809.7 | 3,474.8 | 1,082 | 15.3 | **4,500** |

*Source: `results/inre-comparison-v2/report_summary.csv`*

---

## 5. Dunkelflaute impact — base → dunkelflaute

| Metric | base | dunkelflaute | Change | Report? |
|--------|-----:|-------------:|-------:|:-------:|
| Wind (TWh) | 13.63 | 9.29 | **−4.34 (−32%)** | **Yes** |
| CCGT (TWh) | 4.55 | 5.46 | **+0.91 (+20%)** | **Yes** |
| Period OPEX (M EUR) | 266.9 | 308.4 | **+41.5 (+15.5%)** | **Yes** |
| CO₂ (kt) | 1,020 | 1,082 | +62 (+6.1%) | Yes |
| Solar (TWh) | 0.70 | 3.78 | +3.08 | **No** (artefact) |

---

## 6. Generation mix (TWh, 2-week period)

| Group | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|-------|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| Wind | 13.63 | 9.29 | 7.99 | 8.40 | 8.39 |
| Solar\* | 0.70 | 3.78 | 2.82 | 3.31 | 3.31 |
| CCGT | 4.55 | 5.46 | 5.43 | 5.45 | 5.46 |
| Biomass | 1.94 | 2.69 | 2.69 | 2.69 | 2.69 |
| Nuclear SMR | — | — | 2.27 | — | — |
| Nuclear MSR | — | — | — | 1.36 | — |
| Nuclear LFR | — | — | — | — | 1.36 |
| **Total** | **21.21** | **21.24** | **21.22** | **21.23** | **21.23** |

\*Solar cross-scenario comparison not interpretable (§9).

*Source: `results/inre-comparison-v2/generation_mix_groups_twh.csv`*

---

## 7. Credible capacity (exclude phantom VRE/battery)

| Technology | base | dunkelflaute | dunkelflaute-smr | dunkelflaute-msr | dunkelflaute-lfr |
|------------|-----:|-------------:|-----------------:|-----------------:|-----------------:|
| Existing wind (GW) | 84.5 | 84.5 | 84.5 | 84.5 | 84.5 |
| Existing solar (GW) | 48.8 | 48.8 | 48.8 | 48.8 | 48.8 |
| CCGT (GW) | 30.8 | 36.9 | 35.2 | 35.8 | 36.6 |
| SMR (MW) | 0 | 0 | **7,500** | 0 | 0 |
| MSR (MW) | 0 | 0 | 0 | **4,500** | 0 |
| LFR (MW) | 0 | 0 | 0 | 0 | **4,500** |

Phantom optimiser values (onshore wind up to 488 GW, solar up to 916 GW, link battery up to 414 GW) are in Appendix only.

*Source: `results/inre-comparison-v2/credible_capacity.csv`*

---

## 8. Nuclear results

| Scenario | Built (MW) | Generation (TWh) | Avg CF |
|----------|----------:|-----------------:|-------:|
| dunkelflaute-smr | 7,500 | 2.27 | ~90% |
| dunkelflaute-msr | 4,500 | 1.36 | ~90% |
| dunkelflaute-lfr | 4,500 | 1.36 | ~90% |

Sites filled to **1,500 MW** each (Grohnde, Brokdorf, Isar, Emsland, Neckarwestheim — subset per technology).

**Interpretation:** Endogenous LP outcome under 2-week horizon and site caps. **Not** a policy deployment recommendation.

---

## 9. Scenario deltas

### vs base

| Scenario | Δ OPEX (M EUR) | Δ OPEX (%) | Δ CO₂ (kt) | Δ wind (TWh) |
|----------|---------------:|-----------:|-----------:|-------------:|
| dunkelflaute | +41.5 | +15.5% | +62 | −4.34 |
| dunkelflaute-smr | +68.9 | +25.8% | +57 | −5.64 |
| dunkelflaute-msr | +56.0 | +21.0% | +60 | −5.23 |
| dunkelflaute-lfr | +57.0 | +21.4% | +62 | −5.24 |

### vs dunkelflaute (nuclear incremental)

| Scenario | Δ OPEX (M EUR) | Δ CO₂ (kt) | Δ nuclear (MW) | Abatement meaningful? |
|----------|---------------:|-----------:|---------------:|:---------------------:|
| dunkelflaute-smr | +27.4 | −5.1 | +7,500 | Borderline |
| dunkelflaute-msr | +14.5 | −1.9 | +4,500 | No |
| dunkelflaute-lfr | +15.5 | −0.3 | +4,500 | No |

---

## 10. Solar fixed-capacity sensitivity (dispatch-only)

**Problem:** Main scenarios show solar **increasing** under Dunkelflaute (0.70 → 3.78 TWh) due to phantom solar `p_nom_opt` expansion and non-comparable profiles.

**Fix applied:** Re-solve with solar capacity fixed to base levels (`scripts/inre/dispatch_fixed_solar.py`):
- `results/base-fixedcap/networks/base_s_10_elec_.nc`
- `results/dunkelflaute-fixedcap/networks/base_s_10_elec_.nc`

| Metric | base-fixedcap | dunkelflaute-fixedcap | Interpretation |
|--------|-------------:|----------------------:|----------------|
| Solar (TWh) | 0.705 | **0.203** | Solar **falls** under stress when capacity is comparable |
| Wind (TWh) | 13.61 | 9.29 | Consistent with main scenarios |
| Load shedding (TWh) | 0 | **3.51** | Supply shortfall when phantom investments removed |

**Note:** Dunkelflaute-fixedcap uses high-cost load shedding to maintain feasibility; its OPEX/objective (~35,450 M EUR) is **not comparable** to main scenarios — it reflects the penalty for unserved energy, not operational cost. Use this run **only** to show solar direction and adequacy gap, not for cost headlines.

---

## 11. LCOA — unstable (appendix only)

Reference: dunkelflaute. Threshold: \|ΔCO₂\| < 10 kt → not policy-grade.

| Scenario | Δ CO₂ (kt) | Δ OPEX (M EUR) | Policy-grade? |
|----------|----------:|---------------:|:-------------:|
| dunkelflaute-smr | −5.1 | +27.4 | **No** |
| dunkelflaute-msr | −1.9 | +14.5 | **No** |
| dunkelflaute-lfr | −0.3 | +15.5 | **No** |

**Do not headline negative abatement costs.**

*Source: `results/inre-comparison-v2/lcoa_vs_dunkelflaute.csv`*

---

## 12. GAMSPy (qualitative sensitivity only)

| Trend | PyPSA | GAMSPy |
|-------|-------|--------|
| Wind down under stress | −32% | Sharp reduction |
| Gas fills gap | CCGT +20% | CCGT up |
| Nuclear at site caps | 7.5 / 4.5 GW | Same order |
| CO₂ | 1,020–1,082 kt (below cap) | Flat 1,918 kt (cap-saturated) |

GAMSPy confirms **directional** trends only; absolute levels not comparable.

---

## 13. Caveats (mandatory in report)

| Issue | Action |
|-------|--------|
| 2-week window | Investment outcomes not annual/policy-grade |
| CO₂ cap | 1,918 kt pro-rata; non-binding in PyPSA |
| Phantom VRE/battery | Exclude from capacity headlines |
| Solar in main scenarios | Do not interpret cross-scenario solar TWh |
| Objective in stress runs | Inflated by phantom CAPEX — use period OPEX for cost |
| Nuclear site-cap builds | Model structural outcome, not recommendation |
| LCOA | Unstable; appendix only |
| Fixed-cap run | Solar/adequacy sensitivity only; cost not comparable |

---

## 14. Recommended Results section text (copy-ready)

> Over a 14-day January 2021 window, the Dunkelflaute stress scenario reduces wind generation by 32% (13.6 → 9.3 TWh) and increases period operating cost by 15.5% (267 → 308 M EUR), with combined-cycle gas filling most of the gap (+20%). CO₂ emissions rise by 6% to 1,082 kt, remaining below the non-binding 50 Mt/yr cap (1,918 kt pro-rata). When nuclear is enabled, the optimiser builds to per-site caps (7.5 GW SMR / 4.5 GW MSR or LFR) and supplies 1.4–2.3 TWh baseload, reducing emissions by at most 5 kt relative to stress-only — too small for meaningful abatement-cost interpretation. Large optimiser-reported VRE and link-based battery capacities are numerical artefacts of the short horizon and uncapped extendable carriers and are excluded from capacity findings. Solar generation changes in the main scenario table are not interpreted as Dunkelflaute impacts; a fixed-solar dispatch sensitivity shows solar output falling under stress (0.70 → 0.20 TWh) while revealing a supply adequacy gap.

---

## Appendix A — Do not headline

- Full phantom capacity: `results/inre-comparison-v2/capacity_gw.csv`
- Deprecated LCOE (OPEX + annual CAPEX / period load): base ~104, dunkelflaute ~265 EUR/MWh — **wrong units**
- CO₂ by carrier: `results/inre-comparison-v2/co2_by_carrier_kt.csv`

---

*Generated: 2026-07-07. PyPSA-Eur v2 extraction + solar fixed-cap sensitivity.*
