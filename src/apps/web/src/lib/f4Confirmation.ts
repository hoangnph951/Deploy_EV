import type { PlanProposal, ReplanningOutcome } from "./types";

export function getConfirmableF4Plan(run: ReplanningOutcome): PlanProposal | null {
  if (!run.action.requires_owner_confirmation || run.candidate?.feasibility_verdict !== "FEASIBLE") {
    return null;
  }
  const outcome = run.candidate.outcome;
  if (!outcome || (outcome.outcome !== "PLAN_CREATED" && outcome.outcome !== "CONDITIONAL")) {
    return null;
  }
  const invalidEmptySubstitution = (
    run.candidate.strategy === "MINIMAL_SUBSTITUTION"
    && Boolean(run.context?.unresolved_constraints.excluded_station_ids.length)
    && outcome.plan.charging_stops.length === 0
  );
  if (invalidEmptySubstitution) return null;
  return outcome.plan.status === "PENDING" && outcome.plan.risk_assessment.is_feasible
    ? outcome.plan
    : null;
}

export function completeF4Confirmation(run: ReplanningOutcome, confirmedPlanId: string) {
  return { run, confirmedPlanId };
}

export function completeF4Rejection(run: ReplanningOutcome, rejectedPlanId: string) {
  return { run, rejectedPlanId, continueAvailable: false };
}

export function isPendingF4Plan(activePlan: PlanProposal, candidate: PlanProposal | null): boolean {
  return Boolean(
    candidate
    && activePlan.plan_id === candidate.plan_id
    && activePlan.version === candidate.version
    && activePlan.status === "PENDING",
  );
}
