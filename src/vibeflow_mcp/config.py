"""Runtime configuration (env-overridable). Defaults discovered from
https://vibeflow.fptconsulting.co.jp/config.js."""

import os
from pathlib import Path

WEB_URL = os.environ.get("VIBEFLOW_WEB_URL", "https://vibeflow.fptconsulting.co.jp")
API_URL = os.environ.get("VIBEFLOW_API_URL", "https://api.vibeflow.fptconsulting.co.jp")

# The Azure Application Gateway WAF rejects non-browser User-Agents (incl.
# HeadlessChrome) with 403, so every HTTP call and headless browser uses this.
USER_AGENT = os.environ.get(
    "VIBEFLOW_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
)

HOME = Path(os.environ.get("VIBEFLOW_MCP_HOME", Path.home() / ".vibeflow-mcp"))
TOKEN_FILE = HOME / "tokens.json"
BROWSER_PROFILE = HOME / "browser-profile"

# "auto" = OS keyring when available, else file; or force "keyring" / "file".
TOKEN_BACKEND = os.environ.get("VIBEFLOW_TOKEN_BACKEND", "auto")
KEYRING_SERVICE = "vibeflow-mcp"

# localStorage key where the SPA (zustand persist) keeps {state: {user, tokens}}.
AUTH_STORAGE_KEY = "vibeflow-auth"

LOGIN_TIMEOUT_SECONDS = int(os.environ.get("VIBEFLOW_LOGIN_TIMEOUT", "300"))
# When refresh fails, try a headless login with the saved browser profile.
SILENT_RELOGIN = os.environ.get("VIBEFLOW_SILENT_RELOGIN", "1") != "0"
SILENT_LOGIN_TIMEOUT_SECONDS = int(os.environ.get("VIBEFLOW_SILENT_LOGIN_TIMEOUT", "60"))
# Refresh the access token when it has less than this many seconds left.
REFRESH_MARGIN_SECONDS = 300

# Tool groups to expose. core = auth/workspace/chat/sandbox/meta, code = files/changes/preview.
TOOLSETS = {t.strip() for t in os.environ.get("VIBEFLOW_TOOLSETS", "core,code").split(",") if t.strip()}

# Used by vibeflow_ask when no model is given ('<provider>/<id>' or bare platform id).
DEFAULT_MODEL = os.environ.get("VIBEFLOW_DEFAULT_MODEL", "")

MAX_OUTPUT_CHARS = int(os.environ.get("VIBEFLOW_MAX_OUTPUT_CHARS", "60000"))
