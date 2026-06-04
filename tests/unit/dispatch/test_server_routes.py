"""Route-level tests for the event dispatcher server.

These exercise the FastMCP app through a Starlette ``TestClient``. Using the
``with TestClient(app) as client:`` form runs the ASGI lifespan, which registers
triggers into the registry and starts the trigger sources — required for the
``/webhook`` route to dispatch.

Entry-point discovery for trigger sources lands in a later migration task, so the
``osprey.trigger_sources`` group is empty at runtime today. To make ``/webhook``
route-registration work here, ``osprey.dispatch.source_registry.entry_points`` is
monkeypatched to yield a fake entry point loading ``WebhookSource`` (the same
technique used in ``test_source_registry.py``).

``create_server()`` mutates a module-level FastMCP singleton (``server.mcp``) and
appends routes to it. In production it is called exactly once; in tests we call it
per case, so an autouse fixture snapshots and restores ``_additional_http_routes``
to keep each test's route set clean (otherwise a stale, never-started webhook route
from an earlier ``create_server()`` would shadow the live one and 503).
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from osprey.dispatch import server
from osprey.dispatch.sources.webhook import WebhookSource


class _FakeEntryPoint:
    """Minimal EntryPoint stand-in exposing .name and .load()."""

    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


@pytest.fixture(autouse=True)
def _reset_mcp_routes():
    """Reset the shared FastMCP singleton's routes around each test.

    Keeps only the module-level baseline routes (/health, /dispatch/...) so each
    ``create_server()`` call starts from a clean slate.
    """
    baseline = list(server.mcp._additional_http_routes)
    yield
    server.mcp._additional_http_routes = baseline


@pytest.fixture
def triggers_yml(tmp_path):
    """Write a minimal triggers.yml with one webhook trigger."""
    path = tmp_path / "triggers.yml"
    path.write_text(
        "dispatcher:\n"
        "  dispatch_target: http://localhost:9999\n"
        "  max_concurrent_runs: 2\n"
        "  max_queue_depth: 10\n"
        "triggers:\n"
        "  - name: deploy\n"
        "    source: webhook\n"
        "    action:\n"
        "      prompt: do the thing\n"
        "      allowed_tools: []\n"
    )
    return path


@pytest.fixture
def app(triggers_yml, monkeypatch):
    """Build the dispatcher FastMCP ASGI app with the webhook source discoverable.

    Patches entry-point discovery so ``SourceRegistry.discover()`` finds
    ``WebhookSource`` (real entry points are registered in a later task).
    """
    monkeypatch.setenv("TRIGGERS_YML", str(triggers_yml))
    monkeypatch.setenv("EVENT_DISPATCHER_TOKEN", "secret")

    def fake_entry_points(*, group):
        assert group == "osprey.trigger_sources"
        return [_FakeEntryPoint("webhook", WebhookSource)]

    monkeypatch.setattr("osprey.dispatch.source_registry.entry_points", fake_entry_points)

    return server.create_server().http_app()


def test_health_returns_status_and_pool(app):
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["trigger_count"] == 1
    assert "pool" in body
    assert {"running", "max", "queued"} <= set(body["pool"])


def test_webhook_success_returns_202(app):
    with TestClient(app) as client:
        resp = client.post(
            "/webhook/deploy",
            json={"ref": "main"},
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["dispatched"] is True
    assert isinstance(body["dispatch_id"], str) and body["dispatch_id"]


def test_webhook_wrong_token_returns_401(app):
    with TestClient(app) as client:
        resp = client.post(
            "/webhook/deploy",
            json={},
            headers={"Authorization": "Bearer wrong"},
        )
    assert resp.status_code == 401


def test_webhook_unknown_trigger_returns_404(app):
    with TestClient(app) as client:
        resp = client.post(
            "/webhook/nope",
            json={},
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 404


def test_webhook_unconfigured_token_fails_closed_503(triggers_yml, monkeypatch):
    """With EVENT_DISPATCHER_TOKEN unset, the webhook fails closed (503)."""
    monkeypatch.setenv("TRIGGERS_YML", str(triggers_yml))
    monkeypatch.delenv("EVENT_DISPATCHER_TOKEN", raising=False)

    def fake_entry_points(*, group):
        return [_FakeEntryPoint("webhook", WebhookSource)]

    monkeypatch.setattr("osprey.dispatch.source_registry.entry_points", fake_entry_points)
    app = server.create_server().http_app()
    with TestClient(app) as client:
        resp = client.post("/webhook/deploy", json={}, headers={"Authorization": "Bearer "})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Server misconfigured"}


def test_webhook_disabled_returns_409(app):
    with TestClient(app) as client:
        # Disable the trigger via the status route first.
        put = client.put(
            "/trigger/deploy/status",
            json={"status": "disabled"},
            headers={"Authorization": "Bearer secret"},
        )
        assert put.status_code == 200
        assert put.json() == {"name": "deploy", "status": "disabled"}

        resp = client.post(
            "/webhook/deploy",
            json={},
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 409


def test_dashboard_state_shape(app):
    """/dashboard/state returns the aggregate snapshot keys; runs is [] (no worker)."""
    with TestClient(app) as client:
        resp = client.get("/dashboard/state")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"pool", "triggers", "runs", "timeline", "server_time_iso"}
    # No worker is reachable, so fetch_worker_runs fails and is caught -> [].
    assert body["runs"] == []
    assert any(t["name"] == "deploy" for t in body["triggers"])


def test_check_auth_routes_reject_unconfigured_token(triggers_yml, monkeypatch):
    """Auth-guarded routes fail closed (503) when the token is unset."""
    monkeypatch.setenv("TRIGGERS_YML", str(triggers_yml))
    monkeypatch.delenv("EVENT_DISPATCHER_TOKEN", raising=False)

    def fake_entry_points(*, group):
        return [_FakeEntryPoint("webhook", WebhookSource)]

    monkeypatch.setattr("osprey.dispatch.source_registry.entry_points", fake_entry_points)
    app = server.create_server().http_app()
    with TestClient(app) as client:
        resp = client.put(
            "/trigger/deploy/status",
            json={"status": "disabled"},
            headers={"Authorization": "Bearer anything"},
        )
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Server misconfigured"}


def test_status_route_wrong_token_returns_401(app):
    with TestClient(app) as client:
        resp = client.put(
            "/trigger/deploy/status",
            json={"status": "disabled"},
            headers={"Authorization": "Bearer wrong"},
        )
    assert resp.status_code == 401


def test_status_route_bad_status_returns_400(app):
    with TestClient(app) as client:
        resp = client.put(
            "/trigger/deploy/status",
            json={"status": "bogus"},
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 400


def test_retry_known_trigger_returns_202(app):
    with TestClient(app) as client:
        resp = client.post(
            "/retry/deploy",
            json={"payload": {"ref": "main"}},
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["dispatched"] is True
    assert isinstance(body["dispatch_id"], str) and body["dispatch_id"]


def test_retry_unknown_trigger_returns_404(app):
    with TestClient(app) as client:
        resp = client.post(
            "/retry/nope",
            json={},
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 404


def test_retry_wrong_token_returns_401(app):
    with TestClient(app) as client:
        resp = client.post(
            "/retry/deploy",
            json={},
            headers={"Authorization": "Bearer wrong"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dispatch_with_policy_injects_payload_into_prompt(monkeypatch):
    """A non-empty event payload is folded into the dispatched prompt as JSON."""
    from osprey.dispatch.registry import TriggerRegistry
    from osprey.dispatch.trigger_config import TriggerConfig

    captured: dict = {}

    async def fake_dispatch(url, prompt, allowed_tools, token, timeout=30.0):
        captured["prompt"] = prompt
        return {"run_id": "r1", "status": "ok"}

    monkeypatch.setattr(server, "dispatch_to_worker", fake_dispatch)

    reg = TriggerRegistry()
    trig = TriggerConfig(name="t", source="webhook", action={"prompt": "base prompt"})
    await reg.register(trig)
    await server._dispatch_with_policy(trig, {"ref": "main", "n": 3}, reg, "http://w", "tok")

    assert "base prompt" in captured["prompt"]
    assert "Event payload (JSON):" in captured["prompt"]
    assert '"ref": "main"' in captured["prompt"]


@pytest.mark.asyncio
async def test_dispatch_with_policy_empty_payload_no_injection(monkeypatch):
    """An empty payload leaves the prompt untouched (no trailing payload section)."""
    from osprey.dispatch.registry import TriggerRegistry
    from osprey.dispatch.trigger_config import TriggerConfig

    captured: dict = {}

    async def fake_dispatch(url, prompt, allowed_tools, token, timeout=30.0):
        captured["prompt"] = prompt
        return {"run_id": "r1", "status": "ok"}

    monkeypatch.setattr(server, "dispatch_to_worker", fake_dispatch)

    reg = TriggerRegistry()
    trig = TriggerConfig(name="t", source="webhook", action={"prompt": "base prompt"})
    await reg.register(trig)
    await server._dispatch_with_policy(trig, {}, reg, "http://w", "tok")

    assert captured["prompt"] == "base prompt"


@pytest.mark.asyncio
async def test_dispatch_with_policy_retries_with_backoff_on_dispatch_error(monkeypatch):
    """``on_error: retry`` re-dispatches up to ``max_retries`` with backoff between attempts.

    Automatic retry/backoff fires ONLY when the dispatcher cannot reach the
    worker (i.e. ``dispatch_to_worker`` raises). That is the path the retired
    ``retry-demo`` tutorial trigger could never actually exercise via a ``curl``
    against a healthy stack, so it is covered here as a deterministic,
    token-free check instead of as a (misleading) demo trigger.
    """
    from osprey.dispatch.registry import TriggerRegistry
    from osprey.dispatch.trigger_config import TriggerConfig
    from osprey.dispatch.worker_client import DispatchError

    attempts = {"dispatch": 0}

    async def always_fails(url, prompt, allowed_tools, token, timeout=30.0):
        attempts["dispatch"] += 1
        raise DispatchError("worker unreachable")

    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    # ``server`` calls ``await asyncio.sleep(...)`` against its module-level
    # ``asyncio`` import; patch that so the backoff is asserted without delay.
    monkeypatch.setattr(server, "dispatch_to_worker", always_fails)
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    reg = TriggerRegistry()
    trig = TriggerConfig(
        name="retry-trigger",
        source="webhook",
        action={"prompt": "do a thing"},
        on_error={"action": "retry", "max_retries": 2, "backoff_sec": 0.01},
    )
    await reg.register(trig)

    result = await server._dispatch_with_policy(trig, {}, reg, "http://w", "tok")

    # Retries exhausted -> dropped -> returns None.
    assert result is None
    # Initial attempt + max_retries retries == 3 dispatch calls.
    assert attempts["dispatch"] == 3
    # Backoff slept once before each of the 2 retries (never on the final drop).
    assert slept == [0.01, 0.01]
    # Every failed attempt records an error event in the trigger history.
    history = await reg.get_history("retry-trigger")
    error_events = [e for e in history if str(e["result"]).startswith("error:")]
    assert len(error_events) == 3


def test_sanitize_source_config_redacts_secret_keys():
    """Secret-like source_config keys are redacted before dashboard exposure."""
    cfg = {"interval_sec": 300, "signing_secret": "shhh", "API_KEY": "abc", "pv": "X:Y"}
    sanitized = server._sanitize_source_config(cfg)
    assert sanitized["interval_sec"] == 300
    assert sanitized["pv"] == "X:Y"
    assert sanitized["signing_secret"] == "***"
    assert sanitized["API_KEY"] == "***"  # case-insensitive match
