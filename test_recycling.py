import json
from pathlib import Path
import subprocess
import sys
import unittest

from recycling import RESOURCES, audit


ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "examples" / "wastewater-recycling.json"
FIXTURE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


class RecyclingTests(unittest.TestCase):
    def test_feed_waits_for_the_next_interval(self):
        earth = FIXTURE["profiles"][0]
        first, second = audit(FIXTURE["settings"], earth, 1, trace=True)["intervals"]
        self.assertEqual(first["captured_wastewater_l"], 8)
        self.assertEqual(first["reclaimed_water_l"], 0)
        self.assertEqual(second["reclaimed_water_l"], 6)
        self.assertEqual(second["recovered_nutrient_equivalent_g"], 2.5)
        self.assertEqual(second["treatment_kwh"], 1)
        self.assertEqual(second["grow_water_l"]["supply"], 9)
        self.assertEqual(second["grow_nutrient_equivalent_g"]["supply"], 3.5)

    def test_each_interval_balances_outputs_storage_and_waste(self):
        for profile in FIXTURE["profiles"]:
            for enabled in (False, True):
                with self.subTest(profile=profile["id"], treatment=enabled):
                    report = audit(FIXTURE["settings"], profile, 30, treatment=enabled, trace=True)
                    for row in report["intervals"]:
                        for name in RESOURCES:
                            flow = row[name]
                            self.assertAlmostEqual(flow["start"] + flow["supply"],
                                                   flow["delivered"] + flow["end"] + flow["overflow"])
                        for start, captured, reclaimed, residual, overflow, end in (
                            ("raw_water_start_l", "captured_wastewater_l", "reclaimed_water_l",
                             "treatment_residual_water_l", "raw_water_overflow_l", "raw_water_end_l"),
                            ("raw_nutrients_start_g", "captured_nutrient_equivalent_g",
                             "recovered_nutrient_equivalent_g", "treatment_residual_nutrient_equivalent_g",
                             "raw_nutrient_overflow_g", "raw_nutrients_end_g"),
                        ):
                            self.assertAlmostEqual(row[start] + row[captured],
                                                   row[reclaimed] + row[residual] + row[overflow] + row[end])
                        power = row["energy_kwh"]
                        self.assertAlmostEqual(power["demand"], row["base_load_kwh"] + row["treatment_kwh"])
                        self.assertAlmostEqual(power["supply"],
                                               row["solar_kwh"] + row["other_energy_kwh"] + row["exercise_kwh"])

    def test_treatment_waits_for_spare_power_and_preserves_mixed_feed(self):
        first = FIXTURE["profiles"][0]["steps"][0]
        outage = {**first, "solar_kwh": 0, "exercise_person_hours": 0}
        recovery = {**outage, "solar_kwh": 4.5}
        settings = {**FIXTURE["settings"], "initial_energy_kwh": 0}
        profile = {"id": "outage", "steps": [outage, outage, recovery]}
        rows = audit(settings, profile, 1, trace=True)["intervals"]
        self.assertEqual(rows[1]["treatment_kwh"], 0)
        self.assertEqual(rows[1]["raw_water_end_l"], 16)
        self.assertEqual(rows[2]["processed_wastewater_l"], 4)
        self.assertEqual(rows[2]["processed_nutrient_equivalent_g"], 2.5)
        self.assertEqual(rows[2]["treatment_kwh"], 0.5)
        self.assertEqual(rows[2]["energy_kwh"]["unmet"], 0)

    def test_invalid_recovery_settings_and_feed_are_rejected(self):
        profile = FIXTURE["profiles"][0]
        settings = FIXTURE["settings"]
        for key, value in (("treatment_kwh_per_l", 0), ("water_recovery_fraction", 1.1),
                           ("exercise_generator_efficiency", float("nan"))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit({**settings, key: value}, profile, 1)
        invalid_step = {**profile["steps"][0], "captured_wastewater_l": 0}
        with self.assertRaisesRegex(ValueError, "require a wastewater volume"):
            audit(settings, {**profile, "steps": [invalid_step]}, 1)

    def test_cli_compares_treatment_with_and_without_recovery(self):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "recycling.py"), str(PROFILE_PATH),
             "--scenario", "earth-underground", "--cycles", "2", "--no-exercise"],
            check=True, capture_output=True, text=True,
        )
        enabled, disabled = json.loads(result.stdout)["runs"]
        self.assertGreater(enabled["totals"]["reclaimed_water_l"], 0)
        self.assertEqual(disabled["totals"]["reclaimed_water_l"], 0)
        for run in (enabled, disabled):
            self.assertEqual(run["totals"]["exercise_kwh"], 0)


if __name__ == "__main__":
    unittest.main()
