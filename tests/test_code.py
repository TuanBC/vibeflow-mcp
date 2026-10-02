import json

import httpx
import pytest
import respx

from conftest import API, payload
from vibeflow_mcp.tools import code, sandbox

PLATFORM = {"models": [{"id": "gemini-3.7-flash", "name": "Gemini", "provider": "google-starter"}]}


@pytest.fixture
def api(logged_in):
    """A project p1 with default task t1 and a running sandbox s1."""
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/api/v1/projects/p1/my-recent-task").mock(return_value=httpx.Response(200, json={"task_id": "t1"}))
        mock.get("/api/v1/sessions/status").mock(return_value=httpx.Response(200, json={"status": "running", "session_id": "s1"}))
        mock.get("/api/v1/users/me/platform-models").mock(return_value=httpx.Response(200, json=PLATFORM))
        yield mock


def body_of(route):
    return json.loads(route.calls.last.request.read())


def params_of(route):
    return dict(route.calls.last.request.url.params)


# -------------------------------------------------------------------- files

async def test_list_files_renders_tree(api):
    api.get("/api/v1/files").mock(return_value=httpx.Response(200, json={"root": "/workspace", "truncated": False, "entries": [
        {"name": "README.md", "type": "file"},
        {"name": "src", "type": "directory", "children": [{"name": "app.py", "type": "file"}]}]}))
    out = payload(await code.vibeflow_list_files("p1"))
    assert out == "/workspace/\nREADME.md\nsrc/\n  app.py"


async def test_read_file_pages_large_content(api):
    route = api.get("/api/v1/files/content").mock(return_value=httpx.Response(200, json={"content": "abcdefghij"}))
    out = payload(await code.vibeflow_read_file("p1", "big.txt", offset=2, max_chars=4))
    assert out == {"path": "big.txt", "size": 10, "content": "cdef", "next_offset": 6}
    assert params_of(route) == {"task_id": "t1", "session_id": "s1", "path": "big.txt"}


async def test_write_file_stages_then_moves(api):
    stage = api.post("/sessions/s1/vibeflow/file/upload").mock(return_value=httpx.Response(200, json={"paths": ["/tmp/vf/notes.md"]}))
    move = api.post("/api/v1/files/upload").mock(return_value=httpx.Response(200, json={"ok": True}))
    out = payload(await code.vibeflow_write_file("p1", "/docs/notes.md", "# hi"))
    assert out == {"written": "docs/notes.md", "bytes": 4}
    assert b"# hi" in stage.calls.last.request.read()
    assert body_of(move) == {"pod_path": "/tmp/vf/notes.md", "dir": "docs", "filename": "notes.md", "task_id": "t1", "session_id": "s1"}


async def test_write_file_needs_name(api):
    assert payload(await code.vibeflow_write_file("p1", "docs/", "x"))["error"] == "bad_request"


async def test_delete_file_requires_confirm(api):
    assert payload(await code.vibeflow_delete_file("p1", "a.txt"))["error"] == "confirmation_required"
    route = api.post("/api/v1/files/delete").mock(return_value=httpx.Response(200, json={"ok": True}))
    await code.vibeflow_delete_file("p1", "a.txt", confirm=True)
    assert body_of(route) == {"path": "a.txt", "task_id": "t1", "session_id": "s1"}


async def test_download_file_writes_bytes(api, tmp_path):
    api.get("/api/v1/files/download").mock(return_value=httpx.Response(200, content=b"\x89PNG"))
    out = payload(await code.vibeflow_download_file("p1", "logo.png", str(tmp_path / "out" / "logo.png")))
    assert out["bytes"] == 4 and (tmp_path / "out" / "logo.png").read_bytes() == b"\x89PNG"


async def test_code_tools_require_running_sandbox(logged_in):
    with respx.mock(base_url=API) as mock:
        mock.get("/api/v1/projects/p1/my-recent-task").mock(return_value=httpx.Response(200, json={"task_id": "t1"}))
        mock.get("/api/v1/sessions/status").mock(return_value=httpx.Response(200, json={"status": "stopped"}))
        assert payload(await code.vibeflow_list_files("p1"))["error"] == "no_session"


async def test_branches_on_local_project(api):
    api.get("/api/v1/files/branches").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    out = payload(await code.vibeflow_list_branches("p1"))
    assert out["error"] == "not_found" and "local" in out["message"]


# ------------------------------------------------------------------ changes

async def test_get_changes_compacts(api):
    api.get("/api/v1/changes").mock(return_value=httpx.Response(200, json={
        "branch_name": "main", "diff_base": "HEAD", "totals": {"files": 1},
        "files": [{"path": "a.py", "change_type": "M", "additions": 3, "deletions": 1, "patch": None}], "truncated": False}))
    out = payload(await code.vibeflow_get_changes("p1"))
    assert out["files"] == [{"path": "a.py", "change": "M", "+": 3, "-": 1}] and out["branch"] == "main"


async def test_session_scope_uses_session_diff(api):
    route = api.get("/api/v1/changes/session-diff").mock(return_value=httpx.Response(200, json={"files": []}))
    await code.vibeflow_get_changes("p1", scope="session")
    assert route.called


async def test_generate_commit_message_splits_title(api):
    api.get("/api/v1/changes/generate-message").mock(return_value=httpx.Response(200, json={"message": "feat: add x\n\nDetails here"}))
    assert payload(await code.vibeflow_generate_commit_message("p1")) == {"title": "feat: add x", "body": "Details here"}


async def test_push_requires_confirm_and_defaults_to_all_changed_paths(api):
    assert payload(await code.vibeflow_push_changes("p1", "feat"))["error"] == "confirmation_required"
    api.get("/api/v1/changes").mock(return_value=httpx.Response(200, json={"files": [{"path": "a.py"}, {"path": "b.py"}]}))
    push = api.post("/api/v1/changes/push").mock(return_value=httpx.Response(200, json={"success": True}))
    await code.vibeflow_push_changes("p1", "feat: x", body="why", target_branch="feature/x", confirm=True)
    assert body_of(push) == {"title": "feat: x", "body": "why", "paths": ["a.py", "b.py"], "target_branch": "feature/x",
                             "task_id": "t1", "session_id": "s1"}


async def test_push_with_no_changes_is_error(api):
    api.get("/api/v1/changes").mock(return_value=httpx.Response(200, json={"files": []}))
    assert payload(await code.vibeflow_push_changes("p1", "x", confirm=True))["error"] == "bad_request"


# ----------------------------------------------------------- restore points

async def test_revert_body_and_confirm(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    assert payload(await code.vibeflow_revert_to("r1", "msg_1"))["error"] == "confirmation_required"
    route = api.post("/sessions/s1/vibeflow/runs/r1/revert").mock(return_value=httpx.Response(200, json={"ok": True}))
    await code.vibeflow_revert_to("r1", "msg_1", confirm=True)
    assert body_of(route) == {"messageID": "msg_1"}


async def test_restore_points_after_pod_restart(api):
    api.get("/api/v1/runs/r1").mock(return_value=httpx.Response(200, json={"session_id": "s1"}))
    api.get("/sessions/s1/vibeflow/runs/r1/restore-points").mock(
        return_value=httpx.Response(404, json={"error": "run_not_found", "run_id": "r1"}))
    out = payload(await code.vibeflow_list_restore_points("r1"))
    assert out["error"] == "not_found" and "restarted" in out["message"]


# ------------------------------------------------------------------ preview

async def test_preview_run_hostname_and_model(api):
    route = api.post("/api/v1/preview/run").mock(return_value=httpx.Response(200, json={"run_id": "pr1"}))
    out = payload(await code.vibeflow_preview_run("p1"))
    sent = body_of(route)
    assert sent["hostname"] == "s1-{PORT}.preview.vibeflow.fptconsulting.co.jp"
    assert sent["model"] == "google-starter/gemini-3.7-flash" and out["run_id"] == "pr1"
    assert out["url_pattern"] == "https://s1-{PORT}.preview.vibeflow.fptconsulting.co.jp"


async def test_preview_status_builds_urls(api):
    api.get("/sessions/s1/vibeflow/snapshot").mock(return_value=httpx.Response(200, json={"preview_ports": [{"port": 3000}]}))
    api.get("/api/v1/sessions/s1/preview/logs").mock(return_value=httpx.Response(200, json={"logs": "ready"}))
    out = payload(await code.vibeflow_preview_status("p1"))
    assert out["urls"] == ["https://s1-3000.preview.vibeflow.fptconsulting.co.jp"] and out["logs"] == "ready"


# ------------------------------------------------------------------ sandbox

@pytest.mark.parametrize("project,expected", [
    ({"project_type": "local"}, {"project_id": "p1", "git_setup_mode": "init"}),
    ({"project_type": "git", "git_url": "https://g/x.git", "git_provider": "github"},
     {"project_id": "p1", "git_setup_mode": "clone", "git_url": "https://g/x.git", "git_provider": "github", "git_token": "tok"}),
])
async def test_start_body_matches_spa(logged_in, project, expected):
    with respx.mock(base_url=API) as mock:
        mock.get("/api/v1/projects/p1").mock(return_value=httpx.Response(200, json=project))
        assert await sandbox.start_body("p1", git_token="tok") == expected
