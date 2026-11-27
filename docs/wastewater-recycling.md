# Wastewater recovery for an indoor farm

This AI-assisted study compares treatment enabled and disabled over the same
schedule. The Earth, Moon and Mars examples use invented generation profiles,
loads, recovery fractions and storage capacities to explore the resource
tradeoffs.

```sh
python3 -B recycling.py examples/wastewater-recycling.json --cycles 30
python3 -B recycling.py examples/wastewater-recycling.json --scenario moon-subsurface --cycles 30 --no-exercise --trace
```

1. Serve the base electrical load, including grow lights. Solar, other
   generation and exercise each supply their own kWh. Exercise generation
   multiplies mechanical watts per person by active person-hours and
   generator efficiency, then converts Wh to kWh. The food and heat costs
   of exercise are outside this ledger.
2. Use electricity left after base load to treat wastewater already in the
   raw tank, up to the treatment capacity in liters per interval. Untreated
   feed stays in the tank. The processed share of the mixed liquid carries
   the same share of its fertilizer-equivalent nutrient mass.
3. Split the processed liquid and its nutrients into recovered quantities
   and residuals. Reclaimed water and fertilizer-equivalent nutrients go
   to separately metered growing-system reservoirs with fresh makeup
   inputs. The report includes demand, shortfalls and overflow for both.
4. Add newly captured wastewater at the end of the interval. It can be
   treated from the next interval onward. Overflow from the raw tank
   carries a proportional share of its nutrient mass.

The nutrient quantity is a single synthetic mass in grams. It represents
potential fertilizer replacement in the inventory. A real hydroponic system
would need evidence about its individual nutrient requirements, contaminant
removal, and the quality of both recovered streams. The model takes captured
wastewater, fresh makeup and plant demand as independent inputs. Crop yields,
water quality, and nutrient uptake are outside the calculation.

## Agent-run example

Over 30 synthetic days, the Earth run recovered 354 L of water and 147.5 g
of fertilizer-equivalent nutrients using 59 kWh of treatment electricity.
It still received 180 L of fresh makeup and 60 g of fresh nutrient
equivalent. With treatment disabled, the same fixture had a 342 L water
shortfall and a 143 g nutrient shortfall. Exercise generated 5.4 kWh over
the run, alongside 330 kWh of solar generation. Those quantities depend on
the stated inputs.

## How much farm makeup water can treatment replace?

`farm_water.py` compares three water budgets over repeated 24-hour schedules.
All start with the farm's opening stock and keep its own scheduled agricultural
recovery. The first receives the farm's scheduled makeup, the second receives
zero makeup, and the third receives only water from habitat treatment as makeup.
Stock carries across days. The counterfactual allocates the entire reclaimed
output to this farm. Crediting that water to a second growing system would
count it twice. The source of captured wastewater must be independent of the
farm's existing recovery stream for this comparison to apply.

Run `floridafarm simulate-day` with `--water-handoff-out farm-water.json`
alongside its usual JSON and Markdown output options. The handoff declares
the capacity and a SHA-256 digest for the farm report. The habitat importer
checks the digest and confirms that the capacity reproduces the farm's
recorded interval stocks and overflow. The bundled miniature example assumes
a 30 L tank. [Farm simulation and export](https://github.com/dylanstechmann/rural-florida-agriculture/blob/main/docs/indoor-simulation.md)

```sh
python3 -B farm_water.py farm-day.json farm-water.json examples/wastewater-recycling.json --scenario earth-underground --days 30
```

The agent-run comparison using the full 24-interval farm fixture and its
1,000 L reservoir gave these results over 30 days.

| Source of makeup water | Received by farm | Unmet withdrawals | Start of first shortfall |
| --- | ---: | ---: | --- |
| Scheduled farm makeup | 6,300 L | 0 L | All served |
| No makeup | 0 L | 4,650 L | Hour 42 |
| Earth habitat treatment | 348 L | 4,302 L | Hour 44 |

The treatment fixture produced 354 L. Each batch becomes available at the
first farm interval opening at or after treatment finishes. The last 6 L
was still awaiting transfer at the end of the study. The farm's recovery
remains a scheduled input even if withdrawals run short. The habitat model
supplies treatment electricity. The comparison assumes ideal transfer and
does not calculate pumping energy, nutrient compatibility or water quality.

NASA's ISS water recovery work informs the water-reuse context. ESA's MELiSSA
work identifies nutrient recovery as a separate part of a closed water and
food loop. The fixture coefficients are illustrative. [NASA water recovery demonstration](https://www.nasa.gov/missions/station/iss-research/nasa-achieves-water-recovery-milestone-on-international-space-station/) · [ESA closed water loop](https://www.esa.int/ESA_Multimedia/Images/2019/10/Closed_water_loop)
