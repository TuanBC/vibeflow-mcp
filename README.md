# vibeflow-mcp

MCP server for **VibeFlow** (https://vibeflow.fptconsulting.co.jp) — drive projects, sandboxes and
AI-agent conversations from Claude Code (or any MCP client) without the web UI.

Status: **all 7 planned phases implemented** — 160 tools in 6 toolsets plus MCP resources and prompts, 130 unit
tests, verified against production (see [BACKLOG.md](BACKLOG.md) for what could not be verified live).
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) has the feature map and learnings.

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
| `VIBEFLOW_TOOLSETS` | `core,code` | tool groups: `core`, `code`, `pm`, `analytics`, `advanced`, `admin` |
| `VIBEFLOW_TOKEN_BACKEND` | `auto` | `keyring` (OS credential store), `file`, or `auto` (keyring if available; migrates an old `tokens.json`) |
| `VIBEFLOW_SILENT_RELOGIN` | `1` | when refresh fails, try a headless SSO login with the saved browser profile |
| `VIBEFLOW_DEFAULT_MODEL` | – | model used by `vibeflow_ask` when none is given |
| `VIBEFLOW_USER_AGENT` | Chrome UA | sent on every request (the WAF blocks non-browser UAs) |

### Tests

```bash
.venv/Scripts/python -m pytest
```

## Tools

Toolsets are chosen with `VIBEFLOW_TOOLSETS` (default `core,code`; the bundled `.mcp.json` enables
`core,code,pm,analytics,advanced`). Destructive or publishing tools require `confirm=true`; every tool carries
MCP `readOnlyHint` / `destructiveHint` annotations. Errors come back as `{"error": <code>, "message", "hint"}`
(e.g. `auth_required`, `no_session`, `busy`, `forbidden`, `quota_exceeded`).

| Toolset | Tools | Scope |
|---|---|---|
| `core` | 45 | auth, account, workspace reads, sandbox, models & pickers, chat (`vibeflow_ask`, streaming wait), human-in-the-loop, conversation management, raw API |
| `code` | 24 | workspace files, git changes / push, restore points, preview (+ sign-in link) |
| `pm` | 65 | projects, members & roles, budget, kanban, tasks & attachments, prompt / agent / workflow templates, Canvas workflows, git credentials, LLM providers, Jira, SharePoint, settings |
| `analytics` | 5 | project cost breakdowns, daily cost, KPIs, code activity, csv/pdf report export |
| `advanced` | 9 | code intelligence (LSP), Galaxy code graph, agent goal / cron / memory, sandbox MCP servers, background jobs |
| `admin` | 12 | users, platform providers & budgets, audit, DLP, sessions, system health, org analytics (system admin role) |

**MCP resources:** `vibeflow://runs/{run_id}/transcript`, `vibeflow://runs/{run_id}/messages`,
`vibeflow://projects/{project_id}/overview`, `vibeflow://projects/{project_id}/workflows`.

**MCP prompts:** one per built-in workflow — `vibeflow_bug_fix`, `vibeflow_code_review`, `vibeflow_feature_dev`,
`vibeflow_full_stack`, `vibeflow_db_migration`, `vibeflow_safe_refactor`, `vibeflow_rfp_to_demo`,
`vibeflow_rfp_to_proposal` (arguments: `project_id`, `request`).

### core

| Group | Tools |
|---|---|
| Auth & account | `vibeflow_login`, `vibeflow_set_token`, `vibeflow_auth_status`, `vibeflow_logout`, `vibeflow_whoami`, `vibeflow_my_stats`, `vibeflow_get_quota` |
| Workspace | `vibeflow_list_projects`, `vibeflow_get_project`, `vibeflow_get_recent_task`, `vibeflow_list_tasks`, `vibeflow_get_task`, `vibeflow_get_kanban`, `vibeflow_search` |
| Sandbox | `vibeflow_session_status`, `vibeflow_list_my_sessions`, `vibeflow_start_session`, `vibeflow_save_session`, `vibeflow_stop_session`* |
| Pickers | `vibeflow_list_models`, `vibeflow_list_agents` (!), `vibeflow_list_skills` (/), `vibeflow_list_workflows` (#) |
| Chat | **`vibeflow_ask`**, `vibeflow_start_conversation`, `vibeflow_send_message`, `vibeflow_wait_for_reply` |
| Human in the loop | `vibeflow_pending_prompts`, `vibeflow_reply_permission`, `vibeflow_answer_question` |
| Conversation mgmt | `vibeflow_list_conversations`, `vibeflow_get_conversation`, `vibeflow_get_messages`, `vibeflow_get_transcript`, `vibeflow_conversation_usage`, `vibeflow_list_artifacts`, `vibeflow_abort`*, `vibeflow_resume_conversation`, `vibeflow_compact_conversation`, `vibeflow_fork_conversation`, `vibeflow_rename_conversation`, `vibeflow_pin_conversation`, `vibeflow_archive_conversation`, `vibeflow_delete_conversation`* |
| Escape hatch | `vibeflow_api` |

### code (sandbox must be running)

| Group | Tools |
|---|---|
| Files | `vibeflow_list_files`, `vibeflow_read_file`, `vibeflow_search_files`, `vibeflow_write_file`, `vibeflow_upload_file`, `vibeflow_delete_file`*, `vibeflow_download_file`, `vibeflow_download_workspace` |
| Git | `vibeflow_list_branches`, `vibeflow_checkout_branch`, `vibeflow_get_changes`, `vibeflow_get_diff`, `vibeflow_generate_commit_message`, `vibeflow_push_changes`*, `vibeflow_git_sync` |
| Restore points | `vibeflow_list_restore_points`, `vibeflow_restore_point_diff`, `vibeflow_revert_to`*, `vibeflow_undo_revert` |
| Preview | `vibeflow_preview_run`, `vibeflow_preview_status`, `vibeflow_preview_link`, `vibeflow_preview_stop`, `vibeflow_preview_fix` |

### pm

| Group | Tools |
|---|---|
| Projects | `vibeflow_create_project`, `vibeflow_update_project`, `vibeflow_delete_project`*, `vibeflow_pin_project`, `vibeflow_generate_prompt` |
| People & budget | `vibeflow_list_members`, `vibeflow_search_users`, `vibeflow_list_roles`, `vibeflow_add_member`, `vibeflow_update_member_role`, `vibeflow_remove_member`*, `vibeflow_get_budget`, `vibeflow_set_budget` |
| Kanban & tasks | `vibeflow_create_kanban_task`, `vibeflow_update_kanban_task`, `vibeflow_move_kanban_task`, `vibeflow_assign_kanban_task`, `vibeflow_archive_kanban_task`, `vibeflow_list_archived_tasks`, `vibeflow_delete_kanban_task`*, `vibeflow_create_task`, `vibeflow_update_task`, `vibeflow_delete_task`*, `vibeflow_list_attachments`, `vibeflow_add_attachment`, `vibeflow_download_attachment`, `vibeflow_delete_attachment`* |
| Templates | `vibeflow_list_prompt_templates`, `vibeflow_create_prompt_template`, `vibeflow_delete_prompt_template`*, `vibeflow_get_agent_template`, `vibeflow_create_agent_template`, `vibeflow_update_agent_template`, `vibeflow_delete_agent_template`*, `vibeflow_get_workflow_template`, `vibeflow_create_workflow_template`, `vibeflow_update_workflow_template`, `vibeflow_delete_workflow_template`*, `vibeflow_export_workflow_template`, `vibeflow_import_workflow_template` |
| Canvas | `vibeflow_get_workflow`, `vibeflow_save_workflow`, `vibeflow_run_workflow`, `vibeflow_run_workflow_step` |
| Integrations | `vibeflow_list_git_credentials`, `vibeflow_add_git_credential`, `vibeflow_delete_git_credential`*, `vibeflow_list_llm_providers`, `vibeflow_add_llm_provider`, `vibeflow_verify_llm_provider`, `vibeflow_update_llm_provider`, `vibeflow_delete_llm_provider`*, `vibeflow_list_jira_sites`, `vibeflow_list_jira_projects`, `vibeflow_get_jira_sync`, `vibeflow_configure_jira_sync`, `vibeflow_test_jira_connection`, `vibeflow_trigger_jira_sync`, `vibeflow_delete_jira_sync`*, `vibeflow_get_sharepoint`, `vibeflow_set_sharepoint_source` |
| Settings | `vibeflow_get_settings`, `vibeflow_update_settings`, `vibeflow_get_onboarding`, `vibeflow_accept_terms` |

### analytics · advanced · admin

| Toolset | Tools |
|---|---|
| analytics | `vibeflow_project_cost`, `vibeflow_project_cost_daily`, `vibeflow_project_kpis`, `vibeflow_code_activity`, `vibeflow_export_analytics` |
| advanced | `vibeflow_code_intel`, `vibeflow_code_graph`, `vibeflow_goal_status`, `vibeflow_goal_stop`*, `vibeflow_list_cron`, `vibeflow_agent_memory`, `vibeflow_sandbox_mcp_servers`, `vibeflow_background_tool_call`, `vibeflow_stop_job`* |
| admin | `vibeflow_admin_list`, `vibeflow_admin_analytics`, `vibeflow_admin_user`*, `vibeflow_admin_import_users`*, `vibeflow_admin_archive_project`*, `vibeflow_admin_stop_session`*, `vibeflow_admin_flag_conversation`, `vibeflow_admin_provider`*, `vibeflow_admin_user_key`*, `vibeflow_admin_set_budget`*, `vibeflow_admin_dlp_test`, `vibeflow_admin_export` |

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
