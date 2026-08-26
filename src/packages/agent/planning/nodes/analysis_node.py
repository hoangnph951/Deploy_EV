from src.packages.agent.planning.state import AgentState


async def analyze_node(state: AgentState) -> dict:
    """Analyze the incoming user query."""
    query = state.get("query", "")
    analysis = f"Phan tich: {query}"
    return {"analysis": analysis}


async def respond_node(state: AgentState) -> dict:
    """Build a response from the produced analysis."""
    analysis = state.get("analysis", "")
    error = state.get("error")

    if error:
        return {"response": f"Loi: {error}"}

    response = f"Ket qua dua tren phan tich: {analysis}"
    return {"response": response}
