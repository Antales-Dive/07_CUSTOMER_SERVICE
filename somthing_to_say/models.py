"""Pydantic request and response models for the companion service."""

from typing import Literal

from pydantic import BaseModel, Field


ChatMode = Literal["companion", "problem_solving"]


class SafetyDecision(BaseModel):
    level: Literal["safe", "caution", "urgent", "disallowed"]
    reason_code: str


class OutputDecision(BaseModel):
    result: Literal["approved", "rewrite", "blocked"]
    reason_code: str


class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    mode: ChatMode = "companion"


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
    role: Literal["user", "admin", "super_admin"] = "user"
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=10)
    new_password: str = Field(..., min_length=1, max_length=10)


class AdminRoleUpdate(BaseModel):
    role: Literal["user", "admin"]


class AdminAccountInfo(BaseModel):
    id: str
    username: str
    role: Literal["user", "admin", "super_admin"]
    must_change_password: bool


class AdminSessionInfo(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    deleted_at: str | None = None


class AdminMessageInfo(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str


class AdminSessionDetail(BaseModel):
    session_id: str
    title: str
    username: str
    messages: list[AdminMessageInfo]


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
