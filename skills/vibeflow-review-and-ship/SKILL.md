---
name: vibeflow-review-and-ship
description: Review what the VibeFlow agent changed in the sandbox and publish it - changed files, diffs, AI commit message, commit and push or PR branch, branch sync, and undoing agent edits with restore points. Use after any agent run that modified code, or when the user asks to commit, push, open a PR or roll back.
---

# Review changes and ship (toolset code)

## Review

1. `vibeflow_get_changes(project_id)` -> branch and changed files with +/- counts.
   `scope="session"` = only this sandbox session's edits; `fetch_remote=true` refreshes ahead/behind.
2. `vibeflow_get_diff(project_id, path)` for each relevant file; summarise for the user.
3. Optional second opinion: `vibeflow_ask(project_id, agent="reviewer", mode="plan", prompt="Review the uncommitted changes for bugs and risks.")`.

## Commit and push (git projects)

1. `vibeflow_generate_commit_message(project_id)` - server-side LLM; can be slow or fail, then write the
   message yourself from the diffs.
2. Show title, body and file list to the user and get approval.
3. `vibeflow_push_changes(project_id, title, body, [paths], [target_branch], confirm=true)` -
   `target_branch` pushes to a new branch for a PR; omit `paths` to include every changed file.
4. Branches: `vibeflow_list_branches`, `vibeflow_checkout_branch(project_id, branch, confirm=true)`.
   Remote state: `vibeflow_git_status(project_id, fetch_remote=true)`; pull: `vibeflow_git_sync(project_id, confirm=true)`.
   Behind with conflicts: `vibeflow_ai_pull_merge(project_id, branch, behind_count)` (an agent merges).

Local (non-git) projects cannot push; offer `vibeflow_download_workspace(project_id, local_path)` instead.

## Roll back agent edits (restore points)

1. `vibeflow_list_restore_points(run_id)` -> points per agent turn with file counts.
2. Preview: `vibeflow_restore_point_diff(run_id, point)` -> `[{file, patch}]`.
3. After user approval: `vibeflow_revert_to(run_id, message_id, confirm=true)`.
4. Changed your mind: `vibeflow_undo_revert(run_id)`.

Restore points exist only for conversations that ran in the current sandbox session.

## Guardrails

- Never push, revert, checkout or sync without explicit approval of that exact action.
- Do not push to `main` or protected branches unless asked; prefer a `target_branch`.
