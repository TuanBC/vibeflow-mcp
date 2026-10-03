"""Contract-drift check for this unofficial integration.

VibeFlow has no published OpenAPI, so we treat the SPA bundle as the contract:
fetch the logged-in app bundle, extract every `METHOD /path` the frontend
calls, and diff against the committed endpoints.lock.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import config

LOCK_FILE = Path(__file__).with_name("endpoints.lock")

_PARAM = re.compile(r"\$\{[^}]*\}?")
# api.get("/api/v1/..."), api.post(`/sessions/${id}/vibeflow/...`, ...)
_CLIENT_CALL = re.compile(r"\.(get|post|put|patch|delete|postForm)\(\s*([`\"])((?:/api/v1|/sessions/)[^`\"]*)\2")
# fetch(`${base}/api/v1/...`, {method:"POST"
_FETCH_CALL = re.compile(r"\(\s*`\$\{[^}]+\}(/api/v1[^`]*)`\s*,\s*\{[^}]{0,80}?method:\s*\"(\w+)\"")
# low-level helper with explicit method: Dr(`/api/v1/...`, {method:"PATCH", ...})
_HELPER_CALL = re.compile(r"(?<![.\w$])[A-Za-z_$][\w$]{0,3}\(\s*([`\"])((?:/api/v1|/sessions/)[^`\"]*)\1\s*,\s*\{[^}]{0,120}?method:\s*\"(\w+)\"")


def normalize(path: str) -> str:
    path = _PARAM.sub("{}", path).split("?")[0]
    path = re.sub(r"\{\}[^/]*", "{}", path)  # "{}/..." and "{}{}" collapse
    return path.rstrip("/") or "/"


def extract(bundle: str) -> list[str]:
    found = set()
    for method, _, path in _CLIENT_CALL.findall(bundle):
        found.add(f"{'POST' if method == 'postForm' else method.upper()} {normalize(path)}")
    for path, method in _FETCH_CALL.findall(bundle):
        found.add(f"{method.upper()} {normalize(path)}")
    for _, path, method in _HELPER_CALL.findall(bundle):
        found.add(f"{method.upper()} {normalize(path)}")
    return sorted(found)


async def fetch_bundle() -> str:
    """Load the SPA with the saved (logged-in) browser profile and return the
    app-core chunk, which is only served to authenticated sessions."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(config.BROWSER_PROFILE), headless=True, user_agent=config.USER_AGENT)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(config.WEB_URL, wait_until="networkidle")
            res = await page.evaluate("""async () => {
                const url = performance.getEntriesByType('resource').map(r => r.name)
                    .find(n => /\\/assets\\/app\\/app-core-[^/]+\\.js$/.test(n));
                if (!url) return {error: 'app-core chunk not loaded (not logged in?)'};
                const r = await fetch(url);
                return {status: r.status, url, text: await r.text()};
            }""")
        finally:
            await ctx.close()
    if res.get("error") or res.get("status") != 200:
        raise RuntimeError(res.get("error") or f"bundle fetch HTTP {res.get('status')}; run `vibeflow-mcp login`")
    return res["text"]


def diff(current: list[str], locked: list[str]) -> tuple[list[str], list[str]]:
    cur, old = set(current), set(locked)
    return sorted(cur - old), sorted(old - cur)


def read_lock() -> list[str]:
    if not LOCK_FILE.exists():
        return []
    return [line for line in LOCK_FILE.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


def write_lock(endpoints: list[str]) -> None:
    header = "# VibeFlow endpoints called by the SPA. Regenerate: vibeflow-mcp contract-check --update\n"
    LOCK_FILE.write_text(header + "\n".join(endpoints) + "\n", encoding="utf-8")
