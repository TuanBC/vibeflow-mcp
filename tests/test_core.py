import asyncio
import json

import httpx
import keyring
import pytest
import respx
from keyring.backend import KeyringBackend as _KRBase

from conftest import API, make_jwt, payload
from vibeflow_mcp import app, auth, config, contract, errors, render
from vibeflow_mcp.tools import chat, core, sandbox


# ------------------------------------------------------------------- errors

@pytest.mark.parametrize("status,detail,code", [
    (400, "No running session. Start a Vibe Session first.", "no_session"),
    (403, "pending_approval", "pending_approval"),
    (403, "account_disabled", "account_disabled"),
    (403, "Forbidden", "forbidden"),
    (404, {"error": "run_not_found"}, "not_found"),
    (409, {"message": "still sealing", "retry_after_seconds": 12}, "busy"),
    (429, "Monthly quota exceeded", "quota_exceeded"),
    (502, "Bad gateway", "server_error"),
    (422, [{"loc": ["body"], "msg": "field required"}], "bad_request"),
])
def test_classify(status, detail, code):
    assert errors.classify(status, detail)[0] == code


def test_busy_hint_includes_retry():
    err = errors.ApiError(409, "POST", "/x", {"message": "sealing", "retry_after_seconds": 12})
    assert "12s" in err.to_payload()["hint"]


# --------------------------------------------------------------------- auth

def test_decode_jwt_and_status(logged_in):
    st = app.store.status()
    assert st["authenticated"] and st["email"] == "dev@example.com" and st["backend"] == "file"
    assert 3500 < st["seconds_left"] <= 3600


def test_invalid_jwt_raises():
    with pytest.raises(errors.AuthRequired):
        auth.decode_jwt("not-a-jwt")


def test_file_backend_roundtrip_keeps_refresh_token(logged_in):
    app.store.save({"access_token": make_jwt(jti="j2")})  # refresh response without refresh_token
    fresh = auth.TokenStore(auth.FileBackend())
    assert fresh.load()["refresh_token"] == "r1"
    assert set(fresh.load()["user"]) == {"id", "email", "display_name"}


class MemoryKeyring(_KRBase):
    priority = 1

    def __init__(self):
        super().__init__()
        self.data = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        assert len(password) <= auth.KeyringBackend.CHUNK
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        self.data.pop((service, username), None)


def test_keyring_backend_chunks_large_tokens():
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    backend = auth.KeyringBackend()
    big = {"access_token": "x" * 2500, "refresh_token": "y" * 900}
    backend.write(big)
    assert int(kr.data[(config.KEYRING_SERVICE, "tokens:count")]) >= 4
    assert backend.read() == big
    backend.write({"access_token": "short"})  # shrinking removes stale chunks
    assert backend.read() == {"access_token": "short"}
    backend.delete()
    assert backend.read() is None and not kr.data


@respx.mock
async def test_concurrent_refresh_calls_endpoint_once(logged_in):
    route = respx.post(f"{API}/api/v1/auth/azure/refresh").mock(
        side_effect=lambda req: httpx.Response(200, json={"access_token": make_jwt(jti="new"), "refresh_token": "r2"}))
    stale = app.store.access_token  # five requests all got 401 with the same token
    results = await asyncio.gather(*[auth.refresh_tokens(app.store, stale) for _ in range(5)])
    assert all(results) and route.call_count == 1
    assert app.store.load()["refresh_token"] == "r2"


@respx.mock
async def test_late_401_with_old_token_does_not_refresh_again(logged_in):
    route = respx.post(f"{API}/api/v1/auth/azure/refresh").mock(
        return_value=httpx.Response(200, json={"access_token": make_jwt(jti="new"), "refresh_token": "r2"}))
    old = app.store.access_token
    assert await auth.refresh_tokens(app.store, old)
    assert await auth.refresh_tokens(app.store, old)  # a request that was in flight with the old token
    assert route.call_count == 1


@respx.mock
async def test_refresh_failure_returns_false(logged_in):
    respx.post(f"{API}/api/v1/auth/azure/refresh").mock(return_value=httpx.Response(401))
    assert await auth.refresh_tokens(app.store) is False


# ------------------------------------------------------------------- client

@respx.mock
async def test_client_sends_browser_ua_and_bearer(logged_in):
    route = respx.get(f"{API}/api/v1/auth/me").mock(return_value=httpx.Response(200, json={"user": {}}))
    await app.client.get("/api/v1/auth/me")
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {app.store.access_token}"
    assert "Mozilla/5.0" in req.headers["user-agent"]


@respx.mock
async def test_client_refreshes_on_401_and_retries(logged_in):
    respx.get(f"{API}/api/v1/projects").mock(side_effect=[httpx.Response(401, headers={"WWW-Authenticate": "Bearer"}),
                                                          httpx.Response(200, json={"projects": []})])
    respx.post(f"{API}/api/v1/auth/azure/refresh").mock(
        return_value=httpx.Response(200, json={"access_token": make_jwt(jti="new"), "refresh_token": "r2"}))
    assert await app.client.get("/api/v1/projects") == {"projects": []}


@respx.mock
async def test_client_proactive_refresh_when_expiring():
    app.store.save({"access_token": make_jwt(exp_in=60), "refresh_token": "r1"})
    refresh = respx.post(f"{API}/api/v1/auth/azure/refresh").mock(
        return_value=httpx.Response(200, json={"access_token": make_jwt(jti="new")}))
    respx.get(f"{API}/api/v1/auth/me").mock(return_value=httpx.Response(200, json={}))
    await app.client.get("/api/v1/auth/me")
    assert refresh.called and app.store.seconds_left() > 3000


@respx.mock
async def test_client_raises_classified_error(logged_in):
    respx.get(f"{API}/api/v1/sessions/models").mock(
        return_value=httpx.Response(400, json={"detail": "No running session. Start a Vibe Session first."}))
    with pytest.raises(errors.ApiError) as exc:
        await app.client.get("/api/v1/sessions/models", project_id="p")
    assert exc.value.code == "no_session"


@respx.mock
async def test_client_timeout_is_classified(logged_in):
    respx.get(f"{API}/api/v1/changes/generate-message").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(errors.VibeFlowError) as exc:
        await app.client.get("/api/v1/changes/generate-message")
    assert exc.value.code == "timeout"


async def test_client_requires_login():
    with pytest.raises(errors.AuthRequired):
        await app.client.get("/api/v1/auth/me")


# ------------------------------------------------------------- tool infra

def test_toolsets_registered():
    assert app.REGISTERED["vibeflow_login"] == "core"
    assert set(app.REGISTERED.values()) <= config.TOOLSETS


async def test_tool_returns_structured_error_when_logged_out():
    out = payload(await core.vibeflow_whoami())
    assert out["error"] == "auth_required" and "vibeflow_login" in out["hint"]


async def test_destructive_tool_requires_confirm(logged_in):
    out = payload(await sandbox.vibeflow_stop_session("s1"))
    assert out["error"] == "confirmation_required"


@respx.mock
async def test_destructive_tool_runs_with_confirm(logged_in):
    respx.post(f"{API}/api/v1/sessions/s1/stop").mock(return_value=httpx.Response(200, json={"success": True}))
    assert payload(await sandbox.vibeflow_stop_session("s1", confirm=True)) == {"success": True}


# ------------------------------------------------------------------- models

PLATFORM = {"models": [{"id": "gemini-3.7-flash", "name": "Gemini", "provider": "google-starter"}]}


@respx.mock
async def test_resolve_bare_platform_model(logged_in):
    respx.get(f"{API}/api/v1/users/me/platform-models").mock(return_value=httpx.Response(200, json=PLATFORM))
    assert await chat.resolve_model("gemini-3.7-flash", "auto") == ("google-starter/gemini-3.7-flash", "platform")
    assert await chat.resolve_model("acme/custom", "auto") == ("acme/custom", None)
    assert await chat.resolve_model("acme/custom", "project") == ("acme/custom", "project")


@respx.mock
async def test_start_conversation_body(logged_in):
    respx.get(f"{API}/api/v1/users/me/platform-models").mock(return_value=httpx.Response(200, json=PLATFORM))
    route = respx.post(f"{API}/api/v1/runs").mock(return_value=httpx.Response(200, json={"success": True, "run_id": "r1"}))
    await chat.vibeflow_start_conversation("t1", "hi", "gemini-3.7-flash", mode="plan")
    sent = json.loads(route.calls.last.request.read())
    assert sent["model"] == "google-starter/gemini-3.7-flash" and sent["provider_scope"] == "platform"
    assert sent["task_id"] == "t1" and sent["node_type"] == "console" and sent["mode"] == "plan"


# ----------------------------------------------------------------- contract

def test_contract_extract_and_normalize():
    bundle = ('Pe.get(`/api/v1/runs/${e}/messages?subagent=${x}`);Pe.post("/api/v1/runs",B);'
              'Pe.postForm(`/sessions/${e}/vibeflow/file/upload`,a);'
              'fetch(`${P()}/api/v1/auth/logout`,{method:"POST",headers:{}})')
    assert contract.extract(bundle) == [
        "GET /api/v1/runs/{}/messages", "POST /api/v1/auth/logout", "POST /api/v1/runs",
        "POST /sessions/{}/vibeflow/file/upload"]


def test_contract_diff_and_lock_present():
    assert contract.diff(["A", "B"], ["B", "C"]) == (["A"], ["C"])
    assert "POST /api/v1/runs" in contract.read_lock()


# ------------------------------------------------------------------- render

def test_render_message_with_tool_and_cost():
    msg = {"role": "assistant", "model": "gemini", "metadata": {"cost": 0.0123},
           "parts": [{"type": "step-start"}, {"type": "text", "text": "Done."},
                     {"type": "tool", "tool_name": "bash", "tool_state": {"status": "completed", "title": "ls", "output": "a\nb"}}]}
    out = render.message(msg)
    assert "### assistant (gemini, $0.0123)" in out and "Done." in out and "[tool bash completed] ls -> a b" in out


def test_render_tree_depth_and_diff():
    entries = [{"name": "src", "type": "directory", "children": [
        {"name": "pkg", "type": "directory", "children": [{"name": "x.py", "type": "file"}]}]}]
    assert render.tree(entries, max_depth=2) == ["src/", "  pkg/", "    … (1 entries)"]
    assert render.diff([{"type": "add", "content": "x"}, {"type": "del", "content": "y"}, "@@ hunk"]) == "+x\n-y\n@@ hunk"


@respx.mock
async def test_upstream_401_does_not_touch_session(logged_in):
    """Live bug: a rejected Jira PAT (401 without WWW-Authenticate) triggered a
    token refresh and was reported as auth_required."""
    refresh = respx.post(f"{API}/api/v1/auth/azure/refresh").mock(return_value=httpx.Response(200, json={"access_token": make_jwt(jti="x")}))
    respx.post(f"{API}/api/v1/jira/projects").mock(return_value=httpx.Response(401, json={"detail": "Invalid credential"}))
    with pytest.raises(errors.ApiError) as exc:
        await app.client.post("/api/v1/jira/projects", {"pat": "bad"})
    assert exc.value.code == "credential_rejected" and not refresh.called
