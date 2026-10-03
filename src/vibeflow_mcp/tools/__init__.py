"""Tool modules. Importing a module registers its tools (subject to VIBEFLOW_TOOLSETS).

Toolsets:
  core      - auth, account, projects/tasks/kanban (read), conversations, sandbox, models, raw API
  code      - files, git changes/push, restore points, preview
  pm        - project management: projects, members, budget, kanban, tasks, templates, canvas,
              git credentials, LLM providers, Jira / SharePoint, settings
  analytics - project cost, KPIs, code activity, report export
  admin     - system administration (needs a system admin role)
  advanced  - code intelligence (LSP), code graph, agent goal / cron / memory, sandbox MCP servers, background jobs
  (MCP resources and workflow prompts are always registered)
"""

from . import admin, advanced, chat, code, core, insights, pm, sandbox  # noqa: F401
