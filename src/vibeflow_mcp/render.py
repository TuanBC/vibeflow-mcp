"""Compact text renderers for agent-facing output."""

from __future__ import annotations

from typing import Any


def message(msg: dict[str, Any], *, show_tools: bool = True, max_tool_output: int = 300) -> str:
    """Flatten an OpenCode-style message (text / reasoning / tool parts) to text."""
    lines: list[str] = []
    for p in msg.get("parts") or []:
        kind = p.get("type")
        if kind == "text" and p.get("text"):
            lines.append(p["text"].strip())
        elif kind == "tool" and show_tools:
            state = p.get("tool_state") or {}
            if not isinstance(state, dict):
                state = {}
            line = f"[tool {p.get('tool_name')} {state.get('status', '')}] {state.get('title') or ''}".rstrip()
            out = state.get("output")
            if isinstance(out, str) and out.strip() and max_tool_output:
                snippet = out.strip().replace("\n", " ")
                line += f" -> {snippet[:max_tool_output]}{'…' if len(snippet) > max_tool_output else ''}"
            lines.append(line)
    meta = msg.get("metadata") or {}
    role = msg.get("role", "?")
    head = f"### {role}"
    if role == "assistant":
        cost = meta.get("cost")
        head += f" ({msg.get('model') or meta.get('providerID', '')}" + (f", ${cost:.4f}" if isinstance(cost, (int, float)) else "") + ")"
        if meta.get("agent") and meta.get("agent") != "build":
            head += f" [agent: {meta['agent']}]"
    return head + "\n" + "\n".join(lines)


def messages(msgs: list[dict[str, Any]], last_n: int | None = None, **kw: Any) -> str:
    if last_n:
        msgs = msgs[-last_n:]
    return "\n\n".join(message(m, **kw) for m in msgs)


def tree(entries: list[dict[str, Any]], max_depth: int = 3, _depth: int = 0) -> list[str]:
    """Indented file tree; directories end with '/'."""
    out: list[str] = []
    for e in entries:
        is_dir = e.get("type") == "directory"
        out.append("  " * _depth + e.get("name", "?") + ("/" if is_dir else ""))
        children = e.get("children") or []
        if is_dir and children:
            if _depth + 1 < max_depth:
                out.extend(tree(children, max_depth, _depth + 1))
            else:
                out.append("  " * (_depth + 1) + f"… ({len(children)} entries)")
    return out


def diff(diff_lines: list[Any]) -> str:
    """Render the API's diff_lines (dicts with type/content or plain strings)."""
    out = []
    for line in diff_lines or []:
        if isinstance(line, str):
            out.append(line)
            continue
        kind = line.get("type") or line.get("kind") or ""
        prefix = {"add": "+", "added": "+", "addition": "+", "del": "-", "delete": "-", "deleted": "-",
                  "removed": "-", "deletion": "-", "hunk": "", "header": ""}.get(kind, " ")
        out.append(prefix + str(line.get("content", line.get("text", ""))))
    return "\n".join(out)
