# Backlog

Items that could not be verified live yet. Each has unit tests matching the request shapes the SPA sends.

| # | Item | Tools | Blocked on | How to verify |
|---|---|---|---|---|
| B1 | AI commit message returns "AI returned empty response" after ~61 s (every attempt, 2026-10-03) | `vibeflow_generate_commit_message` | Likely platform-side: the MCP sends the same request as the SPA (`task_id` + `session_id`) | In the web UI open a task → **Changes** → generate commit message. Same error ⇒ report to the VibeFlow team; works ⇒ capture the SPA request and diff |
| B2 | Commit + push / PR to a branch | `vibeflow_push_changes` | A git-backed VibeFlow project (only a local project exists) | Test repo + VibeFlow project linked to it + git credentials (or one-off token); push to `mcp-verify/<date>`, never `main` |
| B3 | Branch list / checkout | `vibeflow_list_branches`, `vibeflow_checkout_branch` | Same as B2 | Same project as B2 |
| B4 | Pull from remote | `vibeflow_git_sync` | Same as B2 | Push a commit to the remote outside VibeFlow, then sync |
| B5 | Sandbox start with clone + one-off token | `vibeflow_start_session(git_token=...)` | Same as B2 | Start the B2 project's sandbox; check `clone_warning` is empty |

## Notes from verification

- Some models refuse prompts that inspect the sandbox OS (e.g. reading `/etc/hostname`); use neutral prompts in live tests.
- Gemini Flash failed a long preview run with a provider error ("missing thought_signature"); the default model worked.
- Live test conversations named "MCP …" remain in the private workspace (not deleted — deletion is permanent).
