"""Entry point.

  vibeflow-mcp            run the MCP server over stdio
  vibeflow-mcp login      interactive SSO login from a terminal (no MCP client needed)
  vibeflow-mcp status     show stored token status
"""

import asyncio
import json
import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "login":
        from .auth import TokenStore, browser_login

        print("Opening browser for Microsoft SSO... complete the sign-in there.")
        result = asyncio.run(browser_login(TokenStore()))
        print(json.dumps(result, indent=2, default=str))
    elif cmd == "status":
        from .auth import TokenStore

        print(json.dumps(TokenStore().status(), indent=2))
    elif cmd == "serve":
        from .server import mcp

        mcp.run()
    else:
        sys.exit(f"Unknown command: {cmd}. Use: serve | login | status")


if __name__ == "__main__":
    main()
