"""Advanced toolset ("advanced") plus MCP resources and prompts.

Tools: code intelligence (sandbox LSP), Galaxy code graph, agent-harness
goal / cron / memory, MCP servers inside the sandbox, background jobs.
Resources: transcripts, messages, project overview, workflow templates.
Prompts: one per built-in VibeFlow workflow."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from .. import render
from ..app import client, default_task, mcp, render as render_output, run_info, run_session, running_session, tool
from ..errors import ApiError, VibeFlowError

WORKDIR = "/workspace"


async def _sandbox(project_id: str) -> str:
    return await running_session(project_id)


# ------------------------------------------------------------ code intelligence

LspMethod = Literal["definition", "references", "hover", "diagnostics", "document-symbol"]


@tool("advanced", read_only=True)
async def vibeflow_code_intel(project_id: str, method: LspMethod, file: str, line: int = 0,
                              character: int = 0) -> Any:
    """Language-server queries on a workspace file: definition / references /
    hover at a position (0-based line and character), diagnostics for the
    file, or document-symbol (outline). file is relative to /workspace."""
    sid = await _sandbox(project_id)
    data = await client.post(f"/sessions/{sid}/vibeflow/lsp/{method}",
                             {"workdir": WORKDIR, "file": file, "line": line, "character": character})
    if isinstance(data, dict) and data.get("ok") is False:
        raise VibeFlowError(data.get("error") or f"LSP {method} failed", code="bad_request",
                            hint="The language server may still be starting; retry in a few seconds.")
    return data.get("result") if isinstance(data, dict) and "result" in data else data


@tool("advanced", read_only=True)
async def vibeflow_code_graph(project_id: str, max_nodes: int = 300, full: bool = False) -> Any:
    """The Galaxy code graph (files/symbols and their relations). Returns a
    summary (node/edge counts by kind, most-connected nodes) unless full=true.
    Answers 'indexing' while the graph is still being built."""
    sid = await _sandbox(project_id)
    resp = await client.raw("GET", f"/sessions/{sid}/vibeflow/graph/layout",
                            params={"workdir": WORKDIR, "max_nodes": max_nodes})
    if resp.status_code == 202:
        return {"status": "indexing", "hint": "The code graph is being built; try again shortly."}
    if resp.status_code >= 400:
        raise ApiError(resp.status_code, "GET", "graph/layout", resp.text[:300])
    graph = resp.json()
    if full:
        return graph
    # Nodes: {id, label (= kind: File/Module/Function/...), name, file_path, x/y/z};
    # edges: {source, target, type (DEFINES/IMPORTS/CALLS/...)}.
    nodes, edges = graph.get("nodes") or [], graph.get("edges") or []
    degree: Counter[str] = Counter()
    for e in edges:
        degree[str(e.get("source"))] += 1
        degree[str(e.get("target"))] += 1
    by_id = {str(n.get("id")): n for n in nodes}

    def describe(node_id: str) -> str:
        n = by_id.get(node_id, {})
        where = f" ({n['file_path']})" if n.get("file_path") and n.get("file_path") != n.get("name") else ""
        return f"{n.get('label', '?')} {n.get('name', node_id)}{where}"

    return {"nodes_shown": len(nodes), "total_nodes": graph.get("total_nodes", len(nodes)), "edges": len(edges),
            "node_kinds": dict(Counter(n.get("label") for n in nodes).most_common()),
            "edge_types": dict(Counter(e.get("type") for e in edges).most_common()),
            "most_connected": [{"node": describe(k), "degree": d} for k, d in degree.most_common(15)]}


# ---------------------------------------------------------------- harness

@tool("advanced", read_only=True)
async def vibeflow_goal_status(run_id: str) -> Any:
    """The active 'goal' (keep-working-until-done condition, set by the goal /
    deep-goal skills) of a conversation, or null."""
    sid, oc_session = await _goal_target(run_id)
    try:
        return await client.get(f"/sessions/{sid}/vibeflow/goal", sessionID=oc_session)
    except ApiError as exc:
        if exc.code == "not_found":  # "no goal set"
            return None
        raise


async def _goal_target(run_id: str) -> tuple[str, str]:
    """The pod keys goals by the conversation's OpenCode session id
    (run.code_session_id), not by the VibeFlow run id."""
    run = await run_info(run_id)
    if not run.get("session_id") or not run.get("code_session_id"):
        raise VibeFlowError(f"Conversation {run_id} has no live agent session.", code="no_session")
    return run["session_id"], run["code_session_id"]


@tool("advanced", destructive=True)
async def vibeflow_goal_stop(run_id: str) -> Any:
    """Stop a conversation's goal loop (the agent stops re-trying)."""
    sid, oc_session = await _goal_target(run_id)
    return await client.post(f"/sessions/{sid}/vibeflow/goal", {"op": "stop", "sessionID": oc_session, "run_id": run_id})


@tool("advanced", read_only=True)
async def vibeflow_list_cron(project_id: str) -> Any:
    """Scheduled jobs the agent created in the sandbox (loop skill / cron)."""
    sid = await _sandbox(project_id)
    return (await client.post(f"/sessions/{sid}/vibeflow/cron", {"op": "list"})).get("jobs", [])


@tool("advanced", read_only=True)
async def vibeflow_agent_memory(project_id: str, name: str | None = None) -> Any:
    """The agent's persistent memory in the sandbox: without name, the list of
    memory entries and conversation work logs; with name, that entry's content."""
    sid = await _sandbox(project_id)
    if name:
        data = await client.post(f"/sessions/{sid}/vibeflow/memory", {"op": "recall", "name": name})
        if not data.get("found"):
            raise VibeFlowError(f"No memory entry '{name}'.", code="not_found")
        return data.get("output")
    rows = (await client.post(f"/sessions/{sid}/vibeflow/memory", {"op": "usage"})).get("rows", [])
    return {"memory": [r for r in rows if not str(r.get("name", "")).startswith("conv-")],
            "work_logs": [r for r in rows if str(r.get("name", "")).startswith("conv-")]}


@tool("advanced", read_only=True)
async def vibeflow_sandbox_mcp_servers(project_id: str) -> Any:
    """MCP servers available to the agent inside the sandbox and their status."""
    sid = await _sandbox(project_id)
    data = await client.get(f"/sessions/{sid}/mcp", directory=WORKDIR)
    if isinstance(data, dict):
        return [{"name": k, "status": (v or {}).get("status", "connected") if isinstance(v, dict) else v}
                for k, v in data.items()]
    return data


@tool("advanced", read_only=True)
async def vibeflow_list_background_jobs(run_id: str) -> Any:
    """Tool calls of a conversation that are still running (movable to the
    background with vibeflow_background_tool_call) and background jobs with
    their status (stoppable with vibeflow_stop_job)."""
    data = await client.get(f"/api/v1/runs/{run_id}/messages")
    running, jobs = [], []
    for m in data.get("messages", []) if isinstance(data, dict) else data:
        for p in m.get("parts") or []:
            if p.get("type") != "tool":
                continue
            state = p.get("tool_state") if isinstance(p.get("tool_state"), dict) else {}
            meta = state.get("metadata") or {}
            call_id = (p.get("metadata") or {}).get("callID")
            title = meta.get("description") or (state.get("input") or {}).get("command")
            if meta.get("background"):
                jobs.append({"job_id": meta.get("jobId") or call_id, "tool": p.get("tool_name"), "title": title,
                             "status": meta.get("backgroundStatus"), "exit": meta.get("exit")})
            elif state.get("status") == "running":
                running.append({"call_id": call_id, "tool": p.get("tool_name"), "title": title})
    return {"running_tool_calls": running, "background_jobs": jobs}


@tool("advanced")
async def vibeflow_background_tool_call(run_id: str, call_id: str) -> Any:
    """Move a long-running tool call (e.g. a build or test run) of the agent to
    the background so the conversation can continue. call_id from
    vibeflow_list_background_jobs (running_tool_calls)."""
    sid = await run_session(run_id)
    return await client.post(f"/sessions/{sid}/vibeflow/runs/{run_id}/jobs/background", {"callID": call_id})


@tool("advanced", destructive=True)
async def vibeflow_stop_job(run_id: str, job_id: str) -> Any:
    """Stop a background shell job of a conversation (job_id from vibeflow_list_background_jobs)."""
    sid = await run_session(run_id)
    return await client.post(f"/sessions/{sid}/vibeflow/runs/{run_id}/jobs/{job_id}/stop", {})


# ------------------------------------------------------------- MCP resources

@mcp.resource("vibeflow://runs/{run_id}/transcript", mime_type="text/markdown",
              description="A conversation's Markdown transcript")
async def run_transcript(run_id: str) -> str:
    return await client.get(f"/api/v1/runs/{run_id}/transcript.md")


@mcp.resource("vibeflow://runs/{run_id}/messages", mime_type="text/markdown",
              description="A conversation's messages rendered as text (live state, incl. tool calls)")
async def run_messages(run_id: str) -> str:
    data = await client.get(f"/api/v1/runs/{run_id}/messages")
    return render.messages(data.get("messages", []) if isinstance(data, dict) else data)


@mcp.resource("vibeflow://projects/{project_id}/overview", mime_type="application/json",
              description="Project details, sandbox status, default task and recent conversations")
async def project_overview(project_id: str) -> str:
    project = await client.get(f"/api/v1/projects/{project_id}")
    status = await client.get("/api/v1/sessions/status", project_id=project_id)
    task_id = await default_task(project_id)
    runs = await client.get("/api/v1/runs", task_id=task_id)
    return render_output({"project": {k: project.get(k) for k in ("id", "name", "description", "project_type", "git_url")},
                          "sandbox": {k: status.get(k) for k in ("status", "session_id", "resumable")},
                          "default_task": task_id,
                          "recent_conversations": [{k: r.get(k) for k in ("id", "session_title", "status", "model")}
                                                   for r in (runs if isinstance(runs, list) else runs.get("runs", []))[:10]]})


@mcp.resource("vibeflow://projects/{project_id}/workflows", mime_type="application/json",
              description="Workflow templates available in a project")
async def project_workflows(project_id: str) -> str:
    data = await client.get(f"/api/v1/projects/{project_id}/templates/workflows")
    items = data if isinstance(data, list) else data.get("workflows", [])
    return render_output([{"id": w.get("id"), "name": w.get("name"), "description": w.get("description"),
                           "hint": w.get("hint")} for w in items])


# --------------------------------------------------------------- MCP prompts

BUILTIN_WORKFLOWS = {
    "bug_fix": ("builtin-bug-fix", "Analyze → fix → test ∥ review a bug", "Describe the bug (symptoms, repro steps, logs)"),
    "code_review": ("builtin-code-review", "Multi-angle review of the current changes", "What to review and any focus areas"),
    "feature_dev": ("builtin-feature-dev", "Plan, implement and test a feature", "Describe the feature and acceptance criteria"),
    "full_stack": ("builtin-full-stack", "Backend + frontend feature end to end", "Describe the feature across API and UI"),
    "db_migration": ("builtin-db-migration", "Safe database migration with rollback", "Describe the schema change"),
    "safe_refactor": ("builtin-refactor-safe", "Behaviour-preserving refactor with tests", "What to refactor and why"),
    "rfp_to_demo": ("builtin-00-rfp-to-demo", "RFP documents → architecture → slides → demo app", "Point to the RFP files or folder"),
    "rfp_to_proposal": ("builtin-01-rfp-to-proposal", "RFP documents → proposal", "Point to the RFP files or folder"),
}


def _register_workflow_prompt(key: str, workflow_id: str, title: str, ask: str) -> None:
    def prompt(project_id: str, request: str) -> str:
        return (f"Run the VibeFlow '{title}' workflow ({workflow_id}) in project {project_id}.\n\n"
                f"Request: {request}\n\n"
                f"Steps:\n1. vibeflow_ask(project_id=\"{project_id}\", workflow=\"{workflow_id}\", prompt=<the request>, "
                f"timeout_seconds=900) - it starts the sandbox if needed.\n"
                "2. If the outcome is needs_input, show the pending prompt to the user and answer with "
                "vibeflow_reply_permission / vibeflow_answer_question, then vibeflow_wait_for_reply.\n"
                "3. If it times out, keep calling vibeflow_wait_for_reply(run_id).\n"
                "4. Summarize the result, then show vibeflow_get_changes; push only after the user confirms.")

    prompt.__name__ = f"vibeflow_{key}"
    mcp.prompt(name=f"vibeflow_{key}", description=f"{title}. Argument 'request': {ask}.")(prompt)


for _key, (_wid, _title, _ask) in BUILTIN_WORKFLOWS.items():
    _register_workflow_prompt(_key, _wid, _title, _ask)
