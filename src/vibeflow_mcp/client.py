"""Async HTTP client for the VibeFlow REST API: auth, refresh, errors, SSE."""

from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from . import config
from .auth import TokenStore, browser_login, refresh_tokens
from .errors import ApiError, AuthRequired, VibeFlowError

log = logging.getLogger(__name__)

RELOGIN_COOLDOWN_SECONDS = 120


@dataclass
class SseEvent:
    event: str
    data: Any
    id: str | None = None


class VibeFlowClient:
    def __init__(self, store: TokenStore | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.store = store or TokenStore()
        self._relogin_lock = asyncio.Lock()
        self._last_relogin_failure = -float(RELOGIN_COOLDOWN_SECONDS)
        self._http = httpx.AsyncClient(
            base_url=config.API_URL,
            timeout=httpx.Timeout(60, connect=15),
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------ auth

    async def _recover(self, stale_token: str | None) -> bool:
        """Refresh, then fall back to a silent headless SSO login. Browser logins
        are serialized (they share one browser profile) and not retried for a
        cooldown period after a failure."""
        if await refresh_tokens(self.store, stale_token):
            return True
        if not (config.SILENT_RELOGIN and self.store.email):
            return False
        async with self._relogin_lock:
            if self.store.access_token != stale_token:
                return True  # a concurrent caller already logged in
            if time.monotonic() - self._last_relogin_failure < RELOGIN_COOLDOWN_SECONDS:
                return False
            try:
                await browser_login(self.store, timeout=config.SILENT_LOGIN_TIMEOUT_SECONDS, headless=True)
                return True
            except Exception as exc:
                self._last_relogin_failure = time.monotonic()
                log.warning("Silent re-login failed (%s): %s", type(exc).__name__, exc)
                return False

    async def ensure_token(self) -> str:
        if not self.store.access_token:
            raise AuthRequired()
        left = self.store.seconds_left()
        if left is not None and left < config.REFRESH_MARGIN_SECONDS:
            if not await self._recover(self.store.access_token) and left <= 0:
                raise AuthRequired("VibeFlow session expired and could not be renewed.")
        return self.store.access_token  # type: ignore[return-value]

    # ----------------------------------------------------------- requests

    async def raw(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                  files: Any = None, data: Any = None, headers: dict | None = None,
                  timeout: float | None = None, _retried: bool = False) -> httpx.Response:
        token = await self.ensure_token()
        params = {k: v for k, v in (params or {}).items() if v is not None}
        kw: dict[str, Any] = {}
        if timeout is not None:
            kw["timeout"] = timeout
        try:
            resp = await self._http.request(
                method.upper(), path, params=params or None, json=json, files=files, data=data,
                headers={"Authorization": f"Bearer {token}", **(headers or {})}, **kw,
            )
        except httpx.TimeoutException as exc:
            raise VibeFlowError(f"Timed out calling {path} ({type(exc).__name__}).", code="timeout",
                                hint="The server is slow (often an LLM step); retry shortly.") from exc
        except httpx.HTTPError as exc:
            raise VibeFlowError(f"Network error calling {path}: {type(exc).__name__} {exc}", code="network_error",
                                hint="Check connectivity to api.vibeflow.fptconsulting.co.jp.") from exc
        # Only a 401 with WWW-Authenticate is about OUR session token; other 401s
        # are proxied from upstream services (e.g. a rejected Jira PAT) and must
        # not trigger a refresh / re-login.
        if resp.status_code == 401 and "www-authenticate" in resp.headers:
            if not _retried and await self._recover(token):
                return await self.raw(method, path, params=params, json=json, files=files, data=data,
                                      headers=headers, timeout=timeout, _retried=True)
            raise AuthRequired("VibeFlow rejected the token.", status=401)
        return resp

    @staticmethod
    def _body(resp: httpx.Response) -> Any:
        if "application/json" in resp.headers.get("content-type", ""):
            try:
                return resp.json()
            except ValueError:
                pass
        return resp.text

    async def request(self, method: str, path: str, *, soft_ok: bool = False, **kw: Any) -> Any:
        """Send a request and return the parsed body. Many VibeFlow endpoints
        answer HTTP 200 with {"success": false} / {"ok": false} on failure;
        those raise operation_failed unless soft_ok=True (for endpoints whose
        job is to report a failure, e.g. credential verification)."""
        resp = await self.raw(method, path, **kw)
        body = self._body(resp)
        if resp.status_code >= 400:
            detail = body.get("detail", body) if isinstance(body, dict) else body
            raise ApiError(resp.status_code, method.upper(), path, detail)
        if not soft_ok and isinstance(body, dict) and (body.get("success") is False or body.get("ok") is False):
            message = body.get("message") or body.get("error") or body.get("detail") or "operation failed"
            raise VibeFlowError(f"{method.upper()} {path} reported failure: {message}", code="operation_failed",
                                detail=body)
        return body

    async def get(self, path: str, /, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any = None, /, **params: Any) -> Any:
        return await self.request("POST", path, json=body if body is not None else {}, params=params)

    async def put(self, path: str, body: Any = None) -> Any:
        return await self.request("PUT", path, json=body)

    async def patch(self, path: str, body: Any = None, /, **params: Any) -> Any:
        return await self.request("PATCH", path, json=body, params=params)

    async def delete(self, path: str, /, **params: Any) -> Any:
        return await self.request("DELETE", path, params=params)

    async def get_bytes(self, path: str, /, **params: Any) -> bytes:
        resp = await self.raw("GET", path, params=params, timeout=300)
        if resp.status_code >= 400:
            body = self._body(resp)
            raise ApiError(resp.status_code, "GET", path, body.get("detail", body) if isinstance(body, dict) else body)
        return resp.content

    async def upload(self, path: str, files: list[tuple[str, bytes]], fields: dict[str, str] | None = None) -> Any:
        multipart = [("file", (name, content)) for name, content in files]
        return await self.request("POST", path, files=multipart, data=fields or {}, timeout=300)

    # ---------------------------------------------------------------- SSE

    async def events(self, session_id: str, last_event_id: str | None = None,
                     timeout: float | None = None) -> AsyncIterator[SseEvent]:
        """Stream the sandbox's live event feed (OpenCode bus, proxied)."""
        token = await self.ensure_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
        if last_event_id:
            headers["Last-Event-Id"] = last_event_id
        to = httpx.Timeout(timeout or 60, connect=15, read=timeout or 60)
        async with self._http.stream("GET", f"/sessions/{session_id}/vibeflow/events",
                                     headers=headers, timeout=to) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise ApiError(resp.status_code, "GET", "events", self._body(resp))
            event, data_lines, eid = "", [], None
            async for line in resp.aiter_lines():
                if line == "":
                    if data_lines:
                        event = event or "message"  # SSE default event type
                        raw = "\n".join(data_lines)
                        try:
                            data: Any = jsonlib.loads(raw)
                        except ValueError:
                            data = raw
                        yield SseEvent(event, data, eid)
                    event, data_lines, eid = "", [], None
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip(" "))
                elif line.startswith("id:"):
                    eid = line[3:].strip()
