"""B8 hardening (workflow runs) and features found in the second site review."""
import io
import json
import zipfile

import httpx
import pytest
import respx

from conftest import API, payload
from vibeflow_mcp import config
from vibeflow_mcp.tools import admin, chat, code, core, pm, sandbox


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(chat.asyncio, "sleep", no_sleep)


@pytest.fixture
def api(logged_in):
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/api/v1/projects/p1/my-recent-task").mock(return_value=httpx.Response(200, json={"task_id": "t1"}))
        mock.get("/api/v1/sessions/status").mock(return_value=httpx.Response(200, json={"status": "running", "session_id": "s1"}))
        mock.get("/api/v1/users/me/platform-models").mock(return_value=httpx.Response(200, json={"models": [
            {"id": "gemini-3.7-flash", "provider": "google-starter"}]}))
        yield mock


def body_of(route):
    return json.loads(route.calls.last.request.read())


def done(text, cost=None):
    return {"role": "assistant", "time_completed": 1, "metadata": {"finish": "stop", **({"cost": cost} if cost else {})},
            "parts": [{"type": "text", "text": text}]}


# ------------------------------------------------------------- B8 workflow runs

async def test_wait_never_finishes_while_a_workflow_step_is_open(api):
    """Live shape: node-1 completed + node-2 pending while the run blinks idle."""
    api.get("/api/v1/runs/r1").mock(side_effect=[
        httpx.Response(200, json={"status": "idle", "steps": [{"node_id": "node-1", "status": "completed"},
                                                               {"node_id": "node-2", "status": "pending"}]}),
        httpx.Response(200, json={"status": "idle", "steps": [{"node_id": "node-1", "status": "completed"},
                                                               {"node_id": "node-2", "status": "pending"}]}),
        httpx.Response(200, json={"status": "idle", "steps": [{"node_id": "node-1", "status": "completed"},
                                                               {"node_id": "node-2", "status": "completed"}]}),
    ])
    api.get("/api/v1/runs/r1/pending-prompts").mock(return_value=httpx.Response(200, json={"pending_prompts": []}))
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [
        {"role": "user", "parts": [{"type": "text", "text": "go"}]}, done("step 1"), done("STEP2 DONE")]}))
    out = await chat.wait_reply("r1", timeout=5, poll=0, min_messages=None, ctx=None)
    assert out["outcome"] == "done"
    assert out["steps"] == [{"node": "node-1", "status": "completed", "error": None},
                            {"node": "node-2", "status": "completed", "error": None}]


async def test_console_runs_do_not_report_steps(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"status": "idle", "steps": [{"node_id": "console", "status": "completed"}]}))
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [
        {"role": "user", "parts": []}, done("hi")]}))
    assert "steps" not in await chat.wait_reply("r1", timeout=5, poll=0, min_messages=None, ctx=None)


# -------------------------------------------------------------------- subagents

async def test_list_subagents_from_task_tool_parts(api):
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [{"role": "assistant", "parts": [
        {"type": "tool", "tool_name": "task", "tool_state": {"status": "completed", "input": {"subagent_type": "tester", "description": "write tests"},
                                                             "metadata": {"sessionId": "ses_child"}}},
        {"type": "tool", "tool_name": "bash", "tool_state": {"status": "completed"}}]}]}))
    assert payload(await chat.vibeflow_list_subagents("r1")) == [
        {"subagent": "ses_child", "agent": "tester", "description": "write tests", "status": "completed"}]


async def test_subagent_messages_retry_and_abort(api):
    msgs = api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": []}))
    await chat.vibeflow_get_messages("r1", subagent="ses_child")
    assert msgs.calls.last.request.url.params["subagent"] == "ses_child"
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    retry = api.post("/sessions/s1/vibeflow/runs/r1/retry").mock(return_value=httpx.Response(200, json={}))
    abort = api.post("/sessions/s1/vibeflow/runs/r1/abort").mock(return_value=httpx.Response(200, json={}))
    await chat.vibeflow_retry_subagent("r1", "ses_child")
    await chat.vibeflow_abort("r1", subagent="ses_child")
    assert retry.calls.last.request.url.params["subagent"] == "ses_child"
    assert abort.calls.last.request.url.params["subagent"] == "ses_child"


async def test_workflow_batches_summary(api):
    api.get("/api/v1/runs/r1/workflow-batches").mock(return_value=httpx.Response(200, json=[{
        "batch_id": 1, "name": "fan-out", "workflow_json": {"nodes": [{"id": "a", "data": {"agentType": "tester", "label": "Tests"}}],
                                                           "edges": [{"source": "a", "target": "b"}]}}]))
    assert payload(await chat.vibeflow_get_workflow_batches("r1")) == [
        {"batch_id": 1, "name": "fan-out", "status": None, "nodes": [{"id": "a", "agent": "tester", "label": "Tests"}],
         "edges": [["a", "b"]]}]


# ------------------------------------------------------------------- git / AI fixes

async def test_git_status_and_ai_helpers(api):
    status = api.get("/api/v1/changes/status").mock(return_value=httpx.Response(200, json={"tasks": [
        {"task_id": "t1", "behind": 2}, {"task_id": "other-project-task", "behind": 9}]}))
    api.get("/api/v1/tasks").mock(return_value=httpx.Response(200, json=[{"id": "t1"}]))
    assert payload(await code.vibeflow_git_status("p1", fetch_remote=True)) == [{"task_id": "t1", "behind": 2}]
    assert status.calls.last.request.url.params["fetch"] == "1"
    merge = api.post("/api/v1/preview/pull-merge").mock(return_value=httpx.Response(200, json={"run_id": "m1"}))
    mermaid = api.post("/api/v1/preview/mermaid-fix").mock(return_value=httpx.Response(200, json={"run_id": "f1"}))
    await code.vibeflow_ai_pull_merge("p1", "main", behind_count=2)
    await code.vibeflow_fix_mermaid("p1", "docs/arch.md", "Parse error on line 3")
    assert body_of(merge) == {"task_id": "t1", "session_id": "s1", "branch": "main", "behind_count": 2,
                              "model": "google-starter/gemini-3.7-flash"}
    assert body_of(mermaid)["file_path"] == "docs/arch.md" and body_of(mermaid)["error_message"] == "Parse error on line 3"


# ---------------------------------------------------------------------- sandbox

async def test_sandbox_housekeeping(api):
    assert payload(await sandbox.vibeflow_stop_idle_sessions())["error"] == "confirmation_required"
    idle = api.post("/api/v1/sessions/mine/stop-idle").mock(return_value=httpx.Response(200, json={"stopped": 1}))
    await sandbox.vibeflow_stop_idle_sessions(min_idle_minutes=45, confirm=True)
    assert idle.calls.last.request.url.params["min_idle_seconds"] == "2700"
    base = api.post("/api/v1/sessions/s1/workspace-baseline").mock(return_value=httpx.Response(200, json={}))
    reload = api.post("/api/v1/changes/session/reload").mock(return_value=httpx.Response(200, json={}))
    await sandbox.vibeflow_reset_session_baseline("s1")
    await sandbox.vibeflow_reload_agent_config("t1", "s1")
    assert base.called and dict(reload.calls.last.request.url.params) == {"task_id": "t1", "session_id": "s1"}


async def test_upload_workspace_zips_folder_skipping_deps(api, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "big.js").write_text("x")
    guard = payload(await code.vibeflow_upload_workspace("p1", str(tmp_path), confirm=True))
    assert guard["error"] == "confirmation_required" and "replaces ALL files" in guard["message"]
    assert payload(await code.vibeflow_upload_workspace("p1", str(tmp_path), replace_workspace=True))["error"] == "confirmation_required"
    api.get("/api/v1/files/download-workspace").mock(return_value=httpx.Response(200, content=b"PK-old-workspace"))
    stage = api.post("/sessions/s1/vibeflow/file/upload").mock(return_value=httpx.Response(200, json={"path": "/tmp/up/ws.zip"}))
    up = api.post("/api/v1/sessions/s1/upload-workspace").mock(return_value=httpx.Response(200, json={"success": True}))
    out = payload(await code.vibeflow_upload_workspace("p1", str(tmp_path), replace_workspace=True, confirm=True))
    assert out["result"] == {"success": True}
    from pathlib import Path
    assert Path(out["previous_workspace_backup"]).read_bytes() == b"PK-old-workspace"
    raw = stage.calls.last.request.read()
    assert b'name="scope"' in raw and b"workspace" in raw
    zdata = raw[raw.index(b"PK\x03\x04"):]
    names = zipfile.ZipFile(io.BytesIO(zdata[:zdata.rindex(b"PK\x05\x06") + 22])).namelist()
    assert names == ["src/app.py"]
    assert b"pod_path=%2Ftmp%2Fup%2Fws.zip" in up.calls.last.request.read()


async def test_upload_workspace_rejects_non_zip(api, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert payload(await code.vibeflow_upload_workspace("p1", str(f), replace_workspace=True, confirm=True))["error"] == "bad_request"


async def test_upload_workspace_aborts_when_backup_fails(api, tmp_path):
    """Regression for the live incident: never replace without a backup."""
    z = tmp_path / "ws.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.txt", "x")
    api.get("/api/v1/files/download-workspace").mock(return_value=httpx.Response(500, json={"detail": "boom"}))
    stage = api.post("/sessions/s1/vibeflow/file/upload").mock(return_value=httpx.Response(200, json={"path": "/p"}))
    up = api.post("/api/v1/sessions/s1/upload-workspace").mock(return_value=httpx.Response(200, json={}))
    out = payload(await code.vibeflow_upload_workspace("p1", str(z), replace_workspace=True, confirm=True))
    assert out["error"] == "backup_failed" and not stage.called and not up.called


# ---------------------------------------------------------------- pm / admin / docs

async def test_jira_statuses_body(api):
    route = api.post("/api/v1/jira/projects/AB/statuses").mock(return_value=httpx.Response(200, json=[{"name": "To Do"}]))
    await pm.vibeflow_list_jira_statuses("AB", "pat", site_id="jira3")
    assert body_of(route) == {"pat": "pat", "site_id": "jira3"}


async def test_admin_update_role_if_match(api):
    route = api.patch("/api/v1/roles/r9").mock(return_value=httpx.Response(200, json={}))
    await admin.vibeflow_admin_update_role("r9", ["a:b"], version=3, confirm=True)
    assert body_of(route) == {"permissions": ["a:b"]} and route.calls.last.request.headers["if-match"] == '"3"'


async def test_docs_search_and_read(api):
    core._docs_index = None
    api.get(f"{config.WEB_URL}/docs/docs-search.json").mock(return_value=httpx.Response(200, json=[
        {"title": "Restore Points", "path": "/docs/features/restore-points", "text": "timeline revert"},
        {"title": "Preview", "path": "/docs/features/preview", "text": "run app"}]))
    api.get(f"{config.WEB_URL}/docs/features/preview").mock(return_value=httpx.Response(
        200, text="<html><nav>menu</nav><main><h1>Preview</h1><p>Run your &amp; app</p><script>x()</script></main></html>"))
    hits = payload(await core.vibeflow_search_docs("revert timeline"))
    assert hits[0]["path"] == "/docs/features/restore-points" and len(hits) == 1
    assert payload(await core.vibeflow_read_docs("features/preview")) == "Preview\nRun your & app"



async def test_restore_point_diff_uses_before_snapshot(api):
    """Live finding: diffs are keyed by before_snapshot; message ids return []."""
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    api.get("/sessions/s1/vibeflow/runs/r1/restore-points").mock(return_value=httpx.Response(200, json={"points": [
        {"message_id": "m1", "assistant_message_id": "a1", "before_snapshot": "snapA", "file_count": 1}]}))
    diff = api.get("/sessions/s1/vibeflow/runs/r1/restore-points/snapA/diff").mock(
        return_value=httpx.Response(200, json={"diff": [{"file": "notes.txt", "patch": "+line two"}]}))
    assert payload(await code.vibeflow_restore_point_diff("r1", "a1")) == [{"file": "notes.txt", "patch": "+line two"}]
    assert payload(await code.vibeflow_restore_point_diff("r1", "m1")) == [{"file": "notes.txt", "patch": "+line two"}]
    assert diff.call_count == 2


async def test_default_task_fallbacks_for_new_project(logged_in):
    """Live finding: a new project has no 'recent task'; fall back to its task
    list, else create the default 'Main' task."""
    from vibeflow_mcp import app
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/api/v1/projects/pA/my-recent-task").mock(return_value=httpx.Response(200, json={}))
        mock.get("/api/v1/tasks").mock(side_effect=[httpx.Response(200, json=[{"id": "tA"}]), httpx.Response(200, json=[])])
        mock.get("/api/v1/projects/pB/my-recent-task").mock(return_value=httpx.Response(200, json={}))
        create = mock.post("/api/v1/kanban/tasks").mock(return_value=httpx.Response(201, json={"id": "tMain"}))
        assert await app.default_task("pA") == "tA"
        assert await app.default_task("pB") == "tMain"
        assert json.loads(create.calls.last.request.read()) == {"project_id": "pB", "name": "Main"}


async def test_list_background_jobs(api):
    from vibeflow_mcp.tools import advanced
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [{"role": "assistant", "parts": [
        {"type": "tool", "tool_name": "bash", "metadata": {"callID": "c1"},
         "tool_state": {"status": "running", "input": {"command": "npm test"}, "metadata": {}}},
        {"type": "tool", "tool_name": "bash", "metadata": {"callID": "c2"},
         "tool_state": {"status": "completed", "metadata": {"background": True, "jobId": "c2", "backgroundStatus": "cancelled",
                                                            "description": "sleep"}}}]}]}))
    assert payload(await advanced.vibeflow_list_background_jobs("r1")) == {
        "running_tool_calls": [{"call_id": "c1", "tool": "bash", "title": "npm test"}],
        "background_jobs": [{"job_id": "c2", "tool": "bash", "title": "sleep", "status": "cancelled", "exit": None}]}
