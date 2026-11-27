# How long can the underground habitat operate without deliveries?

This AI-assisted hobby project tests one part of the *Silo* premise with a
finite inventory experiment. Three below-surface settlements face the same
question on Earth, the Moon and Mars. The fixtures use invented values and a
common 24-hour operating cycle so that the arithmetic is easy to compare.
The cycle represents a work schedule. Planetary illumination, local deposits,
site geometry and weather would each require their own time series.

## Agent-run results

Each example runs twice for 30 cycles (720 hours). The scheduled run serves
every modeled load. The second run removes imported electricity, water and
food from the first interval onward. It retains the same starting stocks,
assumed local generation, fresh local water and potential harvest.

| Subsurface fixture | Scheduled shipments over 30 cycles | First shortage without shipments | Subsequent effect |
| --- | --- | --- | --- |
| Earth | None | All three loads served over 720 h | Collects 360 L of assumed local fresh water and produces 60 kg of assumed harvest. Of that harvest, 59 kg enters the pantry during the run and 1 kg remains pending at the end. |
| Moon | 180 L water | Water at hour 168 | The water shortfall cancels harvest credit. Food first runs short at hour 240. |
| Mars | 30 kg dry food | Food at hour 120 | Cumulative unmet food demand reaches 25 kg. Water and electrical loads remain covered. |

Hours identify the **start of the first affected 12-hour interval**. The
simulation has no finer timing. For example, the lunar fixture consumes
48 L per cycle and can recover at most 36 L per cycle once the loop is
running. Its assumed local supply contributes another 6 L per cycle.
The scheduled 6 L delivery covers the difference. After that delivery stops,
opening inventory temporarily hides the deficit.

## Opening reserves and recurring supply

`cycle_study.py` runs both shipment cases and adds sensitivity tests for
opening stock and recurring local supply. It checks whether electricity,
water, food and both pending credits return to an identical state at the same
point in the schedule. A repeated state can still rely on shipments or miss
demand. Check `period_imports` and `period_unmet` alongside the repeat.

| Fixture | No shipments over 365 synthetic days | Opening stock sensitivity | Recurring supply sensitivity |
| --- | --- | --- | --- |
| Earth | Serves all three modeled loads and returns to the same state after days 1 and 2. | | |
| Moon | Water runs short at hour 168, followed by food at hour 240. | Filling the opening tank moves the first water shortage to hour 324. | Adding 0.25 L/h of assumed local water at zero additional power cost serves all three loads. |
| Mars | Food runs short at hour 120 and later misses 1 kg of demand per cycle. | Filling the opening pantry moves the first food shortage to hour 168. | Adding 0.5 kg of assumed harvest every 12 hours serves all three loads. |

Use `--lunar-water-cost KWH_PER_L` to charge a scheduled electrical load for
the extra 0.25 L/h in a separate lunar case. The illustrative value 4 adds
1 kW in each interval, or 24 kWh per day. With that assumption, the first
electricity shortfall starts at hour 36 and the recovery-dependent water
shortfall starts at hour 96. The experiment charges demand for the extra
water once. It still assumes the extra fresh inflow arrives and does not
dispatch a collection subsystem separately when electricity falls short.

## Reproduce or change the experiment

```sh
python3 -B autonomy.py examples/subsurface-profiles.json
python3 -B autonomy.py examples/subsurface-profiles.json --scenario mars-subsurface --cycles 365
python3 -B autonomy.py examples/subsurface-profiles.json --scenario moon-subsurface --cycles 10 --trace
python3 -B cycle_study.py --cycles 365
python3 -B cycle_study.py --cycles 365 --lunar-water-cost 4
python3 -B -m unittest -v test_autonomy test_cycle_study
```

Edit a copy of the profiles to change the stocks, capacities or schedule. Each
profile uses up to 1,000 intervals across all repetitions. The runner carries
the last interval's stocks and pending recovery and harvest into the next cycle.
The summary gives initial stock, ending stock, delivered and unmet demand,
overflow, local inputs and external receipts. The trace exposes the per-step
balance for each resource.

The cycle study records SHA-256 digests of the profile and the three source
files used to produce the report.

| Input | Unit and timing |
| --- | --- |
| `onsite_kw`, `import_kw`, `load_kw` | Interval-average kW. Load includes the assumed utilities used for recovery and agriculture. |
| `local_water_l_per_hour`, `import_water_l_per_hour`, `demand_l_per_hour` | L/h. Local fresh water, shipments and recovery from the previous interval can serve current demand. |
| `potential_harvest_kg` | Assumed dry food mass per interval. Full delivery of both utility loads credits the harvest for the **next** interval. Either shortfall cancels the credit. |
| `import_food_kg`, `food_demand_kg` | Dry mass per interval. Shipments and the previous harvest are available before demand. Excess after demand spills above pantry capacity. |

The power and water run uses the repository's existing interval simulator.
Fresh inflow in that simulator combines local makeup and imported water. The
audit reports them separately. For each resource, start plus available inflow
equals delivered demand plus overflow plus end. The final pending water and
harvest are reported separately from usable stored stock.

## What full sustainability would require

A finite run can expose an import dependency or a declining stock.
Even the Earth fixture assumes continuing local water collection, generation
and harvest. A full accounting would also need the following evidence.

| System | Evidence needed to extend this model |
| --- | --- |
| Food and growing inputs | Measured dry harvest, nutrient replenishment, losses, growing space, power and water per crop cycle. The agriculture repository already exports synthetic indoor utility loads for comparison through the existing adapter. [Agriculture repository](https://github.com/dylanstechmann/rural-florida-agriculture) · [Aggregate comparison](../README.md#offline-indoor-grow-aggregate-import) |
| Air, water quality and heat | Independent gas inventories, contaminant and water-quality observations, and thermal loads. NASA describes an operating system with separate water recovery, air revitalization and oxygen generation functions. [NASA ECLSS](https://www.nasa.gov/reference/environmental-control-and-life-support-systems-eclss/) |
| Waste, maintenance and spares | Inputs, recoverable fractions, consumable lifetimes, inventory of replacement parts and equipment downtime. |
| Site and structure | Site-specific requirements for Earth, Moon and Mars, including pressure, heat rejection, egress and ground conditions. The equipment repository's microgrid study is a related source of synthetic power scenarios. [Equipment study](https://github.com/dylanstechmann/open-construction-equipment/blob/42783cadb5fcb72f2dbd9dd56986a3050d8e8595/docs/powertrain-microgrid.md) |

The reported shortages are software results. Long-term resource closure and
safe occupancy remain open research questions. [Model boundaries](life-support-scope.md)
