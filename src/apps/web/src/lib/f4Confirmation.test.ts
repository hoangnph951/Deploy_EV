import assert from "node:assert/strict";
import test from "node:test";

import {
  completeF4Confirmation,
  completeF4Rejection,
  getConfirmableF4Plan,
  isPendingF4Plan,
} from "./f4Confirmation.ts";

const pendingPlan = {
  plan_id: "plan-v2",
  version: 2,
  status: "PENDING",
  risk_assessment: { is_feasible: true },
};

test("offers F2 confirmation for a safe pending F4 candidate", () => {
  const run = {
    action: { requires_owner_confirmation: true },
    candidate: {
      feasibility_verdict: "FEASIBLE",
      outcome: { outcome: "PLAN_CREATED", plan: pendingPlan },
    },
  };

  assert.equal(getConfirmableF4Plan(run as never), pendingPlan);
});

test("does not offer confirmation when F4 has no safe pending plan", () => {
  assert.equal(getConfirmableF4Plan({
    action: { requires_owner_confirmation: false }, candidate: null,
  } as never), null);
});

test("does not confirm an empty minimal substitution for an unavailable station", () => {
  const run = {
    action: { requires_owner_confirmation: true },
    context: { unresolved_constraints: { excluded_station_ids: ["ST-FAILED"] } },
    candidate: {
      feasibility_verdict: "FEASIBLE",
      strategy: "MINIMAL_SUBSTITUTION",
      outcome: {
        outcome: "PLAN_CREATED",
        plan: { ...pendingPlan, charging_stops: [] },
      },
    },
  };

  assert.equal(getConfirmableF4Plan(run as never), null);
});

test("keeps the F4 explanation after confirming its replacement plan", () => {
  const run = { agent_run_id: "run-1" };

  const next = completeF4Confirmation(run as never, "plan-v2");

  assert.equal(next.run, run);
  assert.equal(next.confirmedPlanId, "plan-v2");
});

test("keeps the F4 decision state after rejecting an unsafe replacement", () => {
  const run = { agent_run_id: "run-1" };

  const next = completeF4Rejection(run as never, "plan-v2");

  assert.equal(next.run, run);
  assert.equal(next.rejectedPlanId, "plan-v2");
  assert.equal(next.continueAvailable, false);
});

test("identifies the pending F4 plan that needs confirmation in F3", () => {
  assert.equal(isPendingF4Plan(pendingPlan as never, pendingPlan as never), true);
  assert.equal(isPendingF4Plan({ ...pendingPlan, plan_id: "other" } as never, pendingPlan as never), false);
});
