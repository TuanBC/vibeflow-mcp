"""Protocol-level tests: talk to the server through a real MCP client (in-process
and over stdio) so they check what clients see, not SDK internals."""
import os
import sys

import httpx
import respx
from mcp import Client, StdioServerParameters

from conftest import API
from vibeflow_mcp import __version__, app


async def test_server_identity_and_instructions():
    async with Client(app.mcp) as client:
        assert client.server_info.name == "vibeflow"
        assert client.server_info.version == __version__
        assert "vibeflow_auth_status" in (client.instructions or "")


async def test_tool_annotations():
    async with Client(app.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["vibeflow_list_projects"].annotations.read_only_hint is True
    assert tools["vibeflow_stop_session"].annotations.destructive_hint is True
    assert set(tools) == set(app.REGISTERED)


async def test_context_parameter_is_hidden_from_schema():
    async with Client(app.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    props = tools["vibeflow_ask"].input_schema["properties"]
    assert "prompt" in props and "ctx" not in props


async def test_tool_call_returns_structured_error_payload():
    async with Client(app.mcp) as client:
        result = await client.call_tool("vibeflow_stop_session", {"session_id": "s1"})
    assert '"confirmation_required"' in result.content[0].text and not result.is_error


async def test_resources_and_prompts_registered():
    async with Client(app.mcp) as client:
        templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        msgs = await client.get_prompt("vibeflow_bug_fix", {"project_id": "p1", "request": "500 on login"})
    assert "vibeflow://runs/{run_id}/transcript" in templates and "vibeflow://projects/{project_id}/overview" in templates
    assert {"vibeflow_bug_fix", "vibeflow_code_review", "vibeflow_rfp_to_demo"} <= prompts
    text = msgs.messages[0].content.text
    assert 'workflow="builtin-bug-fix"' in text and "500 on login" in text


@respx.mock(base_url=API, assert_all_called=False)
async def test_messages_resource_renders(respx_mock, logged_in):
    respx_mock.get("/api/v1/runs/r1/messages").mock(return_value=httpx.Response(200, json={"messages": [
        {"role": "user", "parts": [{"type": "text", "text": "hi"}]}]}))
    async with Client(app.mcp) as client:
        result = await client.read_resource("vibeflow://runs/r1/messages")
    assert "### user\nhi" in result.contents[0].text


async def test_stdio_entrypoint_serves_all_toolsets(tmp_path):
    """Launch `python -m vibeflow_mcp` like an MCP client does (tokens isolated in tmp_path)."""
    env = {**os.environ, "VIBEFLOW_MCP_HOME": str(tmp_path), "VIBEFLOW_TOKEN_BACKEND": "file",
           "VIBEFLOW_SILENT_RELOGIN": "0", "VIBEFLOW_TOOLSETS": "core,code,pm,analytics,advanced,admin"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "vibeflow_mcp"], env=env)
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        status = await client.call_tool("vibeflow_auth_status", {})
    assert len(tools) == 175
    assert '"authenticated": false' in status.content[0].text
