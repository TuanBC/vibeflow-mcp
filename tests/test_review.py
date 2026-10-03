"""Regression tests for the second code review (correctness + silent failures)."""
import json

import httpx
import keyring
import pytest
import respx

from conftest import API, make_jwt, payload
from vibeflow_mcp import app, auth, errors
from vibeflow_mcp.tools import admin, chat, core


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(chat.asyncio, "sleep", no_sleep)


@pytest.fixture
def api(logged_in):
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        yield mock


def user(text):
    return {"role": "user", "parts": [{"type": "text", "text": text}]}


def answer(text):
    return {"role": "assistant", "time_completed": 1, "metadata": {"finish": "stop"}, "parts": [{"type": "text", "text": text}]}


# ------------------------------------------------------------ soft failures

async def test_http_200_success_false_is_an_error(api):
    api.post("/api/v1/runs/r1/resume").mock(return_value=httpx.Response(200, json={"success": False, "message": "No pending steps to resume."}))
    out = payload(await chat.vibeflow_resume_conversation("r1"))
    assert out["error"] == "operation_failed" and "No pending steps" in out["message"]


async def test_ok_false_is_an_error(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    api.post("/sessions/s1/vibeflow/runs/r1/abort").mock(return_value=httpx.Response(200, json={"ok": False, "error": "not running"}))
    assert payload(await chat.vibeflow_abort("r1"))["error"] == "operation_failed"


async def test_verify_provider_reports_valid_flag_instead_of_raising(api):
    api.post("/api/v1/projects/p1/llm-providers/v1/verify").mock(
        return_value=httpx.Response(200, json={"success": False, "models": [], "error": "Invalid API key"}))
    from vibeflow_mcp.tools import pm
    out = payload(await pm.vibeflow_verify_llm_provider("p1", "v1"))
    assert out["valid"] is False and out["error"] == "Invalid API key"


async def test_unexpected_exception_becomes_internal_error(api):
    @app.tool("not-enabled-toolset")
    async def broken_tool():
        return {}["missing"]
    out = payload(await broken_tool())
    assert out["error"] == "internal_error" and "KeyError" in out["message"]


# -------------------------------------------------------------- wait logic

async def test_timeout_never_returns_previous_turns_reply(api):
    """Stale snapshot bug: poll 1 saw the old idle transcript, then the run went busy."""
    calls = {"n": 0}

    def run_status(request):  # initial fetch + first poll see the old idle run, then it is busy
        calls["n"] += 1
        return httpx.Response(200, json={"status": "idle" if calls["n"] <= 2 else "running"})
    api.get("/api/v1/runs/r1").mock(side_effect=run_status)
    api.get("/api/v1/runs/r1/pending-prompts").mock(return_value=httpx.Response(200, json={"pending_prompts": []}))
    api.get("/api/v1/runs/r1/messages").mock(side_effect=[
        httpx.Response(200, json={"messages": [user("q1"), answer("OLD ANSWER")]})] +
        [httpx.Response(200, json={"messages": [user("q1"), answer("OLD ANSWER"), user("q2")]})] * 50)
    out = await chat.wait_reply("r1", timeout=0.2, poll=0, min_messages=4, ctx=None)
    assert out["outcome"] == "timeout" and out["reply"] is None


async def test_stale_failed_status_does_not_end_follow_up(api):
    """After an abort, a follow-up must not inherit the old 'aborted' status."""
    api.get("/api/v1/runs/r1").mock(side_effect=[httpx.Response(200, json={"status": "aborted"})] * 2 +
                                    [httpx.Response(200, json={"status": "idle"})] * 5)
    old = [user("q1"), answer("partial")]
    api.get("/api/v1/runs/r1/messages").mock(side_effect=[
        httpx.Response(200, json={"messages": old}),
        httpx.Response(200, json={"messages": old + [user("q2"), answer("NEW")]})])
    out = await chat.wait_reply("r1", timeout=5, poll=0, min_messages=4, ctx=None)
    assert out["outcome"] == "done" and out["reply"] == "NEW"


async def test_safety_net_resets_when_run_goes_busy(api):
    """idle x3 (stale), busy, then idle again must not finish on the old count."""
    statuses = ["idle", "idle", "idle", "running", "idle", "idle"]
    api.get("/api/v1/runs/r1").mock(side_effect=[httpx.Response(200, json={"status": s}) for s in statuses] +
                                    [httpx.Response(200, json={"status": "idle"})] * 20)
    api.get("/api/v1/runs/r1/pending-prompts").mock(return_value=httpx.Response(200, json={"pending_prompts": []}))
    step = {"role": "assistant", "time_completed": 1, "metadata": {"finish": "tool-calls"},
            "parts": [{"type": "tool", "tool_name": "bash", "tool_state": {"status": "completed"}}]}
    msgs_before = [user("q"), step]
    msgs_after = msgs_before + [answer("FINAL")]
    api.get("/api/v1/runs/r1/messages").mock(side_effect=[httpx.Response(200, json={"messages": msgs_before})] * 5 +
                                             [httpx.Response(200, json={"messages": msgs_after})] * 20)
    out = await chat.wait_reply("r1", timeout=5, poll=0, min_messages=2, ctx=None)
    assert out["outcome"] == "done" and out["reply"] == "FINAL"


async def test_persistent_poll_errors_surface(api):
    api.get("/api/v1/runs/r1").mock(side_effect=[httpx.Response(200, json={"status": "running"})] +
                                    [httpx.Response(403, json={"detail": "Forbidden"})] * 10)
    with pytest.raises(errors.ApiError):
        await chat.wait_reply("r1", timeout=5, poll=0, min_messages=None, ctx=None)


# ---------------------------------------------------------------- raw API

async def test_raw_api_requires_confirm_for_writes(api):
    assert payload(await core.vibeflow_api("DELETE", "/api/v1/projects/p1"))["error"] == "confirmation_required"
    route = api.get("/api/v1/projects").mock(return_value=httpx.Response(200, json={"projects": []}))
    assert payload(await core.vibeflow_api("GET", "/api/v1/projects")) == {"projects": []} and route.called


# ------------------------------------------------------------------ auth

async def test_set_token_validates_and_drops_previous_account(logged_in):
    assert payload(await core.vibeflow_set_token("not-a-jwt"))["error"] == "auth_required"
    other = make_jwt(email="other@example.com", jti="o1")
    await core.vibeflow_set_token(other)
    data = app.store.load()
    assert data["refresh_token"] == "" and data["user"]["email"] == "other@example.com"


@respx.mock
async def test_refresh_rereads_storage_rotated_by_another_process(logged_in):
    """Another process already rotated the tokens on disk: reuse them, do not post our stale refresh token."""
    stale = app.store.access_token
    auth.FileBackend().write({"access_token": make_jwt(jti="from-other-process"), "refresh_token": "r-new", "user": None})
    route = respx.post(f"{API}/api/v1/auth/azure/refresh").mock(return_value=httpx.Response(200, json={}))
    assert await auth.refresh_tokens(app.store, stale) is True
    assert not route.called and app.store.load()["refresh_token"] == "r-new"


class FlakyKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.data, self.fail_writes = {}, False

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        if self.fail_writes and username != "tokens:count":
            raise RuntimeError("credential manager busy")
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        self.data.pop((service, username), None)


def test_keyring_write_failure_keeps_previous_tokens():
    kr = FlakyKeyring()
    keyring.set_keyring(kr)
    backend = auth.KeyringBackend()
    backend.write({"access_token": "old", "refresh_token": "r-old"})
    kr.fail_writes = True
    with pytest.raises(RuntimeError):
        backend.write({"access_token": "new", "refresh_token": "r-new"})
    assert backend.read() == {"access_token": "old", "refresh_token": "r-old"}


def test_keyring_corrupt_read_returns_none():
    kr = FlakyKeyring()
    keyring.set_keyring(kr)
    kr.data[("vibeflow-mcp", "tokens:count")] = "2"
    kr.data[("vibeflow-mcp", "tokens:0")] = '{"access_tok'
    assert auth.KeyringBackend().read() is None


# ------------------------------------------------------------------ admin

async def test_admin_set_role_and_shared_key_guards(api):
    assert payload(await admin.vibeflow_admin_user("u1", "set_role", confirm=True))["error"] == "bad_request"
    assert payload(await admin.vibeflow_admin_provider("set_shared_key", "pv1", confirm=True))["error"] == "bad_request"
    route = api.put("/api/v1/admin/users/u1/role").mock(return_value=httpx.Response(200, json={}))
    await admin.vibeflow_admin_user("u1", "set_role", clear_role=True, confirm=True)
    assert json.loads(route.calls.last.request.read()) == {"system_role_id": None}
