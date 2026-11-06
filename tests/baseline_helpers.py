"""系统基线测试助手：统一临时环境、任务等待与契约结果读取。"""

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import settings
from app.models import kpi_v6 as kpi_schemas
from app.models.db import init_db
from app.services import rule_network_assignments
from app.services.auth import AuthSession
from app.services.tasks import task_service

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"
VOLATILE_KEYS = {"executed_at", "duration_ms"}
TEST_ADMIN = AuthSession(token="baseline-test-admin", username="baseline-test-admin", role="admin")


@dataclass(slots=True)
class Env:
    """一次测试可复用的本地/在线运行环境。"""

    root: Path
    uploads: Path
    output: Path
    sqlite: Path

    def task_dir(self, task_id: str) -> Path:
        return self.output / task_id

    def rules_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "rules"


def setup_env(
    tmp_path: Path,
    monkeypatch,
    *,
    assign_rules_to: str | Iterable[str] | None = None,
) -> Env:
    """将运行时目录和 SQLite 指向当前测试的临时现场。

    旧基线用例若需要业务规则参与执行，必须显式传入网元类型；生产默认
    仍是未归属规则不执行，不能由测试助手隐式恢复全局启停语义。
    """
    env = Env(
        root=tmp_path,
        uploads=tmp_path / "uploads",
        output=tmp_path / "output",
        sqlite=tmp_path / "patrolx.db",
    )
    env.uploads.mkdir(parents=True, exist_ok=True)
    env.output.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "uploads_dir", env.uploads)
    monkeypatch.setattr(settings, "output_dir", env.output)
    monkeypatch.setattr(settings, "sqlite_path", env.sqlite)
    init_db()
    monkeypatch.chdir(env.root)
    monkeypatch.setattr(settings, "uploads_dir", env.uploads)
    monkeypatch.setattr(settings, "output_dir", env.output)
    monkeypatch.setattr(settings, "sqlite_path", env.sqlite)
    if assign_rules_to is not None:
        assign_all_business_rules(assign_rules_to)
    return env


def _normalize_network_types(network_element_types: str | Iterable[str]) -> list[str]:
    values = [network_element_types] if isinstance(network_element_types, str) else list(network_element_types)
    return list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))


def assign_rules_to_network_element(
    rule_codes: Iterable[str],
    network_element_types: str | Iterable[str] = "UMF",
    *,
    actor: AuthSession = TEST_ADMIN,
) -> None:
    """显式配置测试规则归属；多次配置同一规则时合并网元类型。"""
    requested = list(dict.fromkeys(rule_codes))
    desired_types = _normalize_network_types(network_element_types)
    current = rule_network_assignments.list_rule_assignments(
        actor=actor,
        page=1,
        page_size=200,
    )
    revisions = {item.rule_code: item for item in current.items}
    for rule_code in requested:
        item = revisions[rule_code]
        merged_types = sorted(set(item.network_element_types) | set(desired_types))
        if item.network_element_types == merged_types:
            continue
        rule_network_assignments.update_rule_assignment(
            rule_code,
            kpi_schemas.KpiRuleAssignmentPatchRequestV6(
                expected_revision=item.revision,
                network_element_types=merged_types,
                confirm_unassign=False,
            ),
            actor=actor,
        )


def assign_all_business_rules(
    network_element_types: str | Iterable[str] = "UMF",
    *,
    actor: AuthSession = TEST_ADMIN,
) -> None:
    """为旧基线回归显式归属全部普通规则，模拟已维护的测试配置。"""
    from app.inspectors.registry import registry

    registry.load_all()
    assign_rules_to_network_element(
        (rule.code for rule in registry.all() if not rule.hidden),
        network_element_types,
        actor=actor,
    )


def wait_for_task_service_idle(timeout: float = 30.0) -> None:
    """等待 worker 队列与执行锁空闲，避免测试切换运行环境时污染在途任务。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not task_service._worker.is_alive():
            raise RuntimeError("patrolx-worker 已意外退出")
        with task_service._state_lock:
            active_task = task_service._active_task
        if active_task is None and task_service._queue.empty():
            remaining = max(deadline - time.monotonic(), 0)
            if remaining and task_service._lock.acquire(timeout=remaining):
                task_service._lock.release()
                return
        time.sleep(0.01)
    raise TimeoutError(f"任务 worker 未在 {timeout}s 内空闲")


def wait_for_task(client: TestClient, task_id: str, timeout: float = 180.0) -> dict[str, Any]:
    """轮询在线任务直到 completed/failed；上限覆盖完整月度样例的执行耗时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v2/tasks/{task_id}")
        if response.status_code == 200:
            task = response.json()
            if task["status"] in ("completed", "failed"):
                # 终态可见时 worker 仍可能持有执行锁镜像 KPI 并做留存清理。
                # active 标记先于这些收尾释放，必须再等待执行锁真正空闲。
                while task_service._active_task is not None and time.time() < deadline:
                    time.sleep(0.01)
                remaining = max(deadline - time.time(), 0)
                if remaining and task_service._lock.acquire(timeout=remaining):
                    task_service._lock.release()
                    return task
        time.sleep(0.05)
    raise TimeoutError(f"任务 {task_id} 未在 {timeout}s 内完成")


def upload_package(
    env: Env,
    client: TestClient,
    *,
    package: Path = SAMPLE,
    name: str | None = None,
    product: str | None = "UMF",
    **metadata: str,
) -> str:
    """以在线 API 创建正向任务并返回 task_id；product=None 可显式构造缺失负例。"""
    data = {
        "package_kind": "inspection",
        "name": name or "基线任务",
        "province": "北京",
        "operator": "移动",
        **metadata,
    }
    if data["package_kind"] == "inspection" and product is not None:
        data["product"] = product
    with package.open("rb") as fh:
        response = client.post(
            "/api/v3/tasks",
            files={"package_file": (package.name, fh, "application/zip")},
            data=data,
        )
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def load_task(env: Env, task_id: str) -> dict[str, Any]:
    """读取 output/<task_id>/task.json 契约。"""
    return json.loads((env.task_dir(task_id) / "task.json").read_text(encoding="utf-8"))


def load_system(env: Env, task_id: str) -> dict[str, Any]:
    """读取 output/<task_id>/system.json 契约。"""
    return json.loads((env.task_dir(task_id) / "system.json").read_text(encoding="utf-8"))


def load_rule(env: Env, task_id: str, code: str) -> dict[str, Any]:
    """读取 output/<task_id>/rules/<code>.json 契约。"""
    return json.loads((env.rules_dir(task_id) / f"{code}.json").read_text(encoding="utf-8"))


def load_logs(env: Env, task_id: str) -> list[dict[str, Any]]:
    """读取结构化执行日志。"""
    path = env.task_dir(task_id) / "execution.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def strip_volatile(data: Any) -> Any:
    """剥离执行时间、耗时等运行态字段，用于双模式一致性比较。"""
    if isinstance(data, dict):
        return {k: strip_volatile(v) for k, v in data.items() if k not in VOLATILE_KEYS}
    if isinstance(data, list):
        return [strip_volatile(item) for item in data]
    return data
