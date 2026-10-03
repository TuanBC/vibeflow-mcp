"""Conversations ("runs"): models, pickers (agents/skills/workflows), chat,
streaming wait, human-in-the-loop prompts, conversation management."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any, Literal

from .. import config, render
from ..app import Context, client, default_task, require_confirm, run_info, run_session, running_session, tool
from ..errors import ApiError, VibeFlowError
from .sandbox import ensure_session

ProviderScope = Literal["auto", "platform", "personal", "project"]
Mode = Literal["build", "plan"]
TERMINAL = {"idle", "completed", "succeeded", "failed", "aborted", "cancelled", "error", "closed", "stopped"}
FAILED = {"failed", "aborted", "cancelled", "error"}
STEP_OPEN = {"pending", "queued", "running", "retrying", "starting"}
MAX_POLL_ERRORS = 5

# Prompt the SPA sends when forking a conversation (the platform attaches the
# source transcript as conversation.md).
FORK_PROMPT = (
    "[Forked conversation] The attached `conversation.md` is the COMPLETE transcript of a PRIOR "
    "conversation that this one is forked (branched) from. Treat it as YOUR OWN prior context — the "
    "history of what you and the user already discussed, decided, and did. It is NOT a task brief to "
    "execute.\n\nRead the SUMMARY at the top of that file first; drill into the full transcript below "
    "only if you need specifics. Briefly confirm (2-3 lines) the goal, what is already done, and the "
    "current state — then wait for the user to continue. Do NOT repeat work that is already complete."
)


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


async def default_model() -> str:
    if config.DEFAULT_MODEL:
        return config.DEFAULT_MODEL
    ids = [_full_id(m) for m in await platform_models()]
    if not ids:
        raise VibeFlowError("No platform models available.", code="bad_request",
                            hint="Pass model explicitly (see vibeflow_list_models).")
    return next((m for m in ids if "flash" in m.lower()), ids[0])


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


# ------------------------------------------------------------------- pickers

@tool("core", read_only=True)
async def vibeflow_list_agents(project_id: str) -> Any:
    """Specialist agents (the '!' picker): business-analyst, solution-architect,
    backend-dev, frontend-dev, tester, reviewer, security-auditor, ... plus
    project-defined ones. Pass the name as `agent` to vibeflow_ask /
    vibeflow_start_conversation."""
    data = await client.get(f"/api/v1/projects/{project_id}/templates/agents")
    return [{"name": a.get("name"), "description": a.get("description"), "builtin": a.get("id") is None}
            for a in data.get("agents", [])]


@tool("core", read_only=True)
async def vibeflow_list_skills(project_id: str) -> Any:
    """Packaged skills (the '/' picker), e.g. goal, deep-research, speckit-*,
    slide-craft, workflow. Needs a running sandbox. Pass the name as `skill`."""
    sid = await running_session(project_id)
    data = await client.get("/api/v1/changes/skills", task_id=await default_task(project_id), session_id=sid)
    return [{"name": s.get("name"), "description": (s.get("description") or "")[:300],
             "example": (s.get("options") or {}).get("hint")} for s in data]


@tool("core", read_only=True)
async def vibeflow_list_workflows(project_id: str) -> Any:
    """Multi-step workflow templates (the '#' picker): RFP to Demo, Bug Fix,
    Code Review, DB Migration, Feature Dev, Full-Stack, Safe Refactor, ...
    Pass the id as `workflow` to run one."""
    data = await client.get(f"/api/v1/projects/{project_id}/templates/workflows")
    items = data if isinstance(data, list) else data.get("workflows", [])
    return [{"id": w.get("id"), "name": w.get("name"), "description": w.get("description"),
             "hint": w.get("hint"),
             "steps": [n.get("label") or n.get("agentType") for n in (w.get("workflow_json") or {}).get("nodes", [])]}
            for w in items]


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
    return await run_info(run_id)


@tool("core", read_only=True)
async def vibeflow_get_transcript(run_id: str) -> Any:
    """A conversation as a Markdown transcript (server-generated; may lag the
    latest turn - use vibeflow_get_messages for the live state)."""
    return await client.get(f"/api/v1/runs/{run_id}/transcript.md")


async def fetch_messages(run_id: str, subagent: str | None = None) -> list[dict[str, Any]]:
    data = await client.get(f"/api/v1/runs/{run_id}/messages", subagent=subagent)
    return data.get("messages", []) if isinstance(data, dict) else data


@tool("core", read_only=True)
async def vibeflow_get_messages(run_id: str, last_n: int = 20, raw: bool = False,
                                subagent: str | None = None) -> Any:
    """A conversation's messages rendered as text (text + tool calls). raw=true
    returns the structured JSON (parts, tokens, metadata). subagent: a
    subagent session id from vibeflow_list_subagents to read its own thread."""
    msgs = await fetch_messages(run_id, subagent)
    return msgs[-last_n:] if raw else render.messages(msgs, last_n)


@tool("core", read_only=True)
async def vibeflow_list_subagents(run_id: str) -> Any:
    """Subagents the agent delegated to (the 'task' tool): session id,
    description, agent type and status. Read one with
    vibeflow_get_messages(subagent=...)."""
    out = []
    for m in await fetch_messages(run_id):
        for p in m.get("parts") or []:
            state = p.get("tool_state") if isinstance(p.get("tool_state"), dict) else {}
            meta = state.get("metadata") or {}
            sid = meta.get("sessionId") or meta.get("sessionID")
            if p.get("type") == "tool" and p.get("tool_name") == "task" and sid:
                inp = state.get("input") or {}
                out.append({"subagent": sid, "agent": inp.get("subagent_type") or inp.get("agent"),
                            "description": inp.get("description") or state.get("title"),
                            "status": state.get("status")})
    return out


@tool("core")
async def vibeflow_retry_subagent(run_id: str, subagent: str) -> Any:
    """Re-run a failed or stuck subagent of a conversation."""
    sid = await run_session(run_id)
    return await client.post(f"/sessions/{sid}/vibeflow/runs/{run_id}/retry", subagent=subagent)


@tool("core", read_only=True)
async def vibeflow_get_workflow_batches(run_id: str) -> Any:
    """Dynamic-workflow batches a conversation generated (the 'workflow'
    skill builds and runs a graph of agents on the fly): batch id, name and
    node graph."""
    batches = await client.get(f"/api/v1/runs/{run_id}/workflow-batches")
    return [{"batch_id": b.get("batch_id"), "name": b.get("name") or b.get("workflow_name"), "status": b.get("status"),
             "nodes": [{"id": n.get("id"), "agent": (n.get("data") or n).get("agentType"),
                        "label": (n.get("data") or n).get("label")} for n in (b.get("workflow_json") or {}).get("nodes", [])],
             "edges": [(e.get("source"), e.get("target")) for e in (b.get("workflow_json") or {}).get("edges", [])]}
            for b in batches or []]


@tool("core", read_only=True)
async def vibeflow_conversation_usage(run_id: str) -> Any:
    """Cost (main + subagents) and context-window usage of a conversation."""
    cost = await client.get(f"/api/v1/runs/{run_id}/cost-breakdown")
    out: dict[str, Any] = {"cost": cost.get("total"), "subagent_sessions": cost.get("subagent_session_count")}
    with contextlib.suppress(ApiError):
        ctx = await client.get(f"/api/v1/runs/{run_id}/context-usage")
        out["context"] = {"model": ctx.get("model"), "used": ctx.get("estimatedTotal"),
                          "limit": ctx.get("limit"), "breakdown": ctx.get("breakdown")}
    return out


@tool("core", read_only=True)
async def vibeflow_list_artifacts(run_id: str) -> Any:
    """Files the conversation produced (reports, decks, docs) in the workspace."""
    return await client.get(f"/api/v1/runs/{run_id}/artifacts")


# ---------------------------------------------------------------------- chat

async def upload_attachments(session_id: str, paths: list[str]) -> list[str]:
    """Upload local files into the sandbox; returns pod paths for attached_files."""
    if not paths:
        return []
    files = []
    for p in paths:
        path = Path(p).expanduser()
        if not path.is_file():
            raise VibeFlowError(f"Attachment not found: {p}", code="bad_request")
        files.append((path.name, path.read_bytes()))
    data = await client.upload(f"/sessions/{session_id}/vibeflow/file/upload", files)
    pod_paths = data.get("paths") if isinstance(data, dict) else None
    if not isinstance(pod_paths, list) or len(pod_paths) != len(files):
        raise VibeFlowError("Attachment upload returned no paths.", code="server_error")
    return pod_paths


async def build_body(prompt: str, model: str | None, provider_scope: str, mode: str, *,
                     agent: str | None = None, skill: str | None = None, workflow: str | None = None,
                     attached: list[str] | None = None, thinking: str | None = None,
                     yolo: bool = False) -> dict[str, Any]:
    model, scope = await resolve_model(model or await default_model(), provider_scope)
    body: dict[str, Any] = {"prompt": prompt, "model": model, "attached_files": attached or []}
    if scope:
        body["provider_scope"] = scope
    if agent:
        body["agent_type"] = agent
    if skill:
        body["skill"] = skill
    if workflow:
        body["workflow_template_id"] = workflow
    if mode == "plan" and not agent and not workflow:
        body["mode"] = "plan"
    if thinking:
        body["variant"] = thinking
    if yolo:
        body["yolo_mode"] = True
    return body


async def start_run(task_id: str, body: dict[str, Any]) -> str:
    res = await client.post("/api/v1/runs", {"task_id": task_id, "node_type": "console", "source": "console", **body})
    if not res.get("success") or not res.get("run_id"):
        raise VibeFlowError(res.get("message") or "Run was not started.", code="run_failed")
    return res["run_id"]


@tool("core")
async def vibeflow_start_conversation(
    task_id: str, prompt: str, model: str | None = None, mode: Mode = "build",
    provider_scope: ProviderScope = "auto", agent: str | None = None, skill: str | None = None,
    workflow: str | None = None, attachments: list[str] | None = None,
    thinking: str | None = None, yolo: bool = False,
) -> Any:
    """Start a new agent conversation in a task (sandbox must be running).
    model: '<provider>/<id>' or bare platform id (default: VIBEFLOW_DEFAULT_MODEL
    or a platform Flash model). agent / skill / workflow: from the list_* tools.
    attachments: local file paths uploaded into the sandbox. thinking: model
    reasoning variant (e.g. 'high'). yolo: auto-approve tool permissions.
    Returns run_id; follow with vibeflow_wait_for_reply."""
    attached = await upload_attachments(await _task_session(task_id), attachments) if attachments else []
    body = await build_body(prompt, model, provider_scope, mode, agent=agent, skill=skill, workflow=workflow,
                            attached=attached, thinking=thinking, yolo=yolo)
    return {"run_id": await start_run(task_id, body), "model": body["model"]}


@tool("core")
async def vibeflow_send_message(
    run_id: str, prompt: str, model: str | None = None, mode: Mode = "build",
    provider_scope: ProviderScope = "auto", agent: str | None = None, skill: str | None = None,
    attachments: list[str] | None = None, thinking: str | None = None,
) -> Any:
    """Send a follow-up message to a conversation (same options as
    vibeflow_start_conversation; model defaults to the conversation's model).
    Returns min_messages to pass to vibeflow_wait_for_reply."""
    run = await run_info(run_id)
    attached = await upload_attachments(await run_session(run_id), attachments) if attachments else []
    body = await build_body(prompt, model or run.get("model"), provider_scope, mode, agent=agent,
                            skill=skill, attached=attached, thinking=thinking)
    before = len(await fetch_messages(run_id))
    await client.post(f"/api/v1/runs/{run_id}/messages", body)
    return {"run_id": run_id, "sent": True, "min_messages": before + 2}


async def _task_session(task_id: str) -> str:
    task = await client.get(f"/api/v1/tasks/{task_id}")
    return await running_session(task.get("project_id"))


# ------------------------------------------------------------------ waiting

async def pending_prompts(run_id: str) -> dict[str, Any]:
    return await client.get(f"/api/v1/runs/{run_id}/pending-prompts")


def _summarize_prompt(p: dict[str, Any]) -> dict[str, Any]:
    payload = p.get("payload") or {}
    if p.get("kind") == "question":
        return {"id": p.get("id"), "kind": "question",
                "questions": [{"question": q.get("question") or q.get("header"),
                               "options": [o.get("label") for o in q.get("options") or []],
                               "multiple": q.get("multiple")} for q in payload.get("questions") or []]}
    return {"id": p.get("id"), "kind": "permission", "permission": payload.get("permission") or payload.get("type"),
            "patterns": payload.get("patterns") or payload.get("pattern"), "title": payload.get("title"),
            "metadata": payload.get("metadata")}


def progress_message(ev_name: str, data: Any, run_id: str) -> str | None:
    """Map one sandbox SSE event to a progress line (None = not interesting).
    Events look like {event_type, payload: {sessionID, part|status...},
    conversation_id}; one sandbox serves many conversations, so filter."""
    if ev_name != "message.part.updated" or not isinstance(data, dict):
        return None
    if data.get("conversation_id") not in (run_id, "", None):
        return None
    part = (data.get("payload") or {}).get("part") or {}
    if part.get("type") == "tool":
        state = part.get("state") or {}
        inp = state.get("input") if isinstance(state.get("input"), dict) else {}
        title = state.get("title") or inp.get("description") or inp.get("command") or ""
        return f"tool {part.get('tool')} {state.get('status', '')}: {title}".strip()
    text = (part.get("text") or "").strip()
    if part.get("type") == "text" and text and not text.startswith("<!-- VIBEFLOW_PROMPT"):
        return text.replace("\n", " ")[-160:]
    return None


async def _stream_progress(session_id: str, run_id: str, ctx: Context, stop: asyncio.Event) -> None:
    """Relay live agent activity from the sandbox SSE feed as MCP progress."""
    step = 0
    with contextlib.suppress(Exception):
        async for ev in client.events(session_id, timeout=3600):
            if stop.is_set():
                return
            msg = progress_message(ev.event, ev.data, run_id)
            if msg:
                step += 1
                await ctx.report_progress(step, None, msg)


async def wait_reply(run_id: str, timeout: int, poll: int, min_messages: int | None,
                     ctx: Context | None) -> dict[str, Any]:
    run = await run_info(run_id)
    stop = asyncio.Event()
    streamer = None
    if ctx is not None and run.get("session_id"):
        streamer = asyncio.create_task(_stream_progress(run["session_id"], run_id, ctx, stop))
    deadline = time.monotonic() + timeout
    outcome = "timeout"
    pending: list[dict[str, Any]] = []
    msgs: list[dict[str, Any]] = []
    stable, last_count = 0, -1
    errors = 0
    try:
        while time.monotonic() < deadline:
            try:
                run = await run_info(run_id)
                errors = 0
            except ApiError:
                # Tolerate transient blips; persistent failures must not turn into
                # a misleading "timeout, still working".
                errors += 1
                if errors >= MAX_POLL_ERRORS:
                    raise
                await asyncio.sleep(poll)
                continue
            status = (run.get("status") or "").lower()
            if status in FAILED:
                # A previous turn's failed/aborted status lingers until the new
                # turn starts: only accept it once the expected messages exist.
                msgs = await fetch_messages(run_id)
                if not min_messages or len(msgs) >= min_messages:
                    outcome = status
                    break
                await asyncio.sleep(poll)
                continue
            # Canvas workflow runs: never finish while a node is still queued or running.
            steps_open = any((s.get("status") or "") in STEP_OPEN for s in run.get("steps") or [])
            if status in TERMINAL and not steps_open:
                # A new run reports idle before the agent picks it up, a
                # follow-up before its turn starts, and an answered question /
                # permission before the agent resumes: require the turn's final
                # assistant message - completed and not a mid-turn tool step.
                msgs = await fetch_messages(run_id)
                enough = len(msgs) >= (min_messages or 2)
                if enough and turn_finished(msgs[-1]):
                    outcome = "done"
                    break
                # Safety net: idle with an unchanged transcript (ending in an
                # assistant message) for several polls means the agent stopped
                # without a final answer.
                stable = stable + 1 if len(msgs) == last_count else 0
                last_count = len(msgs)
                if stable >= IDLE_STABLE_POLLS and enough and msgs[-1].get("role") == "assistant":
                    outcome = "done"
                    break
            else:
                stable, last_count = 0, -1
                try:
                    pp = await pending_prompts(run_id)
                except ApiError:
                    pp = {}
                if pp.get("pending_prompts"):
                    pending = [_summarize_prompt(p) for p in pp["pending_prompts"]]
                    outcome = "needs_input"
                    break
            await asyncio.sleep(poll)
    finally:
        stop.set()
        if streamer:
            streamer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await streamer
    if outcome != "done" or not msgs:
        # Never report a reply from a stale snapshot taken before the turn started.
        with contextlib.suppress(ApiError):
            msgs = await fetch_messages(run_id)
    turn = _current_turn(msgs)
    texts = [p["text"].strip() for m in turn for p in m.get("parts") or [] if p.get("type") == "text" and (p.get("text") or "").strip()]
    result: dict[str, Any] = {"run_id": run_id, "outcome": outcome, "status": run.get("status"),
                              "reply": "\n\n".join(texts) or None}
    if run.get("error_message"):
        result["error"] = run["error_message"]
    if pending:
        result["pending_prompts"] = pending
        result["hint"] = "Answer with vibeflow_reply_permission / vibeflow_answer_question, then wait again."
    if outcome == "timeout":
        result["hint"] = "Agent still working; call vibeflow_wait_for_reply again."
    costs = [(m.get("metadata") or {}).get("cost") for m in turn]
    if any(isinstance(c, (int, float)) for c in costs):
        result["cost"] = round(sum(c for c in costs if isinstance(c, (int, float))), 6)
    tools_used = [f"{p.get('tool_name')}" for m in turn for p in m.get("parts") or [] if p.get("type") == "tool"]
    if tools_used:
        result["tools_used"] = tools_used
    if len(run.get("steps") or []) > 1 or (run.get("steps") or [{}])[0].get("node_id") not in (None, "console"):
        result["steps"] = [{"node": s.get("node_id"), "status": s.get("status"), "error": s.get("error_message")}
                           for s in run.get("steps") or []]
    return result


def turn_finished(msg: dict[str, Any]) -> bool:
    """True for a completed assistant message that ends the turn. OpenCode marks
    intermediate steps with finish='tool-calls' (the agent continues after the
    tool result, e.g. once a question is answered) - except when the user
    rejected a permission, which ends the turn on that step."""
    if msg.get("role") != "assistant" or not msg.get("time_completed"):
        return False
    if (msg.get("metadata") or {}).get("finish") != "tool-calls":
        return True
    return any(p.get("type") == "tool" and isinstance(p.get("tool_state"), dict)
               and p["tool_state"].get("status") == "error"
               and "rejected" in str(p["tool_state"].get("error", "")).lower()
               for p in msg.get("parts") or [])


# Polls with an idle run and no new messages before a stalled turn counts as over.
IDLE_STABLE_POLLS = 4


def _current_turn(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assistant messages after the last user message (one turn can span
    several: tool steps, then the answer)."""
    turn: list[dict[str, Any]] = []
    for m in reversed(msgs):
        if m.get("role") == "user":
            break
        turn.append(m)
    return list(reversed(turn))


@tool("core", read_only=True)
async def vibeflow_wait_for_reply(run_id: str, timeout_seconds: int = 300, poll_seconds: int = 4,
                                  min_messages: int | None = None, show_activity: bool = False,
                                  ctx: Context | None = None) -> Any:
    """Wait for the agent to finish its turn; streams live activity as MCP
    progress notifications. Returns outcome done / needs_input (a permission or
    question is pending - see pending_prompts) / failed / timeout, plus the
    reply text. Pass min_messages from vibeflow_send_message so a follow-up is
    not mistaken for the previous finished turn. show_activity adds the recent
    tool calls."""
    result = await wait_reply(run_id, timeout_seconds, poll_seconds, min_messages, ctx)
    if show_activity:
        result["activity"] = render.messages(await fetch_messages(run_id), 3)
    return result


@tool("core")
async def vibeflow_ask(
    prompt: str, project_id: str | None = None, run_id: str | None = None, model: str | None = None,
    agent: str | None = None, skill: str | None = None, workflow: str | None = None, mode: Mode = "build",
    attachments: list[str] | None = None, timeout_seconds: int = 600, ctx: Context | None = None,
) -> Any:
    """One-shot: ensure the project's sandbox is running, start a conversation
    in the default task (or continue run_id), wait for the agent, and return
    its reply. project_id defaults to your first project. Long jobs that
    exceed timeout_seconds keep running - continue with vibeflow_wait_for_reply."""
    min_messages = None
    if run_id:
        sent = await vibeflow_send_message.__wrapped__(run_id, prompt, model=model, mode=mode, agent=agent,
                                                       skill=skill, attachments=attachments)
        min_messages = sent["min_messages"]
    else:
        if not project_id:
            projects = (await client.get("/api/v1/projects", page=1, limit=1)).get("projects") or []
            if not projects:
                raise VibeFlowError("You have no VibeFlow projects.", code="not_found")
            project_id = projects[0]["id"]
        session_id = await ensure_session(project_id)
        attached = await upload_attachments(session_id, attachments) if attachments else []
        body = await build_body(prompt, model, "auto", mode, agent=agent, skill=skill, workflow=workflow,
                                attached=attached)
        run_id = await start_run(await default_task(project_id), body)
    return await wait_reply(run_id, timeout_seconds, 4, min_messages, ctx)


# -------------------------------------------------------- human in the loop

@tool("core", read_only=True)
async def vibeflow_pending_prompts(run_id: str) -> Any:
    """Permission requests and questions the agent is waiting on."""
    pp = await pending_prompts(run_id)
    return {"session_running": pp.get("session_running"),
            "pending": [_summarize_prompt(p) for p in pp.get("pending_prompts") or []]}


async def _reply(run_id: str, request_id: str, kind: str, pod_body: dict[str, Any], replay_reply: str) -> Any:
    pp = await pending_prompts(run_id)
    if pp.get("session_running"):
        sid = await run_session(run_id)
        plural = "permissions" if kind == "permission" else "questions"
        result = await client.post(f"/sessions/{sid}/vibeflow/runs/{run_id}/{plural}/{request_id}/reply", pod_body)
    else:
        # Sandbox restarted since the prompt was raised: replay it from the DB.
        result = await client.post(f"/api/v1/runs/{run_id}/pending-prompts/{request_id}/replay", {"reply": replay_reply})
    # The answered prompt lingers in pending-prompts briefly; wait for it to
    # clear so a following vibeflow_wait_for_reply doesn't report it again.
    for _ in range(15):
        pending = (await pending_prompts(run_id)).get("pending_prompts") or []
        if all(p.get("id") != request_id for p in pending):
            return result
        await asyncio.sleep(1)
    return {"result": result, "warning": "The prompt is still listed as pending after 15 s; check "
                                          "vibeflow_pending_prompts before waiting for the agent."}


@tool("core")
async def vibeflow_reply_permission(run_id: str, request_id: str,
                                    reply: Literal["once", "always", "reject"]) -> Any:
    """Answer an agent permission request (e.g. running a command or editing
    outside the workspace): once = allow this time, always = allow this
    pattern for the session, reject = deny. Ask the user when unsure."""
    return await _reply(run_id, request_id, "permission", {"reply": reply},
                        "deny" if reply == "reject" else "allow")


@tool("core")
async def vibeflow_answer_question(run_id: str, request_id: str, answers: list[list[str]]) -> Any:
    """Answer an agent question. answers has one list per question containing
    the chosen option labels (or free text)."""
    text = "\n".join(", ".join(a) for a in answers)
    return await _reply(run_id, request_id, "question", {"answers": answers}, text)


# ------------------------------------------------------- conversation control

@tool("core")
async def vibeflow_abort(run_id: str, subagent: str | None = None) -> Any:
    """Stop the agent's current turn in a conversation, or only one of its
    subagents (subagent session id from vibeflow_list_subagents)."""
    sid = await run_session(run_id)
    return await client.post(f"/sessions/{sid}/vibeflow/runs/{run_id}/abort", {"reason": "cancelled by user"},
                             subagent=subagent)


@tool("core")
async def vibeflow_resume_conversation(run_id: str) -> Any:
    """Resume a conversation that was interrupted (e.g. by a sandbox stop)."""
    return await client.post(f"/api/v1/runs/{run_id}/resume")


@tool("core")
async def vibeflow_compact_conversation(run_id: str) -> Any:
    """Summarize older turns to free context-window space (see vibeflow_conversation_usage)."""
    return await client.post(f"/api/v1/runs/{run_id}/compact")


@tool("core")
async def vibeflow_fork_conversation(run_id: str, model: str | None = None) -> Any:
    """Branch a conversation: a new conversation starts with the full
    transcript of this one as context. Returns the new run_id."""
    run = await run_info(run_id)
    body = await build_body(FORK_PROMPT, model or run.get("model"), "auto", "build")
    res = await client.post("/api/v1/runs", {"task_id": run["task_id"], "node_type": "fork", "source": "fork",
                                             "forked_from_run_id": run_id, **body})
    if not res.get("run_id"):
        raise VibeFlowError(res.get("message") or "Fork failed.", code="run_failed")
    return {"run_id": res["run_id"], "forked_from": run_id}


@tool("core", idempotent=True)
async def vibeflow_rename_conversation(run_id: str, title: str) -> Any:
    """Rename a conversation."""
    run = await client.patch(f"/api/v1/runs/{run_id}/title", {"title": title})
    return {"id": run.get("id"), "title": run.get("session_title")}


@tool("core", idempotent=True)
async def vibeflow_pin_conversation(run_id: str, pinned: bool = True) -> Any:
    """Pin or unpin a conversation."""
    return await client.post(f"/api/v1/runs/{run_id}/pin", {"pinned": pinned})


@tool("core", idempotent=True)
async def vibeflow_archive_conversation(run_id: str, archived: bool = True) -> Any:
    """Archive (hide) or unarchive a conversation."""
    return await client.patch(f"/api/v1/runs/{run_id}/archive", archive=str(archived).lower())


@tool("core", destructive=True)
async def vibeflow_delete_conversation(run_id: str, confirm: bool = False) -> Any:
    """Permanently delete a conversation. Requires confirm=true."""
    require_confirm(confirm, "delete conversation")
    return await client.delete(f"/api/v1/runs/{run_id}")
