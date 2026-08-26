from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhan tu user")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Phan hoi tu agent")
    analysis: str = Field(default="", description="Phan tich noi bo")
