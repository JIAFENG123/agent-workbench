"""Agent definitions.

Importing this package registers every built-in agent.
"""

from app.agents import (
    compliance,  # noqa: F401
    doc_qa,  # noqa: F401
    listing_optimizer,  # noqa: F401
)
from app.agents.base import (
    AgentDefinition,
    AgentOutcome,
    agent_keys,
    get_agent,
    list_agents,
    register,
)

__all__ = [
    "AgentDefinition",
    "AgentOutcome",
    "agent_keys",
    "get_agent",
    "list_agents",
    "register",
]
