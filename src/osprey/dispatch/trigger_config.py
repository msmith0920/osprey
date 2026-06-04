"""Trigger configuration dataclasses and YAML loader for the event dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

_DEFAULT_ON_ERROR: dict[str, Any] = {
    "action": "drop",
    "max_retries": 0,
    "backoff_sec": 0.0,
}


@dataclass
class TriggerConfig:
    name: str
    source: str
    action: dict[str, Any]
    on_error: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_ON_ERROR))
    source_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class DispatcherConfig:
    dispatch_target: str
    max_concurrent_runs: int = 5
    max_queue_depth: int = 100


def _parse_trigger(raw: dict[str, Any], index: int) -> TriggerConfig:
    name = raw.get("name")
    if not name:
        raise ValueError(f"Trigger at index {index} is missing required field 'name'")

    source = raw.get("source", "")

    action = raw.get("action")
    if not action or not action.get("prompt"):
        raise ValueError(f"Trigger '{name}' is missing required field 'action.prompt'")

    on_error_raw = raw.get("on_error")
    if on_error_raw is None:
        on_error = dict(_DEFAULT_ON_ERROR)
    else:
        on_error = {
            "action": on_error_raw.get("action", _DEFAULT_ON_ERROR["action"]),
            "max_retries": on_error_raw.get("max_retries", _DEFAULT_ON_ERROR["max_retries"]),
            "backoff_sec": on_error_raw.get("backoff_sec", _DEFAULT_ON_ERROR["backoff_sec"]),
        }

    source_config = raw.get("source_config", {})

    return TriggerConfig(
        name=name, source=source, action=action, on_error=on_error, source_config=source_config
    )


def load_triggers(path: str) -> tuple[DispatcherConfig, list[TriggerConfig]]:
    """Parse a triggers YAML file and return (DispatcherConfig, list[TriggerConfig])."""
    with open(path) as f:
        doc = yaml.safe_load(f)

    dispatcher_raw = doc.get("dispatcher", {})
    dispatcher_cfg = DispatcherConfig(
        dispatch_target=dispatcher_raw.get("dispatch_target", ""),
        max_concurrent_runs=dispatcher_raw.get("max_concurrent_runs", 5),
        max_queue_depth=dispatcher_raw.get("max_queue_depth", 100),
    )

    raw_triggers = doc.get("triggers") or []
    triggers = [_parse_trigger(t, i) for i, t in enumerate(raw_triggers)]

    return dispatcher_cfg, triggers
