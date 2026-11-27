"""Offline validation and aggregate import of indoor-grow interval output."""

import argparse
import hashlib
import hmac
import json
import math
from pathlib import Path
import re


REPORT_SCHEMA = "synthetic-habitat-indoor-aggregate-comparison/1"
PRODUCER_SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_INTERVALS = 96
MAX_LOADS = 128
MAX_VALUE = 1_000_000_000_000
TOLERANCE = 1e-8
DISPATCH_POLICY = (
    "solar first; critical before noncritical; grid-down noncritical shedding; "
    "battery for critical loads only; proportional same-class shortfall allocation"
)

TOP_FIELDS = {
    "schema_version", "scenario", "interval_count", "interval_minutes",
    "dispatch_policy", "lighting_profiles", "timer_audits", "energy_summary",
    "load_totals", "water_summary", "chemical_inventory", "intervals", "limitations",
}
SCENARIO_FIELDS = {"name", "version", "status", "location_placeholder", "source_label"}
ENERGY_SUMMARY_FIELDS = {
    "requested_critical_kwh", "requested_noncritical_kwh", "served_critical_kwh",
    "served_noncritical_kwh", "shed_critical_kwh", "shed_noncritical_kwh",
    "solar_available_kwh", "solar_to_loads_kwh", "solar_to_battery_kwh",
    "solar_curtailed_kwh", "grid_to_loads_kwh", "grid_to_battery_kwh",
    "battery_to_loads_kwh", "battery_initial_charge_kwh", "battery_final_charge_kwh",
    "battery_minimum_charge_kwh", "battery_recovery_target_kwh",
    "battery_recovery_target_met", "energy_balance_max_residual_kwh",
    "outage_intervals", "conservation_intervals",
}
WATER_SUMMARY_FIELDS = {
    "requested_withdrawal_l", "served_withdrawal_l", "shortfall_l", "recovered_l",
    "makeup_l", "overflow_l", "initial_stock_l", "final_stock_l",
    "minimum_end_stock_l", "reserve_l", "final_stock_minus_reserve_l",
    "below_reserve_intervals",
}
INTERVAL_ENERGY_FIELDS = {
    "requested_critical_kwh", "requested_noncritical_kwh", "served_critical_kwh",
    "served_noncritical_kwh", "shed_critical_kwh", "shed_noncritical_kwh",
    "solar_available_kwh", "solar_to_loads_kwh", "solar_to_battery_kwh",
    "solar_curtailed_kwh", "grid_to_loads_kwh", "grid_to_battery_kwh",
    "battery_to_loads_kwh", "battery_charge_start_kwh", "battery_charge_end_kwh",
}
INTERVAL_WATER_FIELDS = {
    "water_stock_start_l", "water_recovered_l", "water_makeup_l",
    "water_requested_withdrawal_l", "water_served_withdrawal_l", "water_shortfall_l",
    "water_overflow_l", "water_stock_end_l",
}
INTERVAL_FIELDS = (
    INTERVAL_ENERGY_FIELDS | INTERVAL_WATER_FIELDS |
    {"index", "start_minute", "end_minute", "duration_hours", "grid_available",
     "conservation_mode", "water_below_reserve", "loads"}
)
LOAD_FIELDS = {
    "name", "kind", "criticality", "source_label", "active_minutes",
    "requested_kwh", "served_kwh", "shed_kwh",
}
LOAD_TOTAL_FIELDS = LOAD_FIELDS - {"active_minutes"}
ENERGY_SUMMED_FIELDS = (
    "requested_critical_kwh", "requested_noncritical_kwh", "served_critical_kwh",
    "served_noncritical_kwh", "shed_critical_kwh", "shed_noncritical_kwh",
    "solar_available_kwh", "solar_to_loads_kwh", "solar_to_battery_kwh",
    "solar_curtailed_kwh", "grid_to_loads_kwh", "grid_to_battery_kwh",
    "battery_to_loads_kwh",
)
WATER_SUMMED_FIELDS = (
    "requested_withdrawal_l", "served_withdrawal_l", "shortfall_l", "recovered_l",
    "makeup_l", "overflow_l",
)


def _object(value, fields, path):
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    unknown = sorted(set(value) - fields)
    missing = sorted(fields - set(value))
    if unknown:
        raise ValueError(f"{path} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"{path} is missing fields: {', '.join(missing)}")
    return value


def _number(value, path, *, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{path} must be a finite JSON number")
    if not minimum <= value <= MAX_VALUE:
        raise ValueError(f"{path} must be between {minimum} and {MAX_VALUE}")
    return float(value)


def _integer(value, path, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{path} must be an integer between {minimum} and {maximum}")
    return value


def _boolean(value, path):
    if type(value) is not bool:
        raise ValueError(f"{path} must be a JSON boolean")
    return value


def _text(value, path, limit=4096):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or not value.isprintable():
        raise ValueError(f"{path} must be a printable string of at most {limit} characters")
    return value


def _list(value, path, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{path} must be an array with at most {limit} entries")
    return value


def _numbers(document, fields, path):
    return {field: _number(document[field], f"{path}.{field}") for field in sorted(fields)}


def _close(actual, expected, path):
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=TOLERANCE):
        raise ValueError(f"{path} does not match interval arithmetic: {actual} != {expected}")


def _sum(values, path):
    try:
        result = math.fsum(values)
    except OverflowError as exc:
        raise ValueError(f"{path} has a non-finite total") from exc
    if not math.isfinite(result):
        raise ValueError(f"{path} has a non-finite total")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _load_json(path):
    with Path(path).open("rb") as source:
        raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds the {MAX_INPUT_BYTES}-byte limit")
    if not raw:
        raise ValueError("input is empty")
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    try:
        document = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc
    return document, raw, digest


def _load_identity(load, path, *, total):
    fields = LOAD_TOTAL_FIELDS if total else LOAD_FIELDS
    _object(load, fields, path)
    identity = (
        _text(load["name"], f"{path}.name", 256),
        _text(load["kind"], f"{path}.kind", 32),
        _text(load["criticality"], f"{path}.criticality", 16),
        _text(load["source_label"], f"{path}.source_label", 1024),
    )
    if identity[1] not in {"lighting", "timer", "continuous"}:
        raise ValueError(f"{path}.kind has an unsupported value")
    if identity[2] not in {"critical", "noncritical"}:
        raise ValueError(f"{path}.criticality has an unsupported value")
    values = _numbers(load, {"requested_kwh", "served_kwh", "shed_kwh"}, path)
    _close(values["requested_kwh"], values["served_kwh"] + values["shed_kwh"], f"{path}.requested_kwh")
    return identity, values


def _validate(document, source):
    _object(document, TOP_FIELDS, "input")
    if type(document["schema_version"]) is not int or document["schema_version"] != PRODUCER_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be exactly {PRODUCER_SCHEMA_VERSION}")

    scenario = _object(document["scenario"], SCENARIO_FIELDS, "scenario")
    for field in SCENARIO_FIELDS:
        _text(scenario[field], f"scenario.{field}")
    count = _integer(document["interval_count"], "interval_count", 1, MAX_INTERVALS)
    minutes = _integer(document["interval_minutes"], "interval_minutes", 1, 1440)
    if 1440 % count or minutes != 1440 // count:
        raise ValueError("interval_count must divide 1440 and interval_minutes must equal 1440 / interval_count")
    if document["dispatch_policy"] != DISPATCH_POLICY:
        raise ValueError("dispatch_policy is not the supported schema-v1 policy")
    for field, limit in (("lighting_profiles", MAX_LOADS), ("timer_audits", MAX_LOADS),
                         ("chemical_inventory", MAX_LOADS), ("limitations", 64)):
        _list(document[field], field, limit)
    source_limitations = [
        _text(item, f"limitations[{index}]")
        for index, item in enumerate(document["limitations"])
    ]

    energy_summary_raw = _object(document["energy_summary"], ENERGY_SUMMARY_FIELDS, "energy_summary")
    energy_summary = _numbers(
        energy_summary_raw, ENERGY_SUMMARY_FIELDS - {
            "battery_recovery_target_met", "outage_intervals", "conservation_intervals",
        }, "energy_summary",
    )
    target_met = _boolean(energy_summary_raw["battery_recovery_target_met"], "energy_summary.battery_recovery_target_met")
    outages = _integer(energy_summary_raw["outage_intervals"], "energy_summary.outage_intervals", 0, count)
    conservations = _integer(
        energy_summary_raw["conservation_intervals"], "energy_summary.conservation_intervals", 0, count,
    )
    water_summary_raw = _object(document["water_summary"], WATER_SUMMARY_FIELDS, "water_summary")
    water_summary = _numbers(
        water_summary_raw, WATER_SUMMARY_FIELDS - {"final_stock_minus_reserve_l", "below_reserve_intervals"},
        "water_summary",
    )
    water_summary["final_stock_minus_reserve_l"] = _number(
        water_summary_raw["final_stock_minus_reserve_l"], "water_summary.final_stock_minus_reserve_l",
        minimum=-MAX_VALUE,
    )
    below_reserve_count = _integer(
        water_summary_raw["below_reserve_intervals"], "water_summary.below_reserve_intervals", 0, count,
    )

    total_identities = {}
    total_values = {}
    totals = _list(document["load_totals"], "load_totals", MAX_LOADS)
    for index, load in enumerate(totals):
        identity, values = _load_identity(load, f"load_totals[{index}]", total=True)
        if identity[0] in total_identities:
            raise ValueError(f"duplicate load name: {identity[0]}")
        total_identities[identity[0]] = identity
        total_values[identity[0]] = values

    intervals = _list(document["intervals"], "intervals", MAX_INTERVALS)
    if len(intervals) != count:
        raise ValueError("intervals length must equal interval_count")
    normalized = []
    energy_rows = []
    water_rows = []
    load_sums = {name: {field: [] for field in ("requested_kwh", "served_kwh", "shed_kwh")}
                 for name in total_identities}
    conflicts = []
    previous_energy = None
    previous_water = None
    below_flags = []

    for position, row in enumerate(intervals):
        path = f"intervals[{position}]"
        _object(row, INTERVAL_FIELDS, path)
        index = _integer(row["index"], f"{path}.index", 0, count - 1)
        start = _integer(row["start_minute"], f"{path}.start_minute", 0, 1439)
        end = _integer(row["end_minute"], f"{path}.end_minute", 1, 1440)
        if index != position or start != position * minutes or end != (position + 1) * minutes:
            raise ValueError(f"{path} has inconsistent index or half-open interval boundaries")
        duration = _number(row["duration_hours"], f"{path}.duration_hours")
        _close(duration, minutes / 60, f"{path}.duration_hours")
        grid = _boolean(row["grid_available"], f"{path}.grid_available")
        conservation = _boolean(row["conservation_mode"], f"{path}.conservation_mode")
        if conservation != (not grid):
            raise ValueError(f"{path}.conservation_mode must equal not grid_available")
        below = _boolean(row["water_below_reserve"], f"{path}.water_below_reserve")
        below_flags.append(below)
        energy = _numbers(row, INTERVAL_ENERGY_FIELDS, path)
        water = _numbers(row, INTERVAL_WATER_FIELDS, path)
        energy_rows.append(energy)
        water_rows.append(water)

        requested = energy["requested_critical_kwh"] + energy["requested_noncritical_kwh"]
        served = energy["served_critical_kwh"] + energy["served_noncritical_kwh"]
        shed = energy["shed_critical_kwh"] + energy["shed_noncritical_kwh"]
        for criticality in ("critical", "noncritical"):
            _close(
                energy[f"requested_{criticality}_kwh"],
                energy[f"served_{criticality}_kwh"] + energy[f"shed_{criticality}_kwh"],
                f"{path}.requested_{criticality}_kwh",
            )
        _close(
            served,
            energy["solar_to_loads_kwh"] + energy["grid_to_loads_kwh"] + energy["battery_to_loads_kwh"],
            f"{path} source-to-load energy",
        )
        _close(
            energy["solar_available_kwh"],
            energy["solar_to_loads_kwh"] + energy["solar_to_battery_kwh"] + energy["solar_curtailed_kwh"],
            f"{path}.solar_available_kwh",
        )
        if not grid:
            _close(energy["grid_to_loads_kwh"] + energy["grid_to_battery_kwh"], 0, f"{path} unavailable grid flow")
            _close(energy["served_noncritical_kwh"], 0, f"{path}.served_noncritical_kwh")
        else:
            _close(energy["battery_to_loads_kwh"], 0, f"{path}.battery_to_loads_kwh")
            _close(shed, 0, f"{path} grid-available shed energy")
        if previous_energy is not None:
            _close(energy["battery_charge_start_kwh"], previous_energy["battery_charge_end_kwh"],
                   f"{path}.battery_charge_start_kwh")
        if previous_water is not None:
            _close(water["water_stock_start_l"], previous_water["water_stock_end_l"],
                   f"{path}.water_stock_start_l")
        _close(
            water["water_requested_withdrawal_l"],
            water["water_served_withdrawal_l"] + water["water_shortfall_l"],
            f"{path}.water_requested_withdrawal_l",
        )
        _close(
            water["water_stock_start_l"] + water["water_recovered_l"] + water["water_makeup_l"],
            water["water_served_withdrawal_l"] + water["water_stock_end_l"] + water["water_overflow_l"],
            f"{path} water balance",
        )
        if below != (water["water_stock_end_l"] < water_summary["reserve_l"]):
            raise ValueError(f"{path}.water_below_reserve does not match water_stock_end_l and reserve_l")
        if previous_energy is not None:
            previous_shed = previous_energy["shed_critical_kwh"] + previous_energy["shed_noncritical_kwh"]
            if previous_shed > TOLERANCE and water["water_recovered_l"] > TOLERANCE:
                conflicts.append({
                    "interval_index": index,
                    "previous_interval_index": index - 1,
                    "previous_energy_shed_kwh": previous_shed,
                    "agricultural_water_recovered_l": water["water_recovered_l"],
                })

        loads = _list(row["loads"], f"{path}.loads", MAX_LOADS)
        interval_identities = {}
        class_values = {name: {field: [] for field in ("requested_kwh", "served_kwh", "shed_kwh")}
                        for name in ("critical", "noncritical")}
        for load_index, load in enumerate(loads):
            identity, values = _load_identity(load, f"{path}.loads[{load_index}]", total=False)
            name = identity[0]
            if name in interval_identities:
                raise ValueError(f"{path} has duplicate load name: {name}")
            if name not in total_identities or total_identities[name] != identity:
                raise ValueError(f"{path} has a load absent from or inconsistent with load_totals: {name}")
            interval_identities[name] = identity
            _integer(load["active_minutes"], f"{path}.loads[{load_index}].active_minutes", 0, minutes)
            for field, value in values.items():
                class_values[identity[2]][field].append(value)
                load_sums[name][field].append(value)
        if set(interval_identities) != set(total_identities):
            raise ValueError(f"{path}.loads must contain every load_totals name exactly once")
        for criticality, values in class_values.items():
            for field, items in values.items():
                summary_field = f"{field[:-4]}_{criticality}_kwh"
                _close(energy[summary_field], _sum(items, f"{path} {summary_field}"),
                       f"{path}.{summary_field} load sum")

        normalized.append({
            "index": index,
            "start_minute": start,
            "end_minute": end,
            "energy_kwh": {"requested": requested, "served": served, "shed": shed},
            "agricultural_water_l": {
                "stock_start": water["water_stock_start_l"],
                "recovered": water["water_recovered_l"],
                "makeup": water["water_makeup_l"],
                "requested_withdrawal": water["water_requested_withdrawal_l"],
                "served_withdrawal": water["water_served_withdrawal_l"],
                "shortfall": water["water_shortfall_l"],
                "stock_end": water["water_stock_end_l"],
                "overflow": water["water_overflow_l"],
            },
        })
        previous_energy = energy
        previous_water = water

    for field in ENERGY_SUMMED_FIELDS:
        _close(energy_summary[field], _sum((row[field] for row in energy_rows), field), f"energy_summary.{field}")
    for field in WATER_SUMMED_FIELDS:
        _close(water_summary[field], _sum((row[f"water_{field}"] for row in water_rows), field),
               f"water_summary.{field}")
    _close(energy_summary["battery_initial_charge_kwh"], energy_rows[0]["battery_charge_start_kwh"],
           "energy_summary.battery_initial_charge_kwh")
    _close(energy_summary["battery_final_charge_kwh"], energy_rows[-1]["battery_charge_end_kwh"],
           "energy_summary.battery_final_charge_kwh")
    charge_values = [energy_rows[0]["battery_charge_start_kwh"]] + [row["battery_charge_end_kwh"] for row in energy_rows]
    _close(energy_summary["battery_minimum_charge_kwh"], min(charge_values), "energy_summary.battery_minimum_charge_kwh")
    if target_met != (energy_summary["battery_final_charge_kwh"] >= energy_summary["battery_recovery_target_kwh"]):
        raise ValueError("energy_summary.battery_recovery_target_met does not match final charge and target")
    expected_outages = sum(
        not _boolean(row["grid_available"], f"intervals[{index}].grid_available")
        for index, row in enumerate(intervals)
    )
    expected_conservations = sum(
        _boolean(row["conservation_mode"], f"intervals[{index}].conservation_mode")
        for index, row in enumerate(intervals)
    )
    if outages != expected_outages or conservations != expected_conservations:
        raise ValueError("energy_summary outage/conservation counts do not match intervals")

    _close(water_summary["initial_stock_l"], water_rows[0]["water_stock_start_l"], "water_summary.initial_stock_l")
    _close(water_summary["final_stock_l"], water_rows[-1]["water_stock_end_l"], "water_summary.final_stock_l")
    _close(water_summary["minimum_end_stock_l"], min(row["water_stock_end_l"] for row in water_rows),
           "water_summary.minimum_end_stock_l")
    _close(water_summary["final_stock_minus_reserve_l"],
           water_summary["final_stock_l"] - water_summary["reserve_l"],
           "water_summary.final_stock_minus_reserve_l")
    if below_reserve_count != sum(below_flags):
        raise ValueError("water_summary.below_reserve_intervals does not match intervals")

    for name, values in total_values.items():
        for field, expected in values.items():
            _close(expected, _sum(load_sums[name][field], f"load_totals.{name}.{field}"),
                   f"load_totals.{name}.{field}")

    return {
        "schema": REPORT_SCHEMA,
        "data_kind": "synthetic",
        "report_type": "offline_indoor_aggregate_comparison",
        "source": source,
        "interval_convention": {
            "count": count,
            "minutes_per_interval": minutes,
            "boundaries": "half-open [start_minute, end_minute)",
            "duration_hours": count * minutes / 60,
        },
        "units": {"energy": "kWh", "agricultural_water": "L", "time": "minute"},
        "aggregates": {
            "energy_kwh": dict(sorted(energy_summary.items())),
            "agricultural_water_l": dict(sorted(water_summary.items())),
            "outage_intervals": outages,
            "conservation_intervals": conservations,
            "battery_recovery_target_met": target_met,
            "below_reserve_intervals": below_reserve_count,
        },
        "intervals": normalized,
        "comparison": {
            "declared_summaries_match_interval_sums": True,
            "load_totals_match_interval_loads": True,
            "scenario_conversion": "not_emitted_for_producer_schema_v1",
            "reason": (
                "Producer schema v1 reports post-dispatch flows without the storage capacities and exogenous "
                "aggregate supply inputs needed by Habitat; its priority/lossy battery dispatch and independent "
                "agricultural water ledger are not Habitat's ideal-storage, power-coupled recovery model."
            ),
            "power_water_coupling": {
                "producer": "explicit agricultural recovery and makeup inputs, independent of energy shortfalls",
                "habitat": "recovery is derived from delivered water, delayed one interval, and stopped by energy shortfall",
                "observed_conflicts": conflicts,
            },
            "water_scope": (
                "Simulated agricultural withdrawal, stock, makeup and recovery only; not potable water, "
                "human water demand, water quality, occupancy safety or life-support validation."
            ),
        },
        "limitations": [
            "Aggregate arithmetic comparison only; this report is not a Habitat scenario or reserve calculation.",
            "No crop biology, yield, food closure, nutrition or food-safety assessment.",
            "No occupancy-safety or life-support validation.",
            "SHA-256 provenance supports change pinning, not authenticity or a digital signature.",
            *source_limitations,
        ],
    }


def compare_indoor(path, *, expected_sha256=None):
    """Read one explicit local path and return a deterministic aggregate report."""
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
    ):
        raise ValueError("expected SHA-256 must contain exactly 64 hexadecimal characters")
    document, raw, digest = _load_json(path)
    if expected_sha256 is not None and not hmac.compare_digest(digest, expected_sha256.lower()):
        raise ValueError(f"source SHA-256 mismatch: computed {digest}")
    if not isinstance(document, dict):
        raise ValueError("input must be a JSON object")
    scenario = document.get("scenario")
    scenario = scenario if isinstance(scenario, dict) else {}
    source = {
        "path": str(path),
        "bytes": len(raw),
        "sha256": digest,
        "expected_sha256_verified": expected_sha256 is not None,
        "producer_schema_version": document.get("schema_version"),
        "scenario_name": scenario.get("name"),
        "scenario_version": scenario.get("version"),
        "scenario_status": scenario.get("status"),
        "source_label": scenario.get("source_label"),
        "import_mode": "offline_explicit_path_no_network",
    }
    return _validate(document, source)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Explicit path to indoor-simulation JSON (no sibling-path discovery)")
    parser.add_argument("--expect-sha256", help="Require the source bytes to match this SHA-256 hex digest")
    args = parser.parse_args(argv)
    try:
        report = compare_indoor(args.input, expected_sha256=args.expect_sha256)
        output = json.dumps(report, indent=2, allow_nan=False) + "\n"
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(output, end="")


if __name__ == "__main__":
    main()
