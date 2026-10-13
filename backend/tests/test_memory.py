import uuid
from datetime import UTC, datetime

from app.schemas import MessageOut, RunCreateRequest, TraceOut


def test_run_create_request_with_thread():
    req_no_thread = RunCreateRequest(input="Hello")
    assert req_no_thread.thread_id is None

    tid = uuid.uuid4()
    req_with_thread = RunCreateRequest(input="Follow up question", thread_id=tid)
    assert req_with_thread.thread_id == tid


def test_message_out_model():
    msg = MessageOut(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        role="assistant",
        content="Here is the compliance advice.",
        token_count=120,
        created_at=datetime.now(UTC),
    )
    assert msg.role == "assistant"
    assert msg.token_count == 120


def test_trace_out_model():
    trace_dto = TraceOut(
        trace_id="t-123",
        span_count=2,
        spans=[{"id": "s1", "name": "step1"}],
        tree=[{"id": "s1", "name": "step1", "children": []}],
    )
    assert trace_dto.trace_id == "t-123"
    assert trace_dto.span_count == 2
