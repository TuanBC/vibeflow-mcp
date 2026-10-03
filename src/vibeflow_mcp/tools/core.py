"""Core tools: auth, account, workspace (projects/tasks/kanban/search), models, raw API."""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Literal

import httpx

from .. import config
from ..app import client, store, tool
from ..auth import browser_login
from ..errors import VibeFlowError

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


# ---------------------------------------------------------------------- docs

_docs_index: list[dict[str, Any]] | None = None


async def _public_get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": config.USER_AGENT}) as http:
        resp = await http.get(f"{config.WEB_URL}{path}")
    if resp.status_code >= 400:
        raise VibeFlowError(f"GET {path} -> HTTP {resp.status_code}", code="not_found" if resp.status_code == 404 else "http_error")
    return resp


@tool("core", read_only=True)
async def vibeflow_search_docs(query: str, limit: int = 8) -> Any:
    """Search the VibeFlow user docs (features, agents, skills, workflows,
    tutorials, troubleshooting). Read a hit with vibeflow_read_docs(path)."""
    global _docs_index
    if _docs_index is None:
        _docs_index = (await _public_get("/docs/docs-search.json")).json()
    words = [w for w in query.lower().split() if w]
    scored = []
    for page in _docs_index:
        title, text, path = (page.get("title") or "").lower(), (page.get("text") or "").lower(), page.get("path") or ""
        score = sum(3 * (w in title) + (w in text) + (w in path.lower()) for w in words)
        if score:
            scored.append((score, page))
    scored.sort(key=lambda x: -x[0])
    return [{"title": p.get("title"), "path": p.get("path"), "sections": (p.get("text") or "")[:200]}
            for _, p in scored[:limit]]


@tool("core", read_only=True)
async def vibeflow_read_docs(path: str, max_chars: int = 12000) -> Any:
    """Read a VibeFlow docs page as plain text (path like '/docs/features/restore-points')."""
    if not path.startswith("/docs"):
        path = "/docs/" + path.lstrip("/")
    html = (await _public_get(path)).text
    main = re.search(r"<main[^>]*>(.*?)</main>", html, re.S | re.I)
    body = main.group(1) if main else html
    body = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r"</(p|h[1-6]|li|tr|div|pre)>", "\n", body, flags=re.I)
    text = re.sub(r"<[^>]+>", "", body)
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", unescape(text))).strip()
    return text[:max_chars] + ("\n… (truncated)" if len(text) > max_chars else "")


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
