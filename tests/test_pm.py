import json

import httpx
import pytest
import respx

from conftest import API, payload
from vibeflow_mcp.tools import pm

BOARD = {"project_id": "p1", "columns": [{"id": "c-back", "name": "Backlog", "position": 0, "tasks": []},
                                         {"id": "c-done", "name": "Done", "position": 3, "tasks": []}]}


@pytest.fixture
def api(logged_in):
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/api/v1/kanban/boards").mock(return_value=httpx.Response(200, json=BOARD))
        yield mock


def body_of(route):
    return json.loads(route.calls.last.request.read())


# ----------------------------------------------------------------- projects

async def test_create_git_project_requires_url(api):
    assert payload(await pm.vibeflow_create_project("x", project_type="git"))["error"] == "bad_request"


async def test_create_project_sends_only_set_fields(api):
    route = api.post("/api/v1/projects").mock(return_value=httpx.Response(201, json={"id": "p2"}))
    await pm.vibeflow_create_project("Demo", description="d")
    assert body_of(route) == {"name": "Demo", "description": "d", "project_type": "local"}


async def test_update_project_needs_a_field(api):
    assert payload(await pm.vibeflow_update_project("p1"))["error"] == "bad_request"


async def test_delete_project_requires_confirm(api):
    assert payload(await pm.vibeflow_delete_project("p1"))["error"] == "confirmation_required"


async def test_pin_project_query_param(api):
    route = api.patch("/api/v1/projects/p1/pin").mock(return_value=httpx.Response(200, json={}))
    await pm.vibeflow_pin_project("p1", pinned=False)
    assert route.calls.last.request.url.params["pinned"] == "false"


# ------------------------------------------------------------------ members

async def test_list_members_compacts(api):
    api.get("/api/v1/projects/p1/members").mock(return_value=httpx.Response(200, json={"members": [
        {"user_id": "u1", "user_email": "a@x", "user_display_name": "A", "role": "pm", "id": "m1"}], "total": 1}))
    assert payload(await pm.vibeflow_list_members("p1")) == [{"user_id": "u1", "email": "a@x", "name": "A", "role": "pm"}]


async def test_add_and_update_member(api):
    add = api.post("/api/v1/projects/p1/members").mock(return_value=httpx.Response(201, json={}))
    upd = api.put("/api/v1/projects/p1/members/u2").mock(return_value=httpx.Response(200, json={}))
    await pm.vibeflow_add_member("p1", "u2")
    await pm.vibeflow_update_member_role("p1", "u2", "tl")
    assert body_of(add) == {"user_id": "u2", "role": "member"} and body_of(upd) == {"role": "tl"}


async def test_remove_member_requires_confirm(api):
    assert payload(await pm.vibeflow_remove_member("p1", "u2"))["error"] == "confirmation_required"


# ------------------------------------------------------------------- budget

async def test_set_budget(api):
    assert payload(await pm.vibeflow_set_budget("p1", enabled=True))["error"] == "bad_request"
    route = api.put("/api/v1/projects/p1/budget").mock(return_value=httpx.Response(200, json={}))
    await pm.vibeflow_set_budget("p1", enabled=True, monthly_limit_usd=25)
    assert body_of(route) == {"enabled": True, "monthly_limit": 25}
    await pm.vibeflow_set_budget("p1", enabled=False, monthly_limit_usd=25)
    assert body_of(route) == {"enabled": False, "monthly_limit": None}


# ------------------------------------------------------------------- kanban

async def test_create_kanban_task_resolves_column_name(api):
    route = api.post("/api/v1/kanban/tasks").mock(return_value=httpx.Response(201, json={"id": "k1"}))
    await pm.vibeflow_create_kanban_task("p1", "Fix login", column="backlog", priority="high", story_points=3)
    assert body_of(route) == {"project_id": "p1", "name": "Fix login", "priority": "high", "story_points": 3,
                              "column_id": "c-back"}


async def test_unknown_column_lists_choices(api):
    out = payload(await pm.vibeflow_move_kanban_task("p1", "k1", "Review"))
    assert out["error"] == "bad_request" and "Backlog" in out["hint"]


async def test_move_assign_archive(api):
    move = api.put("/api/v1/kanban/tasks/k1/move").mock(return_value=httpx.Response(200, json={}))
    assign = api.put("/api/v1/kanban/tasks/k1/assign").mock(return_value=httpx.Response(200, json={}))
    arch = api.patch("/api/v1/kanban/tasks/k1/unarchive").mock(return_value=httpx.Response(200, json={}))
    await pm.vibeflow_move_kanban_task("p1", "k1", "c-done", position=2)
    await pm.vibeflow_assign_kanban_task("k1")
    await pm.vibeflow_archive_kanban_task("k1", archived=False)
    assert body_of(move) == {"column_id": "c-done", "position": 2}
    assert body_of(assign) == {"assignee_id": None} and arch.called


async def test_delete_kanban_requires_confirm(api):
    assert payload(await pm.vibeflow_delete_kanban_task("k1"))["error"] == "confirmation_required"


# ------------------------------------------------------------ attachments

async def test_add_attachment_validates_and_uploads(api, tmp_path):
    assert payload(await pm.vibeflow_add_attachment("t1", str(tmp_path / "nope.pdf")))["error"] == "bad_request"
    f = tmp_path / "rfp.pdf"
    f.write_bytes(b"%PDF-1.4")
    route = api.post("/api/v1/tasks/t1/attachments").mock(return_value=httpx.Response(201, json={"id": "a1"}))
    await pm.vibeflow_add_attachment("t1", str(f))
    assert b'filename="rfp.pdf"' in route.calls.last.request.read()


# ---------------------------------------------------------------- templates

async def test_prompt_templates_are_summarized(api):
    api.get("/api/v1/templates/prompts").mock(return_value=httpx.Response(200, json={
        "categories": [{"id": "dev"}], "quickActions": [],
        "templates": [{"id": "t", "name": "Review", "category": "dev", "agent": "reviewer", "variables": ["file"],
                       "isBuiltIn": True, "prompt": "long", "description": "d"}]}))
    out = payload(await pm.vibeflow_list_prompt_templates())
    assert out["categories"] == ["dev"] and "prompt" not in out["templates"][0]


async def test_agent_template_uses_system_prompt_key(api):
    route = api.post("/api/v1/projects/p1/templates/agents").mock(return_value=httpx.Response(201, json={}))
    await pm.vibeflow_create_agent_template("p1", "qa-bot", "You test things.", color="#fff")
    assert body_of(route) == {"name": "qa-bot", "systemPrompt": "You test things.", "color": "#fff"}


async def test_workflow_template_create_and_import(api):
    create = api.post("/api/v1/projects/p1/templates/workflows").mock(return_value=httpx.Response(201, json={}))
    imp = api.post("/api/v1/projects/p1/templates/workflows/import").mock(return_value=httpx.Response(201, json={}))
    wf = {"nodes": [{"id": "n1", "agentType": "tester"}], "edges": []}
    await pm.vibeflow_create_workflow_template("p1", "QA", wf)
    await pm.vibeflow_import_workflow_template("p1", "QA copy", wf)
    assert body_of(create) == {"name": "QA", "icon": "Workflow", "color": "#3B82F6", "workflow_json": wf}
    assert body_of(imp)["workflow"] == wf


# ------------------------------------------------------------------- canvas

async def test_save_workflow_validates_and_wraps(api):
    assert payload(await pm.vibeflow_save_workflow("t1", {"edges": []}))["error"] == "bad_request"
    route = api.put("/api/v1/workflows/t1").mock(return_value=httpx.Response(200, json={}))
    await pm.vibeflow_save_workflow("t1", {"nodes": [], "edges": []})
    assert body_of(route) == {"workflow": {"nodes": [], "edges": []}}


async def test_run_workflow_and_step(api):
    runs = api.post("/api/v1/runs").mock(return_value=httpx.Response(200, json={"run_id": "r1"}))
    step = api.post("/api/v1/runs/step").mock(return_value=httpx.Response(200, json={"run_id": "r2"}))
    await pm.vibeflow_run_workflow("t1", start_from_node_id="n2")
    await pm.vibeflow_run_workflow_step("t1", "n3")
    assert body_of(runs) == {"task_id": "t1", "start_from_node_id": "n2"} and body_of(step) == {"task_id": "t1", "node_id": "n3"}


# ------------------------------------------------------------- integrations

async def test_git_credential_never_echoes_token(api):
    api.post("/api/v1/git-credentials").mock(return_value=httpx.Response(201, json={"id": "g1", "has_token": True, "git_token": "SECRET"}))
    out = payload(await pm.vibeflow_add_git_credential("github", "SECRET"))
    assert "git_token" not in out and out["id"] == "g1"


async def test_configure_jira_creates_when_missing_else_updates(api):
    get = api.get("/api/v1/projects/p1/jira-sync").mock(side_effect=[
        httpx.Response(404, json={"detail": "No Jira sync configured"}), httpx.Response(200, json={"jira_project_key": "AB"})])
    create = api.post("/api/v1/projects/p1/jira-sync").mock(return_value=httpx.Response(201, json={}))
    update = api.put("/api/v1/projects/p1/jira-sync").mock(return_value=httpx.Response(200, json={}))
    await pm.vibeflow_configure_jira_sync("p1", "pat", "AB", site_id="jira3")
    await pm.vibeflow_configure_jira_sync("p1", "pat", "AB")
    assert body_of(create) == {"pat": "pat", "jira_project_key": "AB", "site_id": "jira3"} and update.called and get.call_count == 2


async def test_sharepoint_missing_source_is_none(api):
    api.get("/api/v1/users/me/integrations/sharepoint").mock(return_value=httpx.Response(200, json={"connected": False}))
    api.get("/api/v1/projects/p1/sharepoint-source").mock(return_value=httpx.Response(404, json={"detail": "No SharePoint source"}))
    assert payload(await pm.vibeflow_get_sharepoint("p1")) == {"integration": {"connected": False}, "project_source": None}


async def test_update_settings_needs_field(api):
    assert payload(await pm.vibeflow_update_settings())["error"] == "bad_request"
