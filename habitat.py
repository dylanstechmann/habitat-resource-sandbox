"""Compare power and water shortfalls in synthetic habitat scenarios."""

import argparse
import json
from math import isclose
from pathlib import Path
import re


INTERRUPTION_INPUTS = {
    "both": {"supply_kw": 0, "import_l_per_hour": 0},
    "power": {"supply_kw": 0},
    "water": {"import_l_per_hour": 0},
}


def amount(value, field, *, limit=1_000_000_000):
    if type(value) not in (int, float) or not 0 <= value <= limit:
        raise ValueError(f"{field} must be a finite number between 0 and {limit}")
    return float(value)


def storage(start, capacity, field):
    capacity = amount(capacity, f"{field} capacity")
    return amount(start, f"initial {field}", limit=capacity), capacity


def ledger(stored, supply, demand, capacity):
    available = stored + supply
    delivered = min(available, demand)
    remaining = available - delivered
    end = min(remaining, capacity)
    return {
        "start": stored,
        "supply": supply,
        "demand": demand,
        "delivered": delivered,
        "unmet": 0.0 if isclose(demand, delivered, rel_tol=1e-12) else demand - delivered,
        "end": end,
        "overflow": remaining - end,
    }


def _reserve_stock(deficits, initial, capacity, final_target):
    required = 0.0 if final_target is None else final_target
    minimum_capacity = required
    for deficit in reversed(deficits):
        # Carry enough stock into each interval to serve its demand and leave
        # the stock required at the start of the following interval.
        required = max(0.0, required + deficit)
        minimum_capacity = max(minimum_capacity, required)
    report = {
        "initial_stock": initial,
        "capacity": capacity,
        "minimum_initial_stock": required,
        "minimum_capacity": minimum_capacity,
        "additional_initial_stock": max(0.0, required - initial),
        "additional_capacity": max(0.0, minimum_capacity - capacity),
    }
    if final_target is not None:
        report["minimum_final_stock"] = final_target
    return report


def _reserve_report(scenario, intervals, recovery_fraction, reserve_end):
    energy_target = water_target = None
    if reserve_end is not None:
        energy_target, water_target = reserve_end
        energy_target = amount(energy_target, "final energy target")
        water_target = amount(water_target, "final water target")
    energy_deficits = []
    water_deficits = []
    recovered_l = 0.0
    for row in intervals:
        power = row["energy_kwh"]
        energy_deficits.append(power["demand"] - power["supply"])
        water_demand_l = row["water_l"]["demand"]
        water_deficits.append(water_demand_l - (row["import_l"] + recovered_l))
        # Jointly meeting every load powers recovery of the full water demand.
        recovered_l = water_demand_l * recovery_fraction
    return {
        "energy_kwh": _reserve_stock(energy_deficits, scenario["initial_energy_kwh"],
                                     scenario["energy_capacity_kwh"], energy_target),
        "water_l": _reserve_stock(water_deficits, scenario["initial_water_l"],
                                  scenario["water_capacity_l"], water_target),
    }


def simulate(scenario, *, reserve=False, reserve_end=None):
    battery, battery_capacity = storage(
        scenario["initial_energy_kwh"], scenario["energy_capacity_kwh"], "energy"
    )
    water, water_capacity = storage(
        scenario["initial_water_l"], scenario["water_capacity_l"], "water"
    )
    recovery_fraction = amount(scenario["recovery_fraction"], "recovery_fraction", limit=1)
    duration = amount(scenario["step_hours"], "step_hours", limit=24)
    steps = scenario["steps"]
    if duration == 0 or not isinstance(steps, list) or not 1 <= len(steps) <= 1000:
        raise ValueError("use a positive step duration and between 1 and 1000 steps")
    recovery_l = 0.0
    trace = []
    for index, step in enumerate(steps):
        event = step["event"]
        if not isinstance(event, str) or not 1 <= len(event.strip()) <= 96 or not event.isprintable():
            raise ValueError("event must be a short, printable description")
        power = ledger(
            battery,
            amount(step["supply_kw"], "supply_kw") * duration,
            amount(step["load_kw"], "load_kw") * duration,
            battery_capacity,
        )
        imported_l = amount(step["import_l_per_hour"], "import_l_per_hour") * duration
        water_use = ledger(
            water,
            imported_l + recovery_l,
            amount(step["demand_l_per_hour"], "demand_l_per_hour") * duration,
            water_capacity,
        )
        # The listed power demand already includes recovery when it is scheduled.
        # Recovered water becomes available at the start of the following interval.
        next_recovery_l = water_use["delivered"] * recovery_fraction if power["unmet"] == 0 else 0.0
        trace.append({
            "start_hour": index * duration,
            "event": event,
            "energy_kwh": power,
            "water_l": water_use,
            "import_l": imported_l,
            "recovered_from_previous_l": recovery_l,
            "recovered_for_next_l": next_recovery_l,
        })
        battery, water, recovery_l = power["end"], water_use["end"], next_recovery_l
    result = {
        "scenario": scenario["id"],
        "duration_hours": len(trace) * duration,
        "unmet_energy_kwh": sum(row["energy_kwh"]["unmet"] for row in trace),
        "unmet_water_l": sum(row["water_l"]["unmet"] for row in trace),
        "first_shortfall_hour": next((
            row["start_hour"] for row in trace if row["energy_kwh"]["unmet"] or row["water_l"]["unmet"]
        ), None),
        "final_energy_kwh": battery,
        "final_water_l": water,
        "water_pending_recovery_l": recovery_l,
        "intervals": trace,
    }
    if reserve or reserve_end is not None:
        result["reserve"] = _reserve_report(scenario, trace, recovery_fraction, reserve_end)
    return result


def shortfall_profile(run, resource, step_hours):
    intervals = run["intervals"]
    shortfalls = []
    longest = 0
    consecutive = 0
    for index, row in enumerate(intervals):
        if row[resource]["unmet"]:
            shortfalls.append(index)
            consecutive += 1
            longest = max(longest, consecutive)
        else:
            consecutive = 0

    restored_index = shortfalls[-1] + 1 if shortfalls else len(intervals)
    restored_hour = intervals[restored_index]["start_hour"] if restored_index < len(intervals) else None
    return {
        "first_hour": intervals[shortfalls[0]]["start_hour"] if shortfalls else None,
        "interval_count": len(shortfalls),
        "longest_hours": longest * step_hours,
        "restored_hour": restored_hour,
    }


def compare_interruption(scenario, start_hour, end_hour, *, reserve=False, supply="both", reserve_end=None):
    if not isinstance(supply, str) or supply not in INTERRUPTION_INPUTS:
        raise ValueError("interrupted supply must be both, power or water")
    baseline = simulate(scenario, reserve=reserve, reserve_end=reserve_end)
    step_hours = scenario["step_hours"]
    steps = list(scenario["steps"])
    if not 0 <= start_hour < end_hour:
        raise ValueError(f"{baseline['scenario']}: interruption hours must be nonnegative and ordered")

    def boundary_index(hour):
        interval = hour / step_hours
        if not 0 <= interval <= len(steps) + 1e-9:
            raise ValueError(f"{baseline['scenario']}: interruption must be inside the scenario")
        index = round(interval)
        if not isclose(interval, index, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"{baseline['scenario']}: interruption hours must align with interval boundaries")
        return index

    start = boundary_index(start_hour)
    stop = boundary_index(end_hour)
    if start == stop:
        raise ValueError(f"{baseline['scenario']}: interruption must cover at least one interval")

    for index in range(start, stop):
        steps[index] = {**steps[index], **INTERRUPTION_INPUTS[supply]}
    interrupted = simulate({**scenario, "steps": steps}, reserve=reserve, reserve_end=reserve_end)
    summary = {}
    for resource in ("energy_kwh", "water_l"):
        total = f"unmet_{resource}"
        summary[resource] = {
            "additional_unmet": interrupted[total] - baseline[total],
            "baseline": shortfall_profile(baseline, resource, step_hours),
            "interrupted": shortfall_profile(interrupted, resource, step_hours),
        }
    result = {"scenario": baseline["scenario"], "summary": summary, "baseline": baseline, "interrupted": interrupted}
    if supply != "both":
        result["interrupted_supply"] = supply
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("--scenario", help="Run only this scenario ID")
    parser.add_argument(
        "--interrupt", type=float, nargs=2, metavar=("START_HOUR", "END_HOUR"),
        help="Compare each run with a supply interruption over this interval",
    )
    parser.add_argument("--interrupt-supply", choices=INTERRUPTION_INPUTS,
                        help="Select the external supply to interrupt (default: both)")
    parser.add_argument("--reserve", action="store_true",
                        help="Report starting stocks and capacities needed to meet all modeled demand")
    parser.add_argument("--reserve-end", type=float, nargs=2, metavar=("ENERGY_KWH", "WATER_L"),
                        help="Report reserves that also leave these stocks at the end of the run")
    args = parser.parse_args()
    if args.interrupt_supply is not None and args.interrupt is None:
        parser.error("--interrupt-supply requires --interrupt")
    try:
        document = json.loads(args.scenarios.read_text(encoding="utf-8"))
        if document["schema"] != "synthetic-habitat-resources/1":
            raise ValueError("expected synthetic-habitat-resources/1")
        scenarios = document["scenarios"]
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 32:
            raise ValueError("expected between 1 and 32 scenarios")
        identifiers = [item["id"] for item in scenarios]
        if any(not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name)
               for name in identifiers):
            raise ValueError("each scenario needs a short lowercase ID")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("scenario IDs must be unique")
        candidates = [item for item in scenarios if args.scenario is None or item["id"] == args.scenario]
        if not candidates:
            raise ValueError("no matching scenarios")
        report = {"data_kind": "synthetic"}
        if args.interrupt is None:
            report["runs"] = [
                simulate(item, reserve=args.reserve, reserve_end=args.reserve_end) for item in candidates
            ]
        else:
            start, end = args.interrupt
            report["interruption_hours"] = {"start": start, "end": end}
            report["runs"] = [
                compare_interruption(item, start, end, reserve=args.reserve,
                                     supply=args.interrupt_supply or "both", reserve_end=args.reserve_end)
                for item in candidates
            ]
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
