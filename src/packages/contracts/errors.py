from typing import Any

from pydantic import BaseModel, Field


class ErrorPayload(BaseModel):
    code: str = Field(..., description="Stable application error code")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] = Field(default_factory=dict, description="Structured error details")
    trace_id: str = Field(..., description="Request trace identifier")


class ErrorEnvelope(BaseModel):
    error: ErrorPayload
