---
name: vibeflow-kanban-planning
description: Plan and track work on a VibeFlow project's kanban board - create, describe, estimate, assign, move and archive task cards, and attach specs. Use when the user wants to organise work items or turn a plan into cards (toolset pm).
---

# Kanban planning (toolset pm)

1. Board: `vibeflow_get_kanban(project_id)` -> columns (e.g. Backlog, In Progress, Done) with cards.
2. Create: `vibeflow_create_kanban_task(project_id, name, description, column="Backlog", priority="medium", story_points=3, estimate_hours=4, assignee_id=...)`
   - priority: `low`, `medium`, `high`, `urgent`; `column` accepts a name or an id.
   - Draft a description: `vibeflow_generate_prompt(project_id, kind="task_description", idea=..., name=<card>)`.
3. Update: `vibeflow_update_kanban_task(task_id, ...)`; move: `vibeflow_move_kanban_task(project_id, task_id, column)`;
   assign: `vibeflow_assign_kanban_task(task_id, assignee_id)` (ids from `vibeflow_search_users`).
4. Specs: `vibeflow_add_attachment(task_id, local_path)`; list, download or delete attachments likewise.
5. Done: `vibeflow_archive_kanban_task(task_id)` (reversible; see `vibeflow_list_archived_tasks`).
   `vibeflow_delete_kanban_task` needs confirm.

Each card is also a workbench: conversations and Canvas workflows can run inside its `task_id`.

Turning a plan into cards: one card per deliverable, acceptance criteria in the description, an hour
estimate, and a priority. Show the list to the user before creating many cards.
