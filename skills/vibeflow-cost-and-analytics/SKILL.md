---
name: vibeflow-cost-and-analytics
description: Report VibeFlow LLM spend and delivery metrics - personal quota, per-conversation cost, project cost by user, task and model, daily cost, outcome KPIs, code activity, and CSV/PDF monthly reports. Use when the user asks what VibeFlow work cost or how a project is progressing (toolset analytics).
---

# Cost and analytics

| Question | Tool |
|---|---|
| How much budget do I have left? | `vibeflow_get_quota` |
| What did this conversation cost? | `vibeflow_conversation_usage(run_id)` |
| Project spend for a month (by user, task, model) | `vibeflow_project_cost(project_id, month="YYYY-MM")` |
| Spend per day | `vibeflow_project_cost_daily(project_id, from_date, to_date)` |
| Delivery outcomes (merged vs abandoned work) | `vibeflow_project_kpis(project_id, month)` |
| Lines changed, runs per member | `vibeflow_code_activity(project_id, month)` |
| Report file | `vibeflow_export_analytics(project_id, local_path, month, format="csv" or "pdf")` |
| My own activity | `vibeflow_my_stats` |

Show amounts in USD with 2-4 decimals and say which month they cover. Org-wide figures need the `admin`
toolset and a system-admin account (`vibeflow_admin_analytics`).
