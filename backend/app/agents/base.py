from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentDefinition:
    key: str
    name: str
    description: str
    system_prompt: str
    tool_allowlist: list[str]
    max_steps: int = 8
    opening_message: str = ""


_registry: dict[str, AgentDefinition] = {}


def register(definition: AgentDefinition) -> AgentDefinition:
    if definition.key in _registry:
        raise ValueError(f"Agent {definition.key!r} is already registered")
    _registry[definition.key] = definition
    return definition


def get_agent(key: str) -> AgentDefinition | None:
    return _registry.get(key)


def list_agents() -> list[AgentDefinition]:
    return list(_registry.values())


def agent_keys() -> list[str]:
    return sorted(_registry)


@dataclass
class AgentOutcome:
    answer: str
    citations: list[dict] = field(default_factory=list)
    tool_invocations: list[dict] = field(default_factory=list)
    steps: int = 0
    stopped_reason: str = "completed"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    run_id: uuid.UUID | None = None
