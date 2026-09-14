"""重跑状态可见性回归测试。"""

import time

from fastapi.testclient import TestClient
from test_api import _upload, _wait

from app.inspectors.base import Inspector, PrepareSpec
from app.main import app
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import Executor
from app.services.tasks import task_service


def test_rerun_marks_output_task_pending_before_queueing(monkeypatch) -> None:
    client = TestClient(app)
    task_id = _upload("rerun-pending.zip")
    _wait(task_id)

    # 阻断队列，保证断言发生在 rerun 受理阶段，而不是依赖 worker 完成速度。
    monkeypatch.setattr(task_service._queue, "put", lambda _task_id: None)
    resp = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert resp.status_code == 202

    task = task_service.get(task_id)
    assert task is not None
    assert task.status.value in {"pending", "running"}
    assert task.completed_at is None

    # 避免阻断队列后的残留计划影响同进程后续测试。
    task_service._rerun_plan.pop(task_id, None)


def test_rerun_failure_updates_output_status(monkeypatch) -> None:
    client = TestClient(app)
    task_id = _upload("rerun-failed.zip")
    _wait(task_id)

    def raise_rerun(*args, **kwargs):
        raise RuntimeError("rerun failed")

    monkeypatch.setattr("app.services.tasks.run_single_rule", raise_rerun)
    resp = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert resp.status_code == 202

    deadline = time.time() + 2
    while time.time() < deadline:
        task = task_service.get(task_id)
        assert task is not None
        if task.status.value in {"failed", "completed"}:
            break
        time.sleep(0.02)
    assert task is not None
    assert task.status.value == "failed"
    assert task.completed_at is not None


def test_single_rule_rerun_only_executes_target_prepare_and_inspect(tmp_path) -> None:
    """单规则重跑只执行目标 prepare + inspect，不触发其他普通规则。"""
    from test_prepare_pipeline import make_context, make_registry

    registry, events = make_registry()

    def target_prepare(_ctx) -> None:
        events.append("prepare:rule.target")

    def target_run(_ctx):
        events.append("inspect:rule.target")
        from app.services.executor import make_result

        return make_result(
            registry.get("rule.target"),
            status=RuleStatus.PASS,
            summary="ok",
        )

    def other_run(_ctx) -> None:
        events.append("inspect:rule.other")
        raise AssertionError("单规则重跑不应执行其他普通规则")

    registry.register(
        Inspector(
            code="rule.target",
            name="target",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试目标规则",
            recommendation="测试目标规则",
            source_patterns=[r"^logs/.*\.log$"],
            run=target_run,
            prepare=PrepareSpec(
                code="prepare.rule.target",
                owner_code="rule.target",
                run=target_prepare,
            ),
        )
    )
    registry.register(
        Inspector(
            code="rule.other",
            name="other",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试其他规则",
            recommendation="测试其他规则",
            source_patterns=[r"^other/.*$"],
            run=other_run,
        )
    )
    ctx = make_context(tmp_path, registry, events, {"logs/target.log": "ok"})

    result = Executor(registry).run_rule_with_deps("rule.target", ctx)

    assert events == ["prepare:rule.target", "inspect:rule.target"]
    assert result.status == RuleStatus.PASS


def test_multi_rule_rerun_reuses_one_package_checksum(monkeypatch) -> None:
    """一次多规则重跑计划中的规则共享同一个主包 checksum。"""
    task_id = _upload("multi-rerun-checksum.zip")
    _wait(task_id)
    calls: list[tuple[str, str | None]] = []

    def record_run(code: str, **kwargs):
        calls.append((code, kwargs.get("package_checksum")))

    monkeypatch.setattr("app.services.tasks.run_single_rule", record_run)
    task_service._rerun_plan[task_id] = ["log.error_density", "config.check"]
    try:
        task_service._execute(task_id)
    finally:
        task_service._rerun_plan.pop(task_id, None)

    assert [code for code, _checksum in calls] == ["log.error_density", "config.check"]
    checksums = {checksum for _code, checksum in calls}
    assert len(checksums) == 1
    assert next(iter(checksums)) is not None
