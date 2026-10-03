---
name: vibeflow-project-setup
description: Create and configure a VibeFlow project - local or git-backed project, git credentials, members and roles, monthly budget, project LLM providers, Jira sync, custom agents and prompt templates. Use when the user wants to set up or administer a project (toolset pm).
---

# Project setup (toolset pm)

## Create

- Git project: `vibeflow_add_git_credential(git_provider, git_token)` (once per user), then
  `vibeflow_create_project(name, project_type="git", git_url=..., git_provider=..., default_branch=...)`.
- Local project: `vibeflow_create_project(name, description)`, then seed code on the *empty* project
  with `vibeflow_upload_workspace` (see `vibeflow-workspace-files`).
- `vibeflow_start_session(project_id)` - git projects are cloned on first start.

## People and money

- Members: `vibeflow_search_users(query)` -> `vibeflow_add_member(project_id, user_id, role)` with role
  `pm`, `tl` or `member`; change with `vibeflow_update_member_role`; `vibeflow_remove_member` needs confirm.
  Only add or remove people the user explicitly named.
- Budget: `vibeflow_set_budget(project_id, enabled=true, monthly_limit_usd=50)`; read with `vibeflow_get_budget`.

## Models (own API keys)

`vibeflow_add_llm_provider(project_id, provider="openai", credentials={"api_key": ...})` ->
`vibeflow_verify_llm_provider(project_id, provider_id)` and check `valid`. The project's models then appear
in `vibeflow_list_models(project_id)`.

## Jira

`vibeflow_list_jira_sites` -> `vibeflow_test_jira_connection(project_id, pat, site_id=...)` ->
`vibeflow_list_jira_projects(pat)` / `vibeflow_list_jira_statuses(jira_project_key, pat)` ->
`vibeflow_configure_jira_sync(project_id, pat, jira_project_key, extra={...})` -> `vibeflow_trigger_jira_sync(project_id)`.
A rejected PAT returns `credential_rejected`, not a sign-in problem.

## Customise

- Custom agent: `vibeflow_create_agent_template(project_id, name, prompt, description)` - draft the prompt
  with `vibeflow_generate_prompt(project_id, kind="agent_prompt", idea=..., name=...)`.
- Prompt template: `vibeflow_create_prompt_template(project_id, template_id, name, prompt="Review {{file}}", variables=["file"])`.

## Guardrails

- `vibeflow_delete_project` needs confirm; it archives the project (hidden, data kept).
- Ask the user for tokens and keys; never invent them or repeat them back.
