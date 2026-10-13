from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_minutes: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    tenant_id: uuid.UUID
    tenant_name: str
    created_at: datetime


class AgentOut(BaseModel):
    key: str
    name: str
    description: str
    opening_message: str
    tools: list[str]
    max_steps: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime


class KbLimitsOut(BaseModel):
    max_upload_bytes: int
    max_chunks_per_document: int


class RunCreateRequest(BaseModel):
    agent_key: str = Field(default="compliance", max_length=64)
    input: str = Field(min_length=1, max_length=20000)
    thread_id: uuid.UUID | None = Field(
        default=None, description="Optional thread ID for multi-turn conversations"
    )


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    thread_id: uuid.UUID
    role: str
    content: str
    token_count: int
    created_at: datetime


class TraceOut(BaseModel):
    trace_id: str
    span_count: int
    spans: list[dict[str, Any]]
    tree: list[dict[str, Any]]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_key: str
    status: str
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    created_at: datetime
    updated_at: datetime


class RunCreatedResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    stream_url: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    database: bool
    llm_configured: bool
    active_runs: int
    problems: list[str] = []
