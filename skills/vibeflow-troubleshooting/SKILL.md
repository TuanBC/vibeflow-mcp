---
name: vibeflow-troubleshooting
description: Diagnose and recover from vibeflow MCP errors and stuck runs - error codes such as auth_required, no_session, busy, operation_failed and credential_rejected, runs that time out or never answer, and missing tools. Use whenever a vibeflow tool returns an error or behaves unexpectedly.
---

# Troubleshooting

## Error codes

| error | meaning | recovery |
|---|---|---|
| `auth_required` | not signed in or session expired | `vibeflow_login` |
| `credential_rejected` | a token *you passed* (Jira PAT, API key) was refused | ask the user for a valid one |
| `no_session` | sandbox not running | `vibeflow_start_session(project_id)` |
| `busy` | sandbox starting/saving or agent mid-turn | wait `retry_after_seconds`, retry |
| `operation_failed` | VibeFlow reported the action failed | read `message`; fix input or state |
| `confirmation_required` | destructive tool called without confirm | ask the user, then pass `confirm=true` |
| `not_found` | wrong id, or a resource from an earlier sandbox session | re-list ids |
| `forbidden` | role lacks permission (admin tools need a system admin) | tell the user |
| `quota_exceeded` | budget or quota used up | `vibeflow_get_quota`, `vibeflow_get_budget` |
| `pending_approval` / `account_disabled` | VibeFlow account state | user contacts a VibeFlow admin |
| `timeout` / `network_error` / `server_error` | slow or failing service | retry later; AI-backed endpoints can take over a minute |
| `backup_failed` | workspace backup failed, nothing was replaced | fix the cause before retrying |
| `bad_request` | invalid parameters | read `message` and fix the call |
| `internal_error` | unexpected response or a vibeflow-mcp bug | report the message |

## Runs that hang

- `timeout` = the agent is still working: `vibeflow_wait_for_reply(run_id, timeout_seconds=600)`.
- No progress: `vibeflow_pending_prompts(run_id)` (a permission may be waiting),
  `vibeflow_list_background_jobs(run_id)`, `vibeflow_get_messages(run_id, last_n=5)`.
- Stuck: `vibeflow_abort(run_id)`, then send a clearer prompt or switch model.
- "Model not configured for any provider": pass `provider/id` from `vibeflow_list_models`.

## Missing tools

A tool named in a skill is absent -> its toolset is disabled in `VIBEFLOW_TOOLSETS` (core, code, pm,
analytics, advanced, admin). GitHub Copilot allows at most 128 tools, so enable only what is needed there.

## Learn the platform

`vibeflow_search_docs(query)` then `vibeflow_read_docs(path)` explain VibeFlow features from its own docs.
