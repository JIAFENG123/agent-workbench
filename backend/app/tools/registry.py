from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMError
from app.llm.types import ToolSpec


@dataclass
class ToolContext:
    session: AsyncSession
    tenant_id: uuid.UUID
    run_id: uuid.UUID | None = None


@dataclass
class ToolResult:
    ok: bool
    content: str
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, content: str, **meta: Any) -> ToolResult:
        return cls(ok=True, content=content, meta=meta)

    @classmethod
    def failure(cls, content: str, **meta: Any) -> ToolResult:
        return cls(ok=False, content=content, meta=meta)


Handler = Callable[[ToolContext, Any], Awaitable[ToolResult]]


@dataclass
class Tool:
    """A callable exposed to the model.

    Arguments are declared as a Pydantic model, so the JSON schema handed to the model and
    the validation applied to its reply come from one definition and cannot drift apart.
    """

    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    scopes: tuple[str, ...] = ("read",)

    def spec(self) -> ToolSpec:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)

    async def invoke(self, context: ToolContext, raw_arguments: dict[str, Any]) -> ToolResult:
        try:
            parsed = self.args_model.model_validate(raw_arguments or {})
        except ValidationError as exc:
            return ToolResult.failure(
                f"工具参数校验失败：{exc.errors(include_url=False, include_input=False)}"
            )
        try:
            return await self.handler(context, parsed)
        except LLMError as exc:
            return ToolResult.failure(f"工具执行失败：{exc}")
        except Exception as exc:  # noqa: BLE001 - a broken tool must not kill the whole run
            return ToolResult.failure(f"工具内部错误：{type(exc).__name__}: {exc}")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, allowlist: list[str] | None = None) -> list[ToolSpec]:
        """Tool whitelist enforcement: anything not listed is invisible to the model."""
        if allowlist is None:
            return [tool.spec() for tool in self._tools.values()]
        return [self._tools[name].spec() for name in self._tools if name in set(allowlist)]


registry = ToolRegistry()
