"""Async HTTP client for the VibeFlow REST API with automatic token refresh."""

from __future__ import annotations

from typing import Any

import httpx

from . import config
from .auth import AuthError, TokenStore, refresh_tokens


class ApiError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, detail: Any):
        self.status, self.detail = status, detail
        super().__init__(f"{method} {path} -> HTTP {status}: {detail}")


class VibeFlowClient:
    def __init__(self, store: TokenStore | None = None) -> None:
        self.store = store or TokenStore()
        self._http = httpx.AsyncClient(
            base_url=config.API_URL,
            timeout=httpx.Timeout(60, connect=15),
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _ensure_token(self) -> str:
        if not self.store.access_token:
            raise AuthError("Not logged in. Call the vibeflow_login tool first.")
        left = self.store.seconds_left()
        if left is not None and left < config.REFRESH_MARGIN_SECONDS:
            if not await refresh_tokens(self.store) and left <= 0:
                raise AuthError("Session expired and refresh failed. Call vibeflow_login again.")
        return self.store.access_token  # type: ignore[return-value]

    async def raw(self, method: str, path: str, *, params: dict | None = None,
                  json: Any = None, files: Any = None, data: Any = None,
                  _retried: bool = False) -> httpx.Response:
        token = await self._ensure_token()
        params = {k: v for k, v in (params or {}).items() if v is not None}
        resp = await self._http.request(
            method.upper(), path, params=params or None, json=json, files=files, data=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401 and not _retried and await refresh_tokens(self.store):
            return await self.raw(method, path, params=params, json=json, files=files,
                                  data=data, _retried=True)
        return resp

    async def request(self, method: str, path: str, **kw: Any) -> Any:
        resp = await self.raw(method, path, **kw)
        ctype = resp.headers.get("content-type", "")
        body: Any = resp.json() if "application/json" in ctype else resp.text
        if resp.status_code >= 400:
            detail = body.get("detail", body) if isinstance(body, dict) else body
            raise ApiError(resp.status_code, method.upper(), path, detail)
        return body

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any = None, **params: Any) -> Any:
        return await self.request("POST", path, json=body if body is not None else {}, params=params)

    async def put(self, path: str, body: Any = None) -> Any:
        return await self.request("PUT", path, json=body)

    async def patch(self, path: str, body: Any = None, **params: Any) -> Any:
        return await self.request("PATCH", path, json=body, params=params)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)
