import json

import httpx
import pytest
import respx

from conftest import API, payload
from vibeflow_mcp import app
from vibeflow_mcp.tools import advanced


@pytest.fixture
def api(logged_in):
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/api/v1/sessions/status").mock(return_value=httpx.Response(200, json={"status": "running", "session_id": "s1"}))
        mock.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"id": "r1", "session_id": "s1", "code_session_id": "ses_1"}))
        yield mock


def body_of(route):
    return json.loads(route.calls.last.request.read())


async def test_code_intel_body_and_result(api):
    route = api.post("/sessions/s1/vibeflow/lsp/hover").mock(return_value=httpx.Response(200, json={"ok": True, "result": {"contents": "def f()"}}))
    out = payload(await advanced.vibeflow_code_intel("p1", "hover", "app.py", line=3, character=4))
    assert out == {"contents": "def f()"}
    assert body_of(route) == {"workdir": "/workspace", "file": "app.py", "line": 3, "character": 4}


async def test_code_intel_failure_hint(api):
    api.post("/sessions/s1/vibeflow/lsp/definition").mock(return_value=httpx.Response(200, json={"ok": False, "error": "no server"}))
    out = payload(await advanced.vibeflow_code_intel("p1", "definition", "app.py"))
    assert out["error"] == "bad_request" and "starting" in out["hint"]


async def test_code_graph_summary_and_indexing(api):
    route = api.get("/sessions/s1/vibeflow/graph/layout")
    route.mock(return_value=httpx.Response(202))
    assert payload(await advanced.vibeflow_code_graph("p1"))["status"] == "indexing"
    route.mock(return_value=httpx.Response(200, json={"total_nodes": 900, "nodes": [
        {"id": 1, "label": "File", "name": "app.py", "file_path": "app.py"},
        {"id": 2, "label": "Function", "name": "main", "file_path": "app.py"}],
        "edges": [{"source": 1, "target": 2, "type": "DEFINES"}]}))
    out = payload(await advanced.vibeflow_code_graph("p1"))
    assert out["total_nodes"] == 900 and out["node_kinds"] == {"File": 1, "Function": 1}
    assert out["edge_types"] == {"DEFINES": 1} and out["most_connected"][0]["node"] in ("File app.py", "Function main (app.py)")


async def test_goal_uses_opencode_session_and_handles_no_goal(api):
    route = api.get("/sessions/s1/vibeflow/goal").mock(return_value=httpx.Response(404, json={"error": "no goal set"}))
    assert payload(await advanced.vibeflow_goal_status("r1")) is None
    assert dict(route.calls.last.request.url.params) == {"sessionID": "ses_1"}
    stop = api.post("/sessions/s1/vibeflow/goal").mock(return_value=httpx.Response(200, json={"ok": True}))
    await advanced.vibeflow_goal_stop("r1")
    assert body_of(stop) == {"op": "stop", "sessionID": "ses_1", "run_id": "r1"}


async def test_memory_splits_work_logs_and_recall(api):
    route = api.post("/sessions/s1/vibeflow/memory")
    route.mock(return_value=httpx.Response(200, json={"rows": [{"name": "stack"}, {"name": "conv-abc"}]}))
    assert payload(await advanced.vibeflow_agent_memory("p1")) == {"memory": [{"name": "stack"}], "work_logs": [{"name": "conv-abc"}]}
    route.mock(return_value=httpx.Response(200, json={"found": False}))
    assert payload(await advanced.vibeflow_agent_memory("p1", name="nope"))["error"] == "not_found"


async def test_sandbox_mcp_servers(api):
    api.get("/sessions/s1/mcp").mock(return_value=httpx.Response(200, json={"vibegraph-mcp": {"status": "connected"}, "x": {}}))
    assert payload(await advanced.vibeflow_sandbox_mcp_servers("p1")) == [
        {"name": "vibegraph-mcp", "status": "connected"}, {"name": "x", "status": "connected"}]


async def test_background_job_body(api):
    route = api.post("/sessions/s1/vibeflow/runs/r1/jobs/background").mock(return_value=httpx.Response(200, json={}))
    await advanced.vibeflow_background_tool_call("r1", "call_9")
    assert body_of(route) == {"callID": "call_9"}


async def test_resources_and_prompts_registered():
    templates = {t.uriTemplate for t in await app.mcp.list_resource_templates()}
    assert "vibeflow://runs/{run_id}/transcript" in templates and "vibeflow://projects/{project_id}/overview" in templates
    prompts = {p.name for p in await app.mcp.list_prompts()}
    assert {"vibeflow_bug_fix", "vibeflow_code_review", "vibeflow_rfp_to_demo"} <= prompts
    msgs = await app.mcp.get_prompt("vibeflow_bug_fix", {"project_id": "p1", "request": "500 on login"})
    text = msgs.messages[0].content.text
    assert 'workflow="builtin-bug-fix"' in text and "500 on login" in text


async def test_messages_resource_renders(api):
    api.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [
        {"role": "user", "parts": [{"type": "text", "text": "hi"}]}]}))
    contents = list(await app.mcp.read_resource("vibeflow://runs/r1/messages"))
    assert "### user\nhi" in contents[0].content
