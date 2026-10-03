"""SSO token capture and lifecycle.

VibeFlow auth flow (reverse-engineered from the SPA bundle):
  1. MSAL.js loginRedirect against Azure AD (tenant f01e930a-..., client 3e0b9c91-...).
  2. SPA POSTs {id_token, graph_access_token} to /api/v1/auth/azure/token.
  3. API returns a VibeFlow JWT (8h) + refresh token; SPA persists them in
     localStorage["vibeflow-auth"] as {state: {user, tokens, isAuthenticated}}.
  4. Refresh: POST /api/v1/auth/azure/refresh {refresh_token} (+ Bearer old
     token). The refresh token ROTATES, so refreshes must be serialized.

The Azure app registration only allows the SPA redirect URI, so instead of
running our own OAuth flow we drive a real browser through the normal login
and lift the VibeFlow tokens out of localStorage once the SPA has them.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Protocol

import httpx

from . import config
from .errors import AuthRequired

log = logging.getLogger(__name__)


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode JWT claims without verifying the signature (local expiry checks only)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        if not isinstance(claims, dict):
            raise ValueError("JWT payload is not an object")
        return claims
    except (IndexError, ValueError) as exc:
        raise AuthRequired("Stored access token is not a valid JWT.") from exc


# ------------------------------------------------------------------ backends

class TokenBackend(Protocol):
    name: str
    def read(self) -> dict[str, Any] | None: ...
    def write(self, data: dict[str, Any]) -> None: ...
    def delete(self) -> None: ...


class FileBackend:
    name = "file"

    def read(self) -> dict[str, Any] | None:
        if not config.TOKEN_FILE.exists():
            return None
        return json.loads(config.TOKEN_FILE.read_text(encoding="utf-8"))

    def write(self, data: dict[str, Any]) -> None:
        config.HOME.mkdir(parents=True, exist_ok=True)
        config.TOKEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(config.TOKEN_FILE, 0o600)
        except OSError:
            pass

    def delete(self) -> None:
        config.TOKEN_FILE.unlink(missing_ok=True)


class KeyringBackend:
    """OS credential store. Values are chunked because Windows Credential
    Manager caps a secret at 2560 bytes (~1280 UTF-16 chars)."""

    name = "keyring"
    CHUNK = 1000

    def __init__(self) -> None:
        import keyring

        self._kr = keyring

    def read(self) -> dict[str, Any] | None:
        count = self._kr.get_password(config.KEYRING_SERVICE, "tokens:count")
        if not count:
            return None
        parts = [self._kr.get_password(config.KEYRING_SERVICE, f"tokens:{i}") or "" for i in range(int(count))]
        try:
            return json.loads("".join(parts))
        except ValueError:
            log.warning("Stored VibeFlow token in the keyring is corrupt; a new login is needed.")
            return None

    def write(self, data: dict[str, Any]) -> None:
        # Write the new chunks before switching the count, then drop surplus old
        # chunks, so a failure midway never leaves the store empty.
        blob = json.dumps(data, separators=(",", ":"))
        chunks = [blob[i:i + self.CHUNK] for i in range(0, len(blob), self.CHUNK)]
        old_count = int(self._kr.get_password(config.KEYRING_SERVICE, "tokens:count") or 0)
        for i, chunk in enumerate(chunks):
            self._kr.set_password(config.KEYRING_SERVICE, f"tokens:{i}", chunk)
        self._kr.set_password(config.KEYRING_SERVICE, "tokens:count", str(len(chunks)))
        for i in range(len(chunks), old_count):
            self._delete_key(f"tokens:{i}")

    def _delete_key(self, key: str) -> bool:
        try:
            self._kr.delete_password(config.KEYRING_SERVICE, key)
            return True
        except Exception as exc:
            if self._kr.get_password(config.KEYRING_SERVICE, key) is not None:
                log.warning("Could not delete keyring entry %s: %s", key, exc)
                return False
            return True  # already absent

    def delete(self) -> None:
        count = self._kr.get_password(config.KEYRING_SERVICE, "tokens:count")
        keys = ["tokens:count"] + [f"tokens:{i}" for i in range(int(count or 0))]
        failed = [k for k in keys if not self._delete_key(k)]
        if failed:
            raise AuthRequired("Could not remove the stored token from the OS keyring.", code="keyring_error",
                               hint="Remove the vibeflow-mcp entries in your OS credential manager.")


def _keyring_usable() -> bool:
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        return not isinstance(backend, fail.Keyring) and getattr(backend, "priority", 0) > 0
    except Exception as exc:
        log.warning("OS keyring unavailable (%s); storing the token in %s", exc, config.TOKEN_FILE)
        return False


def make_backend() -> TokenBackend:
    choice = config.TOKEN_BACKEND
    if choice == "file" or (choice == "auto" and not _keyring_usable()):
        return FileBackend()
    backend = KeyringBackend()
    # One-time migration of a plaintext token file into the keyring.
    legacy = FileBackend()
    if choice == "auto" and config.TOKEN_FILE.exists():
        try:
            data = legacy.read()
            if data:
                backend.write(data)
            legacy.delete()
        except Exception as exc:  # keep the file if the keyring write fails
            log.warning("Token migration to keyring failed: %s", exc)
            return legacy
    return backend


# --------------------------------------------------------------------- store

class TokenStore:
    def __init__(self, backend: TokenBackend | None = None) -> None:
        self.backend = backend or make_backend()
        self._data: dict[str, Any] | None = None
        self._loaded = False
        self.refresh_lock = asyncio.Lock()

    def load(self) -> dict[str, Any] | None:
        if not self._loaded:
            self._data = self.backend.read()
            self._loaded = True
        return self._data

    def save(self, tokens: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.load() or {}
        user = user or current.get("user")
        data = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token") or current.get("refresh_token", ""),
            "token_type": tokens.get("token_type", "bearer"),
            "expires_in": tokens.get("expires_in"),
            "saved_at": int(time.time()),
            "user": {k: user.get(k) for k in ("id", "email", "display_name")} if user else None,
        }
        self.backend.write(data)
        self._data, self._loaded = data, True
        return data

    def reload(self) -> None:
        """Forget the in-memory copy so the next load() re-reads storage."""
        self._loaded = False

    def replace(self, tokens: dict[str, Any], user: dict[str, Any] | None) -> dict[str, Any]:
        """Store tokens for a (possibly different) account without carrying over
        the previous refresh token or user."""
        self._data, self._loaded = None, True
        return self.save(tokens, user)

    def clear(self) -> None:
        self._data, self._loaded = None, True
        self.backend.delete()

    @property
    def access_token(self) -> str | None:
        data = self.load()
        return data["access_token"] if data else None

    @property
    def email(self) -> str | None:
        data = self.load() or {}
        return (data.get("user") or {}).get("email")

    def seconds_left(self) -> int | None:
        token = self.access_token
        if not token:
            return None
        exp = decode_jwt(token).get("exp")
        return int(exp - time.time()) if exp else None

    def status(self) -> dict[str, Any]:
        data = self.load()
        base = {"backend": self.backend.name}
        if not data:
            return {"authenticated": False, **base}
        claims = decode_jwt(data["access_token"])
        left = self.seconds_left()
        return {
            "authenticated": left is not None and left > 0,
            "email": claims.get("email"),
            "role": claims.get("role"),
            "expires_at": claims.get("exp"),
            "seconds_left": left,
            "has_refresh_token": bool(data.get("refresh_token")),
            **base,
        }


# ------------------------------------------------------------------- refresh

async def refresh_tokens(store: TokenStore, stale_token: str | None = None) -> bool:
    """Exchange the refresh token for a new access token. Serialized because
    the refresh token rotates. `stale_token` is the token the caller found
    expired/rejected; if the store already holds a different one, another
    coroutine refreshed in the meantime and we reuse its result."""
    stale_token = stale_token or store.access_token
    async with store.refresh_lock:
        # Another process sharing this token store may have rotated the tokens:
        # re-read storage before deciding (its refresh token supersedes ours).
        store.reload()
        if store.access_token != stale_token:
            return True
        data = store.load()
        if not data or not data.get("refresh_token"):
            return False
        try:
            async with httpx.AsyncClient(timeout=30, headers={"User-Agent": config.USER_AGENT}) as http:
                resp = await http.post(
                    f"{config.API_URL}/api/v1/auth/azure/refresh",
                    json={"refresh_token": data["refresh_token"]},
                    headers={"Authorization": f"Bearer {data['access_token']}"},
                )
        except httpx.HTTPError as exc:
            log.warning("Token refresh request failed: %s", exc)
            return False
        if resp.status_code != 200:
            log.warning("Token refresh rejected: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        try:
            body = resp.json()
        except ValueError:
            log.warning("Token refresh returned a non-JSON body")
            return False
        if not isinstance(body, dict) or not body.get("access_token"):
            return False
        store.save(body, body.get("user"))
        return True


# --------------------------------------------------------------- browser SSO

_READ_AUTH_JS = f"""() => {{
  const raw = localStorage.getItem({json.dumps(config.AUTH_STORAGE_KEY)});
  if (!raw) return null;
  try {{
    const s = JSON.parse(raw).state || {{}};
    return s.tokens && s.tokens.access_token ? {{tokens: s.tokens, user: s.user}} : null;
  }} catch (e) {{ return null; }}
}}"""


async def browser_login(store: TokenStore, timeout: int | None = None, headless: bool = False) -> dict[str, Any]:
    """Drive the VibeFlow login page through Microsoft SSO and capture the
    VibeFlow tokens from localStorage.

    headless=False: a visible window; the user completes sign-in.
    headless=True: silent re-login relying on the saved Microsoft session
    cookie in the persistent profile; auto-picks the known account tile.
    """
    from playwright.async_api import async_playwright

    timeout = timeout or config.LOGIN_TIMEOUT_SECONDS
    config.BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    email = store.email

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(config.BROWSER_PROFILE),
            headless=headless,
            user_agent=config.USER_AGENT,  # HeadlessChrome UA is blocked by the WAF
            viewport={"width": 1100, "height": 800},
        )
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(config.WEB_URL, wait_until="domcontentloaded")
            # Drop tokens the SPA cached in this profile on an earlier run: their
            # refresh token may already be rotated away by us. Forces a fresh
            # SSO exchange (silent when the Microsoft session cookie is valid).
            await page.evaluate(f"localStorage.removeItem({json.dumps(config.AUTH_STORAGE_KEY)})")
            await page.goto(f"{config.WEB_URL}/login", wait_until="domcontentloaded")
            try:
                btn = page.get_by_role("button", name="Sign in with Microsoft")
                await btn.wait_for(state="visible", timeout=8000)
                await btn.click()
            except Exception:
                pass  # already signed in, or user will click manually

            deadline = time.monotonic() + timeout
            clicked_tile: set[str] = set()
            while time.monotonic() < deadline:
                for p in ctx.pages:
                    if p.url.startswith(config.WEB_URL):
                        try:
                            found = await p.evaluate(_READ_AUTH_JS)
                        except Exception:
                            found = None  # mid-navigation
                        exp = decode_jwt(found["tokens"]["access_token"]).get("exp", 0) if found else 0
                        if found and exp - time.time() > config.REFRESH_MARGIN_SECONDS:
                            saved = store.replace(found["tokens"], found.get("user"))
                            return {"user": saved.get("user"), **store.status()}
                    elif headless and "login.microsoftonline.com" in p.url and email and p.url not in clicked_tile:
                        # "Pick an account" screen: choose the remembered account.
                        try:
                            tile = p.get_by_text(email, exact=False).first
                            await tile.wait_for(state="visible", timeout=3000)
                            await tile.click()
                            clicked_tile.add(p.url)
                        except Exception:
                            pass
                await page.wait_for_timeout(1000)
            raise AuthRequired(
                f"SSO login did not complete within {timeout}s"
                + (" (silent re-login needs an interactive sign-in)" if headless else "")
            )
        finally:
            await ctx.close()
