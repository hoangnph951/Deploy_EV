import type {
  CompositeMonitoringEventType,
  PlanProposal,
  SimulationFault,
  SimulationScenarioSelection,
} from "./types";


export function buildSimulationStartPayload(
  plan: PlanProposal,
  scenario: SimulationScenarioSelection,
  scenarioValue: number | undefined,
  scenarioEvents: CompositeMonitoringEventType[] | undefined,
  seed: number,
  simulationFault: SimulationFault = "NONE",
) {
  return {
    plan_id: plan.plan_id,
    plan,
    seed,
    simulation_fault: simulationFault,
    scenario,
    scenario_value: scenarioValue,
    scenario_events: scenarioEvents,
    unhappy_probability: 0.5,
  };
}
