import asyncio

import pytest

from app.obs.tracing import (
    Span,
    Trace,
    TraceManager,
    async_span,
    sync_span,
    trace_scope,
)


def test_span_lifecycle():
    span = Span(
        id="span1",
        trace_id="trace1",
        parent_id=None,
        name="test_span",
        kind="llm",
        start_time=10.0,
        attributes={"model": "test"},
    )
    assert span.status == "ok"
    assert span.duration_ms == 0

    span.finish(status="ok")
    assert span.duration_ms >= 0
    d = span.to_dict()
    assert d["name"] == "test_span"
    assert d["kind"] == "llm"
    assert d["attributes"]["model"] == "test"


def test_trace_tree_hierarchy():
    trace = Trace(trace_id="t1")
    root = Span("r", "t1", None, "root", "agent", 0.0)
    root.finish()
    c1 = Span("c1", "t1", "r", "child1", "llm", 0.1)
    c1.finish()
    c2 = Span("c2", "t1", "r", "child2", "tool", 0.2)
    c2.finish()
    c1_1 = Span("c1_1", "t1", "c1", "grandchild", "rag", 0.3)
    c1_1.finish()

    trace.add_span(root)
    trace.add_span(c1)
    trace.add_span(c2)
    trace.add_span(c1_1)

    tree = trace.to_tree()
    assert len(tree) == 1
    assert tree[0]["id"] == "r"
    assert len(tree[0]["children"]) == 2
    child_ids = {c["id"] for c in tree[0]["children"]}
    assert child_ids == {"c1", "c2"}

    c1_node = next(c for c in tree[0]["children"] if c["id"] == "c1")
    assert len(c1_node["children"]) == 1
    assert c1_node["children"][0]["id"] == "c1_1"


def test_trace_manager_eviction():
    manager = TraceManager(max_traces=3)
    manager.get_or_create("t1")
    manager.get_or_create("t2")
    manager.get_or_create("t3")
    assert manager.get("t1") is not None

    manager.get_or_create("t4")
    assert manager.get("t1") is None
    assert manager.get("t4") is not None


@pytest.mark.asyncio
async def test_async_span_and_scope():
    with trace_scope("custom-trace-123"):
        async with async_span("parent_op", kind="agent") as parent:
            assert parent.trace_id == "custom-trace-123"
            await asyncio.sleep(0.01)
            async with async_span("child_op", kind="tool") as child:
                assert child.trace_id == "custom-trace-123"
                assert child.parent_id == parent.id

        assert parent.status == "ok"
        assert parent.duration_ms >= 5


def test_sync_span_exception():
    with pytest.raises(ValueError, match="fail test"), sync_span("failing_op", kind="tool"):
        raise ValueError("fail test")
