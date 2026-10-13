from __future__ import annotations

from typing import Literal

from app.config import get_settings

settings = get_settings()

TaskKind = Literal["route", "generate", "judge", "summarize"]


def route_model(task: TaskKind) -> str:
    """Model routing: cheap/fast models for classification-style work, the strong model for
    anything the user actually reads."""
    if task in ("route", "summarize"):
        return settings.llm_model_fast
    return settings.llm_model
