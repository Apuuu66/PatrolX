"""测试隔离：运行时目录与 SQLite 指向临时目录。"""

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="patrolx-test-"))
os.environ["PATROLX_OUTPUT_DIR"] = str(_TMP / "output")
os.environ["PATROLX_UPLOADS_DIR"] = str(_TMP / "uploads")
os.environ["PATROLX_SQLITE_PATH"] = str(_TMP / "patrolx.db")
os.environ["PATROLX_CONFIG_DIR"] = "deploy/config"


@pytest.fixture(autouse=True)
def _admin_auth_override() -> None:
    """集成测试默认管理员；认证链路由 tests/test_auth.py 单独覆盖。"""
    from app.main import app
    from app.models.db import AuthSession
    from app.services.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: AuthSession(
        token="integration-test-token",
        username="integration-admin",
        role="admin",
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)
