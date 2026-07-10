# Construction of the Stylised Extreme Dunkelflaute

## Rationale

A stylised extreme Dunkelflaute scenario was selected instead of downloading additional multi-year weather datasets. The project already holds a fixed-capacity PyPSA Base case and a local 2021 Atlite cutout archive (`europe-2021-sarah3-era5`). These assets are sufficient to construct a transparent 28-day stress window without new large downloads.

The Dunkelflaute is represented as a deterministic and non-probabilistic resilience stress test rather than as a historical replay. The original Base-case renewable availability profiles are retained exactly during the fourteen-day core period. The seven-day pre-event and post-event buffers are reconstructed from the same local Atlite cutout and spatial availability matrices used by the PyPSA-Eur workflow, while a carrier-specific stress envelope reduces wind and solar availability during the fourteen-day core event.

No return period or occurrence probability is assigned to the scenario.

## Base profiles and 28-day window

Renewable availability is read from `network.generators_t.p_max_pu` for the authoritative 14-day Base network (`results/base/networks/base_s_10_elec_.nc`). The Base window (2021-01-25 to 2021-02-07, 3-hour resolution, 112 snapshots) forms the **core** of the event.

Because the solved Base network covers only 14 days, pre- and post-event buffer days (seven days each) are assembled from the same local Atlite cutout and PyPSA-Eur availability matrices used to build the cluster profiles. Buffer profiles are **not** created by copying or repeating existing days. After assembly, the 14-day core is overwritten with the exact Base `p_max_pu` values.

The buffer and core are produced through two related but not identical profile sources. Their stitching at the core boundaries is explicitly validated (`profile_stitch_validation.csv`, stitch zoom plots).

The full simulation window is:

- Days 1–7: pre-event buffer (cutout-derived)
- Days 8–21: 14-day Dunkelflaute core (exact Base profiles)
- Days 22–28: post-event buffer (cutout-derived)

Total duration: 28 days at 3-hour resolution (224 snapshots).

## Core sub-structure

Within the 14-day core:

- First 2 days: smooth transition into stress (48 hours, 16 snapshots at 3 h)
- Central 10 days: full-stress plateau (`s(t) = 1`, 80 snapshots)
- Final 2 days: smooth transition out of stress (48 hours, 16 snapshots)

Transitions use elapsed clock time (hours), not row indices.

## Severity assumptions

Three explicit deterministic stress levels are defined (not historical observations, probabilities, or climate projections):

| Scenario | Onshore remaining | Offshore remaining | Solar remaining |
|----------|-------------------|--------------------|-----------------|
| `stylised-df-moderate-v4` | 0.35 | 0.40 | 0.30 |
| `stylised-df-severe-v4` (main report) | 0.20 | 0.25 | 0.15 |
| `stylised-df-extreme-v4` | 0.10 | 0.15 | 0.10 |

The severe case was selected as the principal resilience test because it reduces total available VRE energy by approximately 64% over the fourteen-day core while preserving the underlying spatial and chronological variability. The moderate and extreme profiles are retained as lower- and upper-severity sensitivities.

Carrier mapping:

- `onwind` → onshore
- `offwind-ac`, `offwind-dc`, `offwind-float` → offshore
- `solar`, `solar-hsat` → solar

## Mathematical transformation

For carrier group \(k\), let \(r_k\) be the remaining ratio and \(s(t) \in [0,1]\) the stress intensity.

**Raised-cosine transitions** (48 h each):

- Transition in: \(s(t) = 0.5 \left[1 - \cos\left(\pi \cdot \mathrm{elapsed\_hours} / 48\right)\right]\)
- Plateau: \(s(t) = 1\)
- Transition out: \(s(t) = 0.5 \left[1 + \cos\left(\pi \cdot \mathrm{elapsed\_hours\_from\_transition\_start} / 48\right)\right]\)
- Outside core: \(s(t) = 0\)

Transition-out begins at `core_start + (core_days × 24 − transition_hours)`.

**Derating multiplier:**

\[
m[k,t] = 1 - s(t)(1 - r_k)
\]

**Generator availability:**

\[
p_{df}[g,t] = p_{base}[g,t] \cdot m[k,t]
\]

At full stress, \(p_{df}[g,t] = r_k \cdot p_{base}[g,t]\). Outside the core, \(p_{df}[g,t] = p_{base}[g,t]\). Values satisfy \(0 \le p_{df}[g,t] \le p_{base}[g,t] \le 1\). No random noise is added. Night-time solar (where \(p_{base}=0\)) remains zero.

## Fixed-capacity comparison

All scenarios (`matched-base-v4`, `stylised-df-moderate-v4`, `stylised-df-severe-v4`, `stylised-df-extreme-v4`) share identical demand, installed capacities, fossil fleet, storage, transmission, CO₂ treatment, load-shedding settings, and snapshot weights. Only renewable `p_max_pu` differs.

Capacity-weighted aggregate availability:

\[
CF_{weighted}[k,t] = \frac{\sum_g P_g \cdot p_{max\_pu}[g,t]}{\sum_g P_g}
\]

## KPI scopes

Metrics are reported for mutually exclusive sub-phases:

- `pre-buffer` (56 snapshots), `transition-in` (16), `plateau` (80), `transition-out` (16), `post-buffer` (56)
- Aggregate scopes: `core` (112), `full-window` (224)

Energy ratios compare scenario to Base available energy. Plateau ratios match \(r_k\) exactly; core and full-window ratios are higher because transitions and normal buffers are included.

## GAMSPy export

The GAMSPy DE model uses aggregated wind and solar technologies. Factor files are exported per carrier group. Where a single wind technology is used, a fixed-capacity-weighted wind factor is computed:

\[
m_{wind}[t] = \frac{P_{onshore} \cdot m_{onshore}[t] + P_{offshore} \cdot m_{offshore}[t]}{P_{onshore} + P_{offshore}}
\]

with \(P_{onshore}\) and \(P_{offshore}\) taken from the Base network installed capacities.

## Limitations

- Buffer-day profiles depend on cutout reconstruction; the core is exact Base data. Cutout-vs-Base core differences before overwrite are reported in `cutout_base_comparison.csv`.
- Buffer-to-core stitching may show discontinuities from profile-source differences, correction factors, or weather variation; these are validated but not smoothed.
- Stylised severity levels are policy stress assumptions, not calibrated to a historical event or return period.
- Availability-based residual-load diagnostics (demand converted from MW to GW) do not represent optimised dispatch.
- The extreme scenario is intentionally severe for sensitivity analysis; interpret alongside moderate and severe cases.

## Implementation

- Profile builder: `scripts/inre/build_stylised_dunkelflaute_v4.py`
- Network applicator: `scripts/inre/apply_stylised_dunkelflaute_v4.py`
- Network audit: `scripts/inre/audit_stylised_dunkelflaute_v4.py`
- PyPSA profiles: `data/inre/profiles/stylised_dunkelflaute_v4/`
- GAMSPy factors: `gamspy-de/profiles/stylised_dunkelflaute_v4/`
- Scenario keys: `config/inre/scenarios.v4.yaml` (`matched-base-v4`, `stylised-df-*-v4`)
