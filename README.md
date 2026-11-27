# Habitat resource sandbox

An AI-assisted hobby and learning prototype inspired by the closed-loop living premise of *Silo*. The model compares power and water shortages during four synthetic disruptions. Each example covers 24 hours. Supply, demand, storage and recovery inputs are editable in `scenarios.json`.

## Underground habitat autonomy

How long can a subsurface habitat meet demand if deliveries stop? Run the
Earth, Moon and Mars comparison for 30 synthetic days. It tracks stored
electricity, bulk water and dry food across days, including delayed recovery
and harvests.

```sh
python3 -B autonomy.py examples/subsurface-profiles.json --cycles 30
python3 -B autonomy.py examples/subsurface-profiles.json --scenario moon-subsurface --cycles 10 --trace
```

With the sample assumptions and deliveries disabled, the Earth fixture served
all three loads over 720 hours. The lunar fixture first missed water demand at
hour 168. The Mars fixture first missed food demand at hour 120. The
[underground habitat study](docs/subsurface-autonomy.md) gives the inputs,
resource balances, and the evidence still needed to evaluate full sustainability.

## Single-day disruptions

```bash
python3 habitat.py scenarios.json
python3 habitat.py scenarios.json --scenario moon
python3 habitat.py scenarios.json --interrupt 6 18
python3 habitat.py scenarios.json --interrupt 6 18 --reserve
python3 habitat.py scenarios.json --scenario desert-underground --interrupt 0 6 --interrupt-supply power
python3 habitat.py scenarios.json --scenario desert-underground --interrupt 0 6 --interrupt-supply water
```

Each interval draws from stored and incoming resources to meet demand, then records the remaining inventory, overflow and unmet demand. Recovery uses delivered water and becomes available the following interval. The stated electrical load includes recovery, which stops if that aggregate load has a shortfall. The report gives the start hour of the first interval with unmet demand and lists final pending recovery separately from storage. Relative differences up to 1e-12 between demand and delivery are treated as floating-point roundoff when reporting shortfalls.

The agent-run fixture produced these cumulative shortfalls over 24 hours.

| Scenario | Unmet energy (kWh) | Unmet water (L) |
| --- | ---: | ---: |
| Desert underground | 0.00 | 7.16 |
| Moon | 20.00 | 49.32 |
| Mars | 10.00 | 42.20 |
| Underwater | 31.00 | 0.00 |

`--interrupt START_HOUR END_HOUR` removes incoming power and water imports during the selected window. Stored resources and previously recovered water remain available. Both boundaries must match interval edges in every selected scenario, and the end hour is excluded. The report nests the original and interrupted ledgers under each scenario and compares how much additional demand goes unmet. For each resource it also gives the first shortfall interval, the number of affected intervals, the length in hours of the longest run of affected intervals, and the first fully served interval after the final shortfall. The restoration hour is `null` if there were no shortfalls or service had yet to recover when the run ended.

Removing both supplies from hour 6 to 18 added **34 kWh** and **73.64 L** of unmet demand in the desert fixture. The Mars fixture added **24 kWh** of unmet electricity demand with the same water shortage. The Moon and underwater fixtures already had zero incoming power and water for that window and produced identical ledgers for both runs.

Use `--interrupt-supply power` to interrupt only incoming electricity or `--interrupt-supply water` to interrupt only water imports. The option requires `--interrupt`; omitting it or choosing `both` runs the joint outage with identical output. Each targeted run records its choice under `interrupted_supply`, while omitted/`both` reports do not contain that field. Power shortfalls still stop water recovery for the following interval; a water-only interruption leaves the electricity ledger unchanged.

In the desert fixture's first six hours, a power-only outage stopped recovery of 75.6 L for the next interval while water imports continued. Over the full day, it added **36 kWh** and **181.44 L** of unmet demand relative to baseline. Interrupting only water imports over the same six hours added **51.196 L** of unmet water demand, with electricity demand still fully served.

## Offline indoor-grow aggregate import

`indoor_import.py` is a separate, standard-library-only **offline aggregate comparison/import adapter** for `rural-florida-agriculture` indoor interval output. It requires an explicit input path; it never discovers sibling repositories, reads a default producer path, accesses the network, or modifies `scenarios.json`.

```bash
python3 indoor_import.py examples/indoor-grow-aggregate.json
python3 indoor_import.py /explicit/path/to/indoor-simulation.json --expect-sha256 SHA256_HEX
```

The input must be producer `schema_version` 1, UTF-8 JSON no larger than 4 MiB, with 1–96 complete day intervals and fixed kWh/L/minute units. The adapter rejects duplicate or unknown fields in the objects it interprets, non-finite or incorrectly typed numbers, invalid/contiguousness-breaking intervals, inconsistent load identities, and summary/load/interval arithmetic mismatches. Output schema `synthetic-habitat-indoor-aggregate-comparison/1` records the supplied path, byte count, source SHA-256 and scenario source labels. `--expect-sha256` rejects changed bytes before import; this is change pinning, not a signature or proof of authenticity. Identical invocations produce identical JSON without timestamps.

Producer schema v1 is deliberately **aggregate-only**: the adapter does not emit a Habitat scenario. Its post-dispatch critical/noncritical and lossy-battery flows do not supply the exogenous aggregate inputs and storage capacities required by Habitat's ideal-storage model. Its explicit agricultural water recovery/makeup ledger is independent of energy shortfalls, unlike Habitat's delayed, power-coupled recovery. The report names these differences and lists observed intervals where agricultural recovery follows shed energy. It never relabels agricultural withdrawal or recovery as potable/human water.

`examples/indoor-grow-aggregate.json` is a new two-interval synthetic fixture derived by explicit reference to the producer schema; its source label says that its values were newly invented rather than silently copied from measurements or third-party data. An agent-run offline check of the current producer output (source SHA-256 `82981f9df5227450aa41d4b4620494564cc56c90f05fe6198d4ba0d3ffc78ba5`) validated 24 intervals and compared 643.2 kWh requested, 592.2 kWh served and 51.0 kWh shed, plus 480 L requested/served agricultural withdrawal, 315 L recovered and 210 L makeup. It reported one coupling-conflict interval. These are synthetic bookkeeping results only: no crop biology, yield, food closure, potability, occupancy-safety or life-support validation is claimed. See [the exact import contract](docs/model.md#offline-indoor-grow-aggregate-import).

## Minimum stocks and storage

`--reserve` adds the minimum starting stock and storage capacity that would meet both loads in every modeled interval, with zero stock required after the final interval. It adds a reserve report to each ledger, including both ledgers when paired with `--interrupt`. For each resource, the calculation works backward, allowing the next interval's stock to be charged from incoming supply. The largest required stock at any interval boundary sets the minimum storage capacity. The water calculation assumes the power load is met throughout, so the full served water demand contributes to recovery in the following interval.

The agent-run reserve calculation gave these minimum values for the hour 6–18 interruption.

| Scenario | Starting energy (kWh) | Energy capacity (kWh) | Starting water (L) | Water capacity (L) |
| --- | ---: | ---: | ---: | ---: |
| Desert underground | 48 | 84 | 145.20 | 145.20 |
| Moon | 24 | 60 | 132.48 | 132.48 |
| Mars | 54 | 72 | 136.80 | 136.80 |
| Underwater | 78 | 96 | 126.00 | 126.00 |

All four fixtures needed both more electricity in storage at the start and greater energy capacity. With continuous recovery, the desert fixture also needed 5.20 L more starting water. Each fixture's existing water capacity was sufficient for the modeled window.

The included standard-library checks cover selective and joint interruption boundaries, offline indoor aggregate import/provenance and validation, CLI output, deterministic reporting, delayed recovery, resource balance, and forward simulation at the calculated reserves. Run them with `python3 -B -m unittest -v` from this directory. See [the model reference](docs/model.md) for exact interval equations, units, reserve assumptions, and input validation, and [the life-support scope statement](docs/life-support-scope.md) for explicit exclusions. Input validation is implemented directly in `habitat.py`; no JSON Schema package is required.

The model borrows the interval-ledger approach from the Open Construction Equipment microgrid study. Its qualitative disruptions are motivated by documented lunar illumination, Martian dust, an underwater habitat’s dependence on surface utilities, and desert water constraints. All fixture quantities and outage lengths were selected for illustration. This conceptual model has ideal storage, anonymous resource loads and one simplified water loop. Real occupancy requires separate atmospheric, water-quality, thermal, structural, egress and safety analysis. [Source microgrid model](https://github.com/dylanstechmann/open-construction-equipment/blob/42783cadb5fcb72f2dbd9dd56986a3050d8e8595/docs/powertrain-microgrid.md)

- Water recovery and air systems within a larger life-support system. [NASA ECLSS](https://www.nasa.gov/reference/environmental-control-and-life-support-systems-eclss/)
- Location-dependent lunar illumination. [NASA Lunar South Pole](https://www.nasa.gov/reference/moonbase-environment/)
- Solar input disrupted by Martian dust. [NASA Opportunity mission](https://science.nasa.gov/mission/mer-opportunity/)
- Surface-provided utilities for an underwater habitat. [FIU Aquarius](https://environment.fiu.edu/aquarius/about/)
- Water constraints in arid regions. [USGS water availability](https://www.usgs.gov/special-topics/integrated-water-availability-assessments/news/when-surface-water-runs-low)
