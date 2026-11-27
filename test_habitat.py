import json
from pathlib import Path
import subprocess
import sys
import unittest

from habitat import compare_interruption, simulate


class InterruptionTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name("scenarios.json")
        self.scenarios = {
            scenario["id"]: scenario
            for scenario in json.loads(path.read_text(encoding="utf-8"))["scenarios"]
        }
        self.cli = [
            sys.executable, str(path.with_name("habitat.py")), str(path),
            "--scenario", "desert-underground",
        ]

    def assert_conserved(self, run):
        previous = None
        for interval in run["intervals"]:
            for resource in ("energy_kwh", "water_l"):
                ledger = interval[resource]
                self.assertAlmostEqual(ledger["start"] + ledger["supply"],
                                       ledger["delivered"] + ledger["end"] + ledger["overflow"])
                self.assertAlmostEqual(ledger["demand"], ledger["delivered"] + ledger["unmet"])
            self.assertAlmostEqual(interval["water_l"]["supply"],
                                   interval["import_l"] + interval["recovered_from_previous_l"])
            if previous is not None:
                self.assertEqual(interval["energy_kwh"]["start"], previous["energy_kwh"]["end"])
                self.assertEqual(interval["water_l"]["start"], previous["water_l"]["end"])
                self.assertEqual(interval["recovered_from_previous_l"],
                                 previous["recovered_for_next_l"])
            previous = interval
        self.assertEqual(run["final_energy_kwh"], previous["energy_kwh"]["end"])
        self.assertEqual(run["final_water_l"], previous["water_l"]["end"])
        self.assertEqual(run["water_pending_recovery_l"], previous["recovered_for_next_l"])

    def test_interruption_preserves_original_and_balances_both_ledgers(self):
        scenario = self.scenarios["desert-underground"]
        original = simulate(scenario)
        report = compare_interruption(scenario, 6, 18)
        self.assertEqual(report, compare_interruption(scenario, 6, 18, supply="both"))
        self.assertNotIn("interrupted_supply", report)
        self.assertEqual(report["baseline"], original)
        self.assertEqual(simulate(scenario), original)
        self.assertEqual(report["summary"]["energy_kwh"]["additional_unmet"], 34)
        self.assertAlmostEqual(report["summary"]["water_l"]["additional_unmet"], 73.64)
        self.assertEqual(report["summary"]["energy_kwh"]["interrupted"], {
            "first_hour": 12, "interval_count": 2, "longest_hours": 12, "restored_hour": None,
        })
        self.assertEqual(report["interrupted"]["intervals"][3]["import_l"], original["intervals"][3]["import_l"])
        for run in (original, report["interrupted"]):
            self.assert_conserved(run)

    def test_recovery_and_interruption_without_additional_supply_loss(self):
        report = compare_interruption(self.scenarios["moon"], 6, 18)
        self.assertEqual(report["interrupted"], report["baseline"])
        self.assertEqual(report["summary"]["energy_kwh"]["interrupted"]["restored_hour"], 18)
        self.assertIsNone(report["summary"]["water_l"]["interrupted"]["restored_hour"])

    def test_selective_outages_preserve_other_inputs_and_propagate_recovery(self):
        scenario = self.scenarios["desert-underground"]
        baseline = simulate(scenario, reserve=True)
        power = compare_interruption(scenario, 0, 6, supply="power", reserve=True)
        water = compare_interruption(scenario, 0, 6, supply="water", reserve=True)
        for name, report in (("power", power), ("water", water)):
            self.assertEqual(report["interrupted_supply"], name)
            self.assertEqual(report["baseline"], baseline)
            self.assert_conserved(report["interrupted"])
        power_steps = power["interrupted"]["intervals"]
        water_steps = water["interrupted"]["intervals"]
        self.assertEqual(power_steps[0]["energy_kwh"]["supply"], 0)
        self.assertEqual([row["import_l"] for row in power_steps],
                         [row["import_l"] for row in baseline["intervals"]])
        self.assertEqual(power_steps[1]["recovered_from_previous_l"], 0)
        self.assertEqual([row["energy_kwh"] for row in water_steps],
                         [row["energy_kwh"] for row in baseline["intervals"]])
        self.assertEqual(water_steps[0]["import_l"], 0)
        self.assertAlmostEqual(water_steps[1]["recovered_from_previous_l"], 75.6)
        self.assertEqual(power["summary"]["energy_kwh"]["additional_unmet"], 36)
        self.assertAlmostEqual(power["summary"]["water_l"]["additional_unmet"], 181.44)
        self.assertEqual(water["summary"]["energy_kwh"]["additional_unmet"], 0)
        self.assertAlmostEqual(water["summary"]["water_l"]["additional_unmet"], 51.196)
        self.assertEqual(power["interrupted"]["reserve"]["water_l"], baseline["reserve"]["water_l"])
        self.assertEqual(water["interrupted"]["reserve"]["energy_kwh"], baseline["reserve"]["energy_kwh"])

    def test_selective_interruptions_respect_half_open_boundaries(self):
        scenario = self.scenarios["desert-underground"]
        baseline = simulate(scenario)
        for supply in ("power", "water"):
            with self.subTest(supply=supply):
                report = compare_interruption(scenario, 6, 18, supply=supply)
                for index, row in enumerate(report["interrupted"]["intervals"]):
                    original = baseline["intervals"][index]
                    expected_supply = 0 if index in (1, 2) else original["energy_kwh"]["supply"]
                    expected_import = 0 if supply == "water" and index in (1, 2) else original["import_l"]
                    if supply == "power":
                        self.assertEqual(row["energy_kwh"]["supply"], expected_supply)
                        self.assertEqual(row["import_l"], original["import_l"])
                    else:
                        self.assertEqual(row["import_l"], expected_import)
                        self.assertEqual(row["energy_kwh"], original["energy_kwh"])
                self.assert_conserved(report["interrupted"])
        final = compare_interruption(scenario, 18, 24, supply="water")
        self.assertEqual([row["import_l"] for row in final["interrupted"]["intervals"]],
                         [row["import_l"] for row in baseline["intervals"][:3]] + [0])

    def test_supply_validation(self):
        scenario = self.scenarios["desert-underground"]
        for supply in ("storage", "", "POWER", None, 1):
            with self.subTest(supply=supply), self.assertRaisesRegex(ValueError, "interrupted supply"):
                compare_interruption(scenario, 0, 6, supply=supply)

    def test_cli_supply_selection_validation_and_deterministic_output(self):
        window = ["--interrupt", "0", "6"]
        original = subprocess.check_output(self.cli + window)
        self.assertEqual(original, subprocess.check_output(self.cli + window))
        self.assertEqual(original, subprocess.check_output(self.cli + window + ["--interrupt-supply", "both"]))
        self.assertNotIn("interrupted_supply", json.loads(original)["runs"][0])
        for supply in ("power", "water"):
            with self.subTest(supply=supply):
                output = subprocess.check_output(self.cli + window + ["--interrupt-supply", supply])
                self.assertEqual(output, subprocess.check_output(self.cli + window + ["--interrupt-supply", supply]))
                expected = compare_interruption(self.scenarios["desert-underground"], 0, 6, supply=supply)
                self.assertEqual(json.loads(output)["runs"][0], expected)
        missing = subprocess.run(self.cli + ["--interrupt-supply", "power"], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--interrupt-supply requires --interrupt", missing.stderr)
        invalid = subprocess.run(self.cli + window + ["--interrupt-supply", "storage"],
                                 capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid choice", invalid.stderr)

    def test_fractional_boundaries_and_invalid_windows(self):
        scenario = {**self.scenarios["moon"], "step_hours": 0.1}
        for supply in ("both", "power", "water"):
            compare_interruption(scenario, 0.1, 0.3, supply=supply)
        for start, end in ((-0.1, 0.2), (0.15, 0.3), (0.2, 0.2), (0.3, 0.2),
                           (0, 0.5), (0, float("inf")), (float("nan"), 0.2)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                compare_interruption(scenario, start, end)

    def test_reserves_meet_both_loads_during_interruption(self):
        for name, scenario in self.scenarios.items():
            with self.subTest(scenario=name):
                reference = compare_interruption(scenario, 6, 18, reserve=True)["interrupted"]
                energy = reference["reserve"]["energy_kwh"]
                water = reference["reserve"]["water_l"]
                revised = {
                    **scenario,
                    "initial_energy_kwh": energy["minimum_initial_stock"],
                    "energy_capacity_kwh": energy["minimum_capacity"],
                    "initial_water_l": water["minimum_initial_stock"],
                    "water_capacity_l": water["minimum_capacity"],
                }
                interrupted = compare_interruption(revised, 6, 18)["interrupted"]
                self.assertEqual(interrupted["unmet_energy_kwh"], 0)
                self.assertEqual(interrupted["unmet_water_l"], 0)

                for field, unmet in (("initial_energy_kwh", "unmet_energy_kwh"),
                                     ("initial_water_l", "unmet_water_l")):
                    lower_stock = {**revised, field: revised[field] - 0.1}
                    low_run = compare_interruption(lower_stock, 6, 18)["interrupted"]
                    self.assertGreater(low_run[unmet], 0)

    def test_cli_reserve_end_retains_stock_after_an_interruption(self):
        folder = Path(__file__).resolve().parent
        cli = [sys.executable, str(folder / "habitat.py"), str(folder / "scenarios.json"),
               "--scenario", "desert-underground", "--interrupt", "6", "18", "--reserve-end"]
        report = json.loads(subprocess.check_output(cli + ["12", "20"]))["runs"][0]
        energy = report["interrupted"]["reserve"]["energy_kwh"]
        water = report["interrupted"]["reserve"]["water_l"]
        for ledger in (report["baseline"], report["interrupted"]):
            self.assertEqual(ledger["reserve"]["energy_kwh"]["minimum_final_stock"], 12)
            self.assertEqual(ledger["reserve"]["water_l"]["minimum_final_stock"], 20)
        self.assertEqual(energy["minimum_initial_stock"], 60)
        self.assertEqual(energy["minimum_capacity"], 96)
        self.assertAlmostEqual(water["minimum_initial_stock"], 165.2)
        self.assertAlmostEqual(water["minimum_capacity"], 165.2)

        revised = {
            **self.scenarios["desert-underground"],
            "initial_energy_kwh": energy["minimum_initial_stock"],
            "energy_capacity_kwh": energy["minimum_capacity"],
            "initial_water_l": water["minimum_initial_stock"],
            "water_capacity_l": water["minimum_capacity"],
        }
        replay = compare_interruption(revised, 6, 18)["interrupted"]
        self.assertEqual(replay["unmet_energy_kwh"], 0)
        self.assertEqual(replay["unmet_water_l"], 0)
        self.assertEqual(replay["final_energy_kwh"], 12)
        self.assertAlmostEqual(replay["final_water_l"], 20)
        self.assertAlmostEqual(replay["water_pending_recovery_l"], 75.6)

        invalid = subprocess.run(cli + ["0", "nan"], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("final water target must be a finite number", invalid.stderr)

    def test_minimum_capacity_can_exceed_minimum_starting_stock(self):
        scenario = {
            "id": "early-surplus",
            "step_hours": 1,
            "initial_energy_kwh": 0,
            "energy_capacity_kwh": 2,
            "initial_water_l": 0,
            "water_capacity_l": 0,
            "recovery_fraction": 0,
            "steps": [
                {"event": "surplus", "supply_kw": 12, "load_kw": 0,
                 "import_l_per_hour": 0, "demand_l_per_hour": 0},
                {"event": "deficit", "supply_kw": 0, "load_kw": 10,
                 "import_l_per_hour": 0, "demand_l_per_hour": 0},
            ],
        }
        run = simulate(scenario, reserve=True)
        self.assertEqual(run["unmet_energy_kwh"], 8)
        self.assertEqual(run["reserve"]["energy_kwh"], {
            "initial_stock": 0, "capacity": 2, "minimum_initial_stock": 0,
            "minimum_capacity": 10, "additional_initial_stock": 0, "additional_capacity": 8,
        })
        # When surplus arrives in the last interval, the finish target can set
        # the capacity even though no stock is needed at earlier boundaries.
        terminal_surplus = {**scenario, "steps": scenario["steps"][:1]}
        reserve = simulate(terminal_surplus, reserve_end=(10, 0))["reserve"]["energy_kwh"]
        self.assertEqual(reserve["minimum_initial_stock"], 0)
        self.assertEqual(reserve["minimum_capacity"], 10)


if __name__ == "__main__":
    unittest.main()
