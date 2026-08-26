from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.packages.agent.planning.nodes.planning_nodes import (
    feasibility_node,
    no_feasible_plan_node,
    proposal_node,
    recovery_node,
    routing_node,
    station_energy_node,
)
from src.packages.agent.planning.runtime import (
    PlanningRuntime,
    default_planning_runtime,
    use_planning_progress,
    use_planning_runtime,
)
from src.packages.agent.planning.state import AgentState
from src.packages.core.planning.application.orchestrator import (
    PlanningExecution,
    PlanningOrchestrator,
    PlanningRequest,
)


def route_feasibility_outcome(state: AgentState) -> str:
    verdict = state.get("feasibility_verdict")
    if verdict is not None and not verdict.is_feasible:
        return "recovery"
    return "proposal"


def route_recovery_outcome(state: AgentState) -> str:
    verdict = state.get("feasibility_verdict")
    if verdict is not None and verdict.is_feasible:
        return "proposal"
    return "no_feasible_plan"


def build_planning_graph() -> StateGraph:
    """Build LangGraph workflow orchestrating deterministic planning tools."""
    graph = StateGraph(AgentState)

    graph.add_node("routing", routing_node)
    graph.add_node("station_energy", station_energy_node)
    graph.add_node("feasibility", feasibility_node)
    graph.add_node("proposal", proposal_node)
    graph.add_node("recovery", recovery_node)
    graph.add_node("no_feasible_plan", no_feasible_plan_node)

    graph.set_entry_point("routing")
    graph.add_edge("routing", "station_energy")
    graph.add_edge("station_energy", "feasibility")
    graph.add_conditional_edges(
        "feasibility",
        route_feasibility_outcome,
        {
            "proposal": "proposal",
            "recovery": "recovery",
        },
    )
    graph.add_conditional_edges(
        "recovery",
        route_recovery_outcome,
        {
            "proposal": "proposal",
            "no_feasible_plan": "no_feasible_plan",
        },
    )
    graph.add_edge("proposal", END)
    graph.add_edge("no_feasible_plan", END)

    return graph.compile()


class LangGraphPlanningOrchestrator(PlanningOrchestrator):
    """Thin LangGraph adapter around deterministic planning capabilities."""

    def __init__(self, runtime: PlanningRuntime):
        self._runtime = runtime
        self._graph = build_planning_graph()

    def plan(self, request: PlanningRequest, progress_callback=None) -> PlanningExecution:
        with use_planning_runtime(self._runtime), use_planning_progress(progress_callback):
            state = self._graph.invoke(request.to_state())
        return PlanningExecution(state=state)


planning_agent = build_planning_graph()


class LegacyAgentFacade:
    """Backward-compatible chat facade; never invokes the planning graph."""

    async def ainvoke(self, payload: dict) -> dict:
        if "query" in payload and len(payload) == 1:
            return {
                "response": "AI EV Agent sáºµn sÃ ng láº­p káº¿ hoáº¡ch hÃ nh trÃ¬nh vÃ  sáº¡c.",
                "analysis": "Use the trip planning API for deterministic route and safety evaluation.",
                "query": payload["query"],
            }
        return await planning_agent.ainvoke(payload)


agent = LegacyAgentFacade()


def build_planning_orchestrator(runtime: PlanningRuntime | None = None) -> PlanningOrchestrator:
    return LangGraphPlanningOrchestrator(runtime or default_planning_runtime())
