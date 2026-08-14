"""Pydantic request and response models for the companion service."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    role: str = "assistant"
    content: str
    session_id: str


class SessionInfo(BaseModel):
    session_id: str
    title: str
    updated_at: str
    message_count: int = 0


class SessionDetail(BaseModel):
    session_id: str
    title: str
    messages: list[dict]


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=10)


class AuthResponse(BaseModel):
    mode: str
    user_id: str
    username: str | None = None
    anonymous_id: str | None = None
    token: str | None = None


class TicketCreate(BaseModel):
    session_id: str
    user_message: str = Field(..., min_length=1)
    priority: str = "medium"


class TicketInfo(BaseModel):
    id: str
    session_id: str
    user_message: str
    status: str
    priority: str
    created_at: str
