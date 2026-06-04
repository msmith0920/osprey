"""Webhook adapter — creates POST /webhook/{trigger_name} routes."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from osprey.dispatch.registry import TriggerRegistry


def create_webhook_routes(registry: TriggerRegistry, dispatch_fn: Callable) -> APIRouter:
    """Return an APIRouter with a POST /webhook/{trigger_name} endpoint.

    The caller mounts this router on the FastAPI app.
    """
    router = APIRouter()

    @router.post("/webhook/{trigger_name}", status_code=status.HTTP_202_ACCEPTED)
    async def handle_webhook(trigger_name: str, request: Request) -> JSONResponse:
        # Bearer token validation
        expected_token = os.environ.get("EVENT_DISPATCHER_TOKEN", "")
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[len("Bearer ") :] != expected_token:
            raise HTTPException(status_code=401, detail="Unauthorized")

        # Trigger lookup
        try:
            trigger_status = await registry.get_status(trigger_name)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Trigger '{trigger_name}' not found"
            ) from exc

        # Source validation
        if trigger_status["source"] != "webhook":
            raise HTTPException(
                status_code=400,
                detail=f"Trigger '{trigger_name}' source is not 'webhook'",
            )

        # Parse payload
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            payload = {}

        # Retrieve full trigger config for the action
        # registry._triggers is accessed directly — same event loop, lock not needed for read
        trigger_cfg = registry._triggers[trigger_name]

        # Dispatch and record
        dispatch_id = await dispatch_fn(trigger_cfg.action, payload)
        await registry.record_event(trigger_name, payload, "dispatched")

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"dispatched": True, "dispatch_id": dispatch_id},
        )

    return router
