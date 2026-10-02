"""Core tools: auth, account, workspace (projects/tasks/kanban/search), models, raw API."""

from __future__ import annotations

from typing import Any, Literal

from ..app import client, store, tool
from ..auth import browser_login

# ---------------------------------------------------------------------- auth


@tool("core")
async def vibeflow_login(timeout_seconds: int = 300) -> Any:
    """Open a browser window for Microsoft SSO login to VibeFlow and capture the
    session token. The user completes sign-in; returns once the token is
    captured. Reuses a persistent browser profile, so repeat logins are quick."""
    return await browser_login(store, timeout=timeout_seconds)


@tool("core")
async def vibeflow_set_token(access_token: str, refresh_token: str = "") -> Any:
    """Manually import a VibeFlow token (from the browser's
    localStorage['vibeflow-auth'].state.tokens) instead of vibeflow_login."""
    store.save({"access_token": access_token, "refresh_token": refresh_token})
    return store.status()


@tool("core", read_only=True)
async def vibeflow_auth_status() -> Any:
    """Whether a valid VibeFlow token is stored, whose it is, when it expires,
    and which storage backend (keyring/file) holds it."""
    return store.status()


@tool("core", destructive=True)
async def vibeflow_logout() -> Any:
    """Revoke the VibeFlow session server-side and delete the stored token."""
    try:
        await client.post("/api/v1/auth/logout")
    except Exception:
        pass
    store.clear()
    return "Logged out."


@tool("core", read_only=True)
async def vibeflow_whoami() -> Any:
    """Current user's profile, role and permissions."""
    return await client.get("/api/v1/auth/me")


@tool("core", read_only=True)
async def vibeflow_my_stats() -> Any:
    """Current user's dashboard stats: active sandboxes, open tasks, monthly tokens/cost/lines."""
    return await client.get("/api/v1/users/me/stats")


# ----------------------------------------------------------------- workspace


@tool("core", read_only=True)
async def vibeflow_list_projects(page: int = 1, limit: int = 20, search: str | None = None) -> Any:
    """List projects the user can access."""
    return await client.get("/api/v1/projects", page=page, limit=limit, search=search)


@tool("core", read_only=True)
async def vibeflow_get_project(project_id: str) -> Any:
    """A project's details and settings."""
    return await client.get(f"/api/v1/projects/{project_id}")


@tool("core", read_only=True)
async def vibeflow_get_recent_task(project_id: str | None = None) -> Any:
    """The user's most recent task (globally, or in a project) - the default
    task Console conversations are created in."""
    if project_id:
        return await client.get(f"/api/v1/projects/{project_id}/my-recent-task")
    return await client.get("/api/v1/tasks/recent")


@tool("core", read_only=True)
async def vibeflow_list_tasks(project_id: str, mine: bool = True) -> Any:
    """List tasks in a project."""
    return await client.get("/api/v1/tasks", project_id=project_id, mine=str(mine).lower())


@tool("core", read_only=True)
async def vibeflow_get_task(task_id: str) -> Any:
    """A task (workflow node graph, status, metadata)."""
    return await client.get(f"/api/v1/tasks/{task_id}")


@tool("core", read_only=True)
async def vibeflow_get_kanban(project_id: str) -> Any:
    """Kanban board(s), columns and cards for a project."""
    return await client.get("/api/v1/kanban/boards", project_id=project_id)


@tool("core", read_only=True)
async def vibeflow_search(query: str) -> Any:
    """Global search across projects, tasks and conversations."""
    return await client.get("/api/v1/search", q=query)


# ---------------------------------------------------------------------- meta


@tool("core", read_only=True)
async def vibeflow_get_quota() -> Any:
    """The user's monthly platform LLM spend quota and usage."""
    return await client.get("/api/v1/users/me/platform-quota")


@tool("core")
async def vibeflow_api(
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
) -> Any:
    """Escape hatch: call any VibeFlow API path (e.g. '/api/v1/projects/{id}/members'
    or '/sessions/{sid}/vibeflow/snapshot') with the stored token. Prefer the
    dedicated tools; never use this to bypass a confirm=true requirement."""
    if not path.startswith("/"):
        path = "/" + path
    return await client.request(method, path, params=params, json=body)
