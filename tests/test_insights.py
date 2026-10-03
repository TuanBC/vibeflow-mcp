import httpx
import pytest
import respx

from conftest import API, payload
from vibeflow_mcp.tools import insights


@pytest.fixture
def api(logged_in):
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        yield mock


async def test_month_validation(api):
    assert payload(await insights.vibeflow_project_cost("p1", month="10/2026"))["error"] == "bad_request"


async def test_project_cost_aggregates_breakdowns(api):
    base = "/api/v1/projects/p1/analytics/cost"
    api.get(f"{base}/summary").mock(return_value=httpx.Response(200, json={"summary": {"platform_cost": 0.4}}))
    api.get(f"{base}/users").mock(return_value=httpx.Response(200, json={"items": [{"user_id": "u1"}]}))
    tasks = api.get(f"{base}/tasks").mock(return_value=httpx.Response(200, json={"items": []}))
    api.get(f"{base}/provider-model").mock(return_value=httpx.Response(200, json={"items": [{"model": "m"}]}))
    out = payload(await insights.vibeflow_project_cost("p1", month="2026-10", user_id="u1"))
    assert out == {"month": "2026-10", "summary": {"platform_cost": 0.4}, "by_user": [{"user_id": "u1"}],
                   "by_task": [], "by_model": [{"model": "m"}]}
    assert dict(tasks.calls.last.request.url.params) == {"month": "2026-10", "user_id": "u1"}


async def test_daily_and_code_activity_params(api):
    daily = api.get("/api/v1/projects/p1/analytics/cost/daily").mock(return_value=httpx.Response(200, json={"items": []}))
    act = api.get("/api/v1/projects/p1/analytics/code-activity").mock(return_value=httpx.Response(200, json={}))
    await insights.vibeflow_project_cost_daily("p1", "2026-10-01", "2026-10-03")
    assert dict(daily.calls.last.request.url.params) == {"from": "2026-10-01", "to": "2026-10-03"}
    await insights.vibeflow_code_activity("p1", month="2026-09")
    assert dict(act.calls.last.request.url.params) == {"month": "2026-09"}
    await insights.vibeflow_code_activity("p1", from_date="2026-09-01", to_date="2026-09-30")
    assert dict(act.calls.last.request.url.params) == {"from": "2026-09-01", "to": "2026-09-30"}


async def test_kpis_combine_outcome_and_git(api):
    api.get("/api/v1/projects/p1/analytics/outcome-metrics").mock(
        return_value=httpx.Response(200, json={"metrics": {"task_count": 1}, "constants": {"hours_per_MD": 8}}))
    api.get("/api/v1/projects/p1/analytics/git-kpis").mock(return_value=httpx.Response(200, json={"metrics": {"cost_pr": 0}}))
    out = payload(await insights.vibeflow_project_kpis("p1", month="2026-10"))
    assert out == {"month": "2026-10", "outcome": {"task_count": 1}, "constants": {"hours_per_MD": 8}, "git": {"cost_pr": 0}}


async def test_export_writes_file(api, tmp_path):
    route = api.get("/api/v1/projects/p1/analytics/export").mock(return_value=httpx.Response(200, content=b"PK\x03\x04"))
    out = payload(await insights.vibeflow_export_analytics("p1", str(tmp_path / "r.csv"), month="2026-10"))
    assert out["bytes"] == 4 and dict(route.calls.last.request.url.params) == {"month": "2026-10", "format": "csv"}
