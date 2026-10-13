from __future__ import annotations

import contextvars
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_active_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_trace_id", default=None
)
_active_parent_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_parent_span_id", default=None
)


@dataclass
class Span:
    id: str
    trace_id: str
    parent_id: str | None
    name: str
    kind: str  # "agent" | "llm" | "tool" | "rag" | "step"
    start_time: float
    end_time: float | None = None
    duration_ms: int = 0
    status: str = "ok"  # "ok" | "error"
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def finish(self, status: str = "ok", error: str | None = None) -> None:
        self.end_time = time.perf_counter()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)
        self.status = status
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "error": self.error,
        }


@dataclass
class Trace:
    trace_id: str
    spans: list[Span] = field(default_factory=list)

    def add_span(self, span: Span) -> None:
        self.spans.append(span)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_count": len(self.spans),
            "spans": [span.to_dict() for span in self.spans],
            "tree": self.to_tree(),
        }

    def to_tree(self) -> list[dict[str, Any]]:
        """Construct a hierarchy tree from flat spans based on parent_id."""
        by_id: dict[str, dict[str, Any]] = {}
        for s in self.spans:
            d = s.to_dict()
            d["children"] = []
            by_id[s.id] = d

        roots: list[dict[str, Any]] = []
        for s in self.spans:
            node = by_id[s.id]
            if s.parent_id and s.parent_id in by_id:
                by_id[s.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return roots


class TraceManager:
    """In-memory trace registry storing recent traces for API retrieval and debugging."""

    def __init__(self, max_traces: int = 256) -> None:
        self._traces: dict[str, Trace] = {}
        self._max_traces = max_traces

    def get_or_create(self, trace_id: str) -> Trace:
        if trace_id not in self._traces:
            if len(self._traces) >= self._max_traces:
                # Evict the oldest trace
                oldest_key = next(iter(self._traces))
                self._traces.pop(oldest_key, None)
            self._traces[trace_id] = Trace(trace_id=trace_id)
        return self._traces[trace_id]

    def get(self, trace_id: str) -> Trace | None:
        return self._traces.get(trace_id)

    def record_span(self, span: Span) -> None:
        trace = self.get_or_create(span.trace_id)
        trace.add_span(span)


trace_manager = TraceManager()


@contextmanager
def trace_scope(trace_id: str) -> Generator[str, None, None]:
    """Sets the root trace_id for the current context."""
    token = _active_trace_id.set(trace_id)
    try:
        yield trace_id
    finally:
        _active_trace_id.reset(token)


@asynccontextmanager
async def async_span(
    name: str,
    kind: str = "agent",
    attributes: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> AsyncGenerator[Span, None]:
    """Async context manager to trace a code block."""
    actual_trace_id = trace_id or _active_trace_id.get() or uuid.uuid4().hex
    parent_id = _active_parent_span_id.get()
    span_id = uuid.uuid4().hex[:16]

    span = Span(
        id=span_id,
        trace_id=actual_trace_id,
        parent_id=parent_id,
        name=name,
        kind=kind,
        start_time=time.perf_counter(),
        attributes=dict(attributes or {}),
    )

    token_trace = _active_trace_id.set(actual_trace_id)
    token_parent = _active_parent_span_id.set(span_id)
    try:
        yield span
        span.finish(status="ok")
    except Exception as exc:
        span.finish(status="error", error=str(exc))
        raise
    finally:
        _active_parent_span_id.reset(token_parent)
        _active_trace_id.reset(token_trace)
        trace_manager.record_span(span)


@contextmanager
def sync_span(
    name: str,
    kind: str = "agent",
    attributes: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> Generator[Span, None, None]:
    """Synchronous context manager to trace a code block."""
    actual_trace_id = trace_id or _active_trace_id.get() or uuid.uuid4().hex
    parent_id = _active_parent_span_id.get()
    span_id = uuid.uuid4().hex[:16]

    span = Span(
        id=span_id,
        trace_id=actual_trace_id,
        parent_id=parent_id,
        name=name,
        kind=kind,
        start_time=time.perf_counter(),
        attributes=dict(attributes or {}),
    )

    token_trace = _active_trace_id.set(actual_trace_id)
    token_parent = _active_parent_span_id.set(span_id)
    try:
        yield span
        span.finish(status="ok")
    except Exception as exc:
        span.finish(status="error", error=str(exc))
        raise
    finally:
        _active_parent_span_id.reset(token_parent)
        _active_trace_id.reset(token_trace)
        trace_manager.record_span(span)
