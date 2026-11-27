"""Compare synthetic wastewater recovery and hydroponic makeup in a habitat."""

import argparse
import json
from pathlib import Path

from autonomy import resource_summary
from habitat import amount, ledger, storage


SETTINGS = (
    "step_hours", "initial_energy_kwh", "energy_capacity_kwh",
    "initial_grow_water_l", "grow_water_capacity_l", "initial_grow_nutrients_g",
    "grow_nutrient_capacity_g", "raw_capacity_l", "treatment_capacity_l",
    "treatment_kwh_per_l", "water_recovery_fraction", "nutrient_recovery_fraction",
    "exercise_mechanical_w_per_person", "exercise_generator_efficiency",
)
STEP_FIELDS = (
    "solar_kwh", "other_energy_kwh", "exercise_person_hours", "base_load_kwh",
    "captured_wastewater_l", "captured_nutrient_equivalent_g", "fresh_makeup_l",
    "fresh_nutrient_equivalent_g", "grow_water_demand_l", "grow_nutrient_demand_g",
)
RESOURCES = ("energy_kwh", "grow_water_l", "grow_nutrient_equivalent_g")


def quantities(record, fields):
    if not isinstance(record, dict) or record.keys() != set(fields):
        raise ValueError(f"expected exactly these fields: {', '.join(fields)}")
    limits = {"step_hours": 24, "exercise_generator_efficiency": 1}
    return {key: amount(record[key], key, limit=limits.get(
        key, 1 if key.endswith("_fraction") else 1_000_000_000
    )) for key in fields}


def audit(settings, profile, cycles, *, treatment=True, exercise=True, trace=False):
    config = quantities(settings, SETTINGS)
    hours = config["step_hours"]
    cost = config["treatment_kwh_per_l"]
    if hours == 0 or cost == 0:
        raise ValueError("step_hours and treatment_kwh_per_l must be positive")
    if not isinstance(profile, dict) or profile.keys() != {"id", "steps"}:
        raise ValueError("profile must contain id and steps")
    name, raw_steps = profile["id"], profile["steps"]
    if not isinstance(name, str) or not name.strip() or not name.isprintable() or len(name) > 96:
        raise ValueError("profile id must be short, nonempty and printable")
    if (not isinstance(raw_steps, list) or not raw_steps or type(cycles) is not int
            or cycles < 1 or len(raw_steps) * cycles > 1000):
        raise ValueError("choose a positive cycle count covering 1 to 1000 intervals")
    steps = [quantities(step, STEP_FIELDS) for step in raw_steps]
    for step in steps:
        if step["captured_wastewater_l"] == 0 and step["captured_nutrient_equivalent_g"] > 0:
            raise ValueError("captured nutrient equivalents require a wastewater volume")

    battery, energy_capacity = storage(config["initial_energy_kwh"], config["energy_capacity_kwh"], "energy")
    water, water_capacity = storage(config["initial_grow_water_l"], config["grow_water_capacity_l"], "grow water")
    nutrients, nutrient_capacity = storage(
        config["initial_grow_nutrients_g"], config["grow_nutrient_capacity_g"], "grow nutrients"
    )
    raw_water = raw_nutrients = 0.0
    rows = []
    for i, step in enumerate(steps * cycles):
        exercise_kwh = (
            step["exercise_person_hours"] * config["exercise_mechanical_w_per_person"]
            * config["exercise_generator_efficiency"] / 1000
        ) if exercise else 0.0
        supply = step["solar_kwh"] + step["other_energy_kwh"] + exercise_kwh
        base_demand = step["base_load_kwh"]
        spare_kwh = max(0.0, battery + supply - base_demand)
        process_l = min(raw_water, config["treatment_capacity_l"], spare_kwh / cost) if treatment else 0.0
        treatment_kwh = min(spare_kwh, process_l * cost)
        energy = ledger(battery, supply, base_demand + treatment_kwh, energy_capacity)
        process_g = raw_nutrients * (process_l / raw_water) if raw_water else 0.0
        reclaimed_l = process_l * config["water_recovery_fraction"]
        reclaimed_g = process_g * config["nutrient_recovery_fraction"]

        grow_water = ledger(water, step["fresh_makeup_l"] + reclaimed_l, step["grow_water_demand_l"], water_capacity)
        grow_nutrients = ledger(
            nutrients, step["fresh_nutrient_equivalent_g"] + reclaimed_g,
            step["grow_nutrient_demand_g"], nutrient_capacity,
        )

        # New wastewater arrives after treatment. Excess mixed feed spills
        # in proportion to its concentration, carrying its own nutrient mass.
        mixed_l = raw_water - process_l + step["captured_wastewater_l"]
        mixed_g = raw_nutrients - process_g + step["captured_nutrient_equivalent_g"]
        next_raw_water = min(mixed_l, config["raw_capacity_l"])
        next_raw_nutrients = mixed_g * (next_raw_water / mixed_l) if mixed_l else 0.0
        rows.append({
            "start_hour": i * hours,
            "energy_kwh": energy,
            "grow_water_l": grow_water,
            "grow_nutrient_equivalent_g": grow_nutrients,
            "solar_kwh": step["solar_kwh"],
            "other_energy_kwh": step["other_energy_kwh"],
            "exercise_kwh": exercise_kwh,
            "base_load_kwh": base_demand,
            "treatment_kwh": treatment_kwh,
            "fresh_makeup_l": step["fresh_makeup_l"],
            "fresh_nutrient_equivalent_g": step["fresh_nutrient_equivalent_g"],
            "raw_water_start_l": raw_water,
            "raw_nutrients_start_g": raw_nutrients,
            "captured_wastewater_l": step["captured_wastewater_l"],
            "captured_nutrient_equivalent_g": step["captured_nutrient_equivalent_g"],
            "processed_wastewater_l": process_l,
            "processed_nutrient_equivalent_g": process_g,
            "reclaimed_water_l": reclaimed_l,
            "recovered_nutrient_equivalent_g": reclaimed_g,
            "treatment_residual_water_l": process_l - reclaimed_l,
            "treatment_residual_nutrient_equivalent_g": process_g - reclaimed_g,
            "raw_water_overflow_l": mixed_l - next_raw_water,
            "raw_nutrient_overflow_g": mixed_g - next_raw_nutrients,
            "raw_water_end_l": next_raw_water,
            "raw_nutrients_end_g": next_raw_nutrients,
        })
        battery, water, nutrients = energy["end"], grow_water["end"], grow_nutrients["end"]
        raw_water, raw_nutrients = next_raw_water, next_raw_nutrients

    stock_fields = {"start_hour", *RESOURCES, "raw_water_start_l", "raw_nutrients_start_g",
                    "raw_water_end_l", "raw_nutrients_end_g"}
    report = {
        "scenario": name, "cycles": cycles, "duration_hours": hours * len(rows),
        "treatment_enabled": treatment, "exercise_enabled": exercise,
        "resources": {key: resource_summary(rows, key) for key in RESOURCES},
        "totals": {key: sum(row[key] for row in rows) for key in rows[0] if key not in stock_fields},
        "final_raw_water_l": raw_water,
        "final_raw_nutrient_equivalent_g": raw_nutrients,
    }
    if trace:
        report["intervals"] = rows
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", type=Path)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--scenario", help="Select one profile by ID")
    parser.add_argument("--no-exercise", action="store_true", help="Set exercise electricity to zero")
    parser.add_argument("--trace", action="store_true", help="Include interval balances")
    args = parser.parse_args()
    try:
        document = json.loads(args.profiles.read_text(encoding="utf-8"))
        if document["schema"] != "synthetic-wastewater-recycling/1":
            raise ValueError("expected synthetic-wastewater-recycling/1")
        profiles = document["profiles"]
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 32:
            raise ValueError("expected between 1 and 32 profiles")
        ids = [profile["id"] for profile in profiles]
        if any(not isinstance(name, str) for name in ids) or len(set(ids)) != len(ids):
            raise ValueError("profile IDs must be unique strings")
        selected = [profile for profile in profiles if args.scenario in (None, profile["id"])]
        if not selected:
            raise ValueError("no matching scenario")
        results = [
            audit(document["settings"], profile, args.cycles,
                  treatment=treatment, exercise=not args.no_exercise, trace=args.trace)
            for profile in selected for treatment in (True, False)
        ]
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": "synthetic-wastewater-recycling-audit/1", "runs": results},
                     indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
