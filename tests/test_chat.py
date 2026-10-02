import json

import httpx
import pytest
import respx

from conftest import API, payload
from vibeflow_mcp.errors import VibeFlowError
from vibeflow_mcp.tools import chat, sandbox

PLATFORM = {"models": [{"id": "gemini-3.7-flash", "name": "Gemini", "provider": "google-starter"},
                       {"id": "GLM-5.2", "name": "GLM", "provider": "fpt-starter-vn"}]}


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(chat.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(sandbox.asyncio, "sleep", no_sleep)


@pytest.fixture
def api(logged_in):
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/api/v1/users/me/platform-models").mock(return_value=httpx.Response(200, json=PLATFORM))
        yield mock


def body_of(route):
    return json.loads(route.calls.last.request.read())


def msg(role, text, cost=None, done=True):
    return {"role": role, "model": "gemini", "metadata": {"cost": cost} if cost else {},
            "time_completed": 1 if role == "assistant" and done else None,
            "parts": [{"type": "text", "text": text}]}


async def test_wait_new_run_ignores_initial_idle_and_joins_multi_message_turn(api):
    """A fresh run reports idle before the agent starts; a turn can span a tool
    step message plus the answer message."""
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"id": "r1", "status": "idle"}))
    tool_step = {"role": "assistant", "time_completed": 1, "metadata": {"cost": 0.01},
                 "parts": [{"type": "tool", "tool_name": "bash", "tool_state": {"status": "completed"}}]}
    api.get("/api/v1/runs/r1/messages").mock(side_effect=[
        httpx.Response(200, json={"messages": []}),
        httpx.Response(200, json={"messages": [msg("user", "go")]}),
        httpx.Response(200, json={"messages": [msg("user", "go"), msg("assistant", "half", done=False)]}),
        httpx.Response(200, json={"messages": [msg("user", "go"), tool_step, msg("assistant", "PHASE2_OK", cost=0.02)]}),
    ])
    out = await chat.wait_reply("r1", timeout=5, poll=0, min_messages=None, ctx=None)
    assert out["outcome"] == "done" and out["reply"] == "PHASE2_OK"
    assert out["tools_used"] == ["bash"] and out["cost"] == 0.03


# ------------------------------------------------------------------ pickers

async def test_list_agents_strips_prompts(api):
    api.get("/api/v1/projects/p1/templates/agents").mock(return_value=httpx.Response(200, json={"agents": [
        {"id": None, "name": "reviewer", "description": "Reviews", "systemPrompt": "long..."},
        {"id": "a1", "name": "custom", "description": "Mine", "systemPrompt": "x"}]}))
    out = payload(await chat.vibeflow_list_agents("p1"))
    assert out == [{"name": "reviewer", "description": "Reviews", "builtin": True},
                   {"name": "custom", "description": "Mine", "builtin": False}]


async def test_list_workflows_summarizes_steps(api):
    api.get("/api/v1/projects/p1/templates/workflows").mock(return_value=httpx.Response(200, json=[
        {"id": "builtin-bugfix", "name": "Bug Fix", "workflow_json": {"nodes": [{"label": "Reproduce"}, {"agentType": "tester"}]}}]))
    out = payload(await chat.vibeflow_list_workflows("p1"))
    assert out[0]["id"] == "builtin-bugfix" and out[0]["steps"] == ["Reproduce", "tester"]


async def test_list_skills_needs_running_session(api):
    api.get("/api/v1/sessions/status").mock(return_value=httpx.Response(200, json={"status": "stopped"}))
    out = payload(await chat.vibeflow_list_skills("p1"))
    assert out["error"] == "no_session"


# --------------------------------------------------------------------- body

async def test_build_body_options(api):
    body = await chat.build_body("hi", "GLM-5.2", "auto", "plan", skill="goal", thinking="high", yolo=True)
    assert body == {"prompt": "hi", "model": "fpt-starter-vn/GLM-5.2", "attached_files": [], "provider_scope": "platform",
                    "skill": "goal", "mode": "plan", "variant": "high", "yolo_mode": True}
    with_agent = await chat.build_body("hi", None, "auto", "plan", agent="reviewer")
    assert "mode" not in with_agent and with_agent["agent_type"] == "reviewer"
    assert with_agent["model"] == "google-starter/gemini-3.7-flash"  # default prefers a Flash model


async def test_send_message_defaults_to_run_model_and_returns_min_messages(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"id": "r1", "session_id": "s1", "model": "fpt-starter-vn/GLM-5.2"}))
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [msg("user", "a"), msg("assistant", "b")]}))
    send = api.post("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"ok": True}))
    out = payload(await chat.vibeflow_send_message("r1", "next"))
    assert out["min_messages"] == 4 and body_of(send)["model"] == "fpt-starter-vn/GLM-5.2"


async def test_attachments_upload_multipart(api, tmp_path):
    f = tmp_path / "spec.md"
    f.write_text("# spec")
    up = api.post("/sessions/s1/vibeflow/file/upload").mock(return_value=httpx.Response(200, json={"paths": ["/tmp/vibeflow/user/spec.md"]}))
    assert await chat.upload_attachments("s1", [str(f)]) == ["/tmp/vibeflow/user/spec.md"]
    assert b'filename="spec.md"' in up.calls.last.request.read()


async def test_missing_attachment_is_bad_request(api):
    with pytest.raises(VibeFlowError):
        await chat.upload_attachments("s1", ["/nope/missing.txt"])


# --------------------------------------------------------------------- wait

async def test_wait_returns_needs_input_on_pending_permission(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"id": "r1", "status": "running"}))
    api.get("/api/v1/runs/r1/pending-prompts").mock(return_value=httpx.Response(200, json={
        "session_running": True,
        "pending_prompts": [{"id": "perm1", "kind": "permission", "payload": {"permission": "bash", "patterns": ["rm -rf build"]}}]}))
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [msg("user", "clean")]}))
    out = await chat.wait_reply("r1", timeout=5, poll=0, min_messages=None, ctx=None)
    assert out["outcome"] == "needs_input"
    assert out["pending_prompts"][0] == {"id": "perm1", "kind": "permission", "permission": "bash",
                                         "patterns": ["rm -rf build"], "title": None, "metadata": None}


async def test_wait_min_messages_guards_against_stale_idle(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"id": "r1", "status": "idle"}))
    old = [msg("user", "q1"), msg("assistant", "a1")]
    new = old + [msg("user", "q2"), msg("assistant", "a2", cost=0.01)]
    api.get("/api/v1/runs/r1/messages").mock(side_effect=[
        httpx.Response(200, json={"messages": old}), httpx.Response(200, json={"messages": new})])
    out = await chat.wait_reply("r1", timeout=5, poll=0, min_messages=4, ctx=None)
    assert out["outcome"] == "done" and out["reply"] == "a2" and out["cost"] == 0.01


async def test_wait_reports_failure(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"status": "failed", "error_message": "Model not configured"}))
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": []}))
    out = await chat.wait_reply("r1", timeout=5, poll=0, min_messages=None, ctx=None)
    assert out["outcome"] == "failed" and out["error"] == "Model not configured" and out["reply"] is None


def test_progress_message_mapping():
    """Shapes captured from the live sandbox SSE feed."""
    def ev(part, conv="r1"):
        return {"event_type": "message.part.updated", "conversation_id": conv, "payload": {"sessionID": "ses", "part": part}}
    tool = {"type": "tool", "tool": "bash", "state": {"status": "running", "input": {"command": "pwd", "description": "Print dir"}}}
    assert chat.progress_message("message.part.updated", ev(tool), "r1") == "tool bash running: Print dir"
    assert chat.progress_message("message.part.updated", ev({"type": "text", "text": "All\ndone"}), "r1") == "All done"
    assert chat.progress_message("message.part.updated", ev({"type": "text", "text": "<!-- VIBEFLOW_PROMPT -->\nhi"}), "r1") is None
    assert chat.progress_message("message.part.updated", ev(tool, conv="other"), "r1") is None
    assert chat.progress_message("session.status", ev(tool), "r1") is None


# ---------------------------------------------------------------------- ask

async def test_ask_starts_sandbox_and_conversation(api):
    api.get("/api/v1/projects").mock(return_value=httpx.Response(200, json={"projects": [{"id": "p1"}]}))
    api.get("/api/v1/sessions/status").mock(side_effect=[
        httpx.Response(200, json={"status": "stopped"}),
        httpx.Response(200, json={"status": "running", "session_id": "s1"})])
    api.get("/api/v1/projects/p1").mock(return_value=httpx.Response(200, json={"project_type": "local"}))
    start = api.post("/api/v1/sessions/start").mock(return_value=httpx.Response(200, json={"success": True}))
    api.get("/api/v1/projects/p1/my-recent-task").mock(return_value=httpx.Response(200, json={"task_id": "t1"}))
    run = api.post("/api/v1/runs").mock(return_value=httpx.Response(200, json={"success": True, "run_id": "r9"}))
    api.get("/api/v1/runs/r9").mock(return_value=httpx.Response(200, json={"id": "r9", "status": "idle"}))
    api.get("/api/v1/runs/r9/messages").mock(return_value=httpx.Response(200, json={"messages": [msg("user", "hi"), msg("assistant", "hello")]}))
    out = payload(await chat.vibeflow_ask("hi", agent="reviewer"))
    assert out["outcome"] == "done" and out["reply"] == "hello" and out["run_id"] == "r9"
    assert start.called and body_of(run)["task_id"] == "t1" and body_of(run)["agent_type"] == "reviewer"


# ------------------------------------------------------- human in the loop

async def test_reply_permission_live_session_uses_pod_endpoint(api):
    api.get("/api/v1/runs/r1/pending-prompts").mock(return_value=httpx.Response(200, json={"session_running": True, "pending_prompts": []}))
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    pod = api.post("/sessions/s1/vibeflow/runs/r1/permissions/perm1/reply").mock(return_value=httpx.Response(200, json={"ok": True}))
    await chat.vibeflow_reply_permission("r1", "perm1", "always")
    assert body_of(pod) == {"reply": "always"}


async def test_reply_permission_after_restart_uses_replay(api):
    api.get("/api/v1/runs/r1/pending-prompts").mock(return_value=httpx.Response(200, json={"session_running": False, "pending_prompts": []}))
    replay = api.post("/api/v1/runs/r1/pending-prompts/perm1/replay").mock(return_value=httpx.Response(200, json={}))
    await chat.vibeflow_reply_permission("r1", "perm1", "reject")
    assert body_of(replay) == {"reply": "deny"}


async def test_answer_question_pod_body(api):
    api.get("/api/v1/runs/r1/pending-prompts").mock(return_value=httpx.Response(200, json={"session_running": True}))
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    pod = api.post("/sessions/s1/vibeflow/runs/r1/questions/q1/reply").mock(return_value=httpx.Response(200, json={}))
    await chat.vibeflow_answer_question("r1", "q1", [["PostgreSQL"], ["yes"]])
    assert body_of(pod) == {"answers": [["PostgreSQL"], ["yes"]]}


# ------------------------------------------------------------- management

async def test_fork_body(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"task_id": "t1", "model": "google-starter/gemini-3.7-flash"}))
    fork = api.post("/api/v1/runs").mock(return_value=httpx.Response(200, json={"success": True, "run_id": "r2"}))
    out = payload(await chat.vibeflow_fork_conversation("r1"))
    sent = body_of(fork)
    assert out == {"run_id": "r2", "forked_from": "r1"}
    assert sent["node_type"] == "fork" and sent["forked_from_run_id"] == "r1" and sent["prompt"].startswith("[Forked conversation]")


async def test_abort_uses_run_session(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    abort = api.post("/sessions/s1/vibeflow/runs/r1/abort").mock(return_value=httpx.Response(200, json={"ok": True}))
    await chat.vibeflow_abort("r1")
    assert body_of(abort) == {"reason": "cancelled by user"}


async def test_delete_requires_confirm(api):
    assert payload(await chat.vibeflow_delete_conversation("r1"))["error"] == "confirmation_required"
    route = api.delete("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"ok": True}))
    await chat.vibeflow_delete_conversation("r1", confirm=True)
    assert route.called


async def test_archive_and_pin(api):
    arch = api.patch("/api/v1/runs/r1/archive").mock(return_value=httpx.Response(200, json={}))
    pin = api.post("/api/v1/runs/r1/pin").mock(return_value=httpx.Response(200, json={}))
    await chat.vibeflow_archive_conversation("r1", archived=False)
    await chat.vibeflow_pin_conversation("r1")
    assert arch.calls.last.request.url.params["archive"] == "false" and body_of(pin) == {"pinned": True}


async def test_usage_combines_cost_and_context(api):
    api.get("/api/v1/runs/r1/cost-breakdown").mock(return_value=httpx.Response(200, json={"total": {"cost": 0.03}, "subagent_session_count": 0}))
    api.get("/api/v1/runs/r1/context-usage").mock(return_value=httpx.Response(200, json={"model": "m", "estimatedTotal": 40000, "limit": 1000000, "breakdown": {}}))
    out = payload(await chat.vibeflow_conversation_usage("r1"))
    assert out["cost"] == {"cost": 0.03} and out["context"]["used"] == 40000
