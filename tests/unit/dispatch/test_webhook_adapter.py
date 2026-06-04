"""Tests for webhook_adapter."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from osprey.dispatch.registry import TriggerRegistry
from osprey.dispatch.trigger_config import TriggerConfig
from osprey.dispatch.webhook_adapter import create_webhook_routes

_TOKEN = "test-secret-token"


def _make_app(registry: TriggerRegistry, dispatch_fn) -> FastAPI:
    app = FastAPI()
    app.include_router(create_webhook_routes(registry, dispatch_fn))
    return app


async def _noop_dispatch(action, payload) -> str:
    return "dispatch-uuid-1234"


@pytest.fixture(autouse=True)
def set_token(monkeypatch):
    monkeypatch.setenv("EVENT_DISPATCHER_TOKEN", _TOKEN)


@pytest.fixture
async def registry_with_webhook():
    reg = TriggerRegistry()
    await reg.register(
        TriggerConfig(name="beam_loss", source="webhook", action={"prompt": "Handle beam loss"})
    )
    return reg


@pytest.fixture
async def registry_with_non_webhook():
    reg = TriggerRegistry()
    await reg.register(
        TriggerConfig(name="orbit_drift", source="epics", action={"prompt": "Handle orbit drift"})
    )
    return reg


@pytest.mark.asyncio
async def test_valid_request_returns_202(registry_with_webhook):
    app = _make_app(registry_with_webhook, _noop_dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/beam_loss",
            json={"severity": "high"},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["dispatched"] is True
    assert "dispatch_id" in body


@pytest.mark.asyncio
async def test_missing_token_returns_401(registry_with_webhook):
    app = _make_app(registry_with_webhook, _noop_dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhook/beam_loss", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_returns_401(registry_with_webhook):
    app = _make_app(registry_with_webhook, _noop_dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/beam_loss",
            json={},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unknown_trigger_returns_404(registry_with_webhook):
    app = _make_app(registry_with_webhook, _noop_dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/nonexistent",
            json={},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_webhook_source_returns_400(registry_with_non_webhook):
    app = _make_app(registry_with_non_webhook, _noop_dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/orbit_drift",
            json={"val": 1},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_dispatch_fn_called_with_action_and_payload(registry_with_webhook):
    calls = []

    async def capturing_dispatch(action, payload) -> str:
        calls.append({"action": action, "payload": payload})
        return "dispatch-id-abc"

    app = _make_app(registry_with_webhook, capturing_dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/webhook/beam_loss",
            json={"current": 0.4},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )

    assert len(calls) == 1
    assert calls[0]["action"] == {"prompt": "Handle beam loss"}
    assert calls[0]["payload"] == {"current": 0.4}


@pytest.mark.asyncio
async def test_event_recorded_in_registry(registry_with_webhook):
    app = _make_app(registry_with_webhook, _noop_dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/webhook/beam_loss",
            json={"x": 1},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )

    history = await registry_with_webhook.get_history("beam_loss")
    assert len(history) == 1
    assert history[0]["result"] == "dispatched"
    assert history[0]["event_data"] == {"x": 1}
