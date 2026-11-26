import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from indoor_import import MAX_INPUT_BYTES, REPORT_SCHEMA, compare_indoor


class IndoorImportTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent
        self.example = root / "examples" / "indoor-grow-aggregate.json"
        self.importer = root / "indoor_import.py"
        self.raw = self.example.read_bytes()
        self.document = json.loads(self.raw)
        self.digest = hashlib.sha256(self.raw).hexdigest()

    def assert_rejected(self, document, pattern):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, pattern):
                compare_indoor(path)

    def test_valid_aggregate_comparison_and_explicit_provenance(self):
        report = compare_indoor(self.example, expected_sha256=self.digest)
        self.assertEqual(report["schema"], REPORT_SCHEMA)
        self.assertEqual(report["report_type"], "offline_indoor_aggregate_comparison")
        self.assertEqual(report["source"]["sha256"], self.digest)
        self.assertEqual(report["source"]["bytes"], len(self.raw))
        self.assertTrue(report["source"]["expected_sha256_verified"])
        self.assertEqual(report["source"]["import_mode"], "offline_explicit_path_no_network")
        self.assertIn("Derived by explicit reference", report["source"]["source_label"])
        self.assertIn("newly invented", report["source"]["source_label"])
        energy = report["aggregates"]["energy_kwh"]
        self.assertEqual(
            sum(energy[field] for field in ("requested_critical_kwh", "requested_noncritical_kwh")), 20,
        )
        self.assertEqual(sum(energy[field] for field in ("served_critical_kwh", "served_noncritical_kwh")), 15)
        self.assertEqual(sum(energy[field] for field in ("shed_critical_kwh", "shed_noncritical_kwh")), 5)
        water = report["aggregates"]["agricultural_water_l"]
        self.assertEqual(water["requested_withdrawal_l"], 20)
        self.assertEqual(water["served_withdrawal_l"], 20)
        self.assertEqual(water["recovered_l"], 4)
        self.assertEqual(water["makeup_l"], 16)
        self.assertTrue(report["comparison"]["declared_summaries_match_interval_sums"])
        self.assertTrue(report["comparison"]["load_totals_match_interval_loads"])
        self.assertEqual(report["comparison"]["scenario_conversion"], "not_emitted_for_producer_schema_v1")
        self.assertNotIn("scenarios", report)
        self.assertNotIn("steps", report)

    def test_power_water_coupling_conflict_and_agricultural_scope_are_explicit(self):
        report = compare_indoor(self.example)
        coupling = report["comparison"]["power_water_coupling"]
        self.assertEqual(coupling["observed_conflicts"], [{
            "interval_index": 1,
            "previous_interval_index": 0,
            "previous_energy_shed_kwh": 5,
            "agricultural_water_recovered_l": 4,
        }])
        self.assertIn("independent", coupling["producer"])
        self.assertIn("stopped by energy shortfall", coupling["habitat"])
        scope = report["comparison"]["water_scope"]
        self.assertIn("agricultural", scope)
        self.assertIn("not potable water", scope)
        self.assertIn("human water demand", scope)

    def test_cli_is_deterministic_and_verifies_pinned_sha256(self):
        command = [
            sys.executable, str(self.importer), str(self.example), "--expect-sha256", self.digest,
        ]
        first = subprocess.check_output(command)
        second = subprocess.check_output(command)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), compare_indoor(self.example, expected_sha256=self.digest))
        self.assertTrue(first.endswith(bytes((10,))))

    def test_tamper_rejection_by_sha256_even_when_json_remains_valid(self):
        changed = copy.deepcopy(self.document)
        changed["scenario"]["version"] = "tampered-but-valid"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source SHA-256 mismatch"):
                compare_indoor(path, expected_sha256=self.digest)
            changed_report = compare_indoor(path)
            self.assertNotEqual(changed_report["source"]["sha256"], self.digest)
            self.assertFalse(changed_report["source"]["expected_sha256_verified"])

    def test_schema_units_nonfinite_and_unknown_fields_are_rejected(self):
        missing = copy.deepcopy(self.document)
        del missing["schema_version"]
        self.assert_rejected(missing, "missing fields: schema_version")

        incompatible = copy.deepcopy(self.document)
        incompatible["schema_version"] = 2
        self.assert_rejected(incompatible, "schema_version must be exactly 1")

        nonfinite = copy.deepcopy(self.document)
        nonfinite["intervals"][0]["requested_critical_kwh"] = float("nan")
        self.assert_rejected(nonfinite, "non-finite JSON number")

        boolean_number = copy.deepcopy(self.document)
        boolean_number["intervals"][0]["requested_critical_kwh"] = True
        self.assert_rejected(boolean_number, "finite JSON number")

        ambiguous_units = copy.deepcopy(self.document)
        summary = ambiguous_units["energy_summary"]
        summary["requested_critical_kj"] = summary.pop("requested_critical_kwh")
        self.assert_rejected(ambiguous_units, "unknown fields: requested_critical_kj")

        unknown = copy.deepcopy(self.document)
        unknown["unexpected"] = {}
        self.assert_rejected(unknown, "unknown fields: unexpected")

    def test_inconsistent_intervals_and_mismatched_totals_are_rejected(self):
        boundary = copy.deepcopy(self.document)
        boundary["intervals"][1]["start_minute"] = 60
        self.assert_rejected(boundary, "inconsistent index or half-open interval boundaries")

        continuity = copy.deepcopy(self.document)
        continuity["intervals"][1]["water_stock_start_l"] = 19
        self.assert_rejected(continuity, "water_stock_start_l")

        energy_total = copy.deepcopy(self.document)
        energy_total["energy_summary"]["requested_critical_kwh"] += 1
        self.assert_rejected(energy_total, "energy_summary.requested_critical_kwh")

        water_total = copy.deepcopy(self.document)
        water_total["water_summary"]["recovered_l"] += 1
        self.assert_rejected(water_total, "water_summary.recovered_l")

        load_total = copy.deepcopy(self.document)
        load_total["load_totals"][0]["requested_kwh"] += 1
        load_total["load_totals"][0]["shed_kwh"] += 1
        self.assert_rejected(load_total, "load_totals.critical pump")

        arithmetic = copy.deepcopy(self.document)
        arithmetic["intervals"][0]["served_critical_kwh"] += 1
        self.assert_rejected(arithmetic, "requested_critical_kwh")

    def test_duplicate_json_fields_and_load_names_are_rejected(self):
        duplicate = self.raw.decode("utf-8").replace(
            '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON field: schema_version"):
                compare_indoor(path)

        duplicate_load = copy.deepcopy(self.document)
        duplicate_load["load_totals"][1] = duplicate_load["load_totals"][0]
        self.assert_rejected(duplicate_load, "duplicate load name")

    def test_oversized_input_is_bounded_before_json_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "byte limit"):
                compare_indoor(path)

    def test_cli_errors_are_concise_and_return_two(self):
        cases = [
            ([], "the following arguments are required: input"),
            ([str(self.example), "--expect-sha256", "not-a-digest"], "64 hexadecimal"),
            ([str(self.example), "--expect-sha256", "0" * 64], "source SHA-256 mismatch"),
            ([str(self.example) + ".missing"], "No such file"),
        ]
        for arguments, message in cases:
            with self.subTest(message=message):
                result = subprocess.run(
                    [sys.executable, str(self.importer), *arguments], capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            oversized = Path(directory) / "oversized.json"
            oversized.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            result = subprocess.run(
                [sys.executable, str(self.importer), str(oversized)], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("byte limit", result.stderr)


if __name__ == "__main__":
    unittest.main()
