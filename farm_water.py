"""Replay a farm water budget using a subsurface habitat's reclaimed water."""

import argparse
import json
import math
from pathlib import Path

from habitat import amount, ledger
from indoor_import import TOLERANCE, _load_json, compare_indoor
from recycling import audit


def replay(rows, capacity, initial, reserve, makeup, *, minimum_stocks=None):
    """Optionally buy just enough water for demand and the interval/closing stock floors."""
    supplemental_l = 0.0
    peak_l = 0.0
    first_minute = None
    peak_minute = None
    stock = initial
    first_shortfall = None
    totals = dict(makeup_l=0.0, farm_recovered_l=0.0, delivered_l=0.0,
                  unmet_l=0.0, overflow_l=0.0)
    below_reserve = 0
    for i, supplied in enumerate(makeup):
        row = rows[i % len(rows)]
        farm = row["agricultural_water_l"]
        available_supply = supplied + farm["recovered"]
        demand = farm["requested_withdrawal"]
        if minimum_stocks is not None:
            floor = minimum_stocks[1] if i == len(makeup) - 1 else minimum_stocks[0]
            extra = max(0.0, (demand + floor) - (stock + available_supply))
            if extra > 0:
                minute = i // len(rows) * 1440 + row["start_minute"]
                if first_minute is None:
                    first_minute = minute
                if extra > peak_l:
                    peak_l, peak_minute = extra, minute
            supplemental_l += extra
            available_supply += extra
            supplied += extra
        flow = ledger(stock, available_supply, demand, capacity)
        stock = flow["end"]
        totals["makeup_l"] += supplied
        totals["farm_recovered_l"] += farm["recovered"]
        totals["delivered_l"] += flow["delivered"]
        totals["unmet_l"] += flow["unmet"]
        totals["overflow_l"] += flow["overflow"]
        below_reserve += stock < reserve
        if first_shortfall is None and flow["unmet"]:
            first_shortfall = i // len(rows) * 1440 + row["start_minute"]
    if minimum_stocks is not None:
        totals.update(supplemental_l=supplemental_l, first_supplement_minute=first_minute,
                      peak_supplement_interval_l=peak_l, peak_supplement_minute=peak_minute,
                      interval_end_floor_l=minimum_stocks[0], closing_floor_l=minimum_stocks[1])
    return {**totals, "initial_stock_l": initial, "final_stock_l": stock,
            "first_shortfall_minute": first_shortfall, "below_reserve_intervals": below_reserve}


def compare(report_path, handoff_path, profiles_path, scenario, days, *, makeup_budget=False):
    handoff, _, handoff_hash = _load_json(handoff_path)
    if (not isinstance(handoff, dict) or handoff.get("schema") != "synthetic-farm-water-handoff/1"
            or not isinstance(handoff.get("report_sha256"), str)):
        raise ValueError("expected a farm water handoff with a report SHA-256")
    farm = compare_indoor(report_path, expected_sha256=handoff["report_sha256"])
    capacity = amount(handoff["reservoir_capacity_l"], "reservoir_capacity_l")
    water = farm["aggregates"]["agricultural_water_l"]
    initial, reserve = water["initial_stock_l"], water["reserve_l"]
    if capacity <= 0 or max(initial, reserve) > capacity:
        raise ValueError("farm water capacity must cover the opening stock and reserve")
    rows = farm["intervals"]
    for row in rows:
        source = row["agricultural_water_l"]
        original = ledger(source["stock_start"], source["makeup"] + source["recovered"],
                          source["requested_withdrawal"], capacity)
        for key, recorded in (("end", "stock_end"), ("overflow", "overflow")):
            if not math.isclose(original[key], source[recorded], rel_tol=1e-9, abs_tol=TOLERANCE):
                raise ValueError(f"reservoir capacity conflicts with farm interval {row['index']}")

    doc, _, profile_hash = _load_json(profiles_path)
    if doc["schema"] != "synthetic-wastewater-recycling/1":
        raise ValueError("expected wastewater recycling profiles")
    matches = [profile for profile in doc["profiles"] if profile["id"] == scenario]
    if len(matches) != 1:
        raise ValueError("expected exactly one matching recycling scenario")
    settings = doc["settings"]
    run = audit(settings, matches[0], days, trace=True)
    step_minutes = round(60 * settings["step_hours"])
    if step_minutes * len(matches[0]["steps"]) != 1440 or not math.isclose(
            settings["step_hours"] * 60, step_minutes, rel_tol=0, abs_tol=1e-9):
        raise ValueError("the recycling profile must span 24 hours in whole-minute intervals")

    # Release each treatment batch at its end. When interval grids differ,
    # the farm can first withdraw that water at its next interval opening.
    batches = run["intervals"]
    batch_index = 0
    receipts = []
    scheduled = []
    for day in range(days):
        for row in rows:
            start = day * 1440 + row["start_minute"]
            received = 0.0
            while batch_index < len(batches) and (batch_index + 1) * step_minutes <= start:
                received += batches[batch_index]["reclaimed_water_l"]
                batch_index += 1
            receipts.append(received)
            scheduled.append(row["agricultural_water_l"]["makeup"])
    pending = sum(batch["reclaimed_water_l"] for batch in batches[batch_index:])
    alternatives = {"scheduled_farm_makeup": scheduled, "no_makeup": [0.0] * len(receipts),
                    "habitat_reclaimed_only": receipts}
    result = {
        "schema": "synthetic-farm-reclaimed-water-comparison/1", "scenario": scenario, "days": days,
        "farm_report_sha256": farm["source"]["sha256"], "handoff_sha256": handoff_hash,
        "recycling_profiles_sha256": profile_hash, "reservoir_capacity_l": capacity,
        "treatment_kwh": run["totals"]["treatment_kwh"],
        "reclaimed_produced_l": run["totals"]["reclaimed_water_l"], "pending_transfer_l": pending,
        "cases": {name: replay(rows, capacity, initial, reserve, supply)
                  for name, supply in alternatives.items()},
    }
    if makeup_budget:
        floors = {"meet_withdrawals": (0.0, 0.0),
                  "maintain_reserve_and_restore_opening_stock": (reserve, max(reserve, initial))}
        result["supplemental_water_budgets"] = {
            name: replay(rows, capacity, initial, reserve, receipts, minimum_stocks=targets)
            for name, targets in floors.items()
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("farm_report", type=Path)
    parser.add_argument("water_handoff", type=Path)
    parser.add_argument("recycling_profiles", type=Path)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--makeup-budget", action="store_true",
                        help="Calculate minimum additional farm water after reclaimed transfers")
    args = parser.parse_args()
    try:
        result = compare(args.farm_report, args.water_handoff, args.recycling_profiles,
                         args.scenario, args.days, makeup_budget=args.makeup_budget)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
