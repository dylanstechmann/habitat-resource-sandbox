# Model reference

## Scope and determinism

`habitat.py` is a deterministic, standard-library-only ledger for **synthetic** electrical-energy and bulk-water scenarios. It does not model people or certify occupancy or life support; see [life-support-scope.md](life-support-scope.md). The canonical fixtures in `scenarios.json` are illustrative inputs, not recommended designs.

Each run uses the scenario's fixed interval duration and preserves input order. JSON output uses two-space indentation and Python's JSON float representation; reported quantities are not rounded for presentation. Consequently, values such as `181.43999999999997` are the full-day floating-point result corresponding to the rounded **181.44 L** discussed in the README.

## Units and interval boundaries

A scenario has `N` steps of duration `d = step_hours`. Step `i` (zero-based) covers the half-open interval `[i*d, (i+1)*d)` hours after the scenario start. Rates are constant within a step. The final step's end hour is `N*d`, reported as `duration_hours`.

| Input or output field | Unit | Meaning |
| --- | --- | --- |
| `supply_kw` | kW | Incoming electrical power during the step |
| `load_kw` | kW | Aggregate electrical load, including recovery when scheduled |
| `initial_energy_kwh`, `energy_capacity_kwh` | kWh | Starting battery stock and storage capacity |
| `import_l_per_hour` | L/h | External bulk-water import rate |
| `demand_l_per_hour` | L/h | Aggregate bulk-water demand rate |
| `initial_water_l`, `water_capacity_l` | L | Starting water stock and storage capacity |
| `recovery_fraction` | L/L | Fraction of delivered water available as recovered water one step later |
| `import_l`, recovered-water fields | L | Water quantities within or carried across a step |
| `start_hour`, interruption hours | h | Time measured from the scenario start |

Multiplying kW or L/h by `d` hours gives kWh or L for that step. Incoming energy and imports can serve demand in the same step in which they arrive.

## Per-step accounting

For each resource, incoming supply is added to starting stock before delivery. For electricity:

```text
energy_supply_i = supply_kw_i * d
energy_demand_i = load_kw_i * d
energy_available_i = energy_start_i + energy_supply_i
energy_delivered_i = min(energy_available_i, energy_demand_i)
energy_remaining_i = energy_available_i - energy_delivered_i
energy_end_i = min(energy_remaining_i, energy_capacity_kwh)
energy_overflow_i = energy_remaining_i - energy_end_i
```

Water uses the same equations with these supplies and demands:

```text
water_supply_i = import_l_per_hour_i * d + recovered_from_previous_l_i
water_demand_i = demand_l_per_hour_i * d
water_available_i = water_start_i + water_supply_i
water_delivered_i = min(water_available_i, water_demand_i)
water_remaining_i = water_available_i - water_delivered_i
water_end_i = min(water_remaining_i, water_capacity_l)
water_overflow_i = water_remaining_i - water_end_i
```

Thus, apart from recorded unmet demand and overflow:

```text
start + supply = delivered + end + overflow
demand = delivered + unmet
```

Storage has no efficiency loss, self-discharge, leakage, or carry-over limit other than its capacity. Excess supply above demand and capacity is recorded as overflow, not saved for later. The next step starts with the previous step's ending stocks.

`unmet` is `demand - delivered`, except that it is reported as exactly zero when `math.isclose(demand, delivered, rel_tol=1e-12)` accepts the difference as roundoff. This uses the default absolute tolerance of zero.

## Delayed water recovery and power coupling

Recovered water is not reused in the step that produces it. At the beginning of a run, pending recovery is zero. At the end of step `i`:

```text
recovered_for_next_l_i = recovery_fraction * water_delivered_i
                         if energy_unmet_i == 0
recovered_for_next_l_i = 0
                         if energy_unmet_i > 0
recovered_from_previous_l_(i+1) = recovered_for_next_l_i
```

The electrical load is already assumed to include recovery when scheduled. Any reported electrical shortfall stops production of recovered water for the **following** step. It does not remove water recovered in an earlier step and already available in the current step. Recovery is based on water actually delivered, not on nominal demand. Conversely, fully served electricity permits recovery even when water demand is only partly met.

Interrupting incoming power therefore interrupts later recovery only when the resulting energy ledger has a shortfall; stored electricity can instead keep the aggregate load fully served. A water-only interruption changes no electrical inputs or electrical ledger results. Recovery produced by the final step cannot be used within the run and is reported separately as `water_pending_recovery_l`; it is not included in `final_water_l`.

## Selective supply interruptions

`compare_interruption(scenario, start_hour, end_hour, reserve=False, supply="both", reserve_end=None)` first simulates the unchanged scenario, then simulates a shallow-copied step list. The original scenario is not mutated. For every step wholly selected by `[start_hour, end_hour)`, the interruption sets:

| `supply` | Inputs set to zero | Inputs left unchanged |
| --- | --- | --- |
| `both` | `supply_kw`, `import_l_per_hour` | None of the other supply inputs |
| `power` | `supply_kw` | `import_l_per_hour` |
| `water` | `import_l_per_hour` | `supply_kw` |

Stored resources and previously recovered water remain available. Demand, event labels, capacities, recovery fraction, and all steps outside the window are unchanged. A selective result adds `"interrupted_supply": "power"` or `"water"`; omitted and explicit `both` results have identical structure and values and do not contain that key.

The start must be nonnegative and strictly before the end. Both hours must lie within the scenario and align with step boundaries. Boundary alignment uses `round(hour / d)` and `math.isclose(..., rel_tol=0, abs_tol=1e-9)`. Zero-length windows are rejected; the scenario's final end hour is a valid exclusive interruption end. The CLI applies these checks independently to every selected scenario.

For each resource, the comparison reports additional cumulative unmet demand and baseline/interrupted shortfall profiles. `first_hour` is the first affected step's start, `interval_count` counts affected steps, and `longest_hours` is the longest consecutive affected run. `restored_hour` is the start of the first fully served step immediately after the final shortfall. It is `null` when there were no shortfalls or when the scenario ends before a fully served subsequent step. The top-level run's `first_shortfall_hour` instead considers either resource.

## Reserve calculations and assumptions

`reserve=True` does not change the simulation. It adds a separate backward calculation to each baseline or interrupted run, with zero stock required after the final step. For each resource, define the interval deficit from demand and incoming supply:

```text
energy_deficit_i = energy_demand_i - energy_supply_i
water_deficit_i = water_demand_i - import_l_i - assumed_recovered_from_previous_l_i
```

Working backward from `required_stock_N = 0`:

```text
required_stock_i = max(0, required_stock_(i+1) + deficit_i)
minimum_initial_stock = required_stock_0
minimum_capacity = max(required_stock_i for i in 0..N-1)
additional_initial_stock = max(0, minimum_initial_stock - configured_initial_stock)
additional_capacity = max(0, minimum_capacity - configured_capacity)
```

This allows a later interval's required stock to be charged by earlier incoming supply. Surplus cannot create a negative stock requirement. The capacity result is the largest stock required at any interval boundary, which can exceed the minimum starting stock.

`reserve_end=(ENERGY_KWH, WATER_L)` and the CLI option `--reserve-end ENERGY_KWH WATER_L` instead require specified stocks after the final step, without requiring `reserve=True`. Each target must be a finite number in `[0, 1_000_000_000]`. The backward pass starts from `required_stock_N = minimum_final_stock` for each resource, and the target is included in the capacity maximum. Each reserve section then records `minimum_final_stock`. The targets apply to every selected run, including baseline and interrupted ledgers. Stored water alone counts toward the water target; pending recovery remains separate. `--reserve` without `--reserve-end` retains the zero-final-stock calculation above.

The water reserve calculation is deliberately idealized: it assumes the full electrical load is met throughout and the full water demand is delivered, so every step contributes `recovery_fraction * water_demand_i` to the next step. Assumed recovery before the first step is zero. These recovery assumptions are also used when calculating a reserve report for an interrupted run; actual simulated shortfalls do not alter them. In particular, a power-only outage can leave the water reserve calculation unchanged even though its forward simulation loses recovery. Reserve outputs are therefore not a guarantee of served loads during an actual power shortfall.

Final pending recovery is not credited as usable final stock. The calculation does not size equipment, select redundancy, or add a safety margin.

## Accepted input and direct validation

The project documents validation here rather than shipping a separate JSON Schema. Runtime validation uses only the Python standard library; no schema-validation dependency is needed. Unknown JSON fields are ignored.

For CLI input, the UTF-8 JSON document must have `"schema": "synthetic-habitat-resources/1"` and a `scenarios` list containing 1–32 entries. Every scenario needs a unique `id` matching `[a-z0-9][a-z0-9-]{0,39}`. `--scenario ID` selects only exact matches and errors if none exist.

Within each simulated scenario:

- `step_hours` is a number in `(0, 24]`.
- `initial_energy_kwh`, `energy_capacity_kwh`, `initial_water_l`, `water_capacity_l`, `supply_kw`, `load_kw`, `import_l_per_hour`, and `demand_l_per_hour` are numbers in `[0, 1_000_000_000]`.
- Each initial stock is no greater than its corresponding capacity.
- `recovery_fraction` is a number in `[0, 1]`.
- `steps` is a list containing 1–1000 steps.
- Each `event` is a printable string whose whitespace-stripped form contains 1–96 characters.

Here “number” means a Python `int` or `float` decoded from JSON, explicitly excluding booleans and numeric strings. NaN and infinities are rejected by the range checks. Missing required fields, wrong container types, invalid JSON, unreadable files, and invalid values produce CLI errors. Programmatic callers receive the underlying `KeyError`, `TypeError`, or `ValueError` as applicable.

The CLI option `--interrupt-supply` accepts exactly `both`, `power`, or `water` and requires `--interrupt START_HOUR END_HOUR`. The programmatic `supply` argument accepts the same case-sensitive strings and rejects other values with `ValueError`.

## Offline indoor-grow aggregate import

### Purpose and non-conversion boundary

`indoor_import.py` validates and normalizes the separate indoor-grow producer's interval output into report schema `synthetic-habitat-indoor-aggregate-comparison/1`. This is an **aggregate comparison/import report**, not a `synthetic-habitat-resources/1` scenario. It does not call `simulate`, calculate reserves, alter `scenarios.json`, or create `supply_kw`, `load_kw`, water-rate or capacity inputs.

For producer `schema_version` 1, direct scenario conversion is intentionally unsupported. The producer emits post-dispatch critical/noncritical load allocation, grid/solar/battery flows and battery charge after applying its own priorities and efficiencies. It does not emit both storage capacities or an exogenous aggregate supply series sufficient for Habitat's single ideal-storage ledger. Treating served energy as supply, discarding shed energy, or inferring missing capacities would fabricate a different model.

The water models also differ. Producer `water_recovered_l` and `water_makeup_l` are explicit independent agricultural-ledger inputs. Habitat derives recovery from delivered water, delays it one interval, and sets the next interval's recovery to zero after an energy shortfall. The report's `comparison.power_water_coupling.observed_conflicts` lists each interval with nonzero agricultural recovery immediately following nonzero total shed energy. This is a semantic comparison, not a recalculation or rejection of the producer's independent ledger.

All imported water remains labelled `agricultural_water_l`. It is simulated agricultural withdrawal, stock, recovery and makeup, not potable water or human demand. No crop response, yield, food closure, water-quality, occupancy-safety or life-support conclusion is drawn.

### Invocation, provenance and determinism

```bash
python3 indoor_import.py INPUT.json
python3 indoor_import.py INPUT.json --expect-sha256 64_HEXADECIMAL_CHARACTERS
```

The positional path is mandatory and is the only input opened. There is no sibling-path default, producer-repository import, network access, environment lookup, clock, random source or output file side effect. Output is JSON on stdout with two-space indentation and a final newline. For the same source bytes, supplied path string and checksum-option state, output is deterministic. `source.path` preserves the supplied path rather than resolving it.

The report records source byte length, SHA-256, producer schema version, scenario name/version/status/source label, and `import_mode: offline_explicit_path_no_network`. `source.expected_sha256_verified` records whether a pin was supplied. A pin must contain exactly 64 hexadecimal characters; mismatching source bytes fail with `source SHA-256 mismatch` before schema interpretation. Without a pin, the report records the new digest but cannot detect substitution. SHA-256 is neither a digital signature nor evidence that the source is measured, authoritative or safe.

### Bounds, schema and units

- Input is read in binary as at most **4,194,304 bytes (4 MiB)**; the reader requests one additional byte and rejects larger files before decoding. Empty input, invalid UTF-8, malformed JSON and excessive parser nesting are errors.
- Duplicate keys are rejected in every JSON object. NaN, positive/negative infinity and overflowed non-finite decoded numbers are rejected. Booleans are not numbers or integers.
- `schema_version` must be integer `1`; a missing, boolean, string or other version is incompatible. `dispatch_policy` must exactly equal `solar first; critical before noncritical; grid-down noncritical shedding; battery for critical loads only; proportional same-class shortfall allocation`.
- The top level accepts exactly `schema_version`, `scenario`, `interval_count`, `interval_minutes`, `dispatch_policy`, `lighting_profiles`, `timer_audits`, `energy_summary`, `load_totals`, `water_summary`, `chemical_inventory`, `intervals`, and `limitations`. The scenario, energy/water summaries, intervals, interval loads and load totals also have exact field whitelists. Unknown or missing fields in these interpreted objects are errors. Ancillary profile/audit/inventory arrays are count/type checked but their contents are not imported or semantically validated.
- There are 1–96 intervals and at most 128 load-total rows or loads per interval. `interval_count` must divide 1440; `interval_minutes` must equal `1440 / interval_count`. Interval indices and half-open minute boundaries must be ordered and contiguous from 0 through 1440, with `duration_hours = interval_minutes / 60`.
- Energy fields use kWh, water fields use L, boundaries/active durations use whole minutes, and duration uses hours. Renaming a recognized field to another unit is an unknown/missing-field error, not an implicit conversion. Nonnegative numeric inputs must be finite JSON numbers no greater than `1e12`; the signed `final_stock_minus_reserve_l` has lower bound `-1e12`. Counts, indices and active minutes must be integers within their stated ranges, and flags must be JSON booleans.

### Arithmetic comparison

For every interval the adapter checks requested = served + shed by criticality, source-to-load = served, solar availability allocation, grid/conservation behavior, battery and water-stock continuity, requested withdrawal = served + shortfall, and the complete water balance. It checks each `water_below_reserve` flag against the declared reserve and verifies that every interval contains every declared load exactly once with matching kind, criticality and source label. Load requested/served/shed values must sum to the corresponding criticality totals.

Across intervals it recomputes energy and agricultural-water summaries, load totals, battery initial/final/minimum charge, outage/conservation counts, water initial/final/minimum stock and below-reserve counts. Comparisons use `math.fsum` and `math.isclose(rel_tol=1e-9, abs_tol=1e-8)` to accommodate serialized decimal arithmetic. `declared_summaries_match_interval_sums` and `load_totals_match_interval_loads` are emitted only after all checks pass.

The normalized report retains per-interval aggregate requested/served/shed energy and agricultural stock/recovery/makeup/withdrawal/shortfall/overflow. It appends source limitations to explicit adapter exclusions. Invalid input or CLI usage exits through `argparse` with status 2 and an error on stderr; valid output exits 0.

### Example and current producer comparison

`examples/indoor-grow-aggregate.json` uses two 12-hour intervals with newly invented values. Its `scenario.source_label` explicitly references `rural-florida-agriculture/docs/indoor-simulation.json` schema v1 as the schema origin and states that the smaller fixture is not copied measurement or third-party data. Its second interval deliberately demonstrates agricultural recovery after prior shed energy.

The current 24-interval producer output was accepted through an explicitly supplied path in an offline agent run. Source SHA-256 was `82981f9df5227450aa41d4b4620494564cc56c90f05fe6198d4ba0d3ffc78ba5`. The comparison found one coupling-conflict interval: interval 3 retains 15 L of agricultural recovery after interval 2 sheds 26 kWh. This does not make either model wrong; it prevents silently substituting one model's recovery semantics for the other's.
