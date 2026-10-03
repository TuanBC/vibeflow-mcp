# vibeflow-mcp agent skills

Task-focused instructions that teach an AI agent to use the vibeflow MCP tools well. Each skill is a folder
with a `SKILL.md`: YAML frontmatter (`name`, `description`) followed by Markdown instructions - the
[Agent Skills](https://agentskills.io) format read by Claude Code, GitHub Copilot, Hermes Agent and others.
The `description` says *when* to use the skill, so an agent loads the body only when it is relevant.

| Skill | Use when |
|---|---|
| [vibeflow-basics](vibeflow-basics/SKILL.md) | any VibeFlow task: sign-in, project, sandbox, cost, confirm rule |
| [vibeflow-agent-chat](vibeflow-agent-chat/SKILL.md) | ask the cloud agent, follow-ups, permissions and questions |
| [vibeflow-specialists-and-workflows](vibeflow-specialists-and-workflows/SKILL.md) | pick a specialist agent, skill or built-in pipeline |
| [vibeflow-review-and-ship](vibeflow-review-and-ship/SKILL.md) | review diffs, commit, push / PR, restore points |
| [vibeflow-bug-fix](vibeflow-bug-fix/SKILL.md) | fix a reported bug end to end |
| [vibeflow-workspace-files](vibeflow-workspace-files/SKILL.md) | read / write / move files, export or seed the workspace |
| [vibeflow-preview-app](vibeflow-preview-app/SKILL.md) | run and share the app, fix preview errors |
| [vibeflow-canvas-workflows](vibeflow-canvas-workflows/SKILL.md) | custom multi-agent pipelines |
| [vibeflow-project-setup](vibeflow-project-setup/SKILL.md) | create / configure projects, members, budget, providers, Jira |
| [vibeflow-kanban-planning](vibeflow-kanban-planning/SKILL.md) | plan and track work on the board |
| [vibeflow-cost-and-analytics](vibeflow-cost-and-analytics/SKILL.md) | spend, quota, KPIs, reports |
| [vibeflow-troubleshooting](vibeflow-troubleshooting/SKILL.md) | error codes, stuck runs, missing tools |

## Install

Copy (or symlink) the `vibeflow-*` folders to where your agent framework looks for skills:

| Framework | Location |
|---|---|
| Claude Code | `~/.claude/skills/` (all projects) or `<project>/.claude/skills/` |
| GitHub Copilot (VS Code agent mode) | `<repo>/.github/skills/` (Copilot also reads `.claude/skills/`) |
| Hermes Agent | `~/.hermes/skills/` |
| Other frameworks | any skills folder that reads `SKILL.md` with `name` / `description` frontmatter |

```bash
cp -r skills/vibeflow-* ~/.claude/skills/
```

The skills assume the vibeflow MCP server is connected (see the main [README](../README.md)). A tool named
in a skill exists only if its toolset is enabled in `VIBEFLOW_TOOLSETS`.

## Conventions

- Folder name equals the frontmatter `name`: lowercase kebab-case, prefixed `vibeflow-`.
- `description`: what the skill does, then "Use when ..." - this is what the agent matches on.
- Body: exact tool names and parameters in order, decision tables where useful, and guardrails
  (never pass `confirm=true` without the user's approval).
- Shared rules live in `vibeflow-basics`; other skills reference skills by name instead of repeating them.
- Keep each `SKILL.md` short (well under 500 lines) so it is cheap to load.
