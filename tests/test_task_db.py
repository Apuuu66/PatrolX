"""任务快照发布、整批替换与现场读取测试（034 US1 / T014）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.db import TaskKpiPoint, TaskRecord, TaskRuleResult, session_factory
from app.models.schemas import (
    Finding,
    InspectionTask,
    Metric,
    RuleResult,
    RuleStatus,
    Summary,
    SystemInspection,
    TaskStats,
    TaskStatus,
)
from app.services import store, task_db
from app.services.tasks import DeleteResult, TaskDeleteError, task_service
from tests.baseline_helpers import setup_env

CREATED_AT = datetime(2026, 9, 10, 8, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 9, 10, 12, tzinfo=UTC)
CHECKSUM = "b" * 64
KPI_CODE = "kpi.measurement_units"
HIDDEN_CODE = "pkg.extract.main"


def _finding(index: int = 1) -> Finding:
    return Finding(
        finding_id=f"f-{index}",
        title=f"发现 {index}",
        severity="high",
        source_file="data/metrics.csv",
        evidence=f"evidence-{index}",
        metrics=[Metric(key="count", label="数量", value=index)],
    )


def _rule(
    code: str = KPI_CODE,
    *,
    status: RuleStatus = RuleStatus.PASS,
    order: int = 1,
    findings: list[Finding] | None = None,
) -> RuleResult:
    return RuleResult(
        code=code,
        name=f"规则 {code}",
        category="kpi" if code.startswith("kpi") else "other",
        priority=order,
        execution_order=order,
        status=status,
        severity="medium",
        executed_at=COMPLETED_AT,
        skip_reason="无匹配文件" if status is RuleStatus.SKIP else None,
        findings=list(findings or []),
    )


def _task(
    task_id: str,
    rules: list[RuleResult],
    *,
    status: TaskStatus = TaskStatus.COMPLETED,
    name: str | None = None,
) -> InspectionTask:
    summary = store.compute_summary(rules)
    stats = TaskStats.model_validate({**summary.model_dump(by_alias=True), "systems": 1})
    return InspectionTask(
        task_id=task_id,
        name=name or task_id,
        mode="local",
        status=status,
        trigger="api",
        created_at=CREATED_AT,
        completed_at=COMPLETED_AT,
        last_run_at=COMPLETED_AT,
        duration_ms=180_000,
        stats=stats,
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            package_checksum=CHECKSUM,
            version="V1",
            status="completed" if status == TaskStatus.COMPLETED else "failed",
            summary=Summary.model_validate(summary.model_dump(by_alias=True)),
            rules=rules,
            customer={"device_id": "device-a"},
        ),
    )


def _point(
    task_id: str,
    *,
    value: float,
    measured_at: datetime = datetime(2026, 9, 10, 10, tzinfo=UTC),
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "measurement_unit_id": "MU",
        "metric_resource_id": "ME",
        "object_key": "pod-a",
        "period_minutes": 15,
        "measured_at": measured_at.isoformat(),
        "value": value,
        "source_file": "data/metrics.csv",
        "line_number": 1,
    }


def _row_counts(task_id: str) -> tuple[int, int]:
    with session_factory() as session:
        rule_rows = session.query(TaskRuleResult).filter(TaskRuleResult.task_id == task_id).count()
        point_rows = session.query(TaskKpiPoint).filter(TaskKpiPoint.task_id == task_id).count()
    return rule_rows, point_rows


def _write_rule_file(env, task_id: str, name: str, payload: object) -> None:
    rules_dir = env.rules_dir(task_id)
    rules_dir.mkdir(parents=True, exist_ok=True)
    path = rules_dir / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_publish_snapshot_rolls_back_whole_batch_on_failure(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    task_id = "task-db-tx"
    task_db.publish_snapshot(
        _task(task_id, [_rule()]),
        rule_results=[_rule()],
        kpi_points=[_point(task_id, value=1)],
    )
    before = task_db.get_task_summary(task_id)
    assert before is not None and before.status == TaskStatus.COMPLETED

    duplicated = [_rule(KPI_CODE, status=RuleStatus.FAIL), _rule(KPI_CODE)]
    with pytest.raises(IntegrityError):
        task_db.publish_snapshot(
            _task(task_id, duplicated, status=TaskStatus.FAILED, name="被覆盖的任务名"),
            rule_results=duplicated,
            kpi_points=[_point(task_id, value=99)],
        )

    after = task_db.get_task_summary(task_id)
    assert after is not None
    assert after.status == TaskStatus.COMPLETED
    assert after.name == task_id
    results = task_db.list_rule_results(task_id)
    assert [result.code for result in results] == [KPI_CODE]
    assert results[0].status == RuleStatus.PASS
    assert [point["value"] for point in task_db.list_kpi_points(task_id)] == [1.0]
    assert _row_counts(task_id) == (1, 1)


def test_publish_snapshot_replaces_previous_results_with_latest(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    task_id = "task-db-replace"
    task_db.publish_snapshot(
        _task(task_id, [_rule()]),
        rule_results=[_rule()],
        kpi_points=[_point(task_id, value=1)],
    )
    latest_rule = _rule(KPI_CODE, status=RuleStatus.WARN, findings=[_finding(2)])
    task_db.publish_snapshot(
        _task(task_id, [latest_rule]),
        rule_results=[latest_rule],
        kpi_points=[
            _point(task_id, value=2, measured_at=datetime(2026, 9, 10, 11, tzinfo=UTC)),
            _point(task_id, value=3, measured_at=datetime(2026, 9, 10, 12, tzinfo=UTC)),
        ],
    )

    results = task_db.list_rule_results(task_id)
    assert [result.code for result in results] == [KPI_CODE]
    assert results[0].status == RuleStatus.WARN
    assert len(results[0].findings) == 1
    assert [point["value"] for point in task_db.list_kpi_points(task_id)] == [2.0, 3.0]
    assert _row_counts(task_id) == (1, 2)


def test_publish_from_scene_skips_broken_rule_files(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-db-scene"
    valid = _rule()
    _write_rule_file(env, task_id, f"{KPI_CODE}.json", valid.model_dump(by_alias=True, mode="json"))
    _write_rule_file(env, task_id, "broken.json", "{broken")
    _write_rule_file(env, task_id, "invalid.json", {"code": "bad"})
    index = env.task_dir(task_id) / "kpi" / "history" / "index.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        json.dumps(_point(task_id, value=5), ensure_ascii=False) + "\n" + "{not-json}\n",
        encoding="utf-8",
    )

    task_db.publish_from_scene(_task(task_id, [valid]), output=env.output)

    results = task_db.list_rule_results(task_id)
    assert [result.code for result in results] == [KPI_CODE]
    assert results[0].status == RuleStatus.PASS
    assert [point["value"] for point in task_db.list_kpi_points(task_id)] == [5.0]


def test_published_rule_result_matches_scene_contract_json(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-db-contract"
    visible = _rule(findings=[_finding(1)])
    hidden = _rule(HIDDEN_CODE, order=0)
    for rule in (visible, hidden):
        _write_rule_file(env, task_id, f"{rule.code}.json", rule.model_dump(by_alias=True, mode="json"))

    task_db.publish_from_scene(_task(task_id, [visible]), output=env.output)

    stored = task_db.get_rule_result(task_id, KPI_CODE)
    assert stored is not None
    expected = RuleResult.model_validate(
        json.loads((env.rules_dir(task_id) / f"{KPI_CODE}.json").read_text(encoding="utf-8"))
    )
    assert stored.model_dump(by_alias=True, mode="json") == expected.model_dump(by_alias=True, mode="json")
    assert [result.code for result in task_db.list_rule_results(task_id)] == [HIDDEN_CODE, KPI_CODE]
    assert task_db.get_rule_result(task_id, HIDDEN_CODE) is not None


def test_task_delete_cascades_snapshot_rows(tmp_path, monkeypatch) -> None:
    """删除任务时级联删除规则结果与 KPI 点；文件现场成功删除后才删库（T023）。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-db-cascade"
    task = _task(task_id, [_rule()])
    task_db.publish_snapshot(task, rule_results=[_rule()], kpi_points=[_point(task_id, value=1)])
    store.save_task_meta(env.output, task)
    package_dir = env.uploads / task_id
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / f"{task_id}.zip").write_bytes(b"PK")

    assert task_service.delete(task_id) == DeleteResult.DELETED

    assert task_db.get_task(task_id) is None
    assert task_db.get_task_summary(task_id) is None
    assert _row_counts(task_id) == (0, 0)
    with session_factory() as session:
        assert session.get(TaskRecord, task_id) is None
    assert not (env.output / task_id).exists()
    assert not package_dir.exists()


def test_task_delete_failure_keeps_snapshot_rows(tmp_path, monkeypatch) -> None:
    """现场删除失败必须保留库内全部快照数据，避免”文件还在、数据先丢“。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-db-cascade-fail"
    task = _task(task_id, [_rule()])
    task_db.publish_snapshot(task, rule_results=[_rule()], kpi_points=[_point(task_id, value=1)])
    store.save_task_meta(env.output, task)

    def failed_rmtree(_path, *args, **kwargs):
        del args, kwargs
        raise OSError(39, "The directory is not empty")

    monkeypatch.setattr("app.services.tasks.shutil.rmtree", failed_rmtree)
    with pytest.raises(TaskDeleteError):
        task_service.delete(task_id)

    assert task_db.get_task_summary(task_id) is not None
    assert _row_counts(task_id) == (1, 1)
