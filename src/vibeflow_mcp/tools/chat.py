"""Conversations ("runs"): models, start/send/wait, history."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from .. import render
from ..app import client, tool
from ..errors import ApiError, VibeFlowError

ProviderScope = Literal["auto", "platform", "personal", "project"]
TERMINAL = {"idle", "completed", "succeeded", "failed", "aborted", "cancelled", "error", "closed", "stopped"}


# -------------------------------------------------------------------- models

def _full_id(m: dict[str, Any]) -> str:
    provider, mid = m.get("provider"), m["id"]
    return f"{provider}/{mid}" if provider and not mid.startswith(f"{provider}/") else mid


def _norm(items: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
    return [{"model": _full_id(m), "scope": scope, "name": m.get("name"),
             "input": (m.get("modalities") or {}).get("input")} for m in items]


async def platform_models() -> list[dict[str, Any]]:
    return (await client.get("/api/v1/users/me/platform-models")).get("models", [])


async def resolve_model(model: str, scope: str) -> tuple[str, str | None]:
    """Mirror the SPA model picker: the agent expects '<provider>/<id>' plus a
    provider_scope telling the backend whose credentials to use. Bare platform
    ids (e.g. 'gemini-3.7-flash') resolve to 'google-starter/gemini-3.7-flash'."""
    if scope not in ("auto", "platform"):
        return model, scope
    for m in await platform_models():
        if model in (_full_id(m), m["id"]):
            return _full_id(m), "platform"
    if scope == "platform":
        raise VibeFlowError(f"'{model}' is not a platform model.", code="bad_request",
                            hint="See vibeflow_list_models for valid ids.")
    return model, None  # let the backend use the project's own providers


@tool("core", read_only=True)
async def vibeflow_list_models(project_id: str | None = None) -> Any:
    """LLM models usable in conversations as {model, scope, name}. Without
    project_id: shared platform models (always available, billed to your
    quota). With project_id: also project/personal providers (needs a running sandbox)."""
    if not project_id:
        return _norm(await platform_models(), "platform")
    data = await client.get("/api/v1/sessions/models", project_id=project_id)
    if any(k in data for k in ("project_models", "personal_models", "platform_models")):
        return (_norm(data.get("project_models") or [], "project")
                + _norm(data.get("personal_models") or [], "personal")
                + _norm(data.get("platform_models") or [], "platform"))
    return _norm(data.get("models") or [], "project")


# ------------------------------------------------------------------- history

@tool("core", read_only=True)
async def vibeflow_list_conversations(limit: int = 20, task_id: str | None = None) -> Any:
    """Conversations (agent runs): the user's recent ones, or those in a task."""
    if task_id:
        return await client.get("/api/v1/runs", task_id=task_id)
    return await client.get("/api/v1/runs/mine", limit=limit)


@tool("core", read_only=True)
async def vibeflow_get_conversation(run_id: str) -> Any:
    """A conversation's status, model, error, steps and session info."""
    return await client.get(f"/api/v1/runs/{run_id}")


@tool("core", read_only=True)
async def vibeflow_get_transcript(run_id: str) -> Any:
    """A conversation as a Markdown transcript (server-generated; may lag the
    latest turn - use vibeflow_get_messages for the live state)."""
    return await client.get(f"/api/v1/runs/{run_id}/transcript.md")


@tool("core", read_only=True)
async def vibeflow_get_messages(run_id: str, last_n: int = 20, raw: bool = False) -> Any:
    """A conversation's messages rendered as text (text + tool calls). raw=true
    returns the structured JSON (parts, tokens, metadata)."""
    data = await client.get(f"/api/v1/runs/{run_id}/messages")
    msgs = data.get("messages", []) if isinstance(data, dict) else data
    return msgs[-last_n:] if raw else render.messages(msgs, last_n)


# ---------------------------------------------------------------------- chat

def chat_body(prompt: str, model: str, scope: str | None, mode: str) -> dict[str, Any]:
    body: dict[str, Any] = {"prompt": prompt, "model": model, "attached_files": []}
    if scope:
        body["provider_scope"] = scope
    if mode == "plan":
        body["mode"] = "plan"
    return body


@tool("core")
async def vibeflow_start_conversation(
    task_id: str, prompt: str, model: str,
    mode: Literal["build", "plan"] = "build", provider_scope: ProviderScope = "auto",
) -> Any:
    """Start a new agent conversation in a task. `model` is '<provider>/<id>' or
    a bare platform model id (vibeflow_list_models). The sandbox must be
    running. Returns run_id; follow with vibeflow_wait_for_reply."""
    model, scope = await resolve_model(model, provider_scope)
    body = {"task_id": task_id, "node_type": "console", "source": "console",
            **chat_body(prompt, model, scope, mode)}
    return await client.post("/api/v1/runs", body)


@tool("core")
async def vibeflow_send_message(
    run_id: str, prompt: str, model: str,
    mode: Literal["build", "plan"] = "build", provider_scope: ProviderScope = "auto",
) -> Any:
    """Send a follow-up message to an existing conversation (same model rules
    as vibeflow_start_conversation)."""
    model, scope = await resolve_model(model, provider_scope)
    return await client.post(f"/api/v1/runs/{run_id}/messages", chat_body(prompt, model, scope, mode))


async def wait_idle(run_id: str, timeout: int, poll: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    run: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            run = await client.get(f"/api/v1/runs/{run_id}")
        except ApiError as exc:
            if exc.code != "server_error":
                raise
        if (run.get("status") or "").lower() in TERMINAL:
            break
        await asyncio.sleep(poll)
    return run


@tool("core", read_only=True)
async def vibeflow_wait_for_reply(run_id: str, timeout_seconds: int = 300, poll_seconds: int = 5,
                                  last_n_messages: int = 4) -> Any:
    """Wait until the agent stops working (or timeout), then return status,
    error (if any) and the last messages as text."""
    run = await wait_idle(run_id, timeout_seconds, poll_seconds)
    status = (run.get("status") or "").lower()
    data = await client.get(f"/api/v1/runs/{run_id}/messages")
    msgs = data.get("messages", []) if isinstance(data, dict) else data
    return {"status": status, "timed_out": status not in TERMINAL, "error": run.get("error_message"),
            "messages": render.messages(msgs, last_n_messages)}


@tool("core", idempotent=True)
async def vibeflow_rename_conversation(run_id: str, title: str) -> Any:
    """Rename a conversation."""
    run = await client.patch(f"/api/v1/runs/{run_id}/title", {"title": title})
    return {"id": run.get("id"), "title": run.get("session_title", title)}
