"""Project-management toolset ("pm"): projects, members, budget, kanban,
tasks + attachments, templates, canvas workflows, git credentials, project
LLM providers, Jira / SharePoint integrations, user settings.

Request bodies were confirmed against the API's own validation (422 field
lists) and the SPA bundle; see endpoints.lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from ..app import client, require_confirm, tool
from ..errors import VibeFlowError

Role = Literal["pm", "tl", "member"]
Priority = Literal["low", "medium", "high", "urgent"]


def _clean(**fields: Any) -> dict[str, Any]:
    """Only send fields the caller set (the API treats missing as unchanged)."""
    return {k: v for k, v in fields.items() if v is not None}


def _require(body: dict[str, Any], what: str) -> dict[str, Any]:
    if not body:
        raise VibeFlowError(f"Nothing to update for {what}.", code="bad_request", hint="Pass at least one field.")
    return body


# ------------------------------------------------------------------ projects

@tool("pm")
async def vibeflow_create_project(name: str, description: str | None = None,
                                  project_type: Literal["local", "git"] = "local",
                                  git_url: str | None = None, git_provider: str | None = None,
                                  default_branch: str | None = None) -> Any:
    """Create a project. 'local' = sandbox workspace only; 'git' = backed by
    git_url (store a token first with vibeflow_add_git_credential)."""
    if project_type == "git" and not git_url:
        raise VibeFlowError("git projects need git_url.", code="bad_request")
    return await client.post("/api/v1/projects", _clean(name=name, description=description, project_type=project_type,
                                                         git_url=git_url, git_provider=git_provider,
                                                         default_branch=default_branch))


@tool("pm", idempotent=True)
async def vibeflow_update_project(project_id: str, name: str | None = None, description: str | None = None,
                                  git_url: str | None = None, default_branch: str | None = None,
                                  settings: dict[str, Any] | None = None) -> Any:
    """Update project fields. settings follows vibeflow_get_project's shape
    (git / agents / notifications / llm sections)."""
    body = _require(_clean(name=name, description=description, git_url=git_url,
                           default_branch=default_branch, settings=settings), "project")
    return await client.put(f"/api/v1/projects/{project_id}", body)


@tool("pm", destructive=True)
async def vibeflow_delete_project(project_id: str, confirm: bool = False) -> Any:
    """Delete a project with its tasks and conversations. Requires confirm=true."""
    require_confirm(confirm, "delete project")
    return await client.delete(f"/api/v1/projects/{project_id}")


@tool("pm", idempotent=True)
async def vibeflow_pin_project(project_id: str, pinned: bool = True) -> Any:
    """Pin or unpin a project in your project list."""
    return await client.patch(f"/api/v1/projects/{project_id}/pin", pinned=str(pinned).lower())


@tool("pm")
async def vibeflow_generate_prompt(project_id: str, kind: Literal["task_description", "agent_prompt", "workflow_instruction"],
                                   idea: str, name: str = "", task_title: str = "", task_description: str = "",
                                   agent_type: str = "") -> Any:
    """AI writing helper (the SPA's 'Generate Prompt'): expands a rough idea into
    - task_description: a kanban task description (name = task name)
    - agent_prompt: a custom agent's system prompt (name = agent name)
    - workflow_instruction: a Canvas node's instructions (name = node label,
      agent_type, task_title, task_description give context)."""
    if kind == "task_description":
        context = {"type": kind, "task_name": name, "project_name": (await client.get(f"/api/v1/projects/{project_id}")).get("name"),
                   "existing_description": idea}
    elif kind == "agent_prompt":
        context = {"type": kind, "agent_name": name, "agent_description": idea}
    else:
        context = {"type": kind, "agent_type": agent_type, "node_label": name or agent_type, "task_title": task_title,
                   "task_description": task_description, "existing_text": idea}
    return await client.post(f"/api/v1/projects/{project_id}/generate-prompt", {"context": context})


# ---------------------------------------------------------- members & roles

@tool("pm", read_only=True)
async def vibeflow_list_members(project_id: str) -> Any:
    """Project members with their roles (pm / tl / member)."""
    data = await client.get(f"/api/v1/projects/{project_id}/members")
    return [{"user_id": m.get("user_id"), "email": m.get("user_email"), "name": m.get("user_display_name"),
             "role": m.get("role")} for m in data.get("members", [])]


@tool("pm", read_only=True)
async def vibeflow_search_users(query: str) -> Any:
    """Find VibeFlow users by name or email (to add as members / assignees)."""
    return (await client.get("/api/v1/users/search", q=query)).get("users", [])


@tool("pm", read_only=True)
async def vibeflow_list_roles(scope: Literal["project", "system"] | None = None) -> Any:
    """Roles and their permissions."""
    roles = await client.get("/api/v1/roles", **({"scope": scope} if scope else {}))
    return [{"name": r.get("name"), "scope": r.get("scope"), "permissions": r.get("permissions"),
             "description": r.get("description")} for r in roles]


@tool("pm")
async def vibeflow_add_member(project_id: str, user_id: str, role: Role = "member") -> Any:
    """Add a user to a project (user_id from vibeflow_search_users)."""
    return await client.post(f"/api/v1/projects/{project_id}/members", {"user_id": user_id, "role": role})


@tool("pm", idempotent=True)
async def vibeflow_update_member_role(project_id: str, user_id: str, role: Role) -> Any:
    """Change a member's project role: pm (project manager), tl (tech lead) or member."""
    return await client.put(f"/api/v1/projects/{project_id}/members/{user_id}", {"role": role})


@tool("pm", destructive=True)
async def vibeflow_remove_member(project_id: str, user_id: str, confirm: bool = False) -> Any:
    """Remove a member from a project. Requires confirm=true."""
    require_confirm(confirm, "remove project member")
    return await client.delete(f"/api/v1/projects/{project_id}/members/{user_id}")


# -------------------------------------------------------------------- budget

@tool("pm", read_only=True)
async def vibeflow_get_budget(project_id: str) -> Any:
    """Project monthly LLM budget: limit, current spend, remaining."""
    return await client.get(f"/api/v1/projects/{project_id}/budget")


@tool("pm", idempotent=True)
async def vibeflow_set_budget(project_id: str, enabled: bool, monthly_limit_usd: float | None = None) -> Any:
    """Enable (with a monthly USD limit) or disable the project budget."""
    if enabled and monthly_limit_usd is None:
        raise VibeFlowError("monthly_limit_usd is required when enabling the budget.", code="bad_request")
    return await client.put(f"/api/v1/projects/{project_id}/budget",
                            {"enabled": enabled, "monthly_limit": monthly_limit_usd if enabled else None})


# -------------------------------------------------------------------- kanban

async def _column_id(project_id: str, column: str) -> str:
    """Accept a column id or a (case-insensitive) column name such as 'Backlog'."""
    board = await client.get("/api/v1/kanban/boards", project_id=project_id)
    for c in board.get("columns", []):
        if column == c.get("id") or column.lower() == (c.get("name") or "").lower():
            return c["id"]
    names = [c.get("name") for c in board.get("columns", [])]
    raise VibeFlowError(f"Unknown column '{column}'.", code="bad_request", hint=f"Columns: {names}")


@tool("pm")
async def vibeflow_create_kanban_task(project_id: str, name: str, description: str | None = None,
                                      column: str | None = None, priority: Priority | None = None,
                                      story_points: float | None = None, estimate_hours: float | None = None,
                                      assignee_id: str | None = None) -> Any:
    """Create a kanban card (a task with its own workbench). column: name or
    id (default: the board's first column)."""
    body = _clean(project_id=project_id, name=name, description=description, priority=priority,
                  story_points=story_points, estimate_hours=estimate_hours, assignee_id=assignee_id)
    if column:
        body["column_id"] = await _column_id(project_id, column)
    return await client.post("/api/v1/kanban/tasks", body)


@tool("pm", idempotent=True)
async def vibeflow_update_kanban_task(task_id: str, name: str | None = None, description: str | None = None,
                                      priority: Priority | None = None, story_points: float | None = None,
                                      estimate_hours: float | None = None,
                                      remaining_hours: float | None = None) -> Any:
    """Edit a kanban card's fields."""
    body = _require(_clean(name=name, description=description, priority=priority, story_points=story_points,
                           estimate_hours=estimate_hours, remaining_hours=remaining_hours), "kanban task")
    return await client.put(f"/api/v1/kanban/tasks/{task_id}", body)


@tool("pm", idempotent=True)
async def vibeflow_move_kanban_task(project_id: str, task_id: str, column: str, position: int = 0) -> Any:
    """Move a card to another column (name or id) at a position (0 = top).
    May also update the linked Jira issue status."""
    return await client.put(f"/api/v1/kanban/tasks/{task_id}/move",
                            {"column_id": await _column_id(project_id, column), "position": position})


@tool("pm", idempotent=True)
async def vibeflow_assign_kanban_task(task_id: str, assignee_id: str | None = None) -> Any:
    """Assign a card to a user (None = unassign)."""
    return await client.put(f"/api/v1/kanban/tasks/{task_id}/assign", {"assignee_id": assignee_id})


@tool("pm", idempotent=True)
async def vibeflow_archive_kanban_task(task_id: str, archived: bool = True) -> Any:
    """Archive (hide) or restore a card."""
    return await client.patch(f"/api/v1/kanban/tasks/{task_id}/{'archive' if archived else 'unarchive'}")


@tool("pm", read_only=True)
async def vibeflow_list_archived_tasks(project_id: str) -> Any:
    """Archived cards of a project."""
    return (await client.get(f"/api/v1/projects/{project_id}/tasks/archived")).get("tasks", [])


@tool("pm", destructive=True)
async def vibeflow_delete_kanban_task(task_id: str, confirm: bool = False) -> Any:
    """Delete a card permanently. Prefer archiving. Requires confirm=true."""
    require_confirm(confirm, "delete kanban task")
    return await client.delete(f"/api/v1/kanban/tasks/{task_id}")


# --------------------------------------------------------- tasks & attachments

@tool("pm")
async def vibeflow_create_task(name: str, project_id: str | None = None, description: str | None = None) -> Any:
    """Create a workbench task (conversation + workflow container)."""
    return await client.post("/api/v1/tasks", _clean(name=name, project_id=project_id, description=description))


@tool("pm", idempotent=True)
async def vibeflow_update_task(task_id: str, name: str | None = None, description: str | None = None,
                               status: str | None = None, branch_name: str | None = None) -> Any:
    """Update a task's name, description, status or branch."""
    body = _require(_clean(name=name, description=description, status=status, branch_name=branch_name), "task")
    return await client.put(f"/api/v1/tasks/{task_id}", body)


@tool("pm", destructive=True)
async def vibeflow_delete_task(task_id: str, confirm: bool = False) -> Any:
    """Delete a task and its conversations. Requires confirm=true."""
    require_confirm(confirm, "delete task")
    return await client.delete(f"/api/v1/tasks/{task_id}")


@tool("pm", read_only=True)
async def vibeflow_list_attachments(task_id: str) -> Any:
    """Files attached to a task (specs, RFPs, ...)."""
    return await client.get(f"/api/v1/tasks/{task_id}/attachments")


@tool("pm")
async def vibeflow_add_attachment(task_id: str, local_path: str) -> Any:
    """Attach a local file (max 50 MB) to a task."""
    src = Path(local_path).expanduser()
    if not src.is_file():
        raise VibeFlowError(f"Local file not found: {local_path}", code="bad_request")
    if src.stat().st_size > 50 * 1024 * 1024:
        raise VibeFlowError("Attachments are limited to 50 MB.", code="bad_request")
    return await client.upload(f"/api/v1/tasks/{task_id}/attachments", [(src.name, src.read_bytes())])


@tool("pm")
async def vibeflow_download_attachment(task_id: str, attachment_id: str, local_path: str) -> Any:
    """Download a task attachment to a local path."""
    data = await client.get_bytes(f"/api/v1/tasks/{task_id}/attachments/{attachment_id}/download")
    dest = Path(local_path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"saved": str(dest), "bytes": len(data)}


@tool("pm", destructive=True)
async def vibeflow_delete_attachment(task_id: str, attachment_id: str, confirm: bool = False) -> Any:
    """Delete a task attachment. Requires confirm=true."""
    require_confirm(confirm, "delete attachment")
    return await client.delete(f"/api/v1/tasks/{task_id}/attachments/{attachment_id}")


# ----------------------------------------------------------------- templates

@tool("pm", read_only=True)
async def vibeflow_list_prompt_templates(project_id: str | None = None) -> Any:
    """Prompt templates (built-in + project) with categories and variables."""
    path = f"/api/v1/projects/{project_id}/templates/prompts" if project_id else "/api/v1/templates/prompts"
    data = await client.get(path)
    return {"categories": [c.get("id") for c in data.get("categories", [])],
            "templates": [{"id": t.get("id"), "name": t.get("name"), "category": t.get("category"),
                           "agent": t.get("agent"), "variables": t.get("variables"), "builtin": t.get("isBuiltIn"),
                           "description": t.get("description")} for t in data.get("templates", [])]}


def _variables(variables: list[Any] | None) -> list[dict[str, Any]] | None:
    """Template variables are objects {name, type: text|file|select, required,
    description, options, default}; bare names become required text inputs."""
    if variables is None:
        return None
    return [v if isinstance(v, dict) else {"name": str(v), "type": "text", "required": True} for v in variables]


@tool("pm")
async def vibeflow_create_prompt_template(project_id: str, template_id: str, name: str, prompt: str,
                                          category: str | None = None, description: str | None = None,
                                          agent: str | None = None,
                                          variables: list[str | dict[str, Any]] | None = None) -> Any:
    """Save a reusable prompt template in a project. Use {{name}} placeholders in
    prompt; variables: names, or objects {name, type: text|file|select,
    required, description, options, default}."""
    return await client.post(f"/api/v1/projects/{project_id}/templates/prompts", _clean(
        id=template_id, name=name, prompt=prompt, category=category, description=description,
        agent=agent, variables=_variables(variables)))


@tool("pm", destructive=True)
async def vibeflow_delete_prompt_template(project_id: str, template_id: str, confirm: bool = False) -> Any:
    """Delete a project prompt template. Requires confirm=true."""
    require_confirm(confirm, "delete prompt template")
    return await client.delete(f"/api/v1/projects/{project_id}/templates/prompts/{template_id}")


@tool("pm", read_only=True)
async def vibeflow_get_agent_template(project_id: str, name: str) -> Any:
    """Full definition of an agent from vibeflow_list_agents: systemPrompt (built-in
    agents) or userPrompt (custom agents), tools, look."""
    agents = (await client.get(f"/api/v1/projects/{project_id}/templates/agents")).get("agents", [])
    for a in agents:
        if a.get("name") == name:
            return a
    raise VibeFlowError(f"Agent '{name}' not found.", code="not_found")


@tool("pm")
async def vibeflow_create_agent_template(project_id: str, name: str, prompt: str,
                                         description: str | None = None, icon: str | None = None,
                                         color: str | None = None, tools: list[str] | None = None) -> Any:
    """Define a custom specialist agent for a project (usable via the agent
    picker). prompt = the agent's instructions (the SPA's agent prompt field)."""
    return await client.post(f"/api/v1/projects/{project_id}/templates/agents", _clean(
        name=name, userPrompt=prompt, description=description, icon=icon, color=color, tools=tools))


@tool("pm", idempotent=True)
async def vibeflow_update_agent_template(project_id: str, agent_id: str, name: str | None = None,
                                         prompt: str | None = None, description: str | None = None,
                                         icon: str | None = None, color: str | None = None,
                                         tools: list[str] | None = None) -> Any:
    """Update a project-defined agent (built-in agents cannot be edited)."""
    body = _require(_clean(name=name, userPrompt=prompt, description=description, icon=icon,
                           color=color, tools=tools), "agent")
    return await client.put(f"/api/v1/projects/{project_id}/templates/agents/{agent_id}", body)


@tool("pm", destructive=True)
async def vibeflow_delete_agent_template(project_id: str, agent_id: str, confirm: bool = False) -> Any:
    """Delete a project-defined agent. Requires confirm=true."""
    require_confirm(confirm, "delete agent template")
    return await client.delete(f"/api/v1/projects/{project_id}/templates/agents/{agent_id}")


@tool("pm", read_only=True)
async def vibeflow_get_workflow_template(project_id: str, template_id: str) -> Any:
    """Full workflow template (nodes with agent, instructions, edges)."""
    return await client.get(f"/api/v1/projects/{project_id}/templates/workflows/{template_id}")


@tool("pm")
async def vibeflow_create_workflow_template(project_id: str, name: str, workflow_json: dict[str, Any],
                                            icon: str = "Workflow", color: str = "#3B82F6",
                                            description: str | None = None) -> Any:
    """Save a multi-step workflow template. workflow_json: {nodes:[{id,
    agentType, label, instructions, ...}], edges:[{source, target}]} - copy
    the shape from vibeflow_get_workflow_template."""
    return await client.post(f"/api/v1/projects/{project_id}/templates/workflows", _clean(
        name=name, icon=icon, color=color, workflow_json=workflow_json, description=description))


@tool("pm", idempotent=True)
async def vibeflow_update_workflow_template(project_id: str, template_id: str, name: str | None = None,
                                            workflow_json: dict[str, Any] | None = None,
                                            icon: str | None = None, color: str | None = None,
                                            description: str | None = None) -> Any:
    """Update a project workflow template."""
    body = _require(_clean(name=name, workflow_json=workflow_json, icon=icon, color=color,
                           description=description), "workflow template")
    return await client.put(f"/api/v1/projects/{project_id}/templates/workflows/{template_id}", body)


@tool("pm", destructive=True)
async def vibeflow_delete_workflow_template(project_id: str, template_id: str, confirm: bool = False) -> Any:
    """Delete a project workflow template. Requires confirm=true."""
    require_confirm(confirm, "delete workflow template")
    return await client.delete(f"/api/v1/projects/{project_id}/templates/workflows/{template_id}")


@tool("pm", read_only=True)
async def vibeflow_export_workflow_template(project_id: str, template_id: str) -> Any:
    """Portable JSON export of a workflow template (for vibeflow_import_workflow_template)."""
    return await client.get(f"/api/v1/projects/{project_id}/templates/workflows/{template_id}/export")


@tool("pm")
async def vibeflow_import_workflow_template(project_id: str, name: str, workflow: dict[str, Any],
                                            icon: str = "Workflow", color: str = "#3B82F6") -> Any:
    """Import an exported workflow into a project as a new template."""
    return await client.post(f"/api/v1/projects/{project_id}/templates/workflows/import",
                             {"name": name, "icon": icon, "color": color, "workflow": workflow})


# ----------------------------------------------------------- canvas workflows

@tool("pm", read_only=True)
async def vibeflow_get_workflow(task_id: str) -> Any:
    """A task's Canvas workflow graph {nodes, edges}."""
    return (await client.get(f"/api/v1/workflows/{task_id}")).get("workflow")


@tool("pm", idempotent=True)
async def vibeflow_save_workflow(task_id: str, workflow: dict[str, Any]) -> Any:
    """Replace a task's Canvas workflow graph ({nodes, edges}, same shape as vibeflow_get_workflow)."""
    if not isinstance(workflow.get("nodes"), list):
        raise VibeFlowError("workflow must contain a 'nodes' list.", code="bad_request")
    return await client.put(f"/api/v1/workflows/{task_id}", {"workflow": workflow})


@tool("pm")
async def vibeflow_run_workflow(task_id: str, start_from_node_id: str | None = None) -> Any:
    """Run a task's Canvas workflow end to end (or from a node). Needs the
    sandbox running; uses LLM tokens. Follow with vibeflow_wait_for_reply."""
    return await client.post("/api/v1/runs", _clean(task_id=task_id, start_from_node_id=start_from_node_id))


@tool("pm")
async def vibeflow_run_workflow_step(task_id: str, node_id: str) -> Any:
    """Run a single Canvas node. Needs the sandbox running; uses LLM tokens."""
    return await client.post("/api/v1/runs/step", {"task_id": task_id, "node_id": node_id})


# ------------------------------------------------------------ git credentials

@tool("pm", read_only=True)
async def vibeflow_list_git_credentials() -> Any:
    """Stored git credentials (tokens are never returned)."""
    return (await client.get("/api/v1/git-credentials")).get("credentials", [])


@tool("pm")
async def vibeflow_add_git_credential(git_provider: Literal["github", "gitlab", "bitbucket", "azure_devops"],
                                      git_token: str, git_host: str | None = None, label: str | None = None) -> Any:
    """Store a git access token (used to clone/push git projects). git_host
    for self-hosted servers. The token is sent to VibeFlow only."""
    cred = await client.post("/api/v1/git-credentials", _clean(git_provider=git_provider, git_token=git_token,
                                                               git_host=git_host, label=label))
    cred.pop("git_token", None)
    return cred


@tool("pm", destructive=True)
async def vibeflow_delete_git_credential(credential_id: str, confirm: bool = False) -> Any:
    """Delete a stored git credential. Requires confirm=true."""
    require_confirm(confirm, "delete git credential")
    return await client.delete(f"/api/v1/git-credentials/{credential_id}")


# ------------------------------------------------------- project LLM providers

@tool("pm", read_only=True)
async def vibeflow_list_llm_providers(project_id: str | None = None) -> Any:
    """LLM providers configured for a project (or your personal ones)."""
    if project_id:
        return await client.get(f"/api/v1/projects/{project_id}/llm-providers")
    return (await client.get("/api/v1/users/me/llm-providers")).get("providers", [])


@tool("pm")
async def vibeflow_add_llm_provider(project_id: str, provider: str, credentials: dict[str, Any],
                                    name: str | None = None) -> Any:
    """Add a project LLM provider (e.g. provider='openai', credentials={'api_key': ...}).
    Conversations can then use its models with provider_scope='project'."""
    return await client.post(f"/api/v1/projects/{project_id}/llm-providers",
                             _clean(provider=provider, credentials=credentials, name=name))


@tool("pm")
async def vibeflow_verify_llm_provider(project_id: str, provider_id: str,
                                       credentials: dict[str, Any] | None = None) -> Any:
    """Check a provider's credentials and list the models it exposes."""
    return await client.post(f"/api/v1/projects/{project_id}/llm-providers/{provider_id}/verify",
                             {"credentials": credentials})


@tool("pm", idempotent=True)
async def vibeflow_update_llm_provider(project_id: str, provider_id: str, fields: dict[str, Any]) -> Any:
    """Update a project LLM provider (e.g. {'credentials': {...}} or {'enabled': false})."""
    return await client.patch(f"/api/v1/projects/{project_id}/llm-providers/{provider_id}", _require(fields, "provider"))


@tool("pm", destructive=True)
async def vibeflow_delete_llm_provider(project_id: str, provider_id: str, confirm: bool = False) -> Any:
    """Remove a project LLM provider. Requires confirm=true."""
    require_confirm(confirm, "delete LLM provider")
    return await client.delete(f"/api/v1/projects/{project_id}/llm-providers/{provider_id}")


# --------------------------------------------------------------------- Jira

@tool("pm", read_only=True)
async def vibeflow_list_jira_sites() -> Any:
    """Jira servers VibeFlow can sync with."""
    return await client.get("/api/v1/jira/sites")


@tool("pm")
async def vibeflow_list_jira_projects(pat: str, email: str | None = None, site_id: str | None = None) -> Any:
    """Jira projects visible with a personal access token (pat)."""
    return await client.post("/api/v1/jira/projects", _clean(pat=pat, email=email, site_id=site_id))


@tool("pm")
async def vibeflow_list_jira_statuses(jira_project_key: str, pat: str, email: str | None = None,
                                      site_id: str | None = None) -> Any:
    """Workflow statuses of a Jira project (to map kanban columns in
    vibeflow_configure_jira_sync)."""
    return await client.post(f"/api/v1/jira/projects/{jira_project_key}/statuses",
                             _clean(pat=pat, email=email, site_id=site_id))


@tool("pm", read_only=True)
async def vibeflow_get_jira_sync(project_id: str) -> Any:
    """The project's Jira sync configuration (not_found when not configured)."""
    return await client.get(f"/api/v1/projects/{project_id}/jira-sync")


@tool("pm")
async def vibeflow_configure_jira_sync(project_id: str, pat: str, jira_project_key: str,
                                       email: str | None = None, site_id: str | None = None,
                                       extra: dict[str, Any] | None = None) -> Any:
    """Create or update the project's Jira sync (kanban <-> Jira issues).
    extra: additional options such as status mappings."""
    body = {**_clean(pat=pat, jira_project_key=jira_project_key, email=email, site_id=site_id), **(extra or {})}
    try:
        await client.get(f"/api/v1/projects/{project_id}/jira-sync")
        return await client.put(f"/api/v1/projects/{project_id}/jira-sync", body)
    except VibeFlowError as exc:
        if exc.code != "not_found":
            raise
        return await client.post(f"/api/v1/projects/{project_id}/jira-sync", body)


@tool("pm")
async def vibeflow_test_jira_connection(project_id: str, pat: str, email: str | None = None,
                                        site_id: str | None = None) -> Any:
    """Test Jira credentials for this project."""
    return await client.post(f"/api/v1/projects/{project_id}/jira-sync/test-connection",
                             _clean(pat=pat, email=email, site_id=site_id))


@tool("pm")
async def vibeflow_trigger_jira_sync(project_id: str) -> Any:
    """Run a Jira sync now."""
    return await client.post(f"/api/v1/projects/{project_id}/jira-sync/trigger")


@tool("pm", destructive=True)
async def vibeflow_delete_jira_sync(project_id: str, confirm: bool = False) -> Any:
    """Remove the project's Jira sync. Requires confirm=true."""
    require_confirm(confirm, "delete Jira sync")
    return await client.delete(f"/api/v1/projects/{project_id}/jira-sync")


# ----------------------------------------------------------------- SharePoint

@tool("pm", read_only=True)
async def vibeflow_get_sharepoint(project_id: str | None = None) -> Any:
    """Your SharePoint connection, and the project's bound folder if project_id is given."""
    out: dict[str, Any] = {"integration": await client.get("/api/v1/users/me/integrations/sharepoint")}
    if project_id:
        try:
            out["project_source"] = await client.get(f"/api/v1/projects/{project_id}/sharepoint-source")
        except VibeFlowError as exc:
            if exc.code != "not_found":
                raise
            out["project_source"] = None
    return out


@tool("pm", idempotent=True)
async def vibeflow_set_sharepoint_source(project_id: str, drive_id: str, folder: str = "",
                                         drive_name: str | None = None, item_id: str | None = None) -> Any:
    """Bind a SharePoint drive folder as the project's document source."""
    return await client.put(f"/api/v1/projects/{project_id}/sharepoint-source",
                            {"drive_id": drive_id, "drive_name": drive_name, "folder": folder, "item_id": item_id})


# -------------------------------------------------------------- user settings

@tool("pm", read_only=True)
async def vibeflow_get_settings() -> Any:
    """Your user settings (default model, UI language, git provider, ...)."""
    return await client.get("/api/v1/users/me/settings")


@tool("pm", idempotent=True)
async def vibeflow_update_settings(default_model: str | None = None, ui_language: str | None = None,
                                   git_provider: str | None = None, git_host: str | None = None) -> Any:
    """Update your user settings."""
    body = _require(_clean(default_model=default_model, ui_language=ui_language, git_provider=git_provider,
                           git_host=git_host), "settings")
    return await client.put("/api/v1/users/me/settings", body)


@tool("pm", read_only=True)
async def vibeflow_get_onboarding() -> Any:
    """Onboarding checklist progress."""
    return await client.get("/api/v1/users/me/onboarding")


@tool("pm")
async def vibeflow_accept_terms() -> Any:
    """Accept the platform terms of use (needed once for new accounts). Ask the user first."""
    return await client.post("/api/v1/auth/accept-terms")
