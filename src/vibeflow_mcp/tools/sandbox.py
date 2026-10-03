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


async def start_body(project_id: str, git_token: str | None = None) -> dict[str, Any]:
    """Mirror the SPA: local projects 'init' a workspace repo, git projects
    'clone' their remote (optionally with a one-off token)."""
    project = await client.get(f"/api/v1/projects/{project_id}")
    local = project.get("project_type") == "local"
    body: dict[str, Any] = {"project_id": project_id, "git_setup_mode": "init" if local else "clone"}
    if not local:
        body.update(git_url=project.get("git_url"), git_provider=project.get("git_provider"))
        if git_token:
            body["git_token"] = git_token
    return body


async def ensure_session(project_id: str, timeout: int = 300) -> str:
    """Return the running session id, starting the sandbox if needed."""
    status = await client.get("/api/v1/sessions/status", project_id=project_id)
    if status.get("status") != READY:
        await client.post("/api/v1/sessions/start", await start_body(project_id))
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
async def vibeflow_start_session(project_id: str, wait: bool = True, timeout_seconds: int = 300,
                                 git_token: str | None = None) -> Any:
    """Start (or resume) the project's sandbox. Git projects clone their remote
    (git_token: optional one-off access token if no stored git credential).
    With wait=true (default) blocks until running (typically 30-60 s)."""
    started = await client.post("/api/v1/sessions/start", await start_body(project_id, git_token))
    if not wait:
        return started
    status = await wait_running(project_id, timeout_seconds)
    if started.get("clone_warning") or status.get("clone_warning"):
        status["clone_warning"] = started.get("clone_warning") or status.get("clone_warning")
    return status


@tool("core")
async def vibeflow_save_session(session_id: str) -> Any:
    """Snapshot the sandbox workspace now (it is also saved on stop)."""
    return await client.post(f"/api/v1/sessions/{session_id}/save")


@tool("core", destructive=True)
async def vibeflow_stop_idle_sessions(min_idle_minutes: int = 30, confirm: bool = False) -> Any:
    """Stop all of your sandboxes idle for at least min_idle_minutes (saves
    compute; workspaces are saved and resumable). Requires confirm=true."""
    require_confirm(confirm, "stop idle sandboxes")
    return await client.post("/api/v1/sessions/mine/stop-idle", min_idle_seconds=min_idle_minutes * 60)


@tool("core")
async def vibeflow_reset_session_baseline(session_id: str) -> Any:
    """Mark the current workspace as the new baseline for session-scoped
    changes (vibeflow_get_changes(scope='session') starts empty again)."""
    return await client.post(f"/api/v1/sessions/{session_id}/workspace-baseline")


@tool("core")
async def vibeflow_reload_agent_config(task_id: str, session_id: str | None = None) -> Any:
    """Reload agents, skills and MCP config in the running sandbox after they
    were edited (e.g. files under .opencode/ in the workspace)."""
    return await client.post("/api/v1/changes/session/reload", task_id=task_id, session_id=session_id)


@tool("core", destructive=True)
async def vibeflow_stop_session(session_id: str, confirm: bool = False) -> Any:
    """Stop a sandbox. The platform saves the workspace first and it can be
    resumed, but running agents are interrupted. Requires confirm=true."""
    require_confirm(confirm, "stop sandbox session")
    return await client.post(f"/api/v1/sessions/{session_id}/stop")
