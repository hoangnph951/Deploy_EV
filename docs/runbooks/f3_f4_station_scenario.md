# F3/F4 station-outage scenario

Run this scenario only after F1 has produced and the owner has confirmed a plan whose `charging_stops` list is non-empty. F3 does not invent a charging station for a direct, no-stop plan.

## Deterministic automated fixture

- Origin: `21.0, 105.8`
- Destination: `20.0, 105.8`
- Vehicle: `vinfast-vf3-v1`
- Initial SOC: `50%`
- Expected charging stop: `ST-CONTROLLED`
- Simulator seed: `210`
- Scenario: `STATION_UNAVAILABLE`

The API characterization test creates the trip, generates the station-bearing plan, reloads it from persistence, and confirms it. The simulator test then emits exactly one `SIMULATED` station-outage event for `ST-CONTROLLED`.

## Live verification

1. Generate a route with an initial SOC low enough that the direct route violates reserve, while a reachable compatible charging stop makes the trip feasible.
2. Inspect the F1 proposal and verify `charging_stops.length > 0`. Record the first stop ID. If it is empty, change the route/SOC; do not continue with the station-outage scenario.
3. Confirm the proposal as the trip owner.
4. In F3 choose seed `210` and scenario `STATION_UNAVAILABLE`, then start the simulator.
5. Verify one event is emitted with source `SIMULATED` and the recorded station ID, and that the simulator enters `AWAITING_DECISION`.
6. Request F4 replanning. Verify the failed station is in the exclusion constraint, F1 is invoked, and no candidate charging stop reuses that ID.
7. Verify F4 compares the current and candidate plans and waits for explicit owner confirmation. It must not activate the candidate automatically.

For the Hòa Bình → VinUniversity demo at SOC 21%, first check the generated proposal itself contains a stop. A label such as “Xe mô phỏng” is telemetry provenance, not a station location and is not sufficient to exercise station replacement.
