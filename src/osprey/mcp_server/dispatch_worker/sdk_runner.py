"""SDK runner for headless dispatch via claude_agent_sdk.

Wraps claude_agent_sdk.query() to execute agent prompts and return
structured results for use by the dispatch API endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger("osprey.mcp_server.dispatch_worker.sdk_runner")

# SDK imports -- guard so module loads even when SDK is not installed
# (SDK is only available inside the worker container).
try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
        query,
    )

    HAS_SDK = True
except ImportError:
    HAS_SDK = False

_DEFAULT_PROJECT_DIR = "/app/project"


async def run_dispatch(
    prompt: str,
    allowed_tools: list[str],
    max_turns: int = 25,
    event_queue: asyncio.Queue | None = None,
) -> dict[str, Any]:
    """Run a prompt headlessly via the Claude Agent SDK.

    Args:
        prompt: The prompt to send to the agent.
        allowed_tools: List of tool names the agent may use.
        max_turns: Maximum number of agentic turns (default 25).

    Returns:
        dict with keys:
            status: "completed" or "error"
            text_output: concatenated assistant text blocks
            tool_calls: list of {name, input, result} dicts
            error: error message string or None
            duration_sec: wall-clock seconds
            cost_usd: API cost (from ResultMessage, if available)
            num_turns: agentic turn count (from ResultMessage, if available)
    """
    if not HAS_SDK:
        return {
            "status": "error",
            "text_output": "",
            "tool_calls": [],
            "error": "claude_agent_sdk is not installed",
            "duration_sec": 0.0,
            "cost_usd": None,
            "num_turns": None,
        }

    project_dir = os.environ.get("OSPREY_PROJECT_DIR", _DEFAULT_PROJECT_DIR)
    stderr_lines: list[str] = []

    # Build env the same way the OSPREY web server does for operator sessions:
    # build_clean_env() strips CLAUDECODE/CLAUDE_CODE_* vars and resolves auth
    # conflicts.  Provider env (auth token, base URL, model tier IDs) is already
    # injected into os.environ by _inject_provider_env_once() at worker startup.
    from osprey.interfaces.web_terminal.operator_session import build_clean_env
    from osprey.interfaces.web_terminal.sdk_context import (
        build_system_prompt,
        make_tool_allowlist,
    )
    from osprey.utils.config import get_facility_timezone

    sdk_env = build_clean_env(project_cwd=project_dir)

    # Point OSPREY config resolution at the project explicitly. The worker
    # process CWD is the image WORKDIR (``/app`` in the container), not the
    # project dir, and ``osprey.utils.config`` falls back to ``CWD/config.yml``
    # when ``CONFIG_FILE`` is unset — so without this, the spawned agent and its
    # hook subprocesses (which ``ClaudeAgentOptions(cwd=...)`` does not relocate)
    # error with "No config.yml found in current directory" on every dispatch.
    sdk_env["CONFIG_FILE"] = os.path.join(project_dir, "config.yml")

    # The container sets CLAUDE_CONFIG_DIR=/data/claude-config (root-owned, used
    # by osprey-web).  The dispatch user can't write there, and the CLI hangs on
    # startup if it can't write session data.  Override to dispatch user's home.
    dispatch_home = os.environ.get("HOME", "/home/dispatch")
    sdk_env["CLAUDE_CONFIG_DIR"] = os.path.join(dispatch_home, ".claude")

    # NOTE: do NOT use permission_mode="bypassPermissions" — the CLI short-circuits
    # can_use_tool under bypass, so the allowlist would not be enforced. With the
    # default mode and can_use_tool set, the SDK auto-configures
    # permission_prompt_tool_name="stdio" (see client.py:122) which routes every
    # tool permission check to our allowlist callback.
    options = ClaudeAgentOptions(
        allowed_tools=allowed_tools,
        system_prompt=build_system_prompt(get_facility_timezone()),
        can_use_tool=make_tool_allowlist(allowed_tools),
        cwd=project_dir,
        env=sdk_env,
        max_turns=max_turns,
        stderr=lambda line: stderr_lines.append(line),
        setting_sources=["project"],
    )

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    # Map tool_use_id -> index in tool_calls for matching results to calls
    pending_tools: dict[str, int] = {}
    cost_usd: float | None = None
    num_turns: int | None = None

    async def _push(event: dict[str, Any]) -> None:
        if event_queue is not None:
            await event_queue.put(event)

    # can_use_tool requires streaming-mode input (AsyncIterable), not str.
    async def _prompt_stream():
        yield {"type": "user", "message": {"role": "user", "content": prompt}}

    t0 = time.monotonic()
    agen = query(prompt=_prompt_stream(), options=options)
    try:
        async for message in agen:
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
                        await _push({"type": "text", "content": block.text})
                    elif isinstance(block, ToolUseBlock):
                        entry: dict[str, Any] = {
                            "name": block.name,
                            "input": block.input,
                            "result": None,
                        }
                        idx = len(tool_calls)
                        tool_calls.append(entry)
                        pending_tools[block.id] = idx
                        await _push(
                            {"type": "tool_start", "name": block.name, "input": block.input}
                        )
                    elif isinstance(block, ToolResultBlock):
                        idx = pending_tools.get(block.tool_use_id)
                        result_text: str | None = None
                        if idx is not None:
                            content = block.content
                            if isinstance(content, str):
                                result_text = content
                            elif isinstance(content, list):
                                texts = [
                                    item.get("text", "")
                                    for item in content
                                    if isinstance(item, dict) and item.get("type") == "text"
                                ]
                                result_text = "\n".join(texts) if texts else str(content)
                            else:
                                result_text = str(content)
                            tool_calls[idx]["result"] = result_text
                        await _push(
                            {
                                "type": "tool_result",
                                "name": tool_calls[idx]["name"] if idx is not None else None,
                                "result": result_text,
                            }
                        )

            elif isinstance(message, ResultMessage):
                cost_usd = getattr(message, "cost_usd", None)
                num_turns = getattr(message, "num_turns", None)
                await _push({"type": "result", "cost_usd": cost_usd, "num_turns": num_turns})

            elif isinstance(message, SystemMessage):
                logger.debug("SystemMessage: %s", message)

        duration_sec = time.monotonic() - t0
        logger.info(
            "Dispatch completed: %d text blocks, %d tool calls, %.1fs",
            len(text_parts),
            len(tool_calls),
            duration_sec,
        )
        await _push({"type": "done"})
        return {
            "status": "completed",
            "text_output": "".join(text_parts),
            "tool_calls": tool_calls,
            "error": None,
            "duration_sec": round(duration_sec, 2),
            "cost_usd": cost_usd,
            "num_turns": num_turns,
        }

    except asyncio.CancelledError:
        # Close the SDK async generator so the CLI subprocess exits via its own
        # stdin-close path. Measured end-to-end cancel latency: ~0.6s; a few
        # seconds if a tool call is mid-flight and needs to unwind.
        try:
            await agen.aclose()
        except Exception:
            logger.debug("agen.aclose() raised during cancellation", exc_info=True)
        raise
    except Exception as exc:
        duration_sec = time.monotonic() - t0
        stderr_output = "\n".join(stderr_lines) if stderr_lines else None
        logger.error(
            "Dispatch failed after %.1fs: %s",
            duration_sec,
            exc,
            exc_info=True,
        )
        await _push({"type": "error", "message": str(exc)})
        return {
            "status": "error",
            "text_output": "".join(text_parts),
            "tool_calls": tool_calls,
            "error": str(exc),
            "stderr": stderr_output,
            "duration_sec": round(duration_sec, 2),
            "cost_usd": cost_usd,
            "num_turns": num_turns,
        }
