---
name: vibeflow-agent-chat
description: Delegate a coding or analysis task to the VibeFlow cloud agent and get its answer - one-shot questions, follow-ups, plan vs build mode, attachments, models, and answering the agent's permission requests and questions. Use whenever the user wants VibeFlow's agent to do or explain something in a project.
---

# Chat with the VibeFlow agent

## Ask (one call)

`vibeflow_ask(prompt, project_id, [run_id], [model], [agent], [skill], [workflow], [mode], [attachments], [timeout_seconds=600])`

- Starts the sandbox if needed, opens a conversation (or continues `run_id`), waits, and returns
  `{run_id, outcome, reply, ...}`. Keep `run_id` for follow-ups.
- `mode="plan"` = read-only analysis; `"build"` (default) = may edit files.
- `attachments` = local file paths, uploaded into the sandbox for the agent to read.
- Write prompts with goal, constraints and a definition of done ("run the tests and report results").

## Read the outcome

| outcome | meaning | do |
|---|---|---|
| `done` | turn finished | report `reply` |
| `needs_input` | agent waits for a permission or answer | see "Human in the loop" |
| `timeout` | still working | `vibeflow_wait_for_reply(run_id, timeout_seconds=600)` |
| `failed` / `aborted` | run ended badly | show the error; retry, maybe with another model |
| `ended_without_reply` | idle but no answer | `vibeflow_get_messages(run_id, last_n=5)`, then re-ask |

## Follow-ups

- Simplest: `vibeflow_ask(prompt, run_id=...)`.
- Fire-and-wait: `sent = vibeflow_send_message(run_id, prompt)`, then
  `vibeflow_wait_for_reply(run_id, min_messages=sent.min_messages)`. Always pass `min_messages`, otherwise
  the previous turn's answer can be returned as the new one.

## Human in the loop

When `outcome == "needs_input"`, `pending_prompts` lists what the agent waits for (also
`vibeflow_pending_prompts(run_id)`):

- **permission** (e.g. writing outside /workspace): show what and where to the user, then
  `vibeflow_reply_permission(run_id, request_id, reply)` with `once`, `always` or `reject`.
- **question**: show the questions and options, then
  `vibeflow_answer_question(run_id, request_id, answers=[["option label"], ...])` (one list per question).
- Then `vibeflow_wait_for_reply(run_id)` again. Never approve on the user's behalf unless they said so.

## Models

- `vibeflow_list_models(project_id)` -> pass `model` as `provider/id` (or a bare platform id).
- Default is a cheap platform model; choose a stronger model for hard tasks.

## Manage conversations

- Stop the current turn: `vibeflow_abort(run_id)`. Long context: `vibeflow_compact_conversation(run_id)`.
- Branch: `vibeflow_fork_conversation(run_id)`. Name it: `vibeflow_rename_conversation(run_id, title)`.
- History: `vibeflow_get_messages(run_id, last_n=20)`; find old runs: `vibeflow_list_conversations`.
- Files the agent produced: `vibeflow_list_artifacts(run_id)`.

## Example

User: "Ask VibeFlow why the login test fails in project Shop."
1. `vibeflow_list_projects(search="Shop")` -> project_id.
2. `vibeflow_ask(project_id=..., mode="plan", prompt="Run the test suite, find why the login test fails and explain the root cause. Do not change files.")`
3. Report `reply`; offer a build-mode fix as a follow-up with the same `run_id`.
