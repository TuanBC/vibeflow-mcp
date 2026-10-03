"""Entry point.

  vibeflow-mcp                         run the MCP server over stdio
  vibeflow-mcp login [--headless]      SSO login from a terminal (no MCP client needed)
  vibeflow-mcp status                  show stored token status
  vibeflow-mcp logout                  delete the stored token
  vibeflow-mcp install-browser         download the Chromium build Playwright needs
  vibeflow-mcp contract-check [--update]
                                       diff the live SPA's API calls against endpoints.lock
"""

import asyncio
import json
import subprocess
import sys


def _contract_check(update: bool) -> int:
    from . import contract

    current = contract.extract(asyncio.run(contract.fetch_bundle()))
    added, removed = contract.diff(current, contract.read_lock())
    if not current:
        print("Extracted 0 endpoints - the bundle format changed or the fetch failed; lock left unchanged.")
        return 2
    if update:
        contract.write_lock(current)
        print(f"endpoints.lock updated ({len(current)} endpoints).")
        return 0
    if not added and not removed:
        print(f"No API drift ({len(current)} endpoints).")
        return 0
    for e in added:
        print(f"+ {e}")
    for e in removed:
        print(f"- {e}")
    print(f"API drift: {len(added)} added, {len(removed)} removed. Review, then --update.")
    return 1


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "serve"
    if cmd == "serve":
        from .server import mcp

        mcp.run()
    elif cmd == "login":
        from .auth import TokenStore, browser_login

        headless = "--headless" in args
        print("Signing in" + (" silently..." if headless else ": complete Microsoft SSO in the browser window."))
        print(json.dumps(asyncio.run(browser_login(TokenStore(), headless=headless)), indent=2, default=str))
    elif cmd == "status":
        from .auth import TokenStore

        print(json.dumps(TokenStore().status(), indent=2))
    elif cmd == "logout":
        from .auth import TokenStore

        TokenStore().clear()
        print("Local token deleted.")
    elif cmd == "install-browser":
        sys.exit(subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"]))
    elif cmd == "contract-check":
        sys.exit(_contract_check("--update" in args))
    else:
        sys.exit(f"Unknown command: {cmd}. Use: serve | login | status | logout | install-browser | contract-check")


if __name__ == "__main__":
    main()
