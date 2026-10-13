from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.base import AgentDefinition
from app.config import get_settings
from app.db.models import Message, Run, UsageLedger
from app.db.models import RunEvent as RunEventRow
from app.db.session import SessionLocal
from app.llm.cost import compute_cost
from app.llm.types import ChatMessage
from app.obs.tracing import trace_manager, trace_scope
from app.runtime.events import PERSISTED_EVENT_TYPES, RunEvent, bus
from app.runtime.react import run_react_agent

logger = structlog.get_logger(__name__)
settings = get_settings()

TERMINAL_STATUSES = ("succeeded", "failed", "canceled", "interrupted")


class PersistingEmitter:
    """Writes run events to the database and fans them out to live SSE subscribers.

    Token deltas skip the database entirely — they are the highest-volume event by orders of
    magnitude and carry no value for replay.
    """

    def __init__(
        self,
        *,
        run_id: uuid.UUID,
        session_factory: async_sessionmaker,
        sequence_start: int = 0,
    ) -> None:
        self.run_id = run_id
        self._session_factory = session_factory
        self._seq = sequence_start

    @property
    def sequence(self) -> int:
        return self._seq

    async def emit(self, event_type: str, **payload: Any) -> None:
        self._seq += 1
        event = RunEvent(type=event_type, payload=payload, seq=self._seq)
        if event_type in PERSISTED_EVENT_TYPES:
            async with self._session_factory() as session:
                session.add(
                    RunEventRow(
                        run_id=self.run_id,
                        seq=event.seq,
                        type=event.type,
                        payload=payload,
                    )
                )
                await session.commit()
        await bus.publish(self.run_id, event)


class RunManager:
    """Tracks in-flight agent runs inside the web process.

    The free tier provides no worker dyno, so runs are plain asyncio tasks owned by the API
    process. That makes the process itself the failure domain: if it is restarted mid-run,
    the run row is reconciled on next boot by :func:`recover_stale_runs`. Durable step
    resumption arrives with the LangGraph checkpointer in P1.
    """

    def __init__(self, session_factory: async_sessionmaker = SessionLocal) -> None:
        self._session_factory = session_factory
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._started_at: dict[uuid.UUID, float] = {}

    def is_active(self, run_id: uuid.UUID) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def active_runs(self) -> list[uuid.UUID]:
        return [run_id for run_id, task in self._tasks.items() if not task.done()]

    async def launch(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        definition: AgentDefinition,
        user_input: str,
        history: list | None = None,
        thread_id: uuid.UUID | None = None,
    ) -> None:
        if self.is_active(run_id):
            raise RuntimeError(f"Run {run_id} is already active")

        bus.open(run_id)
        task = asyncio.create_task(
            self._execute(
                run_id=run_id,
                tenant_id=tenant_id,
                definition=definition,
                user_input=user_input,
                history=history,
                thread_id=thread_id,
            ),
            name=f"run-{run_id}",
        )
        self._tasks[run_id] = task
        self._started_at[run_id] = time.perf_counter()
        task.add_done_callback(lambda _: self._cleanup(run_id))
        logger.info(
            "run_launched",
            run_id=str(run_id),
            agent=definition.key,
            thread_id=str(thread_id) if thread_id else None,
        )

    def _cleanup(self, run_id: uuid.UUID) -> None:
        self._tasks.pop(run_id, None)
        self._started_at.pop(run_id, None)

    async def cancel(self, run_id: uuid.UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        logger.info("run_cancel_requested", run_id=str(run_id))
        return True

    async def _execute(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        definition: AgentDefinition,
        user_input: str,
        history: list | None,
        thread_id: uuid.UUID | None = None,
    ) -> None:
        emitter = PersistingEmitter(run_id=run_id, session_factory=self._session_factory)
        started = time.perf_counter()

        async with self._session_factory() as session:
            await session.execute(
                update(Run).where(Run.id == run_id).values(status="running", error=None)
            )
            await session.commit()

            # Load thread conversation history if thread_id is set and history is None
            actual_history = history
            if actual_history is None and thread_id is not None:
                stmt = (
                    select(Message)
                    .where(Message.tenant_id == tenant_id, Message.thread_id == thread_id)
                    .order_by(Message.created_at.asc())
                    .limit(20)
                )
                rows = (await session.execute(stmt)).scalars().all()
                actual_history = [ChatMessage(role=r.role, content=r.content) for r in rows]

            try:
                with trace_scope(str(run_id)):
                    outcome = await run_react_agent(
                        emitter=emitter,
                        session=session,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        definition=definition,
                        user_input=user_input,
                        history=actual_history,
                    )
            except asyncio.CancelledError:
                await self._finalize(
                    session,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status="canceled",
                    error="Run canceled by user",
                    result=None,
                    model="",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                await bus.publish(
                    run_id,
                    RunEvent(
                        type="run_finished",
                        payload={"status": "canceled", "stopped_reason": "canceled"},
                        seq=emitter.sequence + 1,
                    ),
                )
                bus.close(run_id)
                raise
            except Exception as exc:  # noqa: BLE001 - never let a run take down the process
                logger.exception("run_failed", run_id=str(run_id))
                await self._finalize(
                    session,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    result=None,
                    model="",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                await bus.publish(
                    run_id,
                    RunEvent(
                        type="error",
                        payload={"message": f"{type(exc).__name__}: {exc}"},
                        seq=emitter.sequence + 1,
                    ),
                )
                bus.close(run_id)
                return

            status = "succeeded" if outcome.stopped_reason == "completed" else "failed"

            # Persist user question and assistant answer into Message table for thread history
            if thread_id is not None and status == "succeeded":
                session.add(
                    Message(
                        tenant_id=tenant_id,
                        thread_id=thread_id,
                        role="user",
                        content=user_input,
                        token_count=outcome.prompt_tokens,
                    )
                )
                if outcome.answer:
                    session.add(
                        Message(
                            tenant_id=tenant_id,
                            thread_id=thread_id,
                            role="assistant",
                            content=outcome.answer,
                            token_count=outcome.completion_tokens,
                        )
                    )
                await session.commit()

            trace = trace_manager.get(str(run_id))
            trace_dict = trace.to_dict() if trace else None

            await self._finalize(
                session,
                run_id=run_id,
                tenant_id=tenant_id,
                status=status,
                error=None if status == "succeeded" else outcome.stopped_reason,
                result={
                    "answer": outcome.answer,
                    "citations": outcome.citations,
                    "tool_invocations": outcome.tool_invocations,
                    "steps": outcome.steps,
                    "stopped_reason": outcome.stopped_reason,
                    "trace": trace_dict,
                },
                model=outcome.model,
                prompt_tokens=outcome.prompt_tokens,
                completion_tokens=outcome.completion_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        bus.close(run_id)

    async def _finalize(
        self,
        session,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        status: str,
        error: str | None,
        result: dict[str, Any] | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
    ) -> None:
        cost = compute_cost(prompt_tokens, completion_tokens, model) if model else 0.0
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status=status,
                error=error,
                result=result,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
            )
        )
        session.add(
            UsageLedger(
                tenant_id=tenant_id,
                run_id=run_id,
                model=model or "unknown",
                operation="react",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                cache_hit=False,
            )
        )
        await session.commit()
        logger.info(
            "run_finished",
            run_id=str(run_id),
            status=status,
            tokens=prompt_tokens + completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )


async def recover_stale_runs(session_factory: async_sessionmaker = SessionLocal) -> int:
    """Runs interrupted by a process restart are marked, never left looking alive.

    Called on every boot. Without a worker dyno this is the only thing standing between a
    crashed process and a run stuck at "running" forever.
    """
    async with session_factory() as session:
        result = await session.execute(
            update(Run)
            .where(Run.status.in_(("queued", "running")))
            .values(status="interrupted", error="Process restarted while this run was in flight")
        )
        await session.commit()
        count = result.rowcount or 0
        if count:
            logger.warning("stale_runs_recovered", count=count)
        return count


async def run_events_after(
    run_id: uuid.UUID,
    after_seq: int,
    session_factory: async_sessionmaker = SessionLocal,
) -> list[RunEvent]:
    """Replay persisted events so a reconnecting SSE client does not lose history."""
    async with session_factory() as session:
        stmt = (
            select(RunEventRow)
            .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
            .order_by(RunEventRow.seq)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [RunEvent(type=row.type, payload=row.payload, seq=row.seq) for row in rows]


manager = RunManager()
