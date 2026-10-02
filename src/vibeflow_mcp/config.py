"""Static configuration discovered from https://vibeflow.fptconsulting.co.jp/config.js."""

import os
from pathlib import Path

WEB_URL = os.environ.get("VIBEFLOW_WEB_URL", "https://vibeflow.fptconsulting.co.jp")
API_URL = os.environ.get("VIBEFLOW_API_URL", "https://api.vibeflow.fptconsulting.co.jp")

# The Azure Application Gateway WAF rejects non-browser User-Agents with 403.
USER_AGENT = os.environ.get(
    "VIBEFLOW_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
)

HOME = Path(os.environ.get("VIBEFLOW_MCP_HOME", Path.home() / ".vibeflow-mcp"))
TOKEN_FILE = HOME / "tokens.json"
BROWSER_PROFILE = HOME / "browser-profile"

# localStorage key where the SPA (zustand persist) keeps {state: {user, tokens}}.
AUTH_STORAGE_KEY = "vibeflow-auth"

LOGIN_TIMEOUT_SECONDS = int(os.environ.get("VIBEFLOW_LOGIN_TIMEOUT", "300"))
# Refresh the access token when it has less than this many seconds left.
REFRESH_MARGIN_SECONDS = 300
