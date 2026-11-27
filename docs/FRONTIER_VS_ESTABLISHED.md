# Frontier versus established evidence

**Status date: 2026-11-27**

This log separates reproduced software behavior from open modeling work and physical or biological claims. The observations below are agent-run software checks, not independent scientific or engineering review.

## Established software observations reproduced here

- `python3 -B -m unittest -v` completed with **27 passing tests**.
- All six original 30-day autonomy baseline summaries were regenerated and checked against their corresponding archived cycle-study cases.
- The cycle study produced **ten cases at both 30 and 365 simulated days**. Both regenerated JSON reports were byte-identical to the archived planning-packet reports.
- Focused checks reproduced delayed water-recovery and harvest credits, pending-resource distinctions between otherwise identical states, repeat classification, and opening-reserve sensitivity.
- Without shipments, the lunar water shortage moved from hour 168 to 324 with a full opening tank, and the Martian food shortage moved from hour 120 to 168 with a full opening pantry. The invented recurring-input cases had no modeled shortages under their stated assumptions.

These are reproducible observations about the checked-in deterministic software and synthetic fixtures. They do not make the fixtures measured or representative of a real site.

**Post-merge recheck (2026-11-27):** After merging `origin/main` at `33f3f67638c22c1148073f905e02ee048baa0b60`, the full suite expanded to **40 passing tests**, including all 27 above. The default 30- and 365-day studies retained identical non-`sha256` fields and all ten case payloads. Whole-file `cmp` now differs only because the reports record updated SHA-256 digests for `cycle_study.py` and `habitat.py`; both new digests were verified against the merged sources.

## Frontier and open modeling work

- Assign explicit energy, labor, equipment, source, timing, loss, and unknown-value accounting to local water collection, treatment, agriculture, and harvest.
- Close resource balances over intervals and complete cycles, including waste, storage losses, growing inputs, and power interruptions without double-counting energy.
- Model air revitalization, oxygen supply, heat rejection, humidity, water quality, maintenance downtime, consumables, replacement parts, and service interruptions as distinct occupancy subsystems.
- Replace the common invented schedule with site-specific Earth, Moon, and Mars boundary conditions, provenance, extended interruptions, and uncertainty analysis.

## Not established: physical or biological claims

No result here establishes actual water availability or potability, crop productivity, nutritional adequacy, biological closure, component reliability, or human health outcomes. Dry-food mass and potential-harvest inputs are accounting quantities, not evidence of agricultural feasibility or an adequate diet.

**Passing resource ledgers do not establish sustainability, safe habitation, construction readiness, or physical or biological validation.** Atmospheric, thermal, nutritional, radiation, fire, structural, pressure, egress, rescue, maintenance, and replacement requirements remain open. Real habitat decisions require separately scoped engineering, scientific, medical, regulatory, and operational evidence.

## Log maintenance

**Update this log whenever evidence status changes.** Record the date, exact commands or evidence source, scope, and whether the result is a synthetic software rerun, independent review, or physical/biological observation; do not promote a software result into a real-world claim.
