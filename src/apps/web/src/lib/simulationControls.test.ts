import assert from "node:assert/strict";
import test from "node:test";

test("simulation start payload preserves the operator-selected seed", async () => {
  const plan = { plan_id: "plan-1" };
  const controls = await import("./simulationControls.ts").catch(() => ({}));
  const payload = (controls as {
    buildSimulationStartPayload?: (...args: unknown[]) => Record<string, unknown>;
  }).buildSimulationStartPayload?.(
    plan,
    "ROUTE_DEVIATION",
    2.01,
    undefined,
    210,
    "F1_PROVIDER_FAILURE",
  );

  assert.deepEqual(payload, {
    plan_id: "plan-1",
    plan,
    seed: 210,
    simulation_fault: "F1_PROVIDER_FAILURE",
    scenario: "ROUTE_DEVIATION",
    scenario_value: 2.01,
    scenario_events: undefined,
    unhappy_probability: 0.5,
  });
});
