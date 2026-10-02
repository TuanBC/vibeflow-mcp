import base64
import json
import os
import tempfile
import time

# Configure before vibeflow_mcp is imported (config reads env at import time).
os.environ["VIBEFLOW_MCP_HOME"] = tempfile.mkdtemp(prefix="vibeflow-test-")
os.environ["VIBEFLOW_TOKEN_BACKEND"] = "file"
os.environ["VIBEFLOW_SILENT_RELOGIN"] = "0"
os.environ.setdefault("VIBEFLOW_TOOLSETS", "core,code")

import pytest  # noqa: E402

from vibeflow_mcp import app, config  # noqa: E402

API = config.API_URL


def make_jwt(exp_in: int = 3600, email: str = "dev@example.com", jti: str = "j1") -> str:
    def enc(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    claims = {"sub": "u1", "email": email, "role": "user", "jti": jti, "exp": int(time.time()) + exp_in}
    return f"{enc({'alg': 'HS256'})}.{enc(claims)}.sig"


@pytest.fixture(autouse=True)
def clean_state():
    app.store.clear()
    app._task_cache.clear()
    yield
    app.store.clear()


@pytest.fixture
def logged_in():
    app.store.save({"access_token": make_jwt(), "refresh_token": "r1"},
                   {"id": "u1", "email": "dev@example.com", "display_name": "Dev"})
    return app.store


def payload(result: str):
    """Tool wrappers return rendered JSON/text; parse JSON when possible."""
    try:
        return json.loads(result)
    except ValueError:
        return result
