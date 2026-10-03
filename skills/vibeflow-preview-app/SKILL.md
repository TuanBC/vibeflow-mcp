---
name: vibeflow-preview-app
description: Run the project's app in the VibeFlow sandbox on a preview URL, give the user a working sign-in link, read logs, and have the agent fix preview or Mermaid diagram errors. Use when the user wants to see, demo or debug the running app.
---

# Preview the app (toolset code)

1. Sandbox running (`vibeflow_start_session`).
2. `run = vibeflow_preview_run(project_id)` - an agent figures out how to start the app (costs tokens).
3. `vibeflow_wait_for_reply(run.run_id, timeout_seconds=480)`.
4. `vibeflow_preview_status(project_id)` -> exposed ports, URLs and recent logs.
5. `vibeflow_preview_link(project_id, [port])` -> give the user **`signin_link`** (single use). The plain
   `url` answers 401 until a browser has opened the sign-in link once.
6. Errors: `vibeflow_preview_fix(project_id, error_context=<log or error excerpt>)` and wait on its run.
   A broken diagram in a markdown file: `vibeflow_fix_mermaid(project_id, file_path, error_message)`.
7. Finished: `vibeflow_preview_stop(project_id)`.

Some models fail long preview runs with provider errors; retry with the default model.
