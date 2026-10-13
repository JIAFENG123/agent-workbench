from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents import get_agent
from app.db.models import Message, Run
from app.db.session import get_session
from app.deps import Principal, get_principal
from app.obs.tracing import trace_manager
from app.runtime.events import bus
from app.runtime.worker import manager, run_events_after
from app.schemas import (
    MessageOut,
    RunCreatedResponse,
    RunCreateRequest,
    RunOut,
    TraceOut,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])


async def _load_run(session: AsyncSession, run_id: uuid.UUID, tenant_id: uuid.UUID) -> Run:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        # Same response whether the run belongs to somebody else or does not exist.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.post("", response_model=RunCreatedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreateRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> RunCreatedResponse:
    definition = get_agent(payload.agent_key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown agent {payload.agent_key!r}"
        )

    run_input: dict[str, object] = {"text": payload.input}
    if payload.thread_id is not None:
        run_input["thread_id"] = str(payload.thread_id)

    run = Run(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        agent_key=definition.key,
        status="queued",
        input=run_input,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    await manager.launch(
        run_id=run.id,
        tenant_id=principal.tenant_id,
        definition=definition,
        user_input=payload.input,
        thread_id=payload.thread_id,
    )

    return RunCreatedResponse(
        run_id=run.id,
        status="queued",
        stream_url=f"/api/runs/{run.id}/stream",
    )


@router.get("", response_model=list[RunOut])
async def list_runs(
    limit: int = 50,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[Run]:
    stmt = (
        select(Run)
        .where(Run.tenant_id == principal.tenant_id)
        .order_by(Run.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Run:
    return await _load_run(session, run_id, principal.tenant_id)


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    run = await _load_run(session, run_id, principal.tenant_id)
    if run.status in ("succeeded", "failed", "canceled", "interrupted"):
        return {"canceled": False, "status": run.status, "reason": "Run already finished"}

    canceled = await manager.cancel(run_id)
    return {
        "canceled": canceled,
        "status": run.status if not canceled else "canceling",
        "reason": "" if canceled else "Run is not active in this process",
    }


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    """Server-sent events: persisted history first, then the live stream.

    Reconnect semantics are deliberately simple — a client that drops and comes back with
    ``Last-Event-ID`` replays everything it missed from the database instead of losing it.
    """
    await _load_run(session, run_id, principal.tenant_id)

    try:
        after_seq = int(last_event_id) if last_event_id else 0
    except ValueError:
        after_seq = 0

    async def event_generator():
        for event in await run_events_after(run_id, after_seq):
            if await request.is_disconnected():
                return
            yield event.to_sse()

        if not manager.is_active(run_id):
            return

        async for event in bus.subscribe(run_id):
            if await request.is_disconnected():
                return
            yield event.to_sse()

    # The ping keeps intermediaries (and Render's proxy) from closing an idle connection
    # during a long tool call, which would otherwise look like a dropped stream.
    return EventSourceResponse(event_generator(), ping=15)


@router.get("/{run_id}/trace", response_model=TraceOut)
async def get_run_trace(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> TraceOut:
    """Retrieve full execution trace tree with spans and timing for observability."""
    run = await _load_run(session, run_id, principal.tenant_id)

    # 1. Check live in-memory trace manager
    trace = trace_manager.get(str(run_id))
    if trace:
        data = trace.to_dict()
        return TraceOut(
            trace_id=data["trace_id"],
            span_count=data["span_count"],
            spans=data["spans"],
            tree=data["tree"],
        )

    # 2. Fall back to persisted trace inside run.result
    if run.result and isinstance(run.result, dict) and run.result.get("trace"):
        data = run.result["trace"]
        return TraceOut(
            trace_id=data.get("trace_id", str(run_id)),
            span_count=data.get("span_count", len(data.get("spans", []))),
            spans=data.get("spans", []),
            tree=data.get("tree", []),
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found for this run"
    )


@router.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
async def list_thread_messages(
    thread_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[Message]:
    """Retrieve multi-turn conversation messages for a given thread."""
    stmt = (
        select(Message)
        .where(Message.tenant_id == principal.tenant_id, Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())
