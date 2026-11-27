"""Conservation, coupling and CLI checks for the underground resource audit."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from autonomy import audit


ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "examples/subsurface-profiles.json"


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.earth, self.moon, self.mars = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]

    def test_repeat_crosses_cycle_boundaries_without_resetting(self):
        original = copy.deepcopy(self.mars)
        run = audit(self.mars, 30, deliveries=False, trace=True)
        rows = run["intervals"]
        self.assertEqual(run["first_shortfall_hour"], 120)
        self.assertEqual(run["first_shortfall_resources"], ["food_kg"])
        self.assertEqual(len(rows), 60)
        for last, current in zip(rows, rows[1:]):
            for resource in ("energy_kwh", "water_l", "food_kg"):
                self.assertEqual(last[resource]["end"], current[resource]["start"])
            self.assertEqual(last["harvest_for_next_kg"], current["harvest_from_previous_kg"])
            self.assertEqual(last["recovered_for_next_l"], current["recovered_from_previous_l"])
        self.assertEqual(self.mars, original)

    def test_inputs_outputs_and_final_pending_stocks_balance(self):
        for profile in (self.earth, self.moon, self.mars):
            for enabled in (True, False):
                run = audit(profile, 30, deliveries=enabled, trace=True)
                local, external = run["local_inputs"], run["external_receipts"]
                sources = {
                    "energy_kwh": local["onsite_energy_kwh"] + external["import_energy_kwh"],
                    "water_l": local["local_water_l"] + external["import_water_l"] +
                              sum(row["recovered_for_next_l"] for row in run["intervals"]) -
                              run["final_pending_recovery_l"],
                    "food_kg": local["harvest_for_next_kg"] + external["import_food_kg"] -
                               run["final_pending_harvest_kg"],
                }
                for key, supply in sources.items():
                    totals = run["resources"][key]
                    self.assertAlmostEqual(totals["initial"] + supply,
                                           totals["delivered"] + totals["final"] + totals["overflow"])
                    self.assertAlmostEqual(totals["demand"], totals["delivered"] + totals["unmet"])

    def test_water_shortfall_interrupts_food_production(self):
        run = audit(self.moon, 30, deliveries=False, trace=True)
        first = next(row for row in run["intervals"] if row["water_l"]["unmet"])
        self.assertEqual(first["start_hour"], 168)
        self.assertEqual(first["energy_kwh"]["unmet"], 0)
        self.assertEqual(first["harvest_from_previous_kg"], 1)
        self.assertEqual(first["harvest_for_next_kg"], 0)
        self.assertEqual(run["resources"]["food_kg"]["first_shortfall_hour"], 240)

    def test_power_cutoff_disables_recovery_and_harvest_and_keeps_ties(self):
        self.earth["initial_energy_kwh"] = 0
        self.earth["initial_food_kg"] = 0
        self.earth["steps"][0].update(onsite_kw=0, import_kw=5, import_food_kg=1)
        connected = audit(self.earth, 1, deliveries=True, trace=True)["intervals"][0]
        cut = audit(self.earth, 1, deliveries=False, trace=True)
        self.assertEqual(connected["import_energy_kwh"], 60)
        self.assertGreater(connected["recovered_for_next_l"], 0)
        self.assertEqual(cut["first_shortfall_resources"], ["energy_kwh", "food_kg"])
        self.assertEqual(cut["intervals"][0]["recovered_for_next_l"], 0)
        self.assertEqual(cut["intervals"][0]["harvest_for_next_kg"], 0)
        self.assertEqual(sum(cut["external_receipts"].values()), 0)

    def test_reject_unusable_cycles_and_invalid_inputs_even_if_imports_disabled(self):
        for cycles in (0, 501, True, 1.5):
            with self.assertRaises(ValueError):
                audit(self.earth, cycles, deliveries=True)
        self.earth["steps"][0]["import_kw"] = -1
        with self.assertRaisesRegex(ValueError, "import_kw"):
            audit(self.earth, 1, deliveries=False)

    def test_cli_matches_fixture_and_both_modes(self):
        cmd = [sys.executable, str(ROOT / "autonomy.py"), str(PROFILES), "--scenario", "mars-subsurface"]
        runs = json.loads(subprocess.check_output(cmd))["runs"]
        baseline, cut = runs
        self.assertEqual(baseline["duration_hours"], 720)
        self.assertEqual(baseline["external_receipts"]["import_food_kg"], 30)
        self.assertIsNone(baseline["first_shortfall_hour"])
        self.assertEqual(cut["resources"]["food_kg"]["unmet"], 25)
        self.assertNotIn("intervals", cut)
