import pytest

from src.packages.agent.planning.graph import agent
from src.packages.agent.planning.nodes.planning_nodes import set_routing_provider
from src.packages.core.policies.application.assumptions import AssumptionSnapshotService
from src.packages.core.policies.domain.entities import DEFAULT_POLICY
from src.packages.core.trips.infrastructure.routing import InMemoryRoutingProvider
from src.packages.core.trips.infrastructure.vehicle_fixtures import load_vehicle_profile_fixtures


@pytest.mark.asyncio
async def test_agent_basic_flow():
    result = await agent.ainvoke({"query": "Hello"})
    assert "response" in result


@pytest.mark.asyncio
async def test_agent_state_structure():
    result = await agent.ainvoke({"query": "Test query"})
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_infeasible_graph_returns_refusal_without_plan_proposal():
    vehicle = load_vehicle_profile_fixtures()[0]
    assumptions = AssumptionSnapshotService().create_snapshot(
        policy=DEFAULT_POLICY,
        vehicle_profile=vehicle,
    )
    set_routing_provider(InMemoryRoutingProvider())

    result = await agent.ainvoke(
        {
            "trip_id": "trip-low-soc",
            "origin_lat": 21.0278,
            "origin_lng": 105.8342,
            "destination_lat": 18.6796,
            "destination_lng": 105.6813,
            "initial_soc_percent": 10.0,
            "vehicle_profile": vehicle,
            "assumptions": assumptions,
        }
    )

    assert "plan_proposal" not in result
    assert result["no_feasible_plan"].outcome == "PROVEN_INFEASIBLE"
    assert result["no_feasible_plan"].charging_stops == []


@pytest.mark.asyncio
async def test_feasible_graph_still_returns_plan_proposal():
    vehicle = load_vehicle_profile_fixtures()[0]
    assumptions = AssumptionSnapshotService().create_snapshot(
        policy=DEFAULT_POLICY,
        vehicle_profile=vehicle,
    )
    set_routing_provider(InMemoryRoutingProvider())

    result = await agent.ainvoke(
        {
            "trip_id": "trip-safe",
            "origin_lat": 21.0278,
            "origin_lng": 105.8342,
            "destination_lat": 20.8133,
            "destination_lng": 105.3383,
            "initial_soc_percent": 90.0,
            "vehicle_profile": vehicle,
            "assumptions": assumptions,
        }
    )

    assert "no_feasible_plan" not in result
    assert result["plan_proposal"].risk_assessment.is_feasible is True
