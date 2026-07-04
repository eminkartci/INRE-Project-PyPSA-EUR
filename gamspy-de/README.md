# INRE Germany — GAMSPy Model

Standalone **10-node Germany electricity** capacity expansion and dispatch model, aligned with the INRE study design. Fully independent from the PyPSA-Eur Snakemake workflow; all inputs are editable CSV/YAML files under your control.

**Report documentation:** see [GAMSPY-MODEL-DOCUMENTATION.md](GAMSPY-MODEL-DOCUMENTATION.md) for inputs, formulation, references, and result interpretation.

## Requirements

- Python 3.10+
- [GAMS](https://www.gams.com/) (Community or academic license)
- `pip install -r requirements.txt`

GAMSPy wraps GAMS — a valid GAMS installation and license are mandatory.

## Quick start

```bash
cd gamspy-de
pip install -r requirements.txt
gamspy install solver highs   # one-time HiGHS install for GAMS
python src/run.py --scenario base
python src/run.py --scenario dunkelflaute-smr
python src/run.py --scenario all
```

Results are written to `results/<scenario>/`.

## Folder structure

| Path | Purpose |
|------|---------|
| `config/model.yaml` | Snapshot window, CO₂ cap, solver |
| `inputs/*.csv` | Network, demand, costs, profiles (you edit these) |
| `scenarios/*.yaml` | Dunkelflaute / nuclear scenario switches |
| `profiles/` | Dunkelflaute wind/solar derating factors (from INRE) |
| `src/` | Data loader, scenario logic, GAMSPy LP, runner |
| `results/` | Solver outputs |

## Input files

### `inputs/buses.csv`

| Column | Unit | Description |
|--------|------|-------------|
| `bus_id` | — | Node ID (`DE0` … `DE9`) |
| `lat`, `lon` | deg | For nuclear site mapping |

### `inputs/lines.csv`

| Column | Unit | Description |
|--------|------|-------------|
| `line_id` | — | Line identifier |
| `bus0`, `bus1` | — | Endpoints |
| `s_nom_MW` | MW | Thermal limit (transport model) |

### `inputs/demand.csv`

Long format: `bus`, `timestamp`, `demand_MW`. Window: **2021-01-25 → 2021-02-08**, 3-hourly (112 snapshots).

### `inputs/technologies.csv`

| Column | Description |
|--------|-------------|
| `capital_cost_EUR_per_MWyr` | Annuitised CAPEX |
| `marginal_cost_EUR_per_MWh` | Operating cost |
| `co2_t_per_MWh` | Emission intensity |
| `extendable` | Allow new build (`true`/`false`) |
| `p_min_pu` | Minimum stable load fraction |
| `ramp_pu_per_h` | Ramp limit per hour |
| `co2_relevant` | Count toward CO₂ cap |

Technologies: `onwind`, `offwind`, `solar`, `ocgt`, `ccgt`, plus `nuclear-smr/msr/lfr` (used only when scenario enables nuclear).

### `inputs/capacity_existing.csv`

`bus`, `tech`, `p_nom_MW` — installed capacity before optimisation.

### `inputs/availability.csv`

`bus`, `tech`, `timestamp`, `p_max_pu` — time-varying availability (weather). Dunkelflaute scenarios multiply wind/solar profiles at runtime.

### `inputs/storage.csv`

Per-bus battery parameters: efficiencies, standing loss, CAPEX, `max_hours`.

### `inputs/nuclear_sites.csv`

Candidate reactor sites (from INRE): `site_id`, `tech`, `bus_id`, `p_nom_max_MW`, operational limits.

### `inputs/snapshots.csv`

`timestamp`, `weight_hours` (3.0 for 3-hour resolution).

## Scenarios

| Scenario | Dunkelflaute | Nuclear |
|----------|:------------:|---------|
| `base` | off | — |
| `dunkelflaute` | on | — |
| `dunkelflaute-smr` | on | SMR (5 sites) |
| `dunkelflaute-msr` | on | MSR (3 sites) |
| `dunkelflaute-lfr` | on | LFR (3 sites) |

Edit or copy YAML files in `scenarios/` to define new cases.

## Regenerating placeholder inputs

Template CSVs with representative Germany-scale values:

```bash
python tools/generate_templates.py
```

Replace values with your own ENTSO-E demand, Atlite profiles, or PyPSA-exported tables as they become available.

## Model formulation

Linear program (INRE methodology §4):

- **Objective:** weighted OPEX + annuitised CAPEX (generators, storage, nuclear)
- **Constraints:** nodal balance, generator bounds, ramps, line limits, storage dynamics, global CO₂ cap (500 Mt/year scaled to window)
- **Transmission:** transport model (`|f| ≤ s_nom`), not DC-OPF
- **Nuclear:** site-level build variables at former NPP locations

## Differences from PyPSA-INRE

| Aspect | PyPSA-INRE | This GAMSPy model |
|--------|------------|-------------------|
| Workflow | Snakemake + `.nc` networks | CSV/YAML + Python |
| Spatial | 10 clusters (k-means) | 10 buses (you define coordinates) |
| Transmission | Linearised DC OPF | Transport limits |
| H₂ chain | Store + pipeline | Not included (battery only) |
| VRE carriers | 6 types | `onwind`, `offwind`, `solar` |
| Dunkelflaute | In-network derating script | Pre-solve profile multiplication |
| Solver | HiGHS via Linopy | HiGHS/CPLEX via GAMS |

## Solver configuration

Set in `config/model.yaml`:

```yaml
solver: highs   # or cplex
```

## License note

GAMS license is your responsibility. PyPSA-Eur code in the parent repo is unchanged; this subfolder is a separate modelling environment.
