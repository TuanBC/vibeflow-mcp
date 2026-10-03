---
name: vibeflow-specialists-and-workflows
description: Pick and run the right VibeFlow specialist agent, packaged skill or built-in multi-agent workflow - reviewer, tester, security-auditor, deep-research, goal loops, Bug Fix / Feature Dev / Code Review pipelines. Use when a task fits a specialist role or a standard pipeline better than a plain chat.
---

# Specialist agents, skills and workflows

| In the web UI | What | List with | Run with |
|---|---|---|---|
| `!` agent | one focused expert role | `vibeflow_list_agents(project_id)` | `vibeflow_ask(..., agent="reviewer")` |
| `/` skill | packaged procedure | `vibeflow_list_skills(project_id)` (sandbox running) | `vibeflow_ask(..., skill="deep-research")` |
| `#` workflow | fixed multi-agent pipeline | `vibeflow_list_workflows(project_id)` | `vibeflow_ask(..., workflow="builtin-bug-fix")` |

## Choosing

- Review, security, tests, DB, cloud, architecture -> agents `reviewer`, `security-auditor`, `tester`,
  `dba-expert`, `cloud-expert`, `solution-architect`, `backend-dev`, `frontend-dev`, `migration-expert`.
- Requirements, planning, docs -> `business-analyst`, `project-manager`, `document-to-md`, `docs-drift`,
  `slide-craft`.
- "Keep going until X is true" -> skill `goal` (heavier: `deep-goal`). Research -> `deep-research`.
  Spec-driven development -> `speckit-*` skills. TDD -> `test-driven-development`.
- Standard pipelines -> `builtin-bug-fix`, `builtin-code-review`, `builtin-feature-dev`, `builtin-full-stack`,
  `builtin-db-migration`, `builtin-refactor-safe`, `builtin-00-rfp-to-demo`, `builtin-01-rfp-to-proposal`.
  The MCP prompts (`vibeflow_bug_fix`, `vibeflow_code_review`, ...) are ready-made starters for these.
- Project-specific custom agents also appear in `vibeflow_list_agents`.

## Running a workflow

1. Check `vibeflow_get_quota`; a workflow runs several agents in sequence.
2. `vibeflow_ask(project_id, workflow=<id>, timeout_seconds=900, prompt=<concrete request + acceptance criteria>)`.
3. On `timeout`, keep calling `vibeflow_wait_for_reply(run_id, timeout_seconds=900)`; results report each
   step's status. Batches: `vibeflow_get_workflow_batches(run_id)`.
4. Subagents: `vibeflow_list_subagents(run_id)`, read one with `vibeflow_get_messages(run_id, subagent=...)`,
   retry a failed one with `vibeflow_retry_subagent(run_id, subagent)`; resume a paused run with
   `vibeflow_resume_conversation(run_id)`.
5. Finish with `vibeflow-review-and-ship` to inspect and publish the changes.

## Goal loops (toolset advanced)

`vibeflow_goal_status(run_id)` shows progress; stop a runaway loop with `vibeflow_goal_stop(run_id)`.
