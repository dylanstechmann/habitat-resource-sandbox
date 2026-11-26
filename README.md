# Habitat resource sandbox

An AI-assisted hobby and learning prototype inspired by the closed-loop living premise of *Silo*. The model compares power and water shortages during four synthetic disruptions. Each example covers 24 hours. Supply, demand, storage and recovery inputs are editable in `scenarios.json`.

```bash
python3 habitat.py scenarios.json
python3 habitat.py scenarios.json --scenario moon
python3 habitat.py scenarios.json --interrupt 6 18
python3 habitat.py scenarios.json --interrupt 6 18 --reserve
python3 habitat.py scenarios.json --scenario desert-underground --interrupt 0 6 --interrupt-supply power
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

Use `--interrupt-supply power` to interrupt incoming electricity or `--interrupt-supply water` to interrupt water imports. Each targeted run records the choice under `interrupted_supply`. Omitting the option or choosing `both` runs the joint outage.

In the desert fixture’s first six hours, a power outage stopped recovery of 75.6 L for the next interval while water imports continued. Over the full day, that added **36 kWh** and **181.44 L** of unmet demand relative to the baseline. Interrupting only water imports over the same six hours added **51.20 L** of unmet water demand, with electricity demand still fully served.

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

The included standard-library checks cover interruption boundaries, recovery, resource balance, and forward simulation at the calculated reserves. Run them with `python3 -B -m unittest -v` from this directory.

The model borrows the interval-ledger approach from the Open Construction Equipment microgrid study. Its qualitative disruptions are motivated by documented lunar illumination, Martian dust, an underwater habitat’s dependence on surface utilities, and desert water constraints. All fixture quantities and outage lengths were selected for illustration. This conceptual model has ideal storage, anonymous resource loads and one simplified water loop. Real occupancy requires separate atmospheric, water-quality, thermal, structural, egress and safety analysis. [Source microgrid model](https://github.com/dylanstechmann/open-construction-equipment/blob/42783cadb5fcb72f2dbd9dd56986a3050d8e8595/docs/powertrain-microgrid.md)

- Water recovery and air systems within a larger life-support system. [NASA ECLSS](https://www.nasa.gov/reference/environmental-control-and-life-support-systems-eclss/)
- Location-dependent lunar illumination. [NASA Lunar South Pole](https://www.nasa.gov/reference/moonbase-environment/)
- Solar input disrupted by Martian dust. [NASA Opportunity mission](https://science.nasa.gov/mission/mer-opportunity/)
- Surface-provided utilities for an underwater habitat. [FIU Aquarius](https://environment.fiu.edu/aquarius/about/)
- Water constraints in arid regions. [USGS water availability](https://www.usgs.gov/special-topics/integrated-water-availability-assessments/news/when-surface-water-runs-low)
