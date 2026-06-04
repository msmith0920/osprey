"""Tests for worker_client using httpx.MockTransport."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from osprey.dispatch.worker_client import (
    AuthError,
    DispatchError,
    dispatch_to_worker,
)


def _mock_transport(status_code: int = 200, body: dict | None = None) -> httpx.MockTransport:
    """Return a MockTransport that always responds with the given status and JSON body."""
    if body is None:
        body = {"run_id": "abc123", "status": "accepted"}
    encoded = json.dumps(body).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            content=encoded,
            headers={"content-type": "application/json"},
            request=request,
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_successful_dispatch_returns_response_dict():
    expected = {"run_id": "abc123", "status": "accepted"}
    transport = _mock_transport(200, expected)

    with patch(
        "httpx.AsyncClient",
        lambda **kw: httpx.AsyncClient(
            transport=transport, **{k: v for k, v in kw.items() if k != "transport"}
        ),
    ):
        # Patch AsyncClient to inject our mock transport
        pass

    # Patch at the module level
    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    with patch("osprey.dispatch.worker_client.httpx.AsyncClient", PatchedClient):
        result = await dispatch_to_worker(
            url="http://dispatch-worker-1:9190",
            prompt="show beam current",
            allowed_tools=["read_pv"],
            token="secret-token",
        )

    assert result == expected


@pytest.mark.asyncio
async def test_connection_error_raises_dispatch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(handler)
    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    with patch("osprey.dispatch.worker_client.httpx.AsyncClient", PatchedClient):
        with pytest.raises(DispatchError, match="Connection error"):
            await dispatch_to_worker(
                url="http://unreachable:9999",
                prompt="test",
                allowed_tools=[],
                token="tok",
            )


@pytest.mark.asyncio
async def test_http_401_raises_auth_error():
    transport = _mock_transport(status_code=401, body={"detail": "invalid token"})
    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    with patch("osprey.dispatch.worker_client.httpx.AsyncClient", PatchedClient):
        with pytest.raises(AuthError, match="Unauthorized"):
            await dispatch_to_worker(
                url="http://worker:9190",
                prompt="test",
                allowed_tools=[],
                token="bad-token",
            )


@pytest.mark.asyncio
async def test_timeout_raises_dispatch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    with patch("osprey.dispatch.worker_client.httpx.AsyncClient", PatchedClient):
        with pytest.raises(DispatchError, match="Timeout"):
            await dispatch_to_worker(
                url="http://worker:9190",
                prompt="test",
                allowed_tools=[],
                token="tok",
                timeout=1.0,
            )


@pytest.mark.asyncio
async def test_bearer_token_sent_in_headers():
    captured_headers: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(
            status_code=200,
            content=json.dumps({"run_id": "x", "status": "ok"}).encode(),
            headers={"content-type": "application/json"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    with patch("osprey.dispatch.worker_client.httpx.AsyncClient", PatchedClient):
        await dispatch_to_worker(
            url="http://worker:9190",
            prompt="test",
            allowed_tools=[],
            token="my-secret-token",
        )

    assert captured_headers.get("authorization") == "Bearer my-secret-token"
