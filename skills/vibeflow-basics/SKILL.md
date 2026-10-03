---
name: vibeflow-basics
description: Start here for any VibeFlow task. Covers sign-in, finding the project, the sandbox lifecycle, cost awareness and the confirm rule that every other vibeflow skill relies on. Use when a user mentions VibeFlow, a VibeFlow project, sandbox or agent conversation.
---

# VibeFlow basics

VibeFlow (vibeflow.fptconsulting.co.jp) is an AI software-development platform. Mental model:

```
project -> task (kanban card = workbench) -> conversation ("run", run_id) -> messages
        -> sandbox session (cloud container with /workspace; one per user + project)
```

## 1. Make sure you are signed in

1. `vibeflow_auth_status` -> if not authenticated, call `vibeflow_login` (opens a browser; the user
   completes Microsoft SSO) and wait for it to return.
2. Tokens refresh automatically. Only sign in again when a tool returns `auth_required`.

## 2. Find the project

- `vibeflow_list_projects(search=...)` -> remember the `project_id`.
- If the user names none and there is exactly one project, use it (and say so).
- Conversations go to the project's default task; tools resolve it from `project_id`.

## 3. Sandbox lifecycle

- Chat, files, git, preview and code tools need the sandbox **running**.
- `vibeflow_ask` starts it for you. Otherwise: `vibeflow_session_status(project_id)` ->
  `vibeflow_start_session(project_id)` (blocks ~30-60 s until running).
- When done with a long session, tell the user, then `vibeflow_stop_session(session_id, confirm=true)`.
  Work is saved and resumable; idle sandboxes also stop on their own.

## 4. Cost awareness

- Every agent turn bills LLM tokens (roughly $0.005-0.03 per simple turn on the default model; workflows,
  deep research and previews cost several times more).
- Check `vibeflow_get_quota` before long jobs; `vibeflow_conversation_usage(run_id)` shows a run's cost.

## Rules

- **`confirm=true`** is required by destructive or publishing tools (delete, push, revert, stop, replace
  workspace, checkout, git sync, raw API writes). Never pass it without the user's explicit approval of
  that specific action - not as a way to get past an error.
- Prefer dedicated tools over `vibeflow_api`; never use the raw API to bypass a confirm guard.
- Errors come back as `{"error": code, "message", "hint"}` - follow the hint (see `vibeflow-troubleshooting`).
- Never invent credentials; ask the user for tokens and never echo them back.

## Toolsets

`VIBEFLOW_TOOLSETS` decides which tools exist: `core` (always), `code`, `pm`, `analytics`, `advanced`,
`admin`. If a tool named in a skill is missing, tell the user which toolset to enable.
