import json
from pathlib import Path
import tempfile
import unittest

from farm_water import compare, replay


EXAMPLES = Path(__file__).parent / "examples"
REPORT = EXAMPLES / "indoor-grow-aggregate.json"
HANDOFF = EXAMPLES / "farm-water-handoff.json"
PROFILES = EXAMPLES / "wastewater-recycling.json"


class FarmWaterTests(unittest.TestCase):
    def test_replacement_preserves_internal_recovery_and_end_batches(self):
        study = compare(REPORT, HANDOFF, PROFILES, "earth-underground", 2)
        cases = study["cases"]
        self.assertEqual(cases["scheduled_farm_makeup"]["makeup_l"], 32)
        self.assertEqual(cases["no_makeup"]["makeup_l"], 0)
        self.assertEqual(cases["habitat_reclaimed_only"]["makeup_l"], 12)
        self.assertEqual(study["reclaimed_produced_l"], 18)
        self.assertEqual(study["pending_transfer_l"], 6)
        for case in cases.values():
            self.assertEqual(case["farm_recovered_l"], 8)
            self.assertAlmostEqual(case["initial_stock_l"] + case["makeup_l"] + case["farm_recovered_l"],
                                   case["delivered_l"] + case["overflow_l"] + case["final_stock_l"])
        self.assertLess(cases["habitat_reclaimed_only"]["unmet_l"], cases["no_makeup"]["unmet_l"])

    def test_as_needed_supply_tracks_arrival_time_reserve_and_closing_stock(self):
        rows = [{"start_minute": minute, "agricultural_water_l": {
                    "requested_withdrawal": 5, "recovered": 1}} for minute in [0, 720]]
        # Late reclaimed water cannot serve an earlier withdrawal.
        late = replay(rows, 10, 2, 3, [0, 20], minimum_stocks=(3, 3))
        self.assertEqual(late["supplemental_l"], 5)
        self.assertEqual(late["first_supplement_minute"], 0)
        self.assertEqual(late["peak_supplement_minute"], 0)
        self.assertEqual(late["overflow_l"], 9)
        self.assertEqual(late["unmet_l"], 0)
        self.assertEqual(late["final_stock_l"], 10)
        early = replay(rows, 10, 2, 3, [20, 0], minimum_stocks=(3, 3))
        self.assertEqual(early["supplemental_l"], 0)
        self.assertIsNone(early["first_supplement_minute"])
        self.assertIsNone(early["peak_supplement_minute"])
        restored = replay(rows, 10, 8, 3, [0, 0], minimum_stocks=(3, 8))
        self.assertEqual(restored["peak_supplement_interval_l"], 8)
        self.assertEqual(restored["peak_supplement_minute"], 720)
        self.assertEqual(restored["final_stock_l"], 8)

    def test_optional_budgets_balance_and_preserve_original_cases(self):
        plain = compare(REPORT, HANDOFF, PROFILES, "earth-underground", 2)
        result = compare(REPORT, HANDOFF, PROFILES, "earth-underground", 2, makeup_budget=True)
        budgets = result.pop("supplemental_water_budgets")
        self.assertEqual(result, plain)
        reclaimed = plain["cases"]["habitat_reclaimed_only"]["makeup_l"]
        for case in budgets.values():
            self.assertEqual(case["unmet_l"], 0)
            self.assertEqual(case["makeup_l"], reclaimed + case["supplemental_l"])
            self.assertEqual(case["initial_stock_l"] + case["makeup_l"] + case["farm_recovered_l"],
                             case["delivered_l"] + case["overflow_l"] + case["final_stock_l"])
        restored = budgets["maintain_reserve_and_restore_opening_stock"]
        self.assertEqual(restored["below_reserve_intervals"], 0)
        self.assertGreaterEqual(restored["final_stock_l"], restored["initial_stock_l"])

    def test_receipts_between_farm_boundaries_wait_until_next_opening(self):
        profiles = json.loads(PROFILES.read_bytes())
        profiles["settings"]["step_hours"] = 8
        profile = profiles["profiles"][0]
        profile["steps"] = [profile["steps"][0]] * 3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eight-hour.json"
            path.write_text(json.dumps(profiles), encoding="utf-8")
            study = compare(REPORT, HANDOFF, path, profile["id"], 1)
        self.assertEqual(study["reclaimed_produced_l"], 12)
        self.assertEqual(study["pending_transfer_l"], 12)
        self.assertEqual(study["cases"]["habitat_reclaimed_only"]["makeup_l"], 0)

    def test_changed_report_and_impossible_capacity_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case.json"
            path.write_bytes(REPORT.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                compare(path, HANDOFF, PROFILES, "earth-underground", 1)
            handoff = json.loads(HANDOFF.read_bytes())
            handoff["reservoir_capacity_l"] = 10
            path.write_text(json.dumps(handoff), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "opening stock"):
                compare(REPORT, path, PROFILES, "earth-underground", 1)
