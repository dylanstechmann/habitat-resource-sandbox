# Life-support scope and exclusions

## Synthetic resource software only

Habitat Resource Sandbox is an AI-assisted hobby and learning model of two anonymous resource ledgers: aggregate electrical energy and bulk water volume. Its scenarios, outage windows, recovery fractions, stock calculations, and reports are synthetic illustrations. They are not occupancy approval, life-support certification, a safety case, or recommendations for a real habitat.

No output establishes that a habitat is safe to occupy or operate. The reserve calculation applies only to the entered synthetic loads and its stated idealized assumptions; it is not an occupancy sizing method and does not establish required reserves for people.

## Explicitly unmodeled requirements

The software does **not** model or verify any of the following:

- **Atmosphere:** oxygen and carbon-dioxide inventories, partial pressures, ventilation, trace contaminants, atmospheric regeneration, or breathable-air quality.
- **Thermal conditions and humidity:** heat generation or rejection, temperature control, condensation, humidity, or environmental limits.
- **Water quality:** potability, contaminants, microbial control, treatment performance, or whether the simplified recovered-water stream is usable for any particular purpose.
- **Food:** nutrition, calories, food storage, preparation, or agricultural production.
- **Waste:** human or solid waste, hazardous waste, sanitation, or detailed wastewater chemistry. The single water-recovery fraction is not a waste-treatment model.
- **Structural integrity:** loads, materials, fatigue, damage, foundations, or structural safety factors.
- **Pressure:** vessel or compartment integrity, pressure differentials, leaks, decompression, or pressure-control systems.
- **Radiation:** source terms, shielding, dose, exposure limits, or radiation monitoring.
- **Fire:** ignition, detection, smoke, combustion, suppression, or fire-safe materials and atmosphere interactions.
- **Egress:** escape routes, emergency exits, accessibility, evacuation timing, or compartment isolation.
- **Rescue:** detection, alarms, communications, emergency response, rescue access, or external support availability.
- **Occupancy requirements:** headcount-dependent needs, metabolic loads, habitability, human factors, medical support, or regulatory occupancy criteria.

Also outside the model are equipment reliability and maintenance, common-cause failures, storage degradation, sensor and control behavior, energy conversion efficiency, detailed fluid inventories, redundancy, emergency procedures, and applicable codes or standards. Electrical and water quantities are not tied to named devices or verified engineering loads.

## Appropriate interpretation

Use the outputs only to inspect the documented arithmetic and explore synthetic what-if inputs. A shortfall, restoration hour, or zero-unmet result describes only this ledger over the selected steps. It says nothing about survival, health, mission success, code compliance, or the completeness of a life-support system.

Real habitat analysis requires separately scoped engineering, safety, medical, regulatory, and operational work with validated requirements and data. This repository neither performs nor substitutes for that work.
