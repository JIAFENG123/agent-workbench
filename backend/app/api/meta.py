from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.agents import list_agents
from app.config import get_settings
from app.db.session import get_session
from app.deps import Principal, get_principal
from app.obs import metrics
from app.runtime.worker import manager
from app.schemas import AgentOut, HealthResponse
from app.tools.registry import registry as tool_registry

settings = get_settings()
router = APIRouter(tags=["meta"])


async def _database_reachable(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - a health check must never raise
        return False


@router.get("/healthz", response_model=HealthResponse)
async def healthz(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    """Unauthenticated on purpose — this is the endpoint Render probes, and the one the
    keepalive workflow pings to stop the free instance from spinning down."""
    database_ok = await _database_reachable(session)
    problems = settings.validate_runtime()
    if not database_ok:
        problems.append("Database is unreachable.")
    return HealthResponse(
        status="ok" if not problems else "degraded",
        version=__version__,
        environment=settings.environment,
        database=database_ok,
        llm_configured=settings.llm_enabled,
        active_runs=len(manager.active_runs()),
        problems=problems,
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> Response:
    return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/api/agents", response_model=list[AgentOut])
async def get_agents(_: Principal = Depends(get_principal)) -> list[AgentOut]:
    return [
        AgentOut(
            key=agent.key,
            name=agent.name,
            description=agent.description,
            opening_message=agent.opening_message,
            tools=agent.tool_allowlist,
            max_steps=agent.max_steps,
        )
        for agent in list_agents()
    ]


@router.get("/api/tools")
async def get_tools(_: Principal = Depends(get_principal)) -> dict[str, list[str]]:
    return {"tools": tool_registry.names()}


@router.get("/api/eval/benchmark")
async def get_eval_benchmark(_: Principal = Depends(get_principal)) -> dict[str, object]:
    from app.eval.benchmark import load_benchmark

    cases = load_benchmark()
    return {"total": len(cases), "cases": [c.model_dump() for c in cases]}


@router.post("/api/eval/run")
async def trigger_eval_run(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    from app.eval.runner import run_benchmark

    report = await run_benchmark(session=session, tenant_id=principal.tenant_id)
    return report.to_dict()
