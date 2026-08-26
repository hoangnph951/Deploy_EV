import logging

from fastapi import APIRouter

from src.packages.contracts.chat import ChatRequest, ChatResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Keep conversation separate from the safety-critical planning graph."""
    logger.info("Processing assistant request")
    return ChatResponse(
        response=(
            "TÃ´i cÃ³ thá»ƒ há»— trá»£ láº­p káº¿ hoáº¡ch chuyáº¿n Ä‘i EV. "
            "HÃ£y táº¡o chuyáº¿n Ä‘i vá»›i Ä‘iá»ƒm Ä‘i, Ä‘iá»ƒm Ä‘áº¿n, xe vÃ  SOC; "
            "Safety Planning Engine sáº½ tÃ­nh route, tráº¡m sáº¡c vÃ  feasibility."
        ),
        analysis="Conversation is separated from the deterministic planning workflow.",
    )


@router.get("/status")
async def agent_status():
    """Return current planning agent status."""
    return {"status": "ready", "agent": "Deterministic EV Planning Engine v2.0"}
