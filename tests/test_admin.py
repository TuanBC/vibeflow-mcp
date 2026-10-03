import json

import httpx
import pytest
import respx

from conftest import API, payload
from vibeflow_mcp.tools import admin


@pytest.fixture
def api(logged_in):
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        yield mock


def body_of(route):
    return json.loads(route.calls.last.request.read())


@pytest.mark.parametrize("report,path", [
    ("cost_daily", "/analytics/cost/daily"), ("cost_provider_model", "/analytics/cost/provider-model"),
    ("code_activity", "/analytics/code-activity"), ("git_kpis", "/analytics/git-kpis"),
    ("infra_cost_projects", "/analytics/infra-cost/projects"), ("filters", "/analytics/filters")])
def test_report_paths(report, path):
    assert admin.report_path(report) == path


async def test_forbidden_has_role_hint(api):
    api.get("/api/v1/admin/overview").mock(return_value=httpx.Response(403, json={"detail": "Forbidden"}))
    out = payload(await admin.vibeflow_admin_list("overview"))
    assert out["error"] == "forbidden" and "system admin" in out["hint"]


async def test_pending_users_defaults(api):
    route = api.get("/api/v1/admin/users").mock(return_value=httpx.Response(200, json={"users": []}))
    await admin.vibeflow_admin_list("pending_users", {"page": 2})
    assert dict(route.calls.last.request.url.params) == {"page": "2", "status": "pending"}


@pytest.mark.parametrize("action,path,body", [
    ("approve", "/whitelist", {"is_whitelisted": True}),
    ("revoke_approval", "/whitelist", {"is_whitelisted": False}),
    ("deactivate", "/activate", {"is_active": False}),
    ("set_role", "/role", {"system_role_id": "r9"}),
])
async def test_user_actions(api, action, path, body):
    assert payload(await admin.vibeflow_admin_user("u1", action))["error"] == "confirmation_required"
    route = api.put(f"/api/v1/admin/users/u1{path}").mock(return_value=httpx.Response(200, json={}))
    await admin.vibeflow_admin_user("u1", action, system_role_id="r9", confirm=True)
    assert body_of(route) == body


async def test_provider_routing(api):
    probe = api.post("/api/v1/admin/platform/providers/probe").mock(return_value=httpx.Response(200, json={}))
    key = api.patch("/api/v1/admin/platform/providers/pv1/shared-key").mock(return_value=httpx.Response(200, json={}))
    sync = api.post("/api/v1/admin/platform/providers/pv1/sync-models").mock(return_value=httpx.Response(200, json={}))
    await admin.vibeflow_admin_provider("probe", body={"kind": "openai"})  # probe needs no confirm
    await admin.vibeflow_admin_provider("set_shared_key", "pv1", api_key="k", confirm=True)
    await admin.vibeflow_admin_provider("sync_models", "pv1", confirm=True)
    assert probe.called and body_of(key) == {"api_key": "k"} and sync.called
    assert payload(await admin.vibeflow_admin_provider("delete", confirm=True))["error"] == "bad_request"


async def test_budget(api):
    assert payload(await admin.vibeflow_admin_set_budget(confirm=True))["error"] == "bad_request"
    cfg = api.put("/api/v1/admin/platform/config").mock(return_value=httpx.Response(200, json={}))
    ovr = api.put("/api/v1/admin/platform/usage/u1/override").mock(return_value=httpx.Response(200, json={}))
    await admin.vibeflow_admin_set_budget(total_monthly_limit_usd=500, user_id="u1", user_monthly_limit_usd=None, confirm=True)
    assert body_of(cfg) == {"total_monthly_limit_usd": 500} and body_of(ovr) == {"monthly_limit_usd": None}
