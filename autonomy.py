"""Audit repeated resource cycles for a synthetic underground habitat."""

import argparse
import json
from pathlib import Path

from habitat import amount, ledger, simulate, storage


def resource_summary(rows, key):
    flows = [row[key] for row in rows]
    return {
        "initial": flows[0]["start"],
        "final": flows[-1]["end"],
        "demand": sum(flow["demand"] for flow in flows),
        "delivered": sum(flow["delivered"] for flow in flows),
        "unmet": sum(flow["unmet"] for flow in flows),
        "overflow": sum(flow["overflow"] for flow in flows),
        "first_shortfall_hour": next((row["start_hour"] for row in rows if row[key]["unmet"]), None),
    }


def audit(profile, cycles, *, deliveries, trace=False):
    """Run all repeated steps in order, starting with empty recovery/harvest buffers."""
    steps = profile["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a nonempty list")
    if type(cycles) is not int or cycles < 1 or len(steps) * cycles > 1000:
        raise ValueError("choose a positive cycle count covering at most 1000 intervals")
    hours = amount(profile["step_hours"], "step_hours", limit=24)
    pantry, pantry_capacity = storage(profile["initial_food_kg"], profile["food_capacity_kg"], "food")
    utility_steps, supplies = [], []
    for step in steps:
        onsite_kw = amount(step["onsite_kw"], "onsite_kw")
        local_water = amount(step["local_water_l_per_hour"], "local_water_l_per_hour")
        grid_kw = amount(step["import_kw"], "import_kw")
        imported_water = amount(step["import_water_l_per_hour"], "import_water_l_per_hour")
        food_shipment = amount(step["import_food_kg"], "import_food_kg")
        if not deliveries:
            grid_kw, imported_water, food_shipment = 0.0, 0.0, 0.0
        utility_steps.append({
            "event": step["event"],
            "supply_kw": onsite_kw + grid_kw,
            "load_kw": step["load_kw"],
            "import_l_per_hour": local_water + imported_water,
            "demand_l_per_hour": step["demand_l_per_hour"],
        })
        supplies.append({
            "onsite_energy_kwh": onsite_kw * hours, "import_energy_kwh": grid_kw * hours,
            "local_water_l": local_water * hours, "import_water_l": imported_water * hours,
            "import_food_kg": food_shipment,
            "potential_harvest_kg": amount(step["potential_harvest_kg"], "potential_harvest_kg"),
            "food_demand_kg": amount(step["food_demand_kg"], "food_demand_kg"),
        })

    utility_run = simulate({**profile, "steps": utility_steps * cycles})
    rows = utility_run["intervals"]
    pending_food = 0.0
    for index, row in enumerate(rows):
        supply = supplies[index % len(supplies)]
        food = ledger(pantry, pending_food + supply["import_food_kg"],
                      supply["food_demand_kg"], pantry_capacity)
        row["food_kg"] = food
        row["harvest_from_previous_kg"] = pending_food
        utilities_met = row["energy_kwh"]["unmet"] == 0 and row["water_l"]["unmet"] == 0
        pending_food = supply["potential_harvest_kg"] if utilities_met else 0.0
        row["harvest_for_next_kg"] = pending_food
        pantry = food["end"]
        # In the base ledger import_l means every fresh inflow to the water tank.
        # In this audit the external and local components are reported separately.
        del row["import_l"]
        row.update(supply)

    resources = {key: resource_summary(rows, key) for key in ("energy_kwh", "water_l", "food_kg")}
    shortfalls = [item["first_shortfall_hour"] for item in resources.values()
                  if item["first_shortfall_hour"] is not None]
    first = min(shortfalls, default=None)
    report = {
        "scenario": profile["id"], "cycles": cycles, "duration_hours": utility_run["duration_hours"],
        "mode": "scheduled_deliveries" if deliveries else "no_deliveries",
        "first_shortfall_hour": first,
        "first_shortfall_resources": [key for key, item in resources.items()
                                      if first is not None and item["first_shortfall_hour"] == first],
        "resources": resources,
        "external_receipts": {key: sum(row[key] for row in rows)
                              for key in ("import_energy_kwh", "import_water_l", "import_food_kg")},
        "local_inputs": {key: sum(row[key] for row in rows)
                         for key in ("onsite_energy_kwh", "local_water_l", "harvest_for_next_kg")},
        "final_pending_recovery_l": utility_run["water_pending_recovery_l"],
        "final_pending_harvest_kg": pending_food,
    }
    if trace:
        report["intervals"] = rows
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", type=Path)
    parser.add_argument("--cycles", type=int, default=30, help="Repeat each profile (default 30)")
    parser.add_argument("--scenario", help="Select a profile by ID")
    parser.add_argument("--trace", action="store_true", help="Include each interval ledger")
    args = parser.parse_args()
    try:
        document = json.loads(args.profiles.read_text(encoding="utf-8"))
        if document["schema"] != "synthetic-underground-autonomy/1":
            raise ValueError("expected synthetic-underground-autonomy/1")
        profiles = document["profiles"]
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 32:
            raise ValueError("expected between 1 and 32 profiles")
        ids = [profile["id"] for profile in profiles]
        if any(not isinstance(name, str) or not name.strip() for name in ids) or len(set(ids)) != len(ids):
            raise ValueError("profile IDs must be nonempty and unique")
        selected = [p for p in profiles if args.scenario is None or p["id"] == args.scenario]
        if not selected:
            raise ValueError("no matching scenario")
        results = [audit(p, args.cycles, deliveries=enabled, trace=args.trace)
                   for p in selected for enabled in (True, False)]
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"schema": "synthetic-underground-audit/1", "runs": results}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
