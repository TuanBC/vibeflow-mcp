---
name: vibeflow-workspace-files
description: Read, search, write, upload, download or delete files in a VibeFlow project's sandbox workspace, inspect code with LSP, and export or seed the whole workspace. Use when the user wants to look at or move files in VibeFlow directly, without asking the agent.
---

# Workspace files (toolset code)

Paths are relative to `/workspace`. The sandbox must be running (`vibeflow_start_session`).

| Need | Tool |
|---|---|
| Tree | `vibeflow_list_files(project_id, max_depth=3)` |
| Find by name | `vibeflow_search_files(project_id, query)` |
| Read text | `vibeflow_read_file(project_id, path, offset=0)` - page on with `next_offset` |
| Create / overwrite text | `vibeflow_write_file(project_id, path, content)` |
| Upload a local file | `vibeflow_upload_file(project_id, local_path, dest_dir)` |
| Download one file | `vibeflow_download_file(project_id, path, local_path)` |
| Export everything | `vibeflow_download_workspace(project_id, local_path)` (zip) |
| Delete | `vibeflow_delete_file(project_id, path, confirm=true)` - ask first |
| Code intelligence (advanced) | `vibeflow_code_intel(project_id, method, file, line, character)` |
| Code map (advanced) | `vibeflow_code_graph(project_id)` |

## DANGER: replacing the workspace

`vibeflow_upload_workspace(project_id, local_path, replace_workspace=true, confirm=true)` **deletes every
existing file** and loads a zip or folder instead. It is meant for seeding a new, empty project. A backup
zip is saved to `~/.vibeflow-mcp/backups/` first, but it does not contain `.env`, `.gitignore` or git
history. To add or change files, use `vibeflow_upload_file` / `vibeflow_write_file` instead.

## Tips

- Large files: page with `offset` / `next_offset` instead of a huge `max_chars`.
- Binary files (images, PDFs, office documents): use `vibeflow_download_file`, not `vibeflow_read_file`.
- New files not showing up: `vibeflow_list_files(project_id, refresh=true)`.
