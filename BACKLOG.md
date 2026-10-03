# Backlog

Items not verified live yet, or deliberately deferred. Implemented items have unit tests matching the request shapes the SPA and the API's validation expect.

| # | Item | Tools | Blocked on | How to verify |
|---|---|---|---|---|
| B1 | AI commit message returns "AI returned empty response" after ~61 s (every attempt, 2026-10-03) | `vibeflow_generate_commit_message` | Likely platform-side: the MCP sends the same request as the SPA (`task_id` + `session_id`) | In the web UI open a task → **Changes** → generate commit message. Same error ⇒ report to the VibeFlow team; works ⇒ capture the SPA request and diff |
| B2 | Commit + push / PR to a branch | `vibeflow_push_changes` | A git-backed VibeFlow project (only a local project exists) | Test repo + VibeFlow project linked to it + git credentials (or one-off token); push to `mcp-verify/<date>`, never `main` |
| B3 | Branch list / checkout | `vibeflow_list_branches`, `vibeflow_checkout_branch` | Same as B2 | Same project as B2 |
| B4 | Pull from remote | `vibeflow_git_sync` | Same as B2 | Push a commit to the remote outside VibeFlow, then sync |
| B5 | Sandbox start with clone + one-off token | `vibeflow_start_session(git_token=...)` | Same as B2 | Start the B2 project's sandbox; check `clone_warning` is empty |
| B6 | Admin toolset end to end | all `vibeflow_admin_*` | The test account is a member; only the 403 path was verified live | With a system-admin account: `vibeflow_admin_list('overview')`, a report, then one reversible write (flag / unflag a conversation) |
| ~~B7~~ | ~~Phase 4 write tools not run live~~ (done, see below) (they create, change or delete shared data) | create/update/delete project; add/update/remove member; set budget; prompt/agent/workflow template create/update/delete/import; task create/update/delete; attachment add/delete; LLM provider add/verify/update/delete; Jira configure/test/trigger/delete; SharePoint source; git credential add/delete; settings update; accept terms; delete kanban task | Bodies confirmed by the API's 422 validation, but these mutate real data | In a throwaway project: create → update → verify → delete each resource; delete the project last |
| ~~B8~~ | ~~Canvas workflow run / single step~~ — **verified live 2026-10-03**: 2-node workflow on a throwaway card; single step, full run (node 2 read node 1's output) and start-from-node-2 (node 1 skipped) | `vibeflow_run_workflow`, `vibeflow_run_workflow_step`, `vibeflow_save_workflow` | — | Done |
| B10 | AI pull-merge not run live (Mermaid fix: done, see below) (start paid agent runs; pull-merge needs a git remote) | `vibeflow_ai_pull_merge`, `vibeflow_fix_mermaid` | B2 for pull-merge | Same as the verified `vibeflow_preview_fix` pattern; run on the B2 project |
| B9 | Local file sync over WebSocket (`/sessions/{id}/file-sync-ticket`) | not implemented | Binary chunked protocol; low value next to upload / download / download_workspace | Implement only if two-way live sync is needed |

## Verified live in a throwaway project (2026-10-03)

Project `mcp-verify-2026-10-03` was created, used and deleted (cost $0.086 of platform quota):
- **B7 done**: project create / update / pin / delete (soft delete); AI prompt helper (fixed: structured context);
  own membership read + role update; budget set / read / disable; prompt templates (fixed: variable objects);
  custom agents (fixed: `userPrompt`); workflow templates create / update / export / import / delete; tasks
  (fixed: kanban endpoints) and attachments upload / download (byte-identical) / delete; kanban card delete;
  LLM provider add / verify / update / delete; git credential add / delete (token never echoed); Jira
  test / configure / list (fixed: upstream 401 handling); SharePoint source; settings update + revert.
- **B10b done**: AI Mermaid fix repaired a broken diagram.
- **Partials done**: restore-point diff (fixed: `before_snapshot`), background a running call + stop job
  (new `vibeflow_list_background_jobs`), goal status + stop, subagent list / thread / retry, static preview served
  through the sign-in link, hover / definition, delete conversation, upload-workspace with automatic backup on a
  brand-new project (fixed: default-task fallback).
- **Deliberately not run**: accept terms (accepts a legal agreement for the user); adding / removing other people
  as members (affects colleagues).
- **Platform findings**: `DELETE /api/v1/tasks/{id}` and `DELETE /api/v1/kanban/tasks/{id}` return 500 for a task
  created through the legacy `POST /api/v1/tasks` (that test task is still readable server-side, inside the deleted
  project); project delete is a soft delete.

## Notes from verification

- Some models refuse prompts that inspect the sandbox OS (e.g. reading `/etc/hostname`); use neutral prompts in live tests.
- Gemini Flash failed a long preview run with a provider error ("missing thought_signature"); the default model worked.
- Live test artifacts remain in the private workspace (deletion is permanent, so they were kept): conversations named "MCP …", and the archived kanban card "MCP verify card".
- During schema probing one junk git credential was created by mistake (`POST /git-credentials` accepts any provider) and was deleted immediately; later probes only used fake-id paths or invalid bodies.

## Incident 2026-10-03: workspace replaced during upload-workspace verification

- `POST /sessions/{id}/upload-workspace` **replaces the entire workspace** (it is the first-load step for new Local
  projects). The live test, written assuming it merged files, left `/workspace` with a single probe file.
- Restored the same day from the full workspace export downloaded earlier that day (`files/download-workspace`):
  **32/32 files restored byte-identical** (README, AGENTS.md, jira_mcp_server.py, pyproject.toml, uv.lock,
  test_mcp_tools.py, .github, .omo, all docs/ incl. the uncommitted docs/00_converted/handoff_to_pm.md); saved to cloud.
- **Not recoverable from that export** (the platform omits them): `.env`, `.env.example`, `.gitignore` and the
  workspace's `.git` history (git was re-initialised). Restore these from your own copy of the project.
- Fix: the tool now says it replaces everything, requires `replace_workspace=true` + `confirm=true`, and downloads a
  backup of the current workspace to `~/.vibeflow-mcp/backups/` first (aborting if the backup fails) — regression-tested.
