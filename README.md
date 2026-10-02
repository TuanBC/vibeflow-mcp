# vibeflow-mcp

MCP server for **VibeFlow** (https://vibeflow.fptconsulting.co.jp) — drive projects, sandboxes and
AI-agent conversations from Claude Code (or any MCP client) without the web UI.

Status: **POC** — 27 tools, verified end-to-end against production (SSO login → sandbox start →
agent conversation → reply → sandbox stop). See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full roadmap.

## How auth works

VibeFlow uses Microsoft Entra ID (MSAL.js, SPA redirect flow). After Microsoft sign-in the SPA exchanges the
ID token at `POST /api/v1/auth/azure/token` for a **VibeFlow JWT (8 h)** + **refresh token** and keeps them in
`localStorage["vibeflow-auth"]`.

The Azure app only allows the SPA redirect URI, so the MCP does not run its own OAuth flow. Instead
`vibeflow_login` opens a real Chromium window (Playwright, persistent profile), you complete SSO as normal,
and the tokens are lifted from localStorage into `~/.vibeflow-mcp/tokens.json`. After that:

- requests send `Authorization: Bearer <jwt>` + a browser User-Agent (the Azure App Gateway WAF 403s non-browser UAs);
- tokens are refreshed automatically via `POST /api/v1/auth/azure/refresh` (rotating) when < 5 min remain or on a 401;
- the browser profile keeps the Microsoft session cookie, so re-login is usually one click.

## Setup

Requires Python ≥ 3.10, `mcp`, `httpx`, `playwright` (+ `playwright install chromium`).

```bash
pip install -e .
```

```bash
vibeflow-mcp login
```

`.mcp.json` in this folder registers the server for Claude Code (edit the interpreter path for your machine).
Alternatively: `claude mcp add vibeflow -- python -m vibeflow_mcp` with `PYTHONPATH=<repo>/src`.

## Tools (POC)

| Group | Tools |
|---|---|
| Auth | `vibeflow_login`, `vibeflow_set_token`, `vibeflow_auth_status`, `vibeflow_logout`, `vibeflow_whoami` |
| Workspace | `vibeflow_list_projects`, `vibeflow_get_project`, `vibeflow_get_recent_task`, `vibeflow_list_tasks`, `vibeflow_get_task`, `vibeflow_get_kanban`, `vibeflow_search` |
| Chat | `vibeflow_list_conversations`, `vibeflow_get_conversation`, `vibeflow_get_transcript`, `vibeflow_get_messages`, `vibeflow_start_conversation`, `vibeflow_send_message`, `vibeflow_wait_for_reply`, `vibeflow_rename_conversation` |
| Sandbox | `vibeflow_session_status`, `vibeflow_list_my_sessions`, `vibeflow_start_session`, `vibeflow_stop_session` |
| Meta | `vibeflow_list_models`, `vibeflow_get_quota`, `vibeflow_api` (raw escape hatch for any endpoint) |

Typical flow:

1. `vibeflow_list_projects` → project id
2. `vibeflow_start_session(project_id)` → poll `vibeflow_session_status` until `running`
3. `vibeflow_get_recent_task(project_id)` → task id
4. `vibeflow_start_conversation(task_id, prompt, model="google-starter/gemini-3.7-flash")` → run id
5. `vibeflow_wait_for_reply(run_id)`; continue with `vibeflow_send_message`
6. `vibeflow_stop_session(session_id)` when done (sandboxes idle-stop after 1 h anyway)

Models are `<provider>/<id>`; `provider_scope="auto"` maps shared platform models to `platform` scope
(billed against your monthly platform quota — see `vibeflow_get_quota`).

## Security notes

- `tokens.json` holds a bearer token for your account — keep it private (file is chmod 600 where supported).
- `browser-profile/` holds your Microsoft session cookies.
- `vibeflow_logout` revokes server-side and deletes the local token.
