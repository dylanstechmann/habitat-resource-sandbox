"""Regression checks for cycle boundaries in the supplemental study."""

import unittest

from cycle_study import PROFILES, cycle_repeat, study


class CycleStudyTests(unittest.TestCase):
    def test_pending_resources_are_part_of_a_boundary(self):
        row = {
            key: {"start": 2, "end": 2, "unmet": 0}
            for key in ("energy_kwh", "water_l", "food_kg")
        }
        row.update(recovered_from_previous_l=0, recovered_for_next_l=0,
                   harvest_from_previous_kg=0, harvest_for_next_kg=0)
        for key in ("recovered_for_next_l", "harvest_for_next_kg"):
            with self.subTest(key=key):
                self.assertIsNone(cycle_repeat([{**row, key: 1}], 1))

    def test_reference_runs_separate_imports_and_shortages_from_the_repeat(self):
        result = study(PROFILES, 30)
        runs = {(case["scenario"], case["case"]): case for case in result["cases"]}
        earth = runs["earth-underground", "no_shipments"]["first_exact_repeat"]
        self.assertEqual((earth["from_completed_cycle"], earth["to_completed_cycle"]), (1, 2))
        self.assertFalse(any(earth["period_unmet"].values()))
        self.assertFalse(any(earth["period_imports"].values()))
        self.assertEqual(earth["state"], {
            "energy_kwh": 12, "water_l": 6, "food_kg": 2, "pending_water_l": 18, "pending_harvest_kg": 1,
        })
        mars = runs["mars-subsurface", "no_shipments"]["first_exact_repeat"]
        self.assertEqual(mars["period_unmet"]["food_kg"], 1)
        moon = runs["moon-subsurface", "scheduled"]["first_exact_repeat"]
        self.assertEqual(moon["period_imports"]["import_water_l"], 6)
        self.assertIsNone(runs["moon-subsurface", "no_shipments"]["first_exact_repeat"])

    def test_more_opening_stock_delays_the_first_shortage(self):
        runs = {(c["scenario"], c["case"]): c for c in study(PROFILES, 30)["cases"]}
        for scenario, larger, additional, resource, base_hour, later_hour in (
            ("moon-subsurface", "full_water_tank", "more_local_water", "water_l", 168, 324),
            ("mars-subsurface", "full_pantry", "more_local_harvest", "food_kg", 120, 168),
        ):
            with self.subTest(scenario=scenario):
                self.assertEqual(runs[scenario, "no_shipments"]["first_gap_hour"][resource], base_hour)
                self.assertEqual(runs[scenario, larger]["first_gap_hour"][resource], later_hour)
                alternative = runs[scenario, additional]
                self.assertTrue(all(hour is None for hour in alternative["first_gap_hour"].values()))
                self.assertFalse(any(alternative["receipt_totals"].values()))
                self.assertIsNotNone(alternative["first_exact_repeat"])

    def test_lunar_collection_charges_only_the_extra_local_water(self):
        result = study(PROFILES, 30, lunar_water_cost=4)
        moon = {c["case"]: c for c in result["cases"] if c["scenario"] == "moon-subsurface"}
        free = moon["more_local_water"]
        powered = moon["more_local_water_with_power_cost"]
        self.assertEqual(result["lunar_extra_water_cost_kwh_per_l"], 4)
        self.assertEqual(powered["energy_demand_kwh"] - free["energy_demand_kwh"], 720)
        self.assertIsNone(free["first_gap_hour"]["energy_kwh"])
        self.assertEqual(powered["first_gap_hour"]["energy_kwh"], 36)
        self.assertFalse(any(powered["receipt_totals"].values()))

    def test_lunar_collection_rejects_invalid_costs(self):
        for invalid in (-1, float("inf"), float("nan")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                study(PROFILES, 1, lunar_water_cost=invalid)


if __name__ == "__main__":
    unittest.main()
