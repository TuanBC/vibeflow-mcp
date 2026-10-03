"""Administration toolset ("admin", opt-in): users, platform LLM providers and
budgets, audit, DLP, sessions, system health and org-wide analytics.

Requires a system admin role; for other users the API answers 403, which is
reported with a clear hint. Kept to a few parameterised tools so enabling the
toolset does not flood the client with ~40 near-identical tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from ..app import client, require_confirm, tool
from ..errors import ApiError, VibeFlowError
from .insights import _month

ADMIN = "/api/v1/admin"


async def _admin(method: str, path: str, **kw: Any) -> Any:
    try:
        return await client.request(method, ADMIN + path, **kw)
    except ApiError as exc:
        if exc.code == "forbidden":
            raise VibeFlowError(f"Admin endpoint {path} refused: your account lacks the required system role.",
                                code="forbidden", status=403,
                                hint="Admin tools need a VibeFlow system admin; check vibeflow_whoami().") from exc
        raise


Resource = Literal["overview", "health", "users", "pending_users", "projects", "sessions", "conversations",
                   "providers", "user_keys", "platform_config", "overrides", "dlp_catalog", "dlp_findings",
                   "capacity", "metrics"]

_RESOURCES: dict[str, str] = {
    "overview": "/overview", "health": "/system/health", "users": "/users", "pending_users": "/users",
    "projects": "/projects", "sessions": "/sessions", "conversations": "/conversations",
    "providers": "/platform/providers", "user_keys": "/platform/user-keys", "platform_config": "/platform/config",
    "overrides": "/platform/overrides", "dlp_catalog": "/dlp/catalog", "dlp_findings": "/dlp/findings",
    "capacity": "/capacity/report", "metrics": "/system/metrics",
}


@tool("admin", read_only=True)
async def vibeflow_admin_list(resource: Resource, params: dict[str, Any] | None = None) -> Any:
    """Read an admin resource. Useful params - users: status, q, sort_by,
    sort_order, page, limit; projects: status, jira, search, page, limit;
    conversations: since, until, status, search, archived; dlp_findings:
    session_id, since, page, limit; metrics: period (e.g. '24h', '7d')."""
    params = dict(params or {})
    if resource == "pending_users":
        params.setdefault("status", "pending")
    if resource == "metrics":
        params.setdefault("period", "24h")
    return await _admin("GET", _RESOURCES[resource], params=params)


Report = Literal["filters", "cost_daily", "cost_projects", "cost_users", "cost_tasks", "cost_provider_model",
                 "code_activity", "git_kpis", "outcome_metrics", "infra_cost", "infra_cost_projects",
                 "infra_session_resources"]


def report_path(report: str) -> str:
    special = {"infra_cost": "infra-cost", "infra_cost_projects": "infra-cost/projects",
               "infra_session_resources": "infra-cost/session-resources"}
    return "/analytics/" + special.get(report, report.replace("cost_", "cost/", 1).replace("_", "-"))


@tool("admin", read_only=True)
async def vibeflow_admin_analytics(report: Report, month: str | None = None, from_date: str | None = None,
                                   to_date: str | None = None, project_id: str | None = None,
                                   user_id: str | None = None) -> Any:
    """Org-wide analytics. Monthly reports take month (YYYY-MM); cost_daily
    and code_activity accept from_date/to_date (YYYY-MM-DD) instead."""
    params: dict[str, Any] = {"project_id": project_id, "user_id": user_id}
    if report != "filters":
        if from_date and to_date and report in ("cost_daily", "code_activity"):
            params.update({"from": from_date, "to": to_date})
        else:
            params["month"] = _month(month)
    return await _admin("GET", report_path(report), params={k: v for k, v in params.items() if v is not None})


UserAction = Literal["approve", "revoke_approval", "activate", "deactivate", "set_role"]


@tool("admin", destructive=True)
async def vibeflow_admin_user(user_id: str, action: UserAction, system_role_id: str | None = None,
                              confirm: bool = False) -> Any:
    """Manage a user: approve / revoke_approval (whitelist), activate /
    deactivate, or set_role (system_role_id from vibeflow_list_roles('system'),
    None to clear). Requires confirm=true."""
    require_confirm(confirm, f"admin user {action}")
    if action in ("approve", "revoke_approval"):
        return await _admin("PUT", f"/users/{user_id}/whitelist", json={"is_whitelisted": action == "approve"})
    if action in ("activate", "deactivate"):
        return await _admin("PUT", f"/users/{user_id}/activate", json={"is_active": action == "activate"})
    return await _admin("PUT", f"/users/{user_id}/role", json={"system_role_id": system_role_id})


@tool("admin", destructive=True)
async def vibeflow_admin_import_users(emails: list[str], confirm: bool = False) -> Any:
    """Pre-approve (whitelist) users by email. Requires confirm=true."""
    require_confirm(confirm, "import users")
    return await _admin("POST", "/users/import", json={"emails": emails})


@tool("admin", destructive=True)
async def vibeflow_admin_archive_project(project_id: str, confirm: bool = False) -> Any:
    """Toggle a project's archived state (admin). Requires confirm=true."""
    require_confirm(confirm, "archive project")
    return await _admin("POST", f"/projects/{project_id}/archive")


@tool("admin", destructive=True)
async def vibeflow_admin_stop_session(session_id: str, confirm: bool = False) -> Any:
    """Force-stop any user's sandbox session. Requires confirm=true."""
    require_confirm(confirm, "stop a user's session")
    return await _admin("POST", f"/sessions/{session_id}/stop")


@tool("admin", idempotent=True)
async def vibeflow_admin_flag_conversation(run_id: str, flagged: bool = True) -> Any:
    """Flag or unflag a conversation for audit review."""
    return await _admin("PATCH", f"/conversations/{run_id}/flag", json={"flagged": flagged})


ProviderAction = Literal["create", "update", "delete", "probe", "sync_models", "set_shared_key",
                         "revoke_all_keys", "delete_all_keys"]


@tool("admin", destructive=True)
async def vibeflow_admin_provider(action: ProviderAction, provider_id: str | None = None,
                                  body: dict[str, Any] | None = None, api_key: str | None = None,
                                  confirm: bool = False) -> Any:
    """Manage platform LLM providers (the shared 'starter' models):
    create/probe (body = provider config), update (body = fields), delete,
    sync_models, set_shared_key (api_key), revoke_all_keys / delete_all_keys
    (per-user keys). Requires confirm=true except probe."""
    if action != "probe":
        require_confirm(confirm, f"provider {action}")
    if action in ("create", "probe"):
        return await _admin("POST", "/platform/providers" + ("/probe" if action == "probe" else ""), json=body or {})
    if not provider_id:
        raise VibeFlowError(f"provider_id is required for {action}.", code="bad_request")
    base = f"/platform/providers/{provider_id}"
    if action == "update":
        return await _admin("PATCH", base, json=body or {})
    if action == "delete":
        return await _admin("DELETE", base)
    if action == "set_shared_key":
        return await _admin("PATCH", f"{base}/shared-key", json={"api_key": api_key})
    return await _admin("POST", f"{base}/{action.replace('_', '-')}", json={})


@tool("admin", destructive=True)
async def vibeflow_admin_user_key(user_id: str, action: str, confirm: bool = False) -> Any:
    """Act on a user's platform key (action as listed by
    vibeflow_admin_list('user_keys'), e.g. revoke / reissue). Requires confirm=true."""
    require_confirm(confirm, f"user key {action}")
    return await _admin("POST", f"/platform/user-keys/{user_id}/{action}", json={})


@tool("admin", destructive=True)
async def vibeflow_admin_set_budget(total_monthly_limit_usd: float | None = None,
                                    user_id: str | None = None, user_monthly_limit_usd: float | None = None,
                                    confirm: bool = False) -> Any:
    """Platform budgets: the org-wide starter-kit monthly limit, and/or a
    per-user monthly override (user_id + user_monthly_limit_usd; None clears).
    Requires confirm=true."""
    require_confirm(confirm, "change platform budget")
    out: dict[str, Any] = {}
    if total_monthly_limit_usd is not None:
        out["platform"] = await _admin("PUT", "/platform/config", json={"total_monthly_limit_usd": total_monthly_limit_usd})
    if user_id:
        out["user"] = await _admin("PUT", f"/platform/usage/{user_id}/override",
                                   json={"monthly_limit_usd": user_monthly_limit_usd})
    if not out:
        raise VibeFlowError("Nothing to change.", code="bad_request")
    return out


@tool("admin", read_only=True)
async def vibeflow_admin_dlp_test(sample: str) -> Any:
    """Run the DLP (data-loss prevention) rules against sample text."""
    return await _admin("POST", "/dlp/tester", json={"sample": sample})


@tool("admin")
async def vibeflow_admin_export(kind: Literal["conversations", "analytics"], local_path: str,
                                params: dict[str, Any] | None = None) -> Any:
    """Download an admin export: conversations (params: since, until, status,
    search, archived) or monthly analytics (params: month, format csv|pdf, project_id)."""
    params = dict(params or {})
    if kind == "analytics":
        params["month"] = _month(params.get("month"))
        params.setdefault("format", "csv")
    path = "/conversations/export" if kind == "conversations" else "/analytics/export"
    try:
        data = await client.get_bytes(ADMIN + path, **params)
    except ApiError as exc:
        if exc.code == "forbidden":
            raise VibeFlowError("Export refused: admin role required.", code="forbidden", status=403) from exc
        raise
    dest = Path(local_path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"saved": str(dest), "bytes": len(data)}
