"""Shared MCP app: server instance, toolset-gated tool decorator, output
shaping, error handling and VibeFlow context resolvers used by all tools."""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import config
from .auth import TokenStore
from .client import VibeFlowClient
from .errors import ConfirmationRequired, VibeFlowError

logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = FastMCP(
    "vibeflow",
    instructions=(
        "Tools for the VibeFlow AI software-development platform (vibeflow.fptconsulting.co.jp). "
        "Start with vibeflow_auth_status; if not authenticated call vibeflow_login (opens a browser "
        "for Microsoft SSO). Hierarchy: project -> task -> conversation (run) -> messages. Agent work "
        "runs in a per-project sandbox session; most chat/code tools need it running "
        "(vibeflow_start_session). For one-shot questions prefer vibeflow_ask. Tools marked "
        "destructive require confirm=true; ask the user before passing it."
    ),
)

store = TokenStore()
client = VibeFlowClient(store)

REGISTERED: dict[str, str] = {}  # tool name -> toolset


def render(data: Any) -> str:
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False, default=str)
    limit = config.MAX_OUTPUT_CHARS
    if len(text) > limit:
        text = text[:limit] + f"\n... [truncated {len(text) - limit} chars]"
    return text


def tool(toolset: str, *, read_only: bool = False, destructive: bool = False,
         idempotent: bool = False) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Register an async function as an MCP tool if its toolset is enabled.
    The function returns plain data; errors become structured payloads."""

    def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                return render(await fn(*args, **kwargs))
            except VibeFlowError as exc:
                return render(exc.to_payload())

        if toolset in config.TOOLSETS:
            mcp.tool(annotations=ToolAnnotations(
                readOnlyHint=read_only,
                destructiveHint=destructive,
                idempotentHint=idempotent or read_only,
                openWorldHint=True,
            ))(wrapper)
            REGISTERED[fn.__name__] = toolset
        return wrapper

    return deco


def require_confirm(confirm: bool, action: str) -> None:
    if not confirm:
        raise ConfirmationRequired(
            f"'{action}' is destructive or publishes changes.",
            hint="Confirm with the user, then call again with confirm=true.",
        )


# ------------------------------------------------------------ context resolvers

_task_cache: dict[str, str] = {}


async def default_task(project_id: str) -> str:
    """The project's default task (where Console conversations live)."""
    if project_id not in _task_cache:
        data = await client.get(f"/api/v1/projects/{project_id}/my-recent-task")
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise VibeFlowError(f"Project {project_id} has no task yet.", code="not_found",
                                hint="Create a task (kanban) in the project first.")
        _task_cache[project_id] = task_id
    return _task_cache[project_id]


async def running_session(project_id: str) -> str:
    """Session id of the project's sandbox; error with a hint if not running."""
    st = await client.get("/api/v1/sessions/status", project_id=project_id)
    if st.get("status") != "running" or not st.get("session_id"):
        raise VibeFlowError(f"Sandbox for project {project_id} is '{st.get('status')}'.", code="no_session",
                            hint="Call vibeflow_start_session(project_id) and wait for it to be running.")
    return st["session_id"]


async def run_info(run_id: str) -> dict[str, Any]:
    return await client.get(f"/api/v1/runs/{run_id}")


async def run_session(run_id: str) -> str:
    sid = (await run_info(run_id)).get("session_id")
    if not sid:
        raise VibeFlowError(f"Conversation {run_id} has no sandbox session.", code="no_session")
    return sid
