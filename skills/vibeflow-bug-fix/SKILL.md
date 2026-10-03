---
name: vibeflow-bug-fix
description: Fix a reported bug end to end with VibeFlow - reproduce, fix the root cause with a regression test, verify, review the diff and ship. Use when the user reports a bug, failing test or error in a VibeFlow project and wants it fixed.
---

# Bug fix with VibeFlow

1. Gather the symptom, steps to reproduce, logs and expected behaviour. Pass log files as `attachments`.
2. Choose depth:
   - Small, clear bug -> `vibeflow_ask(project_id, agent="backend-dev" or "frontend-dev", prompt=...)`.
   - Unclear or risky -> `vibeflow_ask(project_id, workflow="builtin-bug-fix", timeout_seconds=900, prompt=...)`
     (analyse -> fix -> test and review).
3. Prompt template:
   ```
   Bug: <symptom>. Reproduce: <steps>. Expected: <behaviour>.
   First write a failing regression test, then fix the root cause (not the symptom), then run the
   full test suite and report the results. Do not change unrelated code.
   ```
4. Handle `needs_input` and `timeout` as in `vibeflow-agent-chat`.
5. Verify: `vibeflow_get_changes` + `vibeflow_get_diff` on the fix and the new test; for UI bugs reproduce
   in a preview (`vibeflow-preview-app`).
6. Ship with `vibeflow-review-and-ship` (commit message, push to a `fix/...` branch with confirm).

If the fix is wrong: roll back with restore points (`vibeflow_revert_to`, confirm) or ask for another
approach in the same conversation (`vibeflow_ask(prompt, run_id=...)`).
