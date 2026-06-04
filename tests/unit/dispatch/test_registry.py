"""Tests for TriggerRegistry."""

import pytest

from osprey.dispatch.registry import TriggerRegistry
from osprey.dispatch.trigger_config import TriggerConfig


def _make_trigger(name: str, source: str = "webhook") -> TriggerConfig:
    return TriggerConfig(
        name=name,
        source=source,
        action={"prompt": f"Do something for {name}"},
    )


@pytest.mark.asyncio
async def test_register_and_list():
    """register() adds trigger; list_triggers() returns it with correct fields."""
    reg = TriggerRegistry()
    t = _make_trigger("beam_loss", "epics")
    await reg.register(t)

    listing = await reg.list_triggers()
    assert len(listing) == 1
    entry = listing[0]
    assert entry["name"] == "beam_loss"
    assert entry["source"] == "epics"
    assert entry["status"] == "active"
    assert entry["last_fired"] is None


@pytest.mark.asyncio
async def test_get_status_known_trigger():
    """get_status returns correct dict for a registered trigger."""
    reg = TriggerRegistry()
    await reg.register(_make_trigger("fill_pattern"))
    status = await reg.get_status("fill_pattern")
    assert status["name"] == "fill_pattern"
    assert status["status"] == "active"
    assert status["last_fired"] is None


@pytest.mark.asyncio
async def test_get_status_unknown_trigger_raises():
    """get_status raises KeyError for unregistered trigger."""
    reg = TriggerRegistry()
    with pytest.raises(KeyError, match="not registered"):
        await reg.get_status("nonexistent")


@pytest.mark.asyncio
async def test_record_event_updates_last_fired_and_history():
    """record_event updates last_fired and appends to history."""
    reg = TriggerRegistry()
    await reg.register(_make_trigger("orbit_drift"))
    await reg.record_event("orbit_drift", {"bpm": 42}, "ok")

    status = await reg.get_status("orbit_drift")
    assert status["last_fired"] is not None

    history = await reg.get_history("orbit_drift")
    assert len(history) == 1
    entry = history[0]
    assert entry["event_data"] == {"bpm": 42}
    assert entry["result"] == "ok"
    assert "timestamp" in entry


@pytest.mark.asyncio
async def test_get_history_respects_limit():
    """get_history(limit=N) returns at most N most recent entries."""
    reg = TriggerRegistry()
    await reg.register(_make_trigger("heartbeat"))
    for i in range(10):
        await reg.record_event("heartbeat", {"i": i}, "ok")

    recent = await reg.get_history("heartbeat", limit=3)
    assert len(recent) == 3
    # Should be the last 3
    assert [e["event_data"]["i"] for e in recent] == [7, 8, 9]


@pytest.mark.asyncio
async def test_re_registration_resets_status_but_keeps_history():
    """Re-registering a trigger resets status fields but preserves existing history deque."""
    reg = TriggerRegistry()
    await reg.register(_make_trigger("bpm_spike"))
    await reg.record_event("bpm_spike", {"val": 1}, "ok")

    # Re-register
    await reg.register(_make_trigger("bpm_spike", source="new_source"))
    status = await reg.get_status("bpm_spike")
    assert status["source"] == "new_source"
    assert status["last_fired"] is None

    # History deque is preserved (not wiped)
    history = await reg.get_history("bpm_spike")
    assert len(history) == 1


@pytest.mark.asyncio
async def test_record_event_unknown_trigger_raises():
    """record_event raises KeyError for unregistered trigger."""
    reg = TriggerRegistry()
    with pytest.raises(KeyError, match="not registered"):
        await reg.record_event("ghost", {}, "ok")


@pytest.mark.asyncio
async def test_multiple_triggers_isolated():
    """Events for one trigger do not appear in another's history."""
    reg = TriggerRegistry()
    await reg.register(_make_trigger("alpha"))
    await reg.register(_make_trigger("beta"))

    await reg.record_event("alpha", {"x": 1}, "ok")
    await reg.record_event("alpha", {"x": 2}, "ok")
    await reg.record_event("beta", {"y": 99}, "ok")

    alpha_hist = await reg.get_history("alpha")
    beta_hist = await reg.get_history("beta")
    assert len(alpha_hist) == 2
    assert len(beta_hist) == 1
