# vibeflow-mcp

MCP server for **VibeFlow** (https://vibeflow.fptconsulting.co.jp) — drive projects, sandboxes, AI-agent
conversations, workflows, code review, previews and analytics from your AI assistant, without the web UI.

**Quick install** (after [step 1](#1-install-the-server-once)):

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_vibeflow-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=vibeflow&config=%7B%22command%22%3A%22vibeflow-mcp%22%2C%22args%22%3A%5B%5D%2C%22env%22%3A%7B%22VIBEFLOW_TOOLSETS%22%3A%22core%2Ccode%2Canalytics%2Cadvanced%22%7D%7D)
[![Install in VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_vibeflow-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=vibeflow&config=%7B%22command%22%3A%22vibeflow-mcp%22%2C%22args%22%3A%5B%5D%2C%22env%22%3A%7B%22VIBEFLOW_TOOLSETS%22%3A%22core%2Ccode%2Canalytics%2Cadvanced%22%7D%7D&quality=insiders)
[![Claude Code](https://img.shields.io/badge/Claude_Code-one_command-D97757?style=flat-square&logo=anthropic&logoColor=white)](#claude-code)
[![Hermes Agent](https://img.shields.io/badge/Hermes_Agent-config_snippet-6E56CF?style=flat-square)](#hermes-agent)

The VS Code buttons install the server for **GitHub Copilot**. Claude Code and Hermes have no install links, so
their badges jump to a one-step setup below.

Status: all 7 planned phases implemented — 175 tools in 6 toolsets plus MCP resources and prompts, 163 unit
tests, verified against production (see [BACKLOG.md](BACKLOG.md) for what is not yet verified live).
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) has the feature map and learnings.

## Contents

- [What VibeFlow can do (and how this MCP covers it)](#what-vibeflow-can-do-and-how-this-mcp-covers-it)
- [Installation](#installation) — [Claude Code](#claude-code) · [GitHub Copilot](#github-copilot-vs-code) ·
  [Hermes Agent](#hermes-agent) · [Microsoft 365 Copilot / ChatGPT Enterprise](#microsoft-365-copilot-and-chatgpt-enterprise)
- [How auth works](#how-auth-works) · [CLI](#cli) · [Configuration](#configuration-env) · [Tools](#tools)
- [Agent skills](#agent-skills) — ready-made `SKILL.md` playbooks for common workflows

## What VibeFlow can do (and how this MCP covers it)

VibeFlow is an AI software-development platform: every project gets a cloud **sandbox** (a container with the
code) where an **agent harness** reads and writes files, runs commands, delegates to specialist agents, runs
multi-step workflows and serves previews — with git, kanban, budgets and analytics around it.

| Area | VibeFlow capability | MCP tools |
|---|---|---|
| **Chat (Console)** | Talk to the agent in a project; Plan (read-only) vs Build mode; model + thinking-effort picker; attachments; auto-approve | `vibeflow_ask` (one call), `vibeflow_start_conversation`, `vibeflow_send_message`, `vibeflow_wait_for_reply` (live progress) |
| **Agents (`!`)** | 15 built-in specialists (business-analyst, solution-architect, backend-dev, frontend-dev, tester, reviewer, security-auditor, dba-expert, cloud-expert, migration-expert, project-manager, slide-craft, document-to-md, docs-drift, revert-expert) + custom agents | `vibeflow_list_agents`, `agent=` on chat tools, `vibeflow_create/update/delete_agent_template` |
| **Skills (`/`)** | Packaged capabilities: goal, deep-goal, deep-research, speckit-*, slide-craft, workflow, test-driven-development, … | `vibeflow_list_skills`, `skill=` on chat tools |
| **Workflows (`#`)** | 8 built-in pipelines: RFP→Demo, RFP→Proposal, Bug Fix, Code Review, DB Migration, Feature Dev, Full-Stack, Safe Refactor; dynamic workflows | `vibeflow_list_workflows`, `workflow=`, MCP prompts `vibeflow_bug_fix` …, `vibeflow_get_workflow_batches` |
| **Canvas** | Visual multi-agent workflow editor; run all, a single node, or from a node; parallel branches | `vibeflow_get/save_workflow`, `vibeflow_run_workflow`, `vibeflow_run_workflow_step`, workflow templates (create / export / import) |
| **Human in the loop** | Permission prompts (Accept / Deny / Allow always), agent questions | `vibeflow_pending_prompts`, `vibeflow_reply_permission`, `vibeflow_answer_question` |
| **Subagents & background jobs** | Delegated child agents; long commands in the background; scheduled (cron) jobs; goal loops | `vibeflow_list_subagents`, `vibeflow_retry_subagent`, `vibeflow_list_background_jobs`, `vibeflow_background_tool_call`, `vibeflow_stop_job`, `vibeflow_list_cron`, `vibeflow_goal_status/stop` |
| **Conversation management** | Rename, pin, archive, fork, compact, resume, delete; transcripts; cost & context usage | `vibeflow_rename/pin/archive/fork/compact/resume/delete_conversation`, `vibeflow_get_messages`, `vibeflow_conversation_usage` |
| **Sandbox** | Start / stop / resume, auto-save, idle stop, upload a ZIP/folder workspace | `vibeflow_start_session`, `vibeflow_stop_session`, `vibeflow_save_session`, `vibeflow_stop_idle_sessions`, `vibeflow_upload_workspace` |
| **IDE / files** | File tree, read / write / upload / delete / download, workspace zip, code intelligence (hover, definition, references, diagnostics, outline) | `vibeflow_list/read/write/search/upload/delete/download_file`, `vibeflow_download_workspace`, `vibeflow_code_intel` |
| **Changes (git)** | Diff, AI commit message, commit + push / PR, branches, pull, ahead/behind, AI pull-and-merge | `vibeflow_get_changes`, `vibeflow_get_diff`, `vibeflow_generate_commit_message`, `vibeflow_push_changes`, `vibeflow_git_status`, `vibeflow_git_sync`, `vibeflow_ai_pull_merge` |
| **Restore points** | Per-turn checkpoints; preview diff; revert and undo | `vibeflow_list_restore_points`, `vibeflow_restore_point_diff`, `vibeflow_revert_to`, `vibeflow_undo_revert` |
| **Preview** | Run the app on a public preview URL, logs, AI fix, Mermaid fix | `vibeflow_preview_run/status/link/stop/fix`, `vibeflow_fix_mermaid` |
| **Galaxy** | Code knowledge graph of files and symbols | `vibeflow_code_graph` |
| **Context & memory** | Context-window gauge, agent memory and work logs, sandbox MCP servers | `vibeflow_conversation_usage`, `vibeflow_agent_memory`, `vibeflow_sandbox_mcp_servers` |
| **Projects** | Local or git projects, settings, members & roles (pm / tl / member), monthly budget, AI prompt helper | `vibeflow_create/update/delete/pin_project`, `vibeflow_*_member*`, `vibeflow_get/set_budget`, `vibeflow_generate_prompt` |
| **Tasks / kanban** | Board, cards (priority, story points, estimates, assignee), move, archive, attachments | `vibeflow_get_kanban`, `vibeflow_create/update/move/assign/archive/delete_kanban_task`, `vibeflow_*_attachment` |
| **Templates** | Prompt templates with variables, custom agents, workflow templates | `vibeflow_*_prompt_template`, `vibeflow_*_agent_template`, `vibeflow_*_workflow_template` |
| **Integrations** | Project LLM providers (own API keys), git credentials, Jira sync, SharePoint source | `vibeflow_*_llm_provider`, `vibeflow_*_git_credential`, `vibeflow_*jira*`, `vibeflow_get/set_sharepoint*` |
| **Analytics** | Cost by user / task / model, daily cost, outcome & git KPIs, code activity, CSV/PDF report | `vibeflow_project_cost`, `vibeflow_project_cost_daily`, `vibeflow_project_kpis`, `vibeflow_code_activity`, `vibeflow_export_analytics` |
| **Administration** | Users & approvals, roles, platform LLM providers & budgets, DLP, audit, system health, org analytics | `vibeflow_admin_*` (opt-in toolset, needs a system-admin account) |
| **Account & docs** | Platform quota, settings, onboarding, user docs | `vibeflow_get_quota`, `vibeflow_get/update_settings`, `vibeflow_search_docs`, `vibeflow_read_docs` |

Not available through the MCP: two-way local folder sync (browser-only), the SharePoint file picker (the browser
talks to Microsoft Graph directly), and connecting a personal OpenAI account (browser OAuth). See
[BACKLOG.md](BACKLOG.md).

## Installation

### Requirements

- Windows, macOS or Linux with **Python ≥ 3.10** and [**uv**](https://docs.astral.sh/uv/getting-started/installation/)
- A VibeFlow account (Microsoft / FPT SSO)
- Network access to `vibeflow.fptconsulting.co.jp` and `api.vibeflow.fptconsulting.co.jp`

### 1. Install the server (once)

From this repository's folder:

```bash
uv tool install .
```

```bash
uv tool update-shell
```

This puts a `vibeflow-mcp` command on your PATH (open a new terminal after `update-shell`). Then download the
browser used for sign-in and log in once — a window opens for Microsoft SSO:

```bash
vibeflow-mcp install-browser
```

```bash
vibeflow-mcp login
```

The token is stored in your OS credential manager and refreshed automatically; `vibeflow-mcp status` shows it.
To update later, run `uv tool install --reinstall .` from the repository folder.

### 2. Connect your AI assistant

All clients run the same local command, `vibeflow-mcp`, over stdio. `VIBEFLOW_TOOLSETS` picks the tool groups
(see [Configuration](#configuration-env) and the [toolset sizes](#tools)).

#### Claude Code

```bash
claude mcp add vibeflow --scope user -e VIBEFLOW_TOOLSETS=core,code,pm,analytics,advanced -- vibeflow-mcp
```

`--scope user` makes it available in every project; use `--scope project` to write a shared `.mcp.json` instead.
Check with `claude mcp list`, then ask Claude e.g. *"Use vibeflow to list my projects"*.

#### GitHub Copilot (VS Code)

Click **Install in VS Code** (or **VS Code Insiders**) at the top of this page, then open Copilot Chat in **Agent**
mode and enable the `vibeflow` tools. Manual alternative — add to `.vscode/mcp.json` (workspace) or your user
`mcp.json` (*MCP: Open User Configuration*):

```json
{
  "servers": {
    "vibeflow": {
      "type": "stdio",
      "command": "vibeflow-mcp",
      "env": { "VIBEFLOW_TOOLSETS": "core,code,analytics,advanced" }
    }
  }
}
```

Copilot allows at most 128 tools per agent request, so this config leaves out `pm` (96 tools instead of 162). For
project-management work, swap a group in, e.g. `"core,pm"`. Copilot in Visual Studio and JetBrains IDEs uses the
same `command` / `env` fields in its own MCP settings. Your organisation may need to allow MCP servers in its
Copilot policies.

#### Hermes Agent

Add to Hermes' `config.yaml` (`~/.hermes/config.yaml`; on Windows `%LOCALAPPDATA%\hermes\config.yaml`) and restart
Hermes. The longer `timeout` lets agent runs (`vibeflow_ask`, workflows) finish:

```yaml
mcp_servers:
  vibeflow:
    command: "vibeflow-mcp"
    args: []
    env:
      VIBEFLOW_TOOLSETS: "core,code,pm,analytics,advanced"
    timeout: 900
    connect_timeout: 60
```

Hermes needs its optional `mcp` Python package (`pip install mcp`). Tools appear as `mcp_vibeflow_*`.

#### Microsoft 365 Copilot and ChatGPT Enterprise

**Not supported today.** Both connect only to **remote MCP servers over HTTPS** (M365 Copilot through Copilot
Studio / declarative agents, ChatGPT through custom connectors), while this server runs **locally** and acts with
**your personal VibeFlow sign-in**. Exposing it on the internet would let anyone who reaches the URL act as you.
Supporting them needs a hosted, multi-user version with its own OAuth in front of VibeFlow — ideally an official
VibeFlow API or MCP endpoint. Until then, use one of the local clients above.

### Development install

```bash
uv venv .venv && uv pip install -e ".[test]"
```

```bash
.venv/Scripts/python -m pytest
```

`.mcp.json` in this folder is a machine-specific Claude Code config pointing at this checkout's `.venv` (edit the
interpreter path, or switch it to `"command": "vibeflow-mcp"` after step 1).

## Agent skills

[`skills/`](skills/README.md) holds 12 [Agent Skills](https://agentskills.io) (`<name>/SKILL.md`) that teach an
agent the tool sequences, outcomes and guardrails for frequent VibeFlow work: basics, agent chat,
specialists and workflows, review and ship, bug fix, workspace files, preview, Canvas workflows, project
setup, kanban planning, cost and analytics, troubleshooting. Install them with:

```bash
cp -r skills/vibeflow-* ~/.claude/skills/
```

(GitHub Copilot: `<repo>/.github/skills/`; Hermes: `~/.hermes/skills/` — see [skills/README.md](skills/README.md).)

## How auth works

VibeFlow uses Microsoft Entra ID (MSAL.js, SPA redirect flow). After Microsoft sign-in the SPA exchanges the
ID token at `POST /api/v1/auth/azure/token` for a **VibeFlow JWT (8 h)** + **refresh token** and keeps them in
`localStorage["vibeflow-auth"]`.

The Azure app only allows the SPA redirect URI, so the MCP does not run its own OAuth flow. Instead
`vibeflow-mcp login` / `vibeflow_login` opens a real Chromium window (Playwright, persistent profile), you complete
SSO as normal, and the tokens are lifted from localStorage into the OS keyring (or `~/.vibeflow-mcp/tokens.json`).
After that:

- requests send `Authorization: Bearer <jwt>` + a browser User-Agent (the Azure App Gateway WAF 403s non-browser UAs);
- tokens are refreshed automatically via `POST /api/v1/auth/azure/refresh` (rotating) when < 5 min remain or when
  VibeFlow rejects the session; if refresh fails, a silent headless login re-uses the saved Microsoft session.

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

## Tools

Toolsets are chosen with `VIBEFLOW_TOOLSETS` (default `core,code`; the bundled `.mcp.json` enables
`core,code,pm,analytics,advanced`). Destructive or publishing tools require `confirm=true`; every tool carries
MCP `readOnlyHint` / `destructiveHint` annotations. Errors come back as `{"error": <code>, "message", "hint"}`
(e.g. `auth_required`, `no_session`, `busy`, `forbidden`, `quota_exceeded`).

| Toolset | Tools | Scope |
|---|---|---|
| `core` | 53 | auth, account, workspace reads, sandbox, models & pickers, chat (`vibeflow_ask`, streaming wait), human-in-the-loop, conversation management, raw API |
| `code` | 28 | workspace files, git changes / push, restore points, preview (+ sign-in link) |
| `pm` | 66 | projects, members & roles, budget, kanban, tasks & attachments, prompt / agent / workflow templates, Canvas workflows, git credentials, LLM providers, Jira, SharePoint, settings |
| `analytics` | 5 | project cost breakdowns, daily cost, KPIs, code activity, csv/pdf report export |
| `advanced` | 10 | code intelligence (LSP), Galaxy code graph, agent goal / cron / memory, sandbox MCP servers, background jobs |
| `admin` | 13 | users, platform providers & budgets, audit, DLP, sessions, system health, org analytics (system admin role) |

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
| Sandbox | `vibeflow_session_status`, `vibeflow_list_my_sessions`, `vibeflow_start_session`, `vibeflow_save_session`, `vibeflow_stop_session`*, `vibeflow_stop_idle_sessions`*, `vibeflow_reset_session_baseline`, `vibeflow_reload_agent_config` |
| Pickers | `vibeflow_list_models`, `vibeflow_list_agents` (!), `vibeflow_list_skills` (/), `vibeflow_list_workflows` (#) |
| Chat | **`vibeflow_ask`**, `vibeflow_start_conversation`, `vibeflow_send_message`, `vibeflow_wait_for_reply` |
| Human in the loop | `vibeflow_pending_prompts`, `vibeflow_reply_permission`, `vibeflow_answer_question` |
| Subagents & workflow batches | `vibeflow_list_subagents`, `vibeflow_retry_subagent`, `vibeflow_get_workflow_batches` (plus `subagent=` on `vibeflow_get_messages` / `vibeflow_abort`) |
| Conversation mgmt | `vibeflow_list_conversations`, `vibeflow_get_conversation`, `vibeflow_get_messages`, `vibeflow_get_transcript`, `vibeflow_conversation_usage`, `vibeflow_list_artifacts`, `vibeflow_abort`, `vibeflow_resume_conversation`, `vibeflow_compact_conversation`, `vibeflow_fork_conversation`, `vibeflow_rename_conversation`, `vibeflow_pin_conversation`, `vibeflow_archive_conversation`, `vibeflow_delete_conversation`* |
| Docs | `vibeflow_search_docs`, `vibeflow_read_docs` (public VibeFlow user docs) |
| Escape hatch | `vibeflow_api` |

### code (sandbox must be running)

| Group | Tools |
|---|---|
| Files | `vibeflow_list_files`, `vibeflow_read_file`, `vibeflow_search_files`, `vibeflow_write_file`, `vibeflow_upload_file`, `vibeflow_delete_file`*, `vibeflow_download_file`, `vibeflow_download_workspace`, `vibeflow_upload_workspace`* (**replaces the whole workspace**; auto-backup first) |
| Git | `vibeflow_list_branches`, `vibeflow_checkout_branch`*, `vibeflow_get_changes`, `vibeflow_get_diff`, `vibeflow_generate_commit_message`, `vibeflow_push_changes`*, `vibeflow_git_sync`*, `vibeflow_git_status`, `vibeflow_ai_pull_merge` |
| Restore points | `vibeflow_list_restore_points`, `vibeflow_restore_point_diff`, `vibeflow_revert_to`*, `vibeflow_undo_revert` |
| Preview | `vibeflow_preview_run`, `vibeflow_preview_status`, `vibeflow_preview_link`, `vibeflow_preview_stop`, `vibeflow_preview_fix`, `vibeflow_fix_mermaid` |

### pm

| Group | Tools |
|---|---|
| Projects | `vibeflow_create_project`, `vibeflow_update_project`, `vibeflow_delete_project`*, `vibeflow_pin_project`, `vibeflow_generate_prompt` |
| People & budget | `vibeflow_list_members`, `vibeflow_search_users`, `vibeflow_list_roles`, `vibeflow_add_member`, `vibeflow_update_member_role`, `vibeflow_remove_member`*, `vibeflow_get_budget`, `vibeflow_set_budget` |
| Kanban & tasks | `vibeflow_create_kanban_task`, `vibeflow_update_kanban_task`, `vibeflow_move_kanban_task`, `vibeflow_assign_kanban_task`, `vibeflow_archive_kanban_task`, `vibeflow_list_archived_tasks`, `vibeflow_delete_kanban_task`*, `vibeflow_create_task`, `vibeflow_update_task`, `vibeflow_delete_task`*, `vibeflow_list_attachments`, `vibeflow_add_attachment`, `vibeflow_download_attachment`, `vibeflow_delete_attachment`* |
| Templates | `vibeflow_list_prompt_templates`, `vibeflow_create_prompt_template`, `vibeflow_delete_prompt_template`*, `vibeflow_get_agent_template`, `vibeflow_create_agent_template`, `vibeflow_update_agent_template`, `vibeflow_delete_agent_template`*, `vibeflow_get_workflow_template`, `vibeflow_create_workflow_template`, `vibeflow_update_workflow_template`, `vibeflow_delete_workflow_template`*, `vibeflow_export_workflow_template`, `vibeflow_import_workflow_template` |
| Canvas | `vibeflow_get_workflow`, `vibeflow_save_workflow`, `vibeflow_run_workflow`, `vibeflow_run_workflow_step` |
| Integrations | `vibeflow_list_git_credentials`, `vibeflow_add_git_credential`, `vibeflow_delete_git_credential`*, `vibeflow_list_llm_providers`, `vibeflow_add_llm_provider`, `vibeflow_verify_llm_provider`, `vibeflow_update_llm_provider`, `vibeflow_delete_llm_provider`*, `vibeflow_list_jira_sites`, `vibeflow_list_jira_projects`, `vibeflow_list_jira_statuses`, `vibeflow_get_jira_sync`, `vibeflow_configure_jira_sync`, `vibeflow_test_jira_connection`, `vibeflow_trigger_jira_sync`, `vibeflow_delete_jira_sync`*, `vibeflow_get_sharepoint`, `vibeflow_set_sharepoint_source` |
| Settings | `vibeflow_get_settings`, `vibeflow_update_settings`, `vibeflow_get_onboarding`, `vibeflow_accept_terms` |

### analytics · advanced · admin

| Toolset | Tools |
|---|---|
| analytics | `vibeflow_project_cost`, `vibeflow_project_cost_daily`, `vibeflow_project_kpis`, `vibeflow_code_activity`, `vibeflow_export_analytics` |
| advanced | `vibeflow_code_intel`, `vibeflow_code_graph`, `vibeflow_goal_status`, `vibeflow_goal_stop`, `vibeflow_list_cron`, `vibeflow_agent_memory`, `vibeflow_sandbox_mcp_servers`, `vibeflow_list_background_jobs`, `vibeflow_background_tool_call`, `vibeflow_stop_job` |
| admin | `vibeflow_admin_list`, `vibeflow_admin_analytics`, `vibeflow_admin_user`*, `vibeflow_admin_import_users`*, `vibeflow_admin_archive_project`*, `vibeflow_admin_stop_session`*, `vibeflow_admin_flag_conversation`, `vibeflow_admin_provider`*, `vibeflow_admin_user_key`*, `vibeflow_admin_set_budget`*, `vibeflow_admin_update_role`*, `vibeflow_admin_dlp_test`, `vibeflow_admin_export` |

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
