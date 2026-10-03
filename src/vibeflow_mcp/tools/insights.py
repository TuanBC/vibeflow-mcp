"""Analytics toolset ("analytics"): project cost, KPIs, code activity, report export."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Literal

from ..app import client, tool
from ..errors import VibeFlowError


def this_month() -> str:
    return dt.date.today().strftime("%Y-%m")


def _month(month: str | None) -> str:
    month = month or this_month()
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise VibeFlowError(f"month must be YYYY-MM, got '{month}'.", code="bad_request") from exc
    return month


Breakdown = Literal["summary", "users", "tasks", "models", "all"]


@tool("analytics", read_only=True)
async def vibeflow_project_cost(project_id: str, month: str | None = None, breakdown: Breakdown = "all",
                                user_id: str | None = None) -> Any:
    """LLM spend for a project in a month (YYYY-MM, default current): summary
    (project / personal / platform cost, tokens, steps) and breakdowns by
    user, task and provider/model. user_id narrows the task breakdown."""
    month = _month(month)
    base = f"/api/v1/projects/{project_id}/analytics/cost"
    out: dict[str, Any] = {"month": month}
    if breakdown in ("summary", "all"):
        out["summary"] = (await client.get(f"{base}/summary", month=month)).get("summary")
    if breakdown in ("users", "all"):
        out["by_user"] = (await client.get(f"{base}/users", month=month)).get("items", [])
    if breakdown in ("tasks", "all"):
        out["by_task"] = (await client.get(f"{base}/tasks", month=month, user_id=user_id)).get("items", [])
    if breakdown in ("models", "all"):
        out["by_model"] = (await client.get(f"{base}/provider-model", month=month)).get("items", [])
    return out


@tool("analytics", read_only=True)
async def vibeflow_project_cost_daily(project_id: str, from_date: str, to_date: str) -> Any:
    """Daily cost series for a project between two dates (YYYY-MM-DD, inclusive)."""
    return await client.get(f"/api/v1/projects/{project_id}/analytics/cost/daily", **{"from": from_date, "to": to_date})


@tool("analytics", read_only=True)
async def vibeflow_project_kpis(project_id: str, month: str | None = None, user_id: str | None = None) -> Any:
    """Outcome metrics (cost of completed vs abandoned tasks, story points,
    estimate/remaining hours, man-month constants) and git KPIs (token/cost
    split between work that reached a PR and abandoned work) for a month."""
    month = _month(month)
    base = f"/api/v1/projects/{project_id}/analytics"
    outcome = await client.get(f"{base}/outcome-metrics", month=month, user_id=user_id)
    git = await client.get(f"{base}/git-kpis", month=month)
    return {"month": month, "outcome": outcome.get("metrics"), "constants": outcome.get("constants"),
            "git": git.get("metrics")}


@tool("analytics", read_only=True)
async def vibeflow_code_activity(project_id: str, month: str | None = None, from_date: str | None = None,
                                 to_date: str | None = None) -> Any:
    """Lines added/removed, files changed and agent runs - totals, per member
    and per day. Either month (YYYY-MM) or from_date/to_date (YYYY-MM-DD)."""
    params: dict[str, Any] = {"from": from_date, "to": to_date} if from_date and to_date else {"month": _month(month)}
    return await client.get(f"/api/v1/projects/{project_id}/analytics/code-activity", **params)


@tool("analytics")
async def vibeflow_export_analytics(project_id: str, local_path: str, month: str | None = None,
                                    format: Literal["csv", "pdf"] = "csv") -> Any:
    """Download the project's monthly analytics report to a local file."""
    data = await client.get_bytes(f"/api/v1/projects/{project_id}/analytics/export",
                                  month=_month(month), format=format)
    dest = Path(local_path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"saved": str(dest), "bytes": len(data)}
