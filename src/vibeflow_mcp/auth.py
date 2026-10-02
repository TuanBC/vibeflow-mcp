"""SSO token capture and lifecycle.

VibeFlow auth flow (reverse-engineered from the SPA bundle):
  1. MSAL.js loginRedirect against Azure AD (tenant f01e930a-..., client 3e0b9c91-...).
  2. SPA POSTs {id_token, graph_access_token} to /api/v1/auth/azure/token.
  3. API returns a VibeFlow JWT (8h) + refresh token; SPA persists them in
     localStorage["vibeflow-auth"] as {state: {user, tokens, isAuthenticated}}.
  4. Refresh: POST /api/v1/auth/azure/refresh {refresh_token} (+ Bearer old token).

The Azure app registration only allows the SPA redirect URI, so instead of
running our own OAuth flow we drive a real browser through the normal login
and lift the VibeFlow tokens out of localStorage once the SPA has them.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import httpx

from . import config


class AuthError(RuntimeError):
    pass


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode JWT claims without verifying the signature (local expiry checks only)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise AuthError("Access token is not a valid JWT") from exc


class TokenStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] | None = None

    def load(self) -> dict[str, Any] | None:
        if self._data is None and config.TOKEN_FILE.exists():
            self._data = json.loads(config.TOKEN_FILE.read_text(encoding="utf-8"))
        return self._data

    def save(self, tokens: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.load() or {}
        data = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token") or current.get("refresh_token", ""),
            "token_type": tokens.get("token_type", "bearer"),
            "expires_in": tokens.get("expires_in"),
            "saved_at": int(time.time()),
            "user": user or current.get("user"),
        }
        config.HOME.mkdir(parents=True, exist_ok=True)
        config.TOKEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(config.TOKEN_FILE, 0o600)
        except OSError:
            pass
        self._data = data
        return data

    def clear(self) -> None:
        self._data = None
        if config.TOKEN_FILE.exists():
            config.TOKEN_FILE.unlink()

    @property
    def access_token(self) -> str | None:
        data = self.load()
        return data["access_token"] if data else None

    def seconds_left(self) -> int | None:
        token = self.access_token
        if not token:
            return None
        exp = decode_jwt(token).get("exp")
        return int(exp - time.time()) if exp else None

    def status(self) -> dict[str, Any]:
        data = self.load()
        if not data:
            return {"authenticated": False, "token_file": str(config.TOKEN_FILE)}
        claims = decode_jwt(data["access_token"])
        left = self.seconds_left()
        return {
            "authenticated": left is not None and left > 0,
            "email": claims.get("email"),
            "role": claims.get("role"),
            "expires_at": claims.get("exp"),
            "seconds_left": left,
            "has_refresh_token": bool(data.get("refresh_token")),
            "token_file": str(config.TOKEN_FILE),
        }


async def refresh_tokens(store: TokenStore) -> bool:
    """Exchange the stored refresh token for a new access token. Returns success."""
    data = store.load()
    if not data or not data.get("refresh_token"):
        return False
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": config.USER_AGENT}) as http:
        resp = await http.post(
            f"{config.API_URL}/api/v1/auth/azure/refresh",
            json={"refresh_token": data["refresh_token"]},
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
    if resp.status_code != 200:
        return False
    body = resp.json()
    if not body.get("access_token"):
        return False
    store.save(body, body.get("user"))
    return True


_READ_AUTH_JS = f"""() => {{
  const raw = localStorage.getItem({json.dumps(config.AUTH_STORAGE_KEY)});
  if (!raw) return null;
  try {{
    const s = JSON.parse(raw).state || {{}};
    return s.tokens && s.tokens.access_token ? {{tokens: s.tokens, user: s.user}} : null;
  }} catch (e) {{ return null; }}
}}"""


async def browser_login(store: TokenStore, timeout: int | None = None, headless: bool = False) -> dict[str, Any]:
    """Open a browser on the VibeFlow login page, wait for the user to finish
    Microsoft SSO, then capture the VibeFlow tokens from localStorage.

    A persistent profile is used so the Microsoft session cookie survives and
    later logins are usually one click (or fully silent).
    """
    from playwright.async_api import async_playwright

    timeout = timeout or config.LOGIN_TIMEOUT_SECONDS
    config.BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(config.BROWSER_PROFILE),
            headless=headless,
            viewport={"width": 1100, "height": 800},
        )
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(config.WEB_URL, wait_until="domcontentloaded")

            # Kick off SSO automatically if we landed on the login screen.
            try:
                btn = page.get_by_role("button", name="Sign in with Microsoft")
                await btn.wait_for(state="visible", timeout=8000)
                await btn.click()
            except Exception:
                pass  # already signed in, or user will click manually

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for p in ctx.pages:
                    if not p.url.startswith(config.WEB_URL):
                        continue
                    try:
                        found = await p.evaluate(_READ_AUTH_JS)
                    except Exception:
                        found = None  # page mid-navigation
                    if found:
                        saved = store.save(found["tokens"], found.get("user"))
                        return {"user": saved.get("user"), **store.status()}
                await page.wait_for_timeout(1000)
            raise AuthError(f"Timed out after {timeout}s waiting for SSO login to complete")
        finally:
            await ctx.close()
