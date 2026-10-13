from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.agents import list_agents
from app.api import auth as auth_api
from app.api import kb as kb_api
from app.api import meta as meta_api
from app.api import runs as runs_api
from app.config import get_settings
from app.llm.http import close_http_client
from app.obs.logging import configure_logging
from app.rag.index import recover_stale_documents
from app.runtime.worker import recover_stale_runs
from app.tools.builtin import register_builtin_tools

settings = get_settings()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info(
        "startup",
        version=__version__,
        environment=settings.environment,
        agents=[agent.key for agent in list_agents()],
    )

    register_builtin_tools()

    for problem in settings.validate_runtime():
        logger.warning("config_problem", problem=problem)

    # Reconciling crashed state must not stop the process from booting: on a free instance
    # the database may simply be waking up, and a degraded boot beats no boot.
    for recover, label in (
        (recover_stale_runs, "runs"),
        (recover_stale_documents, "documents"),
    ):
        try:
            count = await recover()
            if count:
                logger.warning("recovered_stale_state", kind=label, count=count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("recovery_failed", kind=label, error=str(exc)[:200])

    yield

    await close_http_client()
    logger.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="可观测、可评测、可续跑的 Agent 运行时",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(meta_api.router)
app.include_router(auth_api.router)
app.include_router(kb_api.router)
app.include_router(runs_api.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": __version__, "docs": "/docs"}
