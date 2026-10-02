"""VibeFlow MCP server (POC).

Tool groups:
  auth      - SSO login (browser capture), token status, manual token import
  workspace - projects, tasks, kanban, search
  chat      - conversations ("runs"): create, send message, wait, transcript
  sandbox   - per-project sandbox session lifecycle
  meta      - models, quota, raw API escape hatch
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .auth import TokenStore, browser_login
from .client import ApiError, VibeFlowClient

MAX_OUTPUT_CHARS = 60_000

logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = FastMCP(
    "vibeflow",
    instructions=(
        "Tools for the VibeFlow AI software-development platform (vibeflow.fptconsulting.co.jp). "
        "Call vibeflow_auth_status first; if not authenticated, call vibeflow_login (opens a "
        "browser for Microsoft SSO). Hierarchy: project -> task -> conversation (run) -> messages. "
        "Every project has a default task (see vibeflow_get_recent_task). Agent work runs in a "
        "per-project sandbox session."
    ),
)

store = TokenStore()
client = VibeFlowClient(store)


def _out(data: Any) -> str:
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + f"\n... [truncated {len(text) - MAX_OUTPUT_CHARS} chars]"
    return text


async def _call(coro) -> str:
    try:
        return _out(await coro)
    except ApiError as exc:
        return _out({"error": str(exc), "status": exc.status, "detail": exc.detail})


# --------------------------------------------------------------------------- auth

@mcp.tool()
async def vibeflow_login(timeout_seconds: int = 300) -> str:
    """Open a browser window for Microsoft SSO login to VibeFlow and capture the
    session token. The user completes the sign-in; the tool returns when the
    token is captured (or on timeout). Reuses a persistent browser profile, so
    repeat logins are usually instant."""
    result = await browser_login(store, timeout=timeout_seconds)
    return _out(result)


@mcp.tool()
async def vibeflow_set_token(access_token: str, refresh_token: str = "") -> str:
    """Manually import a VibeFlow token (e.g. copied from the browser's
    localStorage['vibeflow-auth'].state.tokens) instead of using vibeflow_login."""
    store.save({"access_token": access_token, "refresh_token": refresh_token})
    return _out(store.status())


@mcp.tool()
async def vibeflow_auth_status() -> str:
    """Show whether a valid VibeFlow token is stored, who it belongs to, and when it expires."""
    return _out(store.status())


@mcp.tool()
async def vibeflow_logout() -> str:
    """Revoke the VibeFlow session server-side and delete the stored token."""
    try:
        await client.post("/api/v1/auth/logout")
    except Exception:
        pass
    store.clear()
    return "Logged out."


@mcp.tool()
async def vibeflow_whoami() -> str:
    """Return the current user's profile, role and permissions."""
    return await _call(client.get("/api/v1/auth/me"))


# ---------------------------------------------------------------------- workspace

@mcp.tool()
async def vibeflow_list_projects(page: int = 1, limit: int = 20, search: str | None = None) -> str:
    """List projects the user can access."""
    return await _call(client.get("/api/v1/projects", page=page, limit=limit, search=search))


@mcp.tool()
async def vibeflow_get_project(project_id: str) -> str:
    """Get a project's details and settings."""
    return await _call(client.get(f"/api/v1/projects/{project_id}"))


@mcp.tool()
async def vibeflow_get_recent_task(project_id: str | None = None) -> str:
    """Get the user's most recent task (globally, or within a project). Useful to
    find the default task to start conversations in."""
    if project_id:
        return await _call(client.get(f"/api/v1/projects/{project_id}/my-recent-task"))
    return await _call(client.get("/api/v1/tasks/recent"))


@mcp.tool()
async def vibeflow_list_tasks(project_id: str, mine: bool = True) -> str:
    """List tasks in a project."""
    return await _call(client.get("/api/v1/tasks", project_id=project_id, mine=str(mine).lower()))


@mcp.tool()
async def vibeflow_get_task(task_id: str) -> str:
    """Get a task (workflow node graph, status, metadata)."""
    return await _call(client.get(f"/api/v1/tasks/{task_id}"))


@mcp.tool()
async def vibeflow_get_kanban(project_id: str) -> str:
    """Get the kanban board(s), columns and cards for a project."""
    return await _call(client.get("/api/v1/kanban/boards", project_id=project_id))


@mcp.tool()
async def vibeflow_search(query: str) -> str:
    """Global search across projects, tasks and conversations."""
    return await _call(client.get("/api/v1/search", q=query))


# --------------------------------------------------------------------------- chat

@mcp.tool()
async def vibeflow_list_conversations(limit: int = 20, task_id: str | None = None) -> str:
    """List conversations (agent runs): the user's recent ones, or those in a task."""
    if task_id:
        return await _call(client.get("/api/v1/runs", task_id=task_id))
    return await _call(client.get("/api/v1/runs/mine", limit=limit))


@mcp.tool()
async def vibeflow_get_conversation(run_id: str) -> str:
    """Get a conversation's status, model, cost and session info."""
    return await _call(client.get(f"/api/v1/runs/{run_id}"))


@mcp.tool()
async def vibeflow_get_transcript(run_id: str) -> str:
    """Get a conversation as a readable Markdown transcript."""
    return await _call(client.get(f"/api/v1/runs/{run_id}/transcript.md"))


@mcp.tool()
async def vibeflow_get_messages(run_id: str) -> str:
    """Get the raw structured message list (parts, tool calls) of a conversation."""
    return await _call(client.get(f"/api/v1/runs/{run_id}/messages"))


ProviderScope = Literal["auto", "platform", "personal", "project"]


async def _resolve_model(model: str, scope: str) -> tuple[str, str | None]:
    """Mirror the SPA's model picker: the agent expects '<provider>/<id>' plus a
    provider_scope telling the backend whose credentials to use. Platform models
    (the shared, quota-billed ones) are looked up so a bare id like
    'gemini-3.8-flash' resolves to 'google-starter/gemini-3.8-flash'."""
    if scope not in ("auto", "platform"):
        return model, scope
    platform = (await client.get("/api/v1/users/me/platform-models")).get("models", [])
    for m in platform:
        full = f"{m['provider']}/{m['id']}" if m.get("provider") else m["id"]
        if model in (full, m["id"]):
            return full, "platform"
    if scope == "platform":
        raise ValueError(f"'{model}' is not a platform model; see vibeflow_list_models")
    return model, None  # let the backend use the project's own providers


def _chat_body(prompt: str, model: str, scope: str | None, mode: str) -> dict[str, Any]:
    body: dict[str, Any] = {"prompt": prompt, "model": model, "attached_files": []}
    if scope:
        body["provider_scope"] = scope
    if mode == "plan":
        body["mode"] = "plan"
    return body


@mcp.tool()
async def vibeflow_start_conversation(
    task_id: str,
    prompt: str,
    model: str,
    mode: Literal["build", "plan"] = "build",
    provider_scope: ProviderScope = "auto",
    agent_type: str | None = None,
) -> str:
    """Start a new agent conversation in a task with an initial prompt.
    `model` is '<provider>/<id>' or a bare platform model id (see
    vibeflow_list_models). provider_scope 'auto' picks 'platform' for shared
    platform models. Returns run_id; follow with vibeflow_wait_for_reply."""
    try:
        model, scope = await _resolve_model(model, provider_scope)
    except ValueError as exc:
        return _out({"error": str(exc)})
    body = {"task_id": task_id, "node_type": "console", "source": "console",
            **_chat_body(prompt, model, scope, mode if not agent_type else "build")}
    if agent_type:
        body["agent_type"] = agent_type
    return await _call(client.post("/api/v1/runs", body))


@mcp.tool()
async def vibeflow_send_message(
    run_id: str, prompt: str, model: str,
    mode: Literal["build", "plan"] = "build", provider_scope: ProviderScope = "auto",
) -> str:
    """Send a follow-up message to an existing conversation (same model rules
    as vibeflow_start_conversation)."""
    try:
        model, scope = await _resolve_model(model, provider_scope)
    except ValueError as exc:
        return _out({"error": str(exc)})
    return await _call(client.post(f"/api/v1/runs/{run_id}/messages",
                                   _chat_body(prompt, model, scope, mode)))


_TERMINAL = {"idle", "completed", "succeeded", "failed", "aborted", "cancelled", "error", "closed"}


def _render_message(msg: dict[str, Any]) -> str:
    """Flatten an OpenCode-style message (text / reasoning / tool parts) to text."""
    lines = []
    for p in msg.get("parts") or []:
        kind = p.get("type")
        if kind == "text" and p.get("text"):
            lines.append(p["text"].strip())
        elif kind == "tool":
            state = p.get("tool_state") or {}
            status = state.get("status", "") if isinstance(state, dict) else ""
            title = state.get("title", "") if isinstance(state, dict) else ""
            lines.append(f"[tool {p.get('tool_name')} {status}] {title}".rstrip())
    meta = msg.get("metadata") or {}
    head = f"### {msg.get('role')}" + (f" ({msg.get('model')}, ${meta.get('cost', 0):.4f})" if msg.get("role") == "assistant" else "")
    return head + "\n" + "\n".join(lines)


@mcp.tool()
async def vibeflow_wait_for_reply(run_id: str, timeout_seconds: int = 300, poll_seconds: int = 5,
                                  last_n_messages: int = 4) -> str:
    """Poll a conversation until the agent stops working (or timeout), then
    return its status, error (if any) and the last messages rendered as text."""
    deadline = time.monotonic() + timeout_seconds
    run: dict[str, Any] = {}
    status = None
    while time.monotonic() < deadline:
        run = await client.get(f"/api/v1/runs/{run_id}")
        status = (run.get("status") or "").lower()
        if status in _TERMINAL:
            break
        await asyncio.sleep(poll_seconds)
    data = await client.get(f"/api/v1/runs/{run_id}/messages")
    msgs = data.get("messages", []) if isinstance(data, dict) else data
    rendered = "\n\n".join(_render_message(m) for m in msgs[-last_n_messages:])
    return _out({"status": status, "timed_out": status not in _TERMINAL,
                 "error": run.get("error_message"), "messages": rendered})


@mcp.tool()
async def vibeflow_rename_conversation(run_id: str, title: str) -> str:
    """Rename a conversation."""
    return await _call(client.patch(f"/api/v1/runs/{run_id}/title", {"title": title}))


# ------------------------------------------------------------------------ sandbox

@mcp.tool()
async def vibeflow_session_status(project_id: str) -> str:
    """Get the sandbox session status for a project (running/stopped, pod info)."""
    return await _call(client.get("/api/v1/sessions/status", project_id=project_id))


@mcp.tool()
async def vibeflow_list_my_sessions() -> str:
    """List the user's sandbox sessions across projects."""
    return await _call(client.get("/api/v1/sessions/mine"))


@mcp.tool()
async def vibeflow_start_session(project_id: str) -> str:
    """Start (or resume) the sandbox session for a project."""
    return await _call(client.post("/api/v1/sessions/start",
                                   {"project_id": project_id, "git_setup_mode": "none"}))


@mcp.tool()
async def vibeflow_stop_session(session_id: str) -> str:
    """Stop a sandbox session (workspace is saved first by the platform)."""
    return await _call(client.post(f"/api/v1/sessions/{session_id}/stop"))


# --------------------------------------------------------------------------- meta

@mcp.tool()
async def vibeflow_list_models(project_id: str | None = None) -> str:
    """List LLM models usable in conversations, as {model, scope, name}. Without
    project_id: shared platform models (always available). With project_id: also
    project/personal providers (requires a running sandbox session)."""
    def norm(items: list[dict], scope: str) -> list[dict]:
        return [{"model": f"{m['provider']}/{m['id']}" if m.get("provider") and not m["id"].startswith(f"{m['provider']}/") else m["id"],
                 "scope": scope, "name": m.get("name"), "input": (m.get("modalities") or {}).get("input")}
                for m in items]
    try:
        if not project_id:
            data = await client.get("/api/v1/users/me/platform-models")
            return _out(norm(data.get("models", []), "platform"))
        data = await client.get("/api/v1/sessions/models", project_id=project_id)
    except ApiError as exc:
        return _out({"error": str(exc), "detail": exc.detail})
    if any(k in data for k in ("project_models", "personal_models", "platform_models")):
        return _out(norm(data.get("project_models") or [], "project")
                    + norm(data.get("personal_models") or [], "personal")
                    + norm(data.get("platform_models") or [], "platform"))
    return _out(norm(data.get("models") or [], "project"))


@mcp.tool()
async def vibeflow_get_quota() -> str:
    """Show the user's monthly platform LLM spend quota and usage."""
    return await _call(client.get("/api/v1/users/me/platform-quota"))


@mcp.tool()
async def vibeflow_api(
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
) -> str:
    """Escape hatch: call any VibeFlow API path (e.g. '/api/v1/projects/{id}/members'
    or '/sessions/{sid}/vibeflow/snapshot') with the stored token. Prefer the
    dedicated tools when they exist."""
    if not path.startswith("/"):
        path = "/" + path
    return await _call(client.request(method, path, params=params, json=body))
