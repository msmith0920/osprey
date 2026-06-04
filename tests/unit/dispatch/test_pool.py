"""Tests for DispatchPool."""

import asyncio

import pytest

from osprey.dispatch.pool import DispatchPool, QueueFullError


@pytest.mark.asyncio
async def test_submit_runs_dispatch_fn_when_capacity_available():
    """Submit runs dispatch_fn immediately when pool has capacity."""
    pool = DispatchPool(max_concurrent=2, max_queue_depth=5)
    called = []

    async def fn():
        called.append(True)

    dispatch_id = await pool.submit("test_trigger", fn)
    await asyncio.sleep(0)  # yield to allow task to run
    await asyncio.sleep(0)

    assert isinstance(dispatch_id, str)
    assert len(dispatch_id) == 36  # UUID format
    assert called == [True]


@pytest.mark.asyncio
async def test_pool_respects_max_concurrent():
    """Pool never runs more than max_concurrent dispatches simultaneously."""
    max_concurrent = 2
    pool = DispatchPool(max_concurrent=max_concurrent, max_queue_depth=10)

    hold_event = asyncio.Event()
    running_count = []
    peak_concurrent = [0]

    async def fn():
        running_count.append(1)
        peak_concurrent[0] = max(peak_concurrent[0], sum(running_count))
        await hold_event.wait()
        running_count.pop()

    # Submit more tasks than max_concurrent
    for i in range(4):
        await pool.submit(f"trigger_{i}", fn)

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    status = pool.get_pool_status()
    assert status["running"] <= max_concurrent

    # Release all held dispatches
    hold_event.set()
    await asyncio.sleep(0.1)

    assert peak_concurrent[0] <= max_concurrent


@pytest.mark.asyncio
async def test_queue_full_error_raised_when_exceeded():
    """QueueFullError is raised when queue exceeds max_queue_depth."""
    pool = DispatchPool(max_concurrent=1, max_queue_depth=2)

    hold_event = asyncio.Event()

    async def blocking_fn():
        await hold_event.wait()

    # Fill the running slot
    await pool.submit("trigger_0", blocking_fn)
    await asyncio.sleep(0)

    # Fill the queue
    await pool.submit("trigger_1", blocking_fn)
    await pool.submit("trigger_2", blocking_fn)

    # Next submit should raise
    with pytest.raises(QueueFullError):
        await pool.submit("trigger_overflow", blocking_fn)

    hold_event.set()
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_get_pool_status_returns_correct_counts():
    """get_pool_status returns accurate running, max, and queued counts."""
    pool = DispatchPool(max_concurrent=2, max_queue_depth=10)

    hold_event = asyncio.Event()

    async def blocking_fn():
        await hold_event.wait()

    # Submit 2 (fills running slots) + 3 queued
    for i in range(5):
        await pool.submit(f"trigger_{i}", blocking_fn)

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    status = pool.get_pool_status()
    assert status["max"] == 2
    assert status["running"] == 2
    assert status["queued"] == 3

    hold_event.set()
    await asyncio.sleep(0.1)

    final = pool.get_pool_status()
    assert final["running"] == 0
    assert final["queued"] == 0


@pytest.mark.asyncio
async def test_fifo_ordering_is_maintained():
    """Queued dispatches are executed in FIFO order."""
    pool = DispatchPool(max_concurrent=1, max_queue_depth=10)

    hold_event = asyncio.Event()
    execution_order = []

    async def make_fn(label):
        async def fn():
            await hold_event.wait()
            execution_order.append(label)

        return fn

    # Submit 1 (fills running slot) then 3 queued
    await pool.submit("first", await make_fn("first"))
    await asyncio.sleep(0)

    for label in ["second", "third", "fourth"]:
        await pool.submit(label, await make_fn(label))

    hold_event.set()
    await asyncio.sleep(0.2)

    assert execution_order == ["first", "second", "third", "fourth"]
