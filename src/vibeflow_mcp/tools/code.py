"""Code toolset: sandbox workspace files, git changes / push, restore points,
app preview. All tools need the project's sandbox running."""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Any

from .. import render
from ..app import client, default_task, require_confirm, run_session, running_session, tool
from ..errors import ApiError, VibeFlowError
from .chat import default_model, resolve_model

PREVIEW_DOMAIN = "preview.vibeflow.fptconsulting.co.jp"
MAX_FILE_CHARS = 50_000


async def workspace(project_id: str) -> dict[str, str]:
    """task_id + session_id: the context nearly every code endpoint needs."""
    return {"task_id": await default_task(project_id), "session_id": await running_session(project_id)}


# --------------------------------------------------------------------- files

@tool("code", read_only=True)
async def vibeflow_list_files(project_id: str, max_depth: int = 3, refresh: bool = False) -> Any:
    """The sandbox workspace file tree (paths relative to /workspace)."""
    ws = await workspace(project_id)
    data = await client.get("/api/v1/files", **ws, refresh="1" if refresh else None)
    lines = render.tree(data.get("entries") or [], max_depth=max_depth)
    head = f"{data.get('root', '/workspace')}/" + (" (truncated)" if data.get("truncated") else "")
    return head + "\n" + "\n".join(lines)


@tool("code", read_only=True)
async def vibeflow_read_file(project_id: str, path: str, offset: int = 0, max_chars: int = MAX_FILE_CHARS) -> Any:
    """Read a text file from the workspace (path relative to /workspace).
    Use offset/max_chars to page through large files."""
    data = await client.get("/api/v1/files/content", **await workspace(project_id), path=path)
    content = (data.get("content") if isinstance(data, dict) else data) or ""
    out: dict[str, Any] = {"path": path, "size": len(content), "content": content[offset:offset + max_chars]}
    if offset + max_chars < len(content):
        out["next_offset"] = offset + max_chars
    return out


@tool("code", read_only=True)
async def vibeflow_search_files(project_id: str, query: str, limit: int = 20) -> Any:
    """Fuzzy-find workspace files by name/path."""
    data = await client.get("/api/v1/files/search", **await workspace(project_id), q=query, limit=limit)
    return [r.get("path") for r in data.get("results", [])]


async def _put_file(project_id: str, dest_path: str, content: bytes) -> None:
    """Stage bytes in the sandbox, then move them into the workspace."""
    ws = await workspace(project_id)
    name = posixpath.basename(dest_path)
    staged = await client.upload(f"/sessions/{ws['session_id']}/vibeflow/file/upload", [(name, content)])
    paths = staged.get("paths") if isinstance(staged, dict) else None
    if not paths:
        raise VibeFlowError("Sandbox upload returned no path.", code="server_error")
    await client.post("/api/v1/files/upload", {"pod_path": paths[0], "dir": posixpath.dirname(dest_path),
                                               "filename": name, **ws})


@tool("code")
async def vibeflow_write_file(project_id: str, path: str, content: str) -> Any:
    """Create or overwrite a text file in the workspace (path relative to
    /workspace). Overwrites without asking; changes show in vibeflow_get_changes."""
    if path.endswith("/") or not posixpath.basename(path):
        raise VibeFlowError("path must include a file name.", code="bad_request")
    path = path.strip("/")
    data = content.encode("utf-8")
    await _put_file(project_id, path, data)
    return {"written": path, "bytes": len(data)}


@tool("code")
async def vibeflow_upload_file(project_id: str, local_path: str, dest_dir: str = "") -> Any:
    """Upload a local file into workspace directory dest_dir (relative to /workspace)."""
    src = Path(local_path).expanduser()
    if not src.is_file():
        raise VibeFlowError(f"Local file not found: {local_path}", code="bad_request")
    dest = posixpath.join(dest_dir.strip("/"), src.name)
    await _put_file(project_id, dest, src.read_bytes())
    return {"uploaded": dest, "bytes": src.stat().st_size}


@tool("code", destructive=True)
async def vibeflow_delete_file(project_id: str, path: str, confirm: bool = False) -> Any:
    """Delete a file or directory in the workspace. Requires confirm=true."""
    require_confirm(confirm, f"delete {path}")
    return await client.post("/api/v1/files/delete", {"path": path, **await workspace(project_id)})


async def _save(data: bytes, local_path: str) -> dict[str, Any]:
    dest = Path(local_path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"saved": str(dest), "bytes": len(data)}


@tool("code")
async def vibeflow_download_file(project_id: str, path: str, local_path: str) -> Any:
    """Download a workspace file (any type) to a local path."""
    return await _save(await client.get_bytes("/api/v1/files/download", path=path,
                                              task_id=await default_task(project_id)), local_path)


@tool("code")
async def vibeflow_download_workspace(project_id: str, local_path: str) -> Any:
    """Download the whole workspace as a zip archive to a local path."""
    return await _save(await client.get_bytes("/api/v1/files/download-workspace",
                                              task_id=await default_task(project_id)), local_path)


# ------------------------------------------------------------------ branches

@tool("code", read_only=True)
async def vibeflow_list_branches(project_id: str) -> Any:
    """Git branches of the workspace (git-backed projects only)."""
    try:
        return await client.get("/api/v1/files/branches", task_id=await default_task(project_id))
    except ApiError as exc:
        if exc.code == "not_found":
            raise VibeFlowError("No branches: this is a local (non-git) project.", code="not_found") from exc
        raise


@tool("code")
async def vibeflow_checkout_branch(project_id: str, branch: str) -> Any:
    """Switch the workspace to another git branch."""
    return await client.post("/api/v1/files/checkout", {"task_id": await default_task(project_id), "branch": branch})


# ------------------------------------------------------------------- changes

@tool("code", read_only=True)
async def vibeflow_get_changes(project_id: str, scope: str = "workspace", fetch_remote: bool = False) -> Any:
    """Changed files. scope='workspace': uncommitted changes vs HEAD;
    scope='session': changes made during the current sandbox session.
    fetch_remote refreshes ahead/behind info from origin."""
    ws = await workspace(project_id)
    if scope == "session":
        data = await client.get("/api/v1/changes/session-diff", **ws)
    else:
        data = await client.get("/api/v1/changes", **ws, fetch="1" if fetch_remote else None)
    return {"branch": data.get("branch_name"), "base": data.get("diff_base"), "totals": data.get("totals"),
            "files": [{"path": f.get("path"), "change": f.get("change_type"), "+": f.get("additions"),
                       "-": f.get("deletions")} for f in data.get("files", [])],
            "truncated": data.get("truncated")}


@tool("code", read_only=True)
async def vibeflow_get_diff(project_id: str, path: str) -> Any:
    """Unified diff of one changed file."""
    data = await client.get("/api/v1/changes/diff", **await workspace(project_id), path=path)
    text = render.diff(data.get("diff_lines") or [])
    if not text:
        return "(no diff)"
    return text + ("\n… (diff truncated)" if data.get("truncated") else "")


@tool("code", read_only=True)
async def vibeflow_generate_commit_message(project_id: str) -> Any:
    """AI-generated commit/PR title and body for the current changes."""
    # Server-side LLM call: allow well beyond the default 60 s read timeout.
    data = await client.request("GET", "/api/v1/changes/generate-message", params=await workspace(project_id),
                                timeout=180)
    if data.get("error"):
        raise VibeFlowError(data["error"], code="bad_request")
    title, _, body = (data.get("message") or "").strip().partition("\n")
    return {"title": title.strip(), "body": body.strip()}


@tool("code", destructive=True)
async def vibeflow_push_changes(project_id: str, title: str, body: str = "", paths: list[str] | None = None,
                                target_branch: str | None = None, confirm: bool = False) -> Any:
    """Commit and push workspace changes (all changed files unless paths is
    given). target_branch: push to a new branch (opening a PR where the
    platform supports it) instead of the current one. Publishes to the git
    remote - requires confirm=true."""
    require_confirm(confirm, "commit and push changes")
    ws = await workspace(project_id)
    if paths is None:
        changes = await client.get("/api/v1/changes", **ws)
        paths = [f["path"] for f in changes.get("files", [])]
    if not paths:
        raise VibeFlowError("Nothing to push: no changed files.", code="bad_request")
    payload: dict[str, Any] = {"title": title, "body": body, "paths": paths, **ws}
    if target_branch:
        payload["target_branch"] = target_branch
    return await client.post("/api/v1/changes/push", payload)


@tool("code")
async def vibeflow_git_sync(project_id: str) -> Any:
    """Pull new commits from the remote branch into the workspace."""
    data = await client.post("/api/v1/changes/git-sync", await workspace(project_id))
    return {"result": data.get("result"), "pulled": data.get("pulled_count"), "status": data.get("status")}


# ------------------------------------------------------------ restore points

async def _rp_call(run_id: str, method: str, suffix: str, body: Any = None) -> Any:
    sid = await run_session(run_id)
    try:
        return await client.request(method, f"/sessions/{sid}/vibeflow/runs/{run_id}{suffix}", json=body)
    except ApiError as exc:
        if exc.code == "not_found":
            raise VibeFlowError("Restore points exist only for conversations run in the current sandbox "
                                "session (the sandbox was restarted since).", code="not_found") from exc
        raise


@tool("code", read_only=True)
async def vibeflow_list_restore_points(run_id: str) -> Any:
    """Checkpoints of a conversation (agent messages that changed files) and
    the currently applied revert, if any."""
    data = await _rp_call(run_id, "GET", "/restore-points")
    return {"points": data.get("points", []), "current_revert": data.get("current_revert")}


@tool("code", read_only=True)
async def vibeflow_restore_point_diff(run_id: str, message_id: str) -> Any:
    """What reverting to a restore point would change."""
    return (await _rp_call(run_id, "GET", f"/restore-points/{message_id}/diff")).get("diff", [])


@tool("code", destructive=True)
async def vibeflow_revert_to(run_id: str, message_id: str, part_id: str | None = None,
                             confirm: bool = False) -> Any:
    """Roll the workspace (and conversation) back to a restore point. Undo
    with vibeflow_undo_revert. Requires confirm=true."""
    require_confirm(confirm, "revert workspace to restore point")
    body: dict[str, Any] = {"messageID": message_id}
    if part_id:
        body["partID"] = part_id
    return await _rp_call(run_id, "POST", "/revert", body)


@tool("code")
async def vibeflow_undo_revert(run_id: str) -> Any:
    """Undo the last revert of a conversation."""
    return await _rp_call(run_id, "POST", "/unrevert", {})


# ------------------------------------------------------------------- preview

def preview_url(session_id: str, port: Any) -> str:
    return f"https://{session_id}-{port}.{PREVIEW_DOMAIN}"


async def _preview_model(model: str | None) -> str:
    return (await resolve_model(model or await default_model(), "auto"))[0]


@tool("code")
async def vibeflow_preview_run(project_id: str, model: str | None = None) -> Any:
    """Start the app preview: an agent works out how to run the project and
    serves it on a public preview URL. Uses LLM tokens. Returns the agent
    run_id (follow with vibeflow_wait_for_reply) and the URL pattern."""
    ws = await workspace(project_id)
    data = await client.post("/api/v1/preview/run", {
        **ws, "model": await _preview_model(model), "hostname": preview_url(ws["session_id"], "{PORT}")[8:]})
    return {**data, "url_pattern": preview_url(ws["session_id"], "{PORT}")}


@tool("code", read_only=True)
async def vibeflow_preview_status(project_id: str, log_lines: int = 50) -> Any:
    """Preview ports/URLs currently exposed by the sandbox and recent app logs."""
    sid = await running_session(project_id)
    snap = await client.get(f"/sessions/{sid}/vibeflow/snapshot")
    ports = snap.get("preview_ports") or []
    logs = await client.get(f"/api/v1/sessions/{sid}/preview/logs", tail=log_lines)
    return {"ports": ports,
            "urls": [preview_url(sid, p.get("port") if isinstance(p, dict) else p) for p in ports],
            "logs": logs.get("logs", "") if isinstance(logs, dict) else logs}


@tool("code")
async def vibeflow_preview_stop(project_id: str, model: str | None = None) -> Any:
    """Stop the running preview app."""
    return await client.post("/api/v1/preview/stop", {**await workspace(project_id),
                                                      "model": await _preview_model(model)})


@tool("code")
async def vibeflow_preview_fix(project_id: str, error_context: str, model: str | None = None,
                               run_id: str | None = None) -> Any:
    """Ask an agent to fix a preview error (paste the error/log excerpt).
    Uses LLM tokens; returns the fixing run_id."""
    payload: dict[str, Any] = {**await workspace(project_id), "error_context": error_context,
                               "model": await _preview_model(model)}
    if run_id:
        payload["run_id"] = run_id
    return await client.post("/api/v1/preview/fix", payload)
