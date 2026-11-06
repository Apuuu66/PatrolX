"""测试隔离：运行时目录、SQLite 与 v6 KPI 合成现场。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from tests.fixtures.kpi_v6_seed import KpiV6SeedState, seed_kpi_v6_database

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


@pytest.fixture(autouse=True)
def _wait_for_background_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试结束先等待后台任务收尾，再恢复运行目录和 SQLite 的 monkeypatch。"""
    from tests.baseline_helpers import wait_for_task_service_idle

    yield
    wait_for_task_service_idle()


@pytest.fixture(scope="session", autouse=True)
def _initialize_test_database() -> None:
    """共享测试库只需初始化一次；各用例自行清理业务数据。"""
    from app.models.db import init_db

    init_db()


_MEASUREMENT_UNIT_TABLES = (
    "kpi_measurement_bindings",
    "kpi_measurement_derived",
    "kpi_measurement_resources",
    "kpi_metric_maintenance_audits",
    "kpi_metric_maintenance_configs",
    "kpi_v6_measurement_bindings",
    "kpi_v6_measurement_derived",
    "kpi_v6_metric_maintenance_configs",
    "kpi_v6_measurement_resources",
    "kpi_v6_measurement_units",
    "rule_states",
)


@pytest.fixture(autouse=True)
def _clean_measurement_unit_tables() -> None:
    """每个用例开始前清空测量单元数据，不影响其他测试表。"""
    with sqlite3.connect(_TMP / "patrolx.db", timeout=30) as connection:
        for table in _MEASUREMENT_UNIT_TABLES:
            connection.execute(f"DELETE FROM {table}")


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """为单条测试切换到独立 SQLite，并完成 v6 建表与迁移。"""
    from app.core.config import settings
    from app.models.db import init_db

    path = tmp_path / "patrolx-v6.db"
    monkeypatch.setattr(settings, "sqlite_path", path)
    init_db()
    return path


@pytest.fixture
def kpi_v6_seed(tmp_path: Path, isolated_db: Path) -> KpiV6SeedState:
    """构造 UMF/CSP 隔离、20 指标/10 关注、证据失败与 revision 冲突现场。"""
    return seed_kpi_v6_database(isolated_db, seed_root=tmp_path / "kpi-v6-packages")
