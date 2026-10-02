"""Sandbox session lifecycle (one Kubernetes pod per user+project)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..app import client, require_confirm, tool
from ..errors import VibeFlowError

READY = "running"
FAILED = {"error", "failed"}


async def wait_running(project_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = await client.get("/api/v1/sessions/status", project_id=project_id)
        if status.get("status") == READY:
            return status
        if status.get("status") in FAILED:
            raise VibeFlowError(f"Sandbox failed: {status.get('error')}", code="session_failed")
        await asyncio.sleep(5)
    raise VibeFlowError(f"Sandbox not running after {timeout}s (last status: {status.get('status')}).",
                        code="timeout", hint="Check vibeflow_session_status again shortly.")


async def ensure_session(project_id: str, timeout: int = 300) -> str:
    """Return the running session id, starting the sandbox if needed."""
    status = await client.get("/api/v1/sessions/status", project_id=project_id)
    if status.get("status") != READY:
        await client.post("/api/v1/sessions/start", {"project_id": project_id, "git_setup_mode": "none"})
        status = await wait_running(project_id, timeout)
    return status["session_id"]


@tool("core", read_only=True)
async def vibeflow_session_status(project_id: str) -> Any:
    """Sandbox status for a project (running/stopped/provisioning, resumable, idle limits)."""
    return await client.get("/api/v1/sessions/status", project_id=project_id)


@tool("core", read_only=True)
async def vibeflow_list_my_sessions() -> Any:
    """The user's sandbox sessions across projects."""
    return await client.get("/api/v1/sessions/mine")


@tool("core")
async def vibeflow_start_session(project_id: str, wait: bool = True, timeout_seconds: int = 300) -> Any:
    """Start (or resume) the project's sandbox. With wait=true (default) blocks
    until it is running (typically 30-60 s) and returns the session status."""
    started = await client.post("/api/v1/sessions/start", {"project_id": project_id, "git_setup_mode": "none"})
    if not wait:
        return started
    return await wait_running(project_id, timeout_seconds)


@tool("core", destructive=True)
async def vibeflow_stop_session(session_id: str, confirm: bool = False) -> Any:
    """Stop a sandbox. The platform saves the workspace first and it can be
    resumed, but running agents are interrupted. Requires confirm=true."""
    require_confirm(confirm, "stop sandbox session")
    return await client.post(f"/api/v1/sessions/{session_id}/stop")
