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
| B7 | Phase 4 write tools not run live (they create, change or delete shared data) | create/update/delete project; add/update/remove member; set budget; prompt/agent/workflow template create/update/delete/import; task create/update/delete; attachment add/delete; LLM provider add/verify/update/delete; Jira configure/test/trigger/delete; SharePoint source; git credential add/delete; settings update; accept terms; delete kanban task | Bodies confirmed by the API's 422 validation, but these mutate real data | In a throwaway project: create → update → verify → delete each resource; delete the project last |
| B8 | Canvas workflow run / single step | `vibeflow_run_workflow`, `vibeflow_run_workflow_step` | Costs a multi-agent run | Run one step of a small custom workflow and wait with `vibeflow_wait_for_reply` |
| B9 | Local file sync over WebSocket (`/sessions/{id}/file-sync-ticket`) | not implemented | Binary chunked protocol; low value next to upload / download / download_workspace | Implement only if two-way live sync is needed |

## Notes from verification

- Some models refuse prompts that inspect the sandbox OS (e.g. reading `/etc/hostname`); use neutral prompts in live tests.
- Gemini Flash failed a long preview run with a provider error ("missing thought_signature"); the default model worked.
- Live test artifacts remain in the private workspace (deletion is permanent, so they were kept): conversations named "MCP …", and the archived kanban card "MCP verify card".
- During schema probing one junk git credential was created by mistake (`POST /git-credentials` accepts any provider) and was deleted immediately; later probes only used fake-id paths or invalid bodies.
