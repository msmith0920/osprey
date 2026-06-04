"""Unit tests for the dispatch-worker FastAPI app.

Exercises the HTTP surface of ``osprey.mcp_server.dispatch_worker.dispatch_api``
with a sync ``TestClient`` (lifespan runs inside the ``with`` block). The real
``sdk_runner.run_dispatch`` calls the Claude Agent SDK, so it is monkeypatched
with a fast canned coroutine — the background task then completes without the
SDK and tests never assert a timing-dependent terminal status.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from osprey.mcp_server.dispatch_worker import dispatch_api

_TOKEN = "test-secret-token"

_CANNED_RESULT: dict[str, Any] = {
    "status": "completed",
    "text_output": "ok",
    "tool_calls": [],
    "error": None,
    "duration_sec": 0.01,
    "cost_usd": 0.0,
    "num_turns": 1,
}


@pytest.fixture
def client(monkeypatch):
    """A TestClient with auth configured and run_dispatch stubbed out.

    Resets the module-level in-memory stores so tests do not leak state into
    each other, and patches ``sdk_runner.run_dispatch`` with a fast async stub.
    """
    monkeypatch.setenv("DISPATCH_WORKER_TOKEN", _TOKEN)

    # Isolate global state between tests.
    monkeypatch.setattr(dispatch_api, "_runs", {})
    monkeypatch.setattr(dispatch_api, "_queues", {})
    monkeypatch.setattr(dispatch_api, "_tasks", {})

    async def _fake_run_dispatch(*, prompt, allowed_tools, max_turns, event_queue):
        if event_queue is not None:
            await event_queue.put({"type": "done"})
        return dict(_CANNED_RESULT)

    monkeypatch.setattr(dispatch_api.sdk_runner, "run_dispatch", _fake_run_dispatch)
    # Avoid touching disk during the background task.
    monkeypatch.setattr(dispatch_api, "_persist_run", lambda run_id, run: None)

    with TestClient(dispatch_api.app) as c:
        yield c


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


def _wait_for_terminal(client: TestClient, run_id: str, timeout: float = 5.0) -> dict:
    """Poll a run until it leaves the ``pending`` state (or time out)."""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        resp = client.get(f"/dispatch/{run_id}", headers=_auth())
        assert resp.status_code == 200
        last = resp.json()
        if last.get("status") != "pending":
            return last
        time.sleep(0.02)
    return last


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    for key in ("pending_runs", "completed_runs", "error_runs", "total_runs"):
        assert key in body
        assert isinstance(body[key], int)


# ---------------------------------------------------------------------------
# POST /dispatch
# ---------------------------------------------------------------------------


def test_dispatch_accepts_benign_tools(client):
    resp = client.post(
        "/dispatch",
        json={"prompt": "do it", "allowed_tools": ["Read"]},
        headers=_auth(),
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert isinstance(body["run_id"], str)
    assert body["run_id"]


def test_dispatch_rejects_denied_tool(client):
    resp = client.post(
        "/dispatch",
        json={"prompt": "fetch", "allowed_tools": ["Read", "WebFetch"]},
        headers=_auth(),
    )
    assert resp.status_code == 403
    assert "WebFetch" in resp.json()["detail"]


def test_dispatch_rejects_wildcard_denied_tool(client):
    """Denylist '*'-suffix entries block by prefix (e.g. all playwright tools)."""
    tool = "mcp__plugin_playwright_playwright__browser_click"
    resp = client.post(
        "/dispatch",
        json={"prompt": "click", "allowed_tools": [tool]},
        headers=_auth(),
    )
    assert resp.status_code == 403
    assert tool in resp.json()["detail"]


def test_dispatch_wrong_token(client):
    resp = client.post(
        "/dispatch",
        json={"prompt": "do it", "allowed_tools": ["Read"]},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_dispatch_no_auth_header(client):
    # HTTPBearer auto-error rejects a missing Authorization header. The exact
    # code depends on the FastAPI version (older: 403, current: 401); accept
    # either so the test tracks behavior without pinning a version-specific code.
    resp = client.post(
        "/dispatch",
        json={"prompt": "do it", "allowed_tools": ["Read"]},
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /dispatch/{run_id}
# ---------------------------------------------------------------------------


def test_get_dispatch_unknown_id_404(client):
    resp = client.get("/dispatch/does-not-exist", headers=_auth())
    assert resp.status_code == 404


def test_get_dispatch_returns_status(client):
    post = client.post(
        "/dispatch",
        json={"prompt": "do it", "allowed_tools": ["Read"]},
        headers=_auth(),
    )
    run_id = post.json()["run_id"]

    result = _wait_for_terminal(client, run_id)
    assert result.get("status") in ("pending", "completed", "error")
    # With the fast stub the run should reach completion.
    assert result["status"] == "completed"
    assert result["text_output"] == "ok"


# ---------------------------------------------------------------------------
# DELETE /dispatch/{run_id}
# ---------------------------------------------------------------------------


def test_cancel_unknown_id_404(client):
    resp = client.delete("/dispatch/does-not-exist", headers=_auth())
    assert resp.status_code == 404


def test_cancel_finished_run(client):
    post = client.post(
        "/dispatch",
        json={"prompt": "do it", "allowed_tools": ["Read"]},
        headers=_auth(),
    )
    run_id = post.json()["run_id"]
    # Let the stub finish so the run is no longer pending.
    _wait_for_terminal(client, run_id)

    resp = client.delete(f"/dispatch/{run_id}", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert "cancelled" in body
    # A finished run cannot be cancelled.
    assert body["cancelled"] is False


# ---------------------------------------------------------------------------
# GET /dashboard/runs
# ---------------------------------------------------------------------------


def test_dashboard_runs_requires_auth(client):
    # The runs feed leaks full text_output/error, so it is token-gated like the
    # other worker endpoints. HTTPBearer auto-error rejects a missing header
    # (401 current FastAPI, 403 older) — accept either.
    resp = client.get("/dashboard/runs")
    assert resp.status_code in (401, 403)


def test_dashboard_runs_with_auth(client):
    # Seed one run via the API.
    client.post(
        "/dispatch",
        json={"prompt": "do it", "allowed_tools": ["Read"]},
        headers=_auth(),
    )
    resp = client.get("/dashboard/runs", headers=_auth())
    assert resp.status_code == 200
    runs = resp.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1
    assert "run_id" in runs[0]
    assert "status" in runs[0]


# ---------------------------------------------------------------------------
# Startup Claude-artifact provisioning
# ---------------------------------------------------------------------------
#
# The deployed worker mounts only config.yml into the project dir, so it must
# regenerate .mcp.json / .claude/ at startup; otherwise dispatched agents have
# no project MCP servers (e.g. osprey_workspace) and no safety hooks.


def test_provision_skips_when_no_config(tmp_path, monkeypatch):
    """No config.yml in the project dir → provisioning is a no-op (no regen call)."""
    monkeypatch.setenv("OSPREY_PROJECT_DIR", str(tmp_path))
    called = {"n": 0}

    class _FakeTM:
        def regenerate_claude_code(self, *a, **k):
            called["n"] += 1
            return {"changed": []}

    monkeypatch.setattr("osprey.cli.templates.manager.TemplateManager", _FakeTM, raising=True)
    dispatch_api._provision_claude_artifacts_once()  # must not raise
    assert called["n"] == 0, "regen must not run without a config.yml"


def test_provision_regenerates_when_mcp_json_absent(tmp_path, monkeypatch):
    """config.yml present but .mcp.json absent (the container case) → regen runs."""
    (tmp_path / "config.yml").write_text("project_name: t\n", encoding="utf-8")
    monkeypatch.setenv("OSPREY_PROJECT_DIR", str(tmp_path))
    seen = {}

    class _FakeTM:
        def regenerate_claude_code(self, project_dir, *a, **k):
            seen["project_dir"] = project_dir
            return {"changed": [".mcp.json", "CLAUDE.md"]}

    monkeypatch.setattr("osprey.cli.templates.manager.TemplateManager", _FakeTM, raising=True)
    dispatch_api._provision_claude_artifacts_once()
    assert str(seen.get("project_dir")) == str(tmp_path)


def test_provision_skips_when_already_provisioned(tmp_path, monkeypatch):
    """A project that already has .mcp.json must NOT be regenerated.

    The subprocess path and non-container deploys run in the real project dir,
    which ships container-correct artifacts and may carry user customizations
    (e.g. via ``osprey eject``). Regenerating would clobber them.
    """
    (tmp_path / "config.yml").write_text("project_name: t\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OSPREY_PROJECT_DIR", str(tmp_path))
    called = {"n": 0}

    class _FakeTM:
        def regenerate_claude_code(self, *a, **k):
            called["n"] += 1
            return {"changed": []}

    monkeypatch.setattr("osprey.cli.templates.manager.TemplateManager", _FakeTM, raising=True)
    dispatch_api._provision_claude_artifacts_once()
    assert called["n"] == 0, "must not regenerate when .mcp.json already exists"


def test_provision_swallows_regen_errors(tmp_path, monkeypatch):
    """A regen failure must not crash the worker (it still serves no-tool triggers)."""
    (tmp_path / "config.yml").write_text("project_name: t\n", encoding="utf-8")
    monkeypatch.setenv("OSPREY_PROJECT_DIR", str(tmp_path))

    class _FakeTM:
        def regenerate_claude_code(self, *a, **k):
            raise RuntimeError("boom")

    monkeypatch.setattr("osprey.cli.templates.manager.TemplateManager", _FakeTM, raising=True)
    dispatch_api._provision_claude_artifacts_once()  # must not raise
