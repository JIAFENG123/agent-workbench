from __future__ import annotations

import asyncio
import uuid

from app.runtime.events import EventBus, RunEvent


async def _collect(bus: EventBus, run_id: uuid.UUID) -> list[str]:
    return [event.type async for event in bus.subscribe(run_id)]


async def test_subscribing_after_close_returns_immediately() -> None:
    """A client that connects once the run is already over must not hang forever."""
    bus = EventBus()
    run_id = uuid.uuid4()
    bus.close(run_id)

    assert await asyncio.wait_for(_collect(bus, run_id), timeout=1) == []


async def test_open_revives_a_closed_run() -> None:
    bus = EventBus()
    run_id = uuid.uuid4()
    bus.close(run_id)
    assert bus.is_closed(run_id)

    bus.open(run_id)
    assert not bus.is_closed(run_id)


async def test_subscriber_receives_published_events_until_close() -> None:
    bus = EventBus()
    run_id = uuid.uuid4()

    reader = asyncio.ensure_future(_collect(bus, run_id))
    await asyncio.sleep(0)  # let the subscriber register its queue

    await bus.publish(run_id, RunEvent(type="step", payload={"step": 1}, seq=1))
    await bus.publish(run_id, RunEvent(type="token", payload={"text": "hi"}, seq=2))
    bus.close(run_id)

    assert await asyncio.wait_for(reader, timeout=1) == ["step", "token"]
    assert not bus.has_subscribers(run_id)


async def test_publish_without_subscribers_is_a_no_op() -> None:
    bus = EventBus()
    await bus.publish(uuid.uuid4(), RunEvent(type="token", seq=1))


async def test_events_from_different_runs_do_not_cross() -> None:
    bus = EventBus()
    mine, theirs = uuid.uuid4(), uuid.uuid4()

    reader = asyncio.ensure_future(_collect(bus, mine))
    await asyncio.sleep(0)

    await bus.publish(theirs, RunEvent(type="token", payload={"text": "secret"}, seq=1))
    await bus.publish(mine, RunEvent(type="token", payload={"text": "mine"}, seq=1))
    bus.close(mine)

    assert await asyncio.wait_for(reader, timeout=1) == ["token"]


async def test_slow_subscriber_drops_oldest_instead_of_blocking_producer() -> None:
    """Queue backpressure must never stall an agent run, and a backlogged subscriber must
    still receive the end-of-run sentinel rather than hanging on a finished run."""
    bus = EventBus(max_queue=2)
    run_id = uuid.uuid4()

    reader = asyncio.ensure_future(_collect(bus, run_id))
    await asyncio.sleep(0)

    for seq in range(1, 6):
        await bus.publish(run_id, RunEvent(type="token", payload={"seq": seq}, seq=seq))
    bus.close(run_id)

    received = await asyncio.wait_for(reader, timeout=1)
    assert 0 < len(received) <= 2, "queue must stay bounded by max_queue"


async def test_run_event_serialises_to_sse_with_sequence() -> None:
    event = RunEvent(type="step", payload={"node": "planner"}, seq=7)
    frame = event.to_sse()
    assert frame["event"] == "step"
    assert '"seq": 7' in frame["data"]
    assert '"node": "planner"' in frame["data"]


async def test_run_event_keeps_non_ascii_readable() -> None:
    event = RunEvent(type="token", payload={"text": "合规审查"}, seq=1)
    assert "合规审查" in event.to_sse()["data"]
