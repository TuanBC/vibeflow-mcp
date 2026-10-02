# vibeflow-mcp

MCP server for **VibeFlow** (https://vibeflow.fptconsulting.co.jp) — drive projects, sandboxes and
AI-agent conversations from Claude Code (or any MCP client) without the web UI.

Status: **Phases 1–3 done** — 68 tools (hardening, full conversation feature set, code loop), verified
against production. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the roadmap (phases 4–7: project
management, analytics, admin, advanced).

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

Requires Python ≥ 3.10.

```bash
uv venv .venv && uv pip install -e ".[test]"
```

```bash
.venv/Scripts/vibeflow-mcp install-browser
```

```bash
.venv/Scripts/vibeflow-mcp login
```

`.mcp.json` in this folder registers the server for Claude Code (edit the interpreter path for your machine).

### CLI

| Command | Purpose |
|---|---|
| `vibeflow-mcp` | run the MCP server (stdio) |
| `vibeflow-mcp login [--headless]` | SSO login; `--headless` re-uses the saved Microsoft session silently |
| `vibeflow-mcp status` / `logout` | token status / delete local token |
| `vibeflow-mcp install-browser` | download Playwright's Chromium |
| `vibeflow-mcp contract-check [--update]` | diff the live SPA's API calls against `endpoints.lock` (exit 1 on drift) |

### Configuration (env)

| Variable | Default | Meaning |
|---|---|---|
| `VIBEFLOW_TOOLSETS` | `core,code` | tool groups to expose |
| `VIBEFLOW_TOKEN_BACKEND` | `auto` | `keyring` (OS credential store), `file`, or `auto` (keyring if available; migrates an old `tokens.json`) |
| `VIBEFLOW_SILENT_RELOGIN` | `1` | when refresh fails, try a headless SSO login with the saved browser profile |
| `VIBEFLOW_DEFAULT_MODEL` | – | model used by `vibeflow_ask` when none is given |
| `VIBEFLOW_USER_AGENT` | Chrome UA | sent on every request (the WAF blocks non-browser UAs) |

### Tests

```bash
.venv/Scripts/python -m pytest
```

## Tools (68)

Toolsets are chosen with `VIBEFLOW_TOOLSETS` (default `core,code`). Destructive or publishing tools require
`confirm=true`; every tool carries MCP `readOnlyHint` / `destructiveHint` annotations. Errors come back as
`{"error": <code>, "message", "hint"}` (e.g. `auth_required`, `no_session`, `busy`, `quota_exceeded`).

### core

| Group | Tools |
|---|---|
| Auth & account | `vibeflow_login`, `vibeflow_set_token`, `vibeflow_auth_status`, `vibeflow_logout`, `vibeflow_whoami`, `vibeflow_my_stats`, `vibeflow_get_quota` |
| Workspace | `vibeflow_list_projects`, `vibeflow_get_project`, `vibeflow_get_recent_task`, `vibeflow_list_tasks`, `vibeflow_get_task`, `vibeflow_get_kanban`, `vibeflow_search` |
| Sandbox | `vibeflow_session_status`, `vibeflow_list_my_sessions`, `vibeflow_start_session` (waits; git clone for git projects), `vibeflow_save_session`, `vibeflow_stop_session`* |
| Pickers | `vibeflow_list_models`, `vibeflow_list_agents` (!), `vibeflow_list_skills` (/), `vibeflow_list_workflows` (#) |
| Chat | **`vibeflow_ask`** (one call: sandbox → conversation → reply), `vibeflow_start_conversation`, `vibeflow_send_message`, `vibeflow_wait_for_reply` (live progress via SSE) |
| Human in the loop | `vibeflow_pending_prompts`, `vibeflow_reply_permission`, `vibeflow_answer_question` |
| Conversation mgmt | `vibeflow_list_conversations`, `vibeflow_get_conversation`, `vibeflow_get_messages`, `vibeflow_get_transcript`, `vibeflow_conversation_usage`, `vibeflow_list_artifacts`, `vibeflow_abort`*, `vibeflow_resume_conversation`, `vibeflow_compact_conversation`, `vibeflow_fork_conversation`, `vibeflow_rename_conversation`, `vibeflow_pin_conversation`, `vibeflow_archive_conversation`, `vibeflow_delete_conversation`* |
| Escape hatch | `vibeflow_api` (any endpoint) |

### code (sandbox must be running)

| Group | Tools |
|---|---|
| Files | `vibeflow_list_files`, `vibeflow_read_file`, `vibeflow_search_files`, `vibeflow_write_file`, `vibeflow_upload_file`, `vibeflow_delete_file`*, `vibeflow_download_file`, `vibeflow_download_workspace` |
| Git | `vibeflow_list_branches`, `vibeflow_checkout_branch`, `vibeflow_get_changes`, `vibeflow_get_diff`, `vibeflow_generate_commit_message`, `vibeflow_push_changes`*, `vibeflow_git_sync` |
| Restore points | `vibeflow_list_restore_points`, `vibeflow_restore_point_diff`, `vibeflow_revert_to`*, `vibeflow_undo_revert` |
| Preview | `vibeflow_preview_run`, `vibeflow_preview_status`, `vibeflow_preview_stop`, `vibeflow_preview_fix` |

\* destructive / publishing: requires `confirm=true`.

### Typical flows

- **Quick question / task:** `vibeflow_ask(prompt, project_id?, agent?, skill?, workflow?)` — returns the reply,
  cost and tools used; long jobs continue with `vibeflow_wait_for_reply(run_id)`.
- **Multi-turn:** `vibeflow_send_message(run_id, ...)` → `vibeflow_wait_for_reply(run_id, min_messages=...)`.
  If the outcome is `needs_input`, answer with `vibeflow_reply_permission` / `vibeflow_answer_question`.
- **Code review loop:** `vibeflow_get_changes` → `vibeflow_get_diff` → `vibeflow_generate_commit_message` →
  `vibeflow_push_changes(confirm=true)`; undo agent edits with restore points.

Models are `<provider>/<id>`; bare platform ids resolve automatically and `provider_scope="auto"` bills shared
platform models to your monthly quota (`vibeflow_get_quota`). A first turn costs ≈ 40k input tokens of agent
system prompt (~$0.005–0.03 depending on model).

## Security notes

- Tokens live in the OS keyring (Windows Credential Manager / macOS Keychain / Secret Service) by default; with
  `VIBEFLOW_TOKEN_BACKEND=file` they are in `~/.vibeflow-mcp/tokens.json` (chmod 600 where supported).
- `~/.vibeflow-mcp/browser-profile/` holds your Microsoft session cookies (used for silent re-login).
- `git_token` passed to `vibeflow_start_session` is sent to VibeFlow only and never echoed back.
- `vibeflow_logout` revokes server-side and deletes the local token.
