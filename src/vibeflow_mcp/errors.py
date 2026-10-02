"""Error model: every failure surfaces to the MCP client as
{"error": <code>, "message": ..., "hint": ..., "status": ...}."""

from __future__ import annotations

from typing import Any


class VibeFlowError(Exception):
    code = "error"

    def __init__(self, message: str, *, code: str | None = None, hint: str | None = None,
                 status: int | None = None, detail: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.hint = hint
        self.status = status
        self.detail = detail

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        if self.status is not None:
            payload["status"] = self.status
        return payload


class AuthRequired(VibeFlowError):
    code = "auth_required"

    def __init__(self, message: str = "Not logged in to VibeFlow.", **kw: Any):
        kw.setdefault("hint", "Call vibeflow_login to sign in with Microsoft SSO.")
        super().__init__(message, **kw)


class ConfirmationRequired(VibeFlowError):
    code = "confirmation_required"


class ApiError(VibeFlowError):
    """Non-2xx API response, classified into a stable error code."""

    def __init__(self, status: int, method: str, path: str, detail: Any):
        code, hint = classify(status, detail)
        super().__init__(f"{method} {path} -> HTTP {status}: {_detail_text(detail)}",
                         code=code, hint=hint, status=status, detail=detail)


def _detail_text(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("error") or detail)
    return str(detail)[:500]


def classify(status: int, detail: Any) -> tuple[str, str | None]:
    text = _detail_text(detail).lower()
    retry = detail.get("retry_after_seconds") if isinstance(detail, dict) else None
    if text == "pending_approval":
        return "pending_approval", "Your VibeFlow account is awaiting admin approval."
    if text == "account_disabled":
        return "account_disabled", "Your VibeFlow account is disabled; contact an administrator."
    if "no running session" in text or "start a vibe session" in text:
        return "no_session", "Start the sandbox first: vibeflow_start_session(project_id), then retry."
    if ("quota" in text or "budget" in text) and status in (402, 403, 429):
        return "quota_exceeded", "Check vibeflow_get_quota / the project budget."
    if status == 401:
        return "unauthorized", "Session expired. Call vibeflow_login."
    if status == 403:
        return "forbidden", "Your role does not allow this action."
    if status == 404:
        return "not_found", None
    if status in (409, 423, 429) or retry:
        wait = f" Retry in ~{retry}s." if retry else ""
        return "busy", f"The resource is busy (e.g. sandbox still sealing or agent working).{wait}"
    if status in (400, 422):
        return "bad_request", None
    if status >= 500:
        return "server_error", "VibeFlow server error; retry later."
    return "http_error", None
