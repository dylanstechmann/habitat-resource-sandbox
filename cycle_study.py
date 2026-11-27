"""Compare opening reserves and recurring inputs in the three underground fixtures."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from autonomy import audit


HERE = Path(__file__).resolve().parent
PROFILES = HERE / "examples" / "subsurface-profiles.json"
RESOURCES = ("energy_kwh", "water_l", "food_kg")
IMPORTS = ("import_energy_kwh", "import_water_l", "import_food_kg")
LOCAL = ("onsite_energy_kwh", "local_water_l", "harvest_for_next_kg")


def cycle_repeat(rows, steps_per_cycle):
    """Compare complete states only at the start of the same schedule phase."""
    first = rows[0]
    initial = tuple(first[key]["start"] for key in RESOURCES) + (
        first["recovered_from_previous_l"], first["harvest_from_previous_kg"]
    )
    seen = {initial: 0}
    for stop in range(steps_per_cycle, len(rows) + 1, steps_per_cycle):
        last = rows[stop - 1]
        state = tuple(last[key]["end"] for key in RESOURCES) + (
            last["recovered_for_next_l"], last["harvest_for_next_kg"]
        )
        cycle = stop // steps_per_cycle
        if state in seen:
            start = seen[state]
            period = rows[start * steps_per_cycle:stop]
            return {
                "from_completed_cycle": start,
                "to_completed_cycle": cycle,
                "period_cycles": cycle - start,
                "state": dict(zip((*RESOURCES, "pending_water_l", "pending_harvest_kg"), state)),
                "period_unmet": {k: sum(row[k]["unmet"] for row in period) for k in RESOURCES},
                "period_imports": {k: sum(row[k] for row in period) for k in IMPORTS},
                "period_local_inputs": {k: sum(row[k] for row in period) for k in LOCAL},
            }
        seen[state] = cycle
    return None


def cases(profile):
    yield "scheduled", "Scheduled receipts and original stocks", profile, True
    yield "no_shipments", "Zero receipts and original stocks", profile, False
    if profile["id"] == "moon-subsurface":
        reserve = deepcopy(profile)
        reserve["initial_water_l"] = reserve["water_capacity_l"]
        yield "full_water_tank", "Zero receipts, start with a full water tank", reserve, False
        local = deepcopy(profile)
        for step in local["steps"]:
            step["local_water_l_per_hour"] += 0.25
        yield "more_local_water", "Zero receipts, add 0.25 L/h of assumed local water", local, False
    if profile["id"] == "mars-subsurface":
        reserve = deepcopy(profile)
        reserve["initial_food_kg"] = reserve["food_capacity_kg"]
        yield "full_pantry", "Zero receipts, start with a full pantry", reserve, False
        local = deepcopy(profile)
        for step in local["steps"]:
            step["potential_harvest_kg"] += 0.5
        yield "more_local_harvest", "Zero receipts, add 0.5 kg of potential harvest per interval", local, False


def study(profile_path, cycles):
    document = json.loads(profile_path.read_bytes())
    if document["schema"] != "synthetic-underground-autonomy/1":
        raise ValueError("expected the underground autonomy profile format")
    sources = (profile_path, HERE / "autonomy.py", HERE / "habitat.py", Path(__file__))
    inputs = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    results = []
    for profile in document["profiles"]:
        for name, change, scenario, shipments in cases(profile):
            run = audit(scenario, cycles, deliveries=shipments, trace=True)
            results.append({
                "scenario": profile["id"], "case": name, "assumption": change,
                "duration_hours": run["duration_hours"], "receipt_totals": run["external_receipts"],
                "first_gap_hour": {k: run["resources"][k]["first_shortfall_hour"] for k in RESOURCES},
                "unmet_totals": {k: run["resources"][k]["unmet"] for k in RESOURCES},
                "first_exact_repeat": cycle_repeat(run["intervals"], len(scenario["steps"])),
            })
    return {"schema": "underground-cycle-study/1", "cycles": cycles, "sha256": inputs, "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=30)
    args = parser.parse_args()
    try:
        result = study(PROFILES, args.cycles)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
