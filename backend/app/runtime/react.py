from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentDefinition, AgentOutcome
from app.config import get_settings
from app.llm.client import LLMError, get_chat_client
from app.llm.types import ChatMessage, ToolCall, Usage
from app.obs.tracing import async_span
from app.runtime.events import Emitter
from app.tools.registry import ToolContext
from app.tools.registry import registry as tool_registry

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class _Turn:
    text: str = ""
    tool_calls: list[ToolCall] | None = None
    usage: Usage | None = None
    model: str = ""


async def _run_turn(
    emitter: Emitter,
    messages: list[ChatMessage],
    tool_specs: list,
    *,
    step: int | None,
) -> _Turn:
    """One assistant turn, streamed token by token."""
    turn = _Turn()
    client = get_chat_client()
    async with async_span(f"llm.step_{step}", kind="llm", attributes={"step": step}):
        async for event in client.stream(messages, tools=tool_specs or None):
            if event.type == "delta":
                turn.text += event.text
                await emitter.emit("token", text=event.text, step=step)
            elif event.type == "tool_calls":
                turn.tool_calls = event.tool_calls
            elif event.type == "done" and event.result is not None:
                turn.usage = event.result.usage
                turn.model = event.result.model
    return turn


async def run_react_agent(
    *,
    emitter: Emitter,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    definition: AgentDefinition,
    user_input: str,
    history: list[ChatMessage] | None = None,
) -> AgentOutcome:
    """ReAct loop: stream a turn, execute any tool calls it asks for, repeat until the model
    answers without calling a tool or the step budget runs out."""
    started = time.perf_counter()
    max_steps = definition.max_steps or settings.agent_max_steps
    allowed = set(definition.tool_allowlist)
    tool_specs = tool_registry.specs(definition.tool_allowlist)
    tool_context = ToolContext(session=session, tenant_id=tenant_id, run_id=run_id)

    messages: list[ChatMessage] = [ChatMessage(role="system", content=definition.system_prompt)]
    messages.extend(history or [])
    messages.append(ChatMessage(role="user", content=user_input))

    outcome = AgentOutcome(answer="", run_id=run_id)
    total_usage = Usage()

    await emitter.emit(
        "run_started",
        agent=definition.key,
        agent_name=definition.name,
        tools=[spec.name for spec in tool_specs],
        max_steps=max_steps,
    )

    for step in range(1, max_steps + 1):
        await emitter.emit("step", step=step, phase="reasoning", status="start")
        try:
            turn = await _run_turn(emitter, messages, tool_specs, step=step)
        except LLMError as exc:
            outcome.stopped_reason = "llm_error"
            await emitter.emit("error", message=str(exc), step=step)
            logger.error("agent_llm_error", run_id=str(run_id), error=str(exc)[:300])
            break

        outcome.steps = step
        if turn.usage:
            total_usage = total_usage + turn.usage
            outcome.prompt_tokens = total_usage.prompt_tokens
            outcome.completion_tokens = total_usage.completion_tokens
        outcome.model = turn.model or outcome.model

        produced_tool_calls = bool(turn.tool_calls)
        await emitter.emit(
            "step",
            step=step,
            phase="reasoning",
            status="end",
            produced_tool_calls=produced_tool_calls,
        )

        if not produced_tool_calls:
            outcome.answer = turn.text
            outcome.stopped_reason = "completed"
            break

        assistant_message = ChatMessage(
            role="assistant", content=turn.text, tool_calls=turn.tool_calls or []
        )
        messages.append(assistant_message)

        for call in turn.tool_calls or []:
            await _execute_tool_call(
                emitter=emitter,
                tool_context=tool_context,
                messages=messages,
                call=call,
                allowed=allowed,
                step=step,
                outcome=outcome,
            )
    else:
        outcome.stopped_reason = "max_steps"
        await emitter.emit(
            "error",
            message=f"达到最大步数 {max_steps}，未能给出最终答案。",
            step=max_steps,
        )

    if outcome.citations:
        await emitter.emit("citations", items=outcome.citations)

    await emitter.emit(
        "usage",
        prompt_tokens=total_usage.prompt_tokens,
        completion_tokens=total_usage.completion_tokens,
        model=outcome.model,
    )
    await emitter.emit(
        "run_finished",
        status="succeeded" if outcome.stopped_reason == "completed" else "failed",
        stopped_reason=outcome.stopped_reason,
        steps=outcome.steps,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return outcome


async def _execute_tool_call(
    *,
    emitter: Emitter,
    tool_context: ToolContext,
    messages: list[ChatMessage],
    call: ToolCall,
    allowed: set[str],
    step: int,
    outcome: AgentOutcome,
) -> None:
    arguments = call.parsed_arguments()
    await emitter.emit("tool_call", step=step, name=call.name, call_id=call.id, arguments=arguments)

    tool = tool_registry.get(call.name)
    tool_started = time.perf_counter()

    async with async_span(
        f"tool.{call.name}",
        kind="tool",
        attributes={"tool": call.name, "step": step, "call_id": call.id, "arguments": arguments},
    ):
        if tool is None:
            result = None
            content = f"未知工具：{call.name}。可用工具：{tool_registry.names()}"
        elif call.name not in allowed:
            result = None
            content = f"工具 {call.name} 未被该 Agent 授权使用。"
        else:
            result = await tool.invoke(tool_context, arguments)
            content = result.content

    duration_ms = int((time.perf_counter() - tool_started) * 1000)
    ok = result.ok if result else False

    if result and result.meta.get("citations"):
        for item in result.meta["citations"]:
            if item not in outcome.citations:
                outcome.citations.append(item)

    outcome.tool_invocations.append(
        {
            "step": step,
            "name": call.name,
            "arguments": arguments,
            "ok": ok,
            "duration_ms": duration_ms,
        }
    )

    await emitter.emit(
        "tool_result",
        step=step,
        name=call.name,
        call_id=call.id,
        ok=ok,
        duration_ms=duration_ms,
        preview=content[:300],
    )

    messages.append(ChatMessage(role="tool", content=content, tool_call_id=call.id, name=call.name))
