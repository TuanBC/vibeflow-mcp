# VibeFlow MCP — Feature Review & Implementation Plan

_Prepared 2026-10-02, after the POC was verified against production._

## 1. What VibeFlow is (from the API's point of view)

VibeFlow ("Frictionless Software Development", FPT Consulting Japan) is an AI software-development platform.
Each user/project gets a **Kubernetes sandbox** running an **OpenCode-based agent harness**. Users chat with
agents in a "Console", invoke specialist agents/skills/workflows, review diffs, and push to Git, with
cost tracking, kanban and admin governance on top.

```
Project ──┬── Members / roles / budget / LLM providers / Jira / SharePoint / templates
          ├── Kanban board ── Task ──┬── Conversations ("runs") ── messages / parts / tool calls
          │                          ├── Workflow graph (Canvas nodes → runs/step)
          │                          └── Attachments
          └── Sandbox session (pod) ── files, git changes, preview server, restore points,
                                        live events (SSE), goal / cron / memory, LSP
```

### Architecture facts discovered

| Item | Value |
|---|---|
| Web SPA | `https://vibeflow.fptconsulting.co.jp` (React + Vite, app chunks gated until login) |
| REST API | `https://api.vibeflow.fptconsulting.co.jp/api/v1/*` (FastAPI; no public OpenAPI) |
| Sandbox proxy | `https://api…/sessions/{session_id}/vibeflow/*` (OpenCode server proxied per session) |
| Live updates | SSE `GET /sessions/{sid}/vibeflow/events` (`Last-Event-Id` resume); poll `GET /runs/poll-cursor` |
| Auth | Entra ID MSAL redirect → `POST /auth/azure/token` → VibeFlow JWT (8 h, claims sub/email/role) + rotating refresh token (`POST /auth/azure/refresh`) |
| WAF | Azure App Gateway rejects non-browser User-Agents (403) |
| Preview | `*.preview.vibeflow.fptconsulting.co.jp`, token via `POST /preview/exchange-token` |
| Cost baseline | ~39k input tokens per first turn (agent system prompt) ≈ $0.03 on Gemini Flash |

**API surface:** ~234 distinct `/api/v1` paths (168 method+path pairs resolved), plus ~28 sandbox-proxy paths.

## 2. Feature inventory → API map

Legend: ✅ in POC · ◻ planned · 🔒 admin-only

### 2.1 Auth & account
| Feature | Endpoints | Status |
|---|---|---|
| SSO login / token capture | `/auth/azure/config`, `/auth/azure/token` (via browser) | ✅ |
| Refresh / logout / me | `/auth/azure/refresh`, `/auth/logout`, `/auth/me` | ✅ |
| Accept terms | `POST /auth/accept-terms` | ◻ |
| Impersonate role 🔒 | `PUT/DELETE /auth/impersonate` | ◻ |
| User settings / onboarding / stats | `/users/me/settings`, `/users/me/onboarding`, `/users/me/stats` | ◻ (stats via raw ✅) |
| Personal LLM providers (incl. OpenAI OAuth) | `/users/me/llm-providers`, `…/openai/callback` | ◻ |
| Platform models & quota | `/users/me/platform-models`, `/users/me/platform-quota` | ✅ |
| SharePoint integration | `/users/me/integrations/sharepoint` | ◻ |
| User search / avatar | `/users/search`, `/users/{id}/avatar` | ◻ |

### 2.2 Projects
| Feature | Endpoints | Status |
|---|---|---|
| List / get | `GET /projects`, `GET /projects/{id}` | ✅ |
| Create / update / delete / pin | `POST /projects`, `PUT/DELETE /projects/{id}`, `PATCH /projects/{id}/pin` | ◻ |
| Members & roles | `/projects/{id}/members[/{uid}]`, `/roles` | ◻ |
| Budget | `GET/PUT /projects/{id}/budget` | ◻ |
| Project LLM providers | `/projects/{id}/llm-providers[/{pid}[/verify]]` | ◻ |
| Jira sync | `/jira/sites`, `/jira/projects[/{k}/statuses]`, `/projects/{id}/jira-sync[/test-connection,/trigger]` | ◻ |
| SharePoint source | `/projects/{id}/sharepoint-source` | ◻ |
| Generate prompt (AI helper) | `POST /projects/{id}/generate-prompt` | ◻ |
| Templates: agents / prompts / workflows (+import/export) | `/projects/{id}/templates/{agents,prompts,workflows}…`, `/templates/{agents,prompts}` | ◻ |
| Git credentials | `/git-credentials[/{id}]`, `/git-proxy` | ◻ |

### 2.3 Tasks & Kanban
| Feature | Endpoints | Status |
|---|---|---|
| Recent / list / get task | `/tasks/recent`, `/tasks`, `/tasks/{id}`, `/projects/{id}/my-recent-task` | ✅ |
| Create / update / delete task | `POST /tasks`, `PUT/DELETE /tasks/{id}` | ◻ |
| Attachments | `/tasks/{id}/attachments[/{aid}[/download]]` | ◻ |
| Kanban board | `GET /kanban/boards?project_id` | ✅ |
| Kanban cards: create/edit/move/assign/archive | `/kanban/tasks[/{id}[/move,/assign,/archive,/unarchive]]`, `/projects/{id}/tasks/archived` | ◻ |
| Global search | `GET /search?q` (projects, tasks, conversations) | ✅ |

### 2.4 Conversations (Console / runs)
| Feature | Endpoints | Status |
|---|---|---|
| List mine / by task / get | `/runs/mine`, `/runs?task_id`, `/runs/{id}` | ✅ |
| Start conversation | `POST /runs {task_id,node_type:"console",prompt,model,provider_scope,…}` | ✅ |
| Send message | `POST /runs/{id}/messages {prompt,model,provider_scope,mode,…}` | ✅ |
| Messages / transcript | `/runs/{id}/messages[?subagent,step_id,before_time]`, `/runs/{id}/transcript.md` | ✅ |
| Rename / pin / archive / delete | `PATCH /runs/{id}/title`, `POST /runs/{id}/pin`, `PATCH|POST …/archive`, `DELETE /runs/{id}` | ✅ rename · ◻ rest |
| **Agent picker (!)** — 15 built-in agents (backend-dev, reviewer, tester, security-auditor, solution-architect, …) | `GET /changes/agents?task_id` → `agent_type` field | ◻ |
| **Skill picker (/)** — goal, deep-research, speckit, slide-craft, workflow, … | `GET /changes/skills?task_id` → `skill` field | ◻ |
| **Workflow picker (#)** — Bug Fix, Code Review, DB Migration, Feature Dev, Full-Stack, RFP→Demo/Proposal, Safe Refactor | `workflow_template_id` field, `/runs/{id}/workflow-batches` | ◻ |
| Plan vs Build mode, thinking variant, yolo mode | `mode`, `variant`, `yolo_mode` fields | ✅ mode · ◻ rest |
| File attachments in prompt | `attached_files`, `file_parts`, `/sessions/{sid}/vibeflow/file/upload` | ◻ |
| Fork conversation | `POST /runs {node_type:"fork",forked_from_run_id}` | ◻ |
| Abort / retry | `/sessions/{sid}/vibeflow/runs/{rid}/abort|retry[?subagent]` | ◻ |
| Permission & question prompts (human-in-the-loop) | `…/runs/{rid}/permissions/{id}/reply {reply}`, `…/questions/{id}/reply {answers}`, `/runs/{id}/pending-prompts[/{pid}/replay]` | ◻ |
| Resume / compact | `POST /runs/{id}/resume`, `POST /runs/{id}/compact` | ◻ |
| Cost & context usage | `/runs/{id}/cost-breakdown`, `/runs/{id}/context-usage`, `/sessions/{sid}/vibeflow/context` | ◻ |
| Artifacts | `/runs/{id}/artifacts` | ◻ |
| Background jobs / subagents | `…/runs/{rid}/jobs/{id|background}`, `?subagent=` | ◻ |
| Restore points (timeline, diff, revert, undo) | `/sessions/{sid}/vibeflow/runs/{rid}/restore-points[/{id}/diff]` | ◻ |
| Live streaming | SSE `/sessions/{sid}/vibeflow/events`, `/runs/poll-cursor`, `…/snapshot` | ◻ (POC polls) |

### 2.5 Sandbox sessions
| Feature | Endpoints | Status |
|---|---|---|
| Status / mine / start / stop | `/sessions/status`, `/sessions/mine`, `/sessions/start`, `/sessions/{id}/stop` | ✅ |
| Start with git clone | `/sessions/start {git_setup_mode,git_url,git_provider,git_token}` | ◻ |
| Save / stop-idle / baseline / upload workspace | `/sessions/{id}/save`, `/sessions/mine/stop-idle`, `…/workspace-baseline`, `…/upload-workspace` | ◻ |
| Models for project | `/sessions/models?project_id` (needs running session) | ✅ |
| Goal / cron / memory (harness) | `/sessions/{sid}/vibeflow/{goal,cron,memory}` (`op` verbs) | ◻ |
| Local file sync (WebSocket) | `/sessions/{id}/file-sync-ticket`, `…/vibeflow/file/sync` | ◻ (later) |
| LSP / Galaxy graph | `…/vibeflow/lsp/{x}`, `…/vibeflow/graph/layout` | ◻ (later) |

### 2.6 Code: files, changes, preview
| Feature | Endpoints | Status |
|---|---|---|
| Workdir / tree / read / binary / download / zip | `/files/workdir`, `/files`, `/files/content`, `/files/binary`, `/files/download`, `/files/download-workspace` | ◻ |
| Upload / delete / search | `/files/upload`, `/files/delete`, `/files/search` | ◻ |
| Branches / checkout | `/files/branches`, `/files/checkout` | ◻ |
| Changes status / list / diff / session-diff | `/changes/status`, `/changes`, `/changes/diff`, `/changes/session-diff` | ◻ |
| AI commit message / push / PR / git-sync | `/changes/generate-message`, `/changes/push`, `/changes/git-sync`, `/changes/session/reload` | ◻ |
| Preview run / stop / logs / AI fix / pull-merge | `/preview/{run,stop,fix,mermaid-fix,pull-merge,exchange-token}`, `/sessions/{id}/preview/logs` | ◻ |

### 2.7 Workflows (Canvas)
| Feature | Endpoints | Status |
|---|---|---|
| Get / save workflow graph | `GET/PUT /workflows/{id} {workflow:{nodes,edges}}` | ◻ |
| Run whole workflow / single step | `POST /runs {task_id,file_parts_by_node,start_from_node_id}`, `POST /runs/step {task_id,node_id}` | ◻ |

### 2.8 Analytics
| Feature | Endpoints | Status |
|---|---|---|
| Project cost (daily, summary, users, tasks, provider-model) | `/projects/{id}/analytics/cost/*` | ◻ |
| Git KPIs, outcome metrics, code activity, export | `/projects/{id}/analytics/{git-kpis,outcome-metrics,code-activity,export}` | ◻ |

### 2.9 Administration 🔒 (system roles only; ~40 endpoints)
Users (list, pending approvals, import, activate, role, whitelist) · roles · platform config/overrides ·
LLM providers & shared keys (probe, sync-models, revoke/delete keys) · user keys · usage overrides ·
project archive · session stop · conversation audit (flag, export) · DLP (catalog, findings, tester) ·
system health/metrics · capacity report · org-wide analytics & infra cost.

## 3. MCP design principles

1. **Toolsets, not a flat list.** 150+ tools would swamp an agent's context. Gate by env
   `VIBEFLOW_TOOLSETS=core,code,pm,analytics,admin` (default `core,code`). Keep `vibeflow_api` as the
   universal escape hatch.
2. **Task-shaped tools over endpoint mirrors.** E.g. `vibeflow_ask(project, prompt, agent?, skill?, workflow?)`
   = ensure sandbox → resolve default task → start run → wait → return reply. Low-level tools stay for control.
3. **Safety annotations.** Mark tools with MCP `readOnlyHint` / `destructiveHint` / `idempotentHint`. Destructive
   ops (delete project/task/run, push, revert, stop session, admin key revocation) require `confirm=true`.
4. **Cost awareness.** Surface `cost` per reply; `vibeflow_get_quota` check before long runs; optional
   `VIBEFLOW_MAX_RUN_COST` guard.
5. **Long-running work.** Phase 2 replaces polling with the SSE stream: emit MCP progress notifications
   (tool calls, text deltas) and return when the session goes idle; auto-handle `pending-prompts`.
6. **Compact outputs.** Render messages/diffs as text; strip noise (step-start/finish parts, metadata);
   paginate; cap at ~60k chars.
7. **Resources & prompts.** Expose transcripts (`vibeflow://runs/{id}/transcript`), files and diffs as MCP
   resources; ship MCP prompts for the 8 built-in workflows.

## 4. Phased plan

| Phase | Scope | Tools (≈) | Effort |
|---|---|---|---|
| **0 — POC** ✅ | SSO capture, refresh, 27 tools, live chat verified | 27 | done |
| **1 — Hardening** ✅ | uv packaging + `playwright install` bootstrap; OS keyring for tokens; silent headless re-login with the saved profile; unified error model (401/403/pending_approval/account_disabled/cooling_down); tool annotations; httpx mocks (respx) + recorded fixtures; contract-drift check (hash the SPA bundle, diff the extracted endpoint list) | +3 | 2–3 d |
| **2 — Conversation completeness** ✅ | agents/skills/workflow pickers; `vibeflow_ask` composite; fork/resume/compact/abort/retry; permission & question replies + pending prompts; attachments upload; cost/context usage; pin/archive/delete; SSE streaming with progress notifications | +18 | 4–5 d |
| **3 — Code loop** ✅ | files (tree/read/search/upload/delete/download), branches/checkout, changes status/diff, AI commit message, push/PR, git-sync, restore points (list/diff/revert/undo), preview run/stop/logs/fix, start-session-with-git | +20 | 4–5 d |
| **4 — Project management** ✅ | projects CRUD/pin, members/roles, kanban CRUD/move/assign/archive, task CRUD + attachments, templates (agents/prompts/workflows + import/export), Canvas workflow get/put/run/step, git credentials, project & personal LLM providers, budget, Jira, SharePoint, settings/onboarding/terms | +35 | 5–6 d |
| **5 — Analytics** ✅ | project cost/KPI/outcome/code-activity tools + export; user stats | +8 | 1–2 d |
| **6 — Admin** ✅ (opt-in toolset, role-checked at startup via `/auth/me`) | users/approvals/whitelist/roles, providers & keys, DLP, audit, sessions, health/metrics/capacity, org analytics | +30 | 3–4 d |
| **7 — Advanced** ✅ | MCP resources & workflow prompts, goal/cron/memory harness ops, local file sync over WebSocket, Galaxy graph, LSP queries | +10 | 3–5 d |

Total ≈ 150 tools / ~4–5 weeks for one engineer; Phases 1–3 (~2 weeks) already cover the day-to-day
"use VibeFlow without the GUI" workflow.

## 5. Testing strategy

- **Unit:** respx-mocked client; JSON fixtures captured from live responses (secrets scrubbed).
- **Contract:** nightly script fetches the logged-in SPA bundle, re-extracts `METHOD /api/v1/...` pairs and
  diffs against `endpoints.lock` — catches silent API changes in this unofficial integration.
- **Live smoke (opt-in):** read-only suite + one cheap chat turn on a platform Flash model in a private
  workspace, with session stop in `finally`.

## 6. Risks & open questions

| Risk | Mitigation |
|---|---|
| **Unofficial API** — no OpenAPI, can change on any deploy | Contract-drift check; keep `vibeflow_api` raw tool; ask the VibeFlow team for an official API / PAT support |
| **Policy** — automation via captured SSO token may need approval | Confirm with platform owners (the code has an "e2e" token path, suggesting automation is anticipated) |
| WAF User-Agent filter | Configurable `VIBEFLOW_USER_AGENT` |
| Refresh-token rotation | MCP uses its own browser profile/session, so it doesn't fight the user's browser |
| Cost (≈$0.03 baseline per turn, $50/month quota) | Cost surfaced per reply; quota guard |
| Secrets in payloads (git tokens, Jira PATs, LLM keys) | Never echo back; redact in logs/outputs |
| Model availability differs by provider scope | `vibeflow_list_models` returns `provider/id` + scope; auto-resolve platform models |

## 7. POC learnings that shape the build

- Models must be sent as `<provider>/<id>` **with** `provider_scope`; a bare id fails with
  "not configured for any LLM provider on this project".
- `/sessions/models` requires a running sandbox; `/users/me/platform-models` does not.
- `transcript.md` lags behind; structured `/runs/{id}/messages` (parts: text / tool / step-*) is authoritative.
- Run status settles to `idle` on success, `failed` with `error_message` on error.
- Sandbox start → running took ≈ 30–60 s; stop is immediate (workspace auto-saved; resumable).

## 8. Learnings from Phases 1–3 (2026-10-03)

- **Status: phases 1–3 shipped** — 68 tools, 74 unit tests, each phase verified live against production.
- Refresh tokens rotate: refreshes are serialized **and keyed on the stale token the failing request used**;
  keying on "the token at call time" made a late 401 rotate a second time.
- Headless Chromium must override the `HeadlessChrome` UA (WAF 403s it). Silent re-login must clear the SPA's
  cached localStorage tokens first, or it lifts a stale pair whose refresh token was already rotated away.
- Windows Credential Manager caps secrets at 2560 bytes → keyring storage is chunked.
- `mcp` 2.x renamed FastMCP → pinned `mcp<2`.
- A **new run reports `idle` before the agent picks it up**, and a follow-up before its turn starts: completion =
  idle + last message is a *completed* assistant message + message count ≥ expected. One turn can span several
  assistant messages (tool step, then answer).
- Sandbox SSE events are wrapped `{event_type, payload, conversation_id}`; one sandbox serves many
  conversations, so progress is filtered by `conversation_id`.
- Sessions start with `git_setup_mode = init` (local projects) / `clone` (git projects), not `none`.
- Code endpoints take `task_id` (the project's default task) + `session_id`; file writes are two-step
  (stage via `/sessions/{sid}/vibeflow/file/upload`, then `POST /files/upload`).
- `/changes/generate-message` runs an LLM server-side (> 60 s observed) and sometimes returns
  "AI returned empty response" — a platform-side issue, surfaced as a `bad_request` error.
- Restore points exist only for conversations run in the current pod (`run_not_found` after a restart).


## 9. Phases 4–7 (2026-10-03)

- **Status: all planned phases implemented** — 160 tools in 6 toolsets (`core` 45, `code` 24, `pm` 65,
  `analytics` 5, `advanced` 9, `admin` 12) + 4 MCP resource templates + 8 workflow prompts; 130 unit tests.
- Live-verified: every Phase 4 read tool, reversible writes (pin/unpin project, kanban card create → update →
  move → assign → archive, Canvas workflow save round-trip), all analytics tools incl. csv/pdf export, the admin
  403 path, LSP (document-symbol, diagnostics), code graph, memory, cron, sandbox MCP servers, goal status,
  resources and prompts. Not run live: see BACKLOG B6–B9.
- Request schemas were discovered with FastAPI's own 422 validation: `{}` bodies on fake-id paths list the
  required fields without side effects (an invalid enum value lists the allowed values). Top-level create
  endpoints can accept an arbitrary body — `POST /git-credentials` created a junk credential once (deleted).
- Facts that differ from first guesses: member roles are `pm | tl | member`; kanban priority
  `low | medium | high | urgent`; budget body key is `monthly_limit`; analytics export formats are only
  `csv | pdf`; daily cost needs `from`/`to`; goals are keyed by the conversation's OpenCode `sessionID`
  (`code_session_id`), not the run id; code-graph nodes use `label` for the kind and `name`/`file_path` for
  identity; LSP body is `{workdir, file, line, character}`.
- Local WebSocket file sync was deferred (BACKLOG B9).
