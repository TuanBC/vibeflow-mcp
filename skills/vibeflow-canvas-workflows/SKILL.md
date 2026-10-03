---
name: vibeflow-canvas-workflows
description: Build, edit and run custom multi-agent VibeFlow Canvas workflows (a graph of specialist-agent nodes) - run all nodes, from a node or a single node, and save reusable workflow templates. Use when the user wants a repeatable multi-step agent pipeline that the built-in workflows do not cover.
---

# Canvas workflows

A Canvas workflow belongs to a task and is `{nodes, edges}`. Each node runs one agent with instructions;
edges hand over to the next node (later nodes read earlier nodes' files).

## Build

1. A task to hold it: `vibeflow_create_kanban_task(project_id, name)` (toolset pm), or an existing `task_id`.
2. Start from a template (`vibeflow_get_workflow_template(project_id, "builtin-feature-dev")`) or write nodes:
   ```json
   {"nodes": [
     {"id": "node-1", "type": "agent", "position": {"x": 0, "y": 0},
      "data": {"agentType": "backend-dev", "label": "Implement", "instructions": "...", "model": "",
               "contextFiles": [], "compact": true, "self_verify": false}},
     {"id": "node-2", "type": "agent", "position": {"x": 300, "y": 0},
      "data": {"agentType": "tester", "label": "Test", "instructions": "...", "model": "",
               "contextFiles": [], "compact": true, "self_verify": false}}],
    "edges": [{"id": "e-1-2", "source": "node-1", "target": "node-2"}]}
   ```
   `model: ""` = default model. Draft node instructions with
   `vibeflow_generate_prompt(project_id, kind="workflow_instruction", idea=..., name=<label>, agent_type=...)`.
3. `vibeflow_save_workflow(task_id, workflow)`; check with `vibeflow_get_workflow(task_id)`.

## Run

- Whole workflow: `vibeflow_run_workflow(task_id)`; from a node: `start_from_node_id="node-2"`;
  one node only: `vibeflow_run_workflow_step(task_id, node_id)`.
- `vibeflow_wait_for_reply(run_id, timeout_seconds=900)` - reports each node's status and only finishes
  when no node is pending or running.

## Reuse

- Save as a template: `vibeflow_create_workflow_template(project_id, name, workflow_json)`.
- Share: `vibeflow_export_workflow_template` -> `vibeflow_import_workflow_template` in another project.

Keep instructions short and `self_verify` off at first to limit cost; check `vibeflow_get_quota`.
