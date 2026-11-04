"""启动回填：现场任务导入 SQLite 的幂等与容错测试（034 US1 / T015）。"""

from __future__ import annotations

import json
import tracemalloc
from datetime import UTC, datetime

from app.models.db import TaskKpiPoint, TaskRecord, TaskRuleResult, session_factory
from app.models.schemas import InspectionTask, RuleResult, RuleStatus, Summary, SystemInspection, TaskStats
from app.services import store, task_db
from tests.baseline_helpers import setup_env

CREATED_AT = datetime(2026, 9, 10, 8, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 9, 10, 12, tzinfo=UTC)
KPI_CODE = "kpi.measurement_units"
HIDDEN_CODE = "pkg.extract.main"


def _rule(code: str = KPI_CODE, *, order: int = 1, status: RuleStatus = RuleStatus.PASS) -> RuleResult:
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
    )


def _scene_task(task_id: str, *, status: str = "completed", visible: list[RuleResult] | None = None) -> InspectionTask:
    rules = visible if visible is not None else [_rule()]
    summary = store.compute_summary(rules)
    stats = TaskStats.model_validate({**summary.model_dump(by_alias=True), "systems": 1})
    return InspectionTask(
        task_id=task_id,
        name=f"现场任务 {task_id}",
        mode="local",
        status=status,
        trigger="cli",
        created_at=CREATED_AT,
        completed_at=COMPLETED_AT,
        last_run_at=CREATED_AT,
        duration_ms=240_000,
        stats=stats,
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            package_checksum="c" * 64,
            version="V3",
            status="completed" if status == "completed" else "failed",
            summary=Summary.model_validate(summary.model_dump(by_alias=True)),
            rules=rules,
            customer={"device_id": "device-scene", "province": "北京"},
        ),
    )


def _write_scene(env, task: InspectionTask, *, rules: list[RuleResult], points: list[dict[str, object]]) -> None:
    """只写现场文件，不经过 save_task_meta（避免顺带写入任务行）。"""
    store.write_json_atomic(
        env.task_dir(task.task_id) / "task.json",
        task.model_dump(by_alias=True, mode="json"),
    )
    for rule in rules:
        path = env.rules_dir(task.task_id) / f"{rule.code}.json"
        store.write_json_atomic(path, rule.model_dump(by_alias=True, mode="json"))
    index = env.task_dir(task.task_id) / "kpi" / "history" / "index.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(point, ensure_ascii=False) for point in points]
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _point(task_id: str, *, value: float) -> dict[str, object]:
    return {
        "task_id": task_id,
        "rule_code": KPI_CODE,
        "measurement_unit_id": "MU",
        "metric_resource_id": "ME",
        "object_key": "pod-a",
        "period_minutes": 15,
        "measured_at": "2026-09-10T10:00:00+00:00",
        "value": value,
        "source_file": "data/metrics.csv",
        "line_number": 1,
    }


def _scene_rows(task_id: str) -> tuple[int, int]:
    with session_factory() as session:
        rule_rows = session.query(TaskRuleResult).filter(TaskRuleResult.task_id == task_id).count()
        point_rows = session.query(TaskKpiPoint).filter(TaskKpiPoint.task_id == task_id).count()
    return rule_rows, point_rows


def test_backfill_imports_scene_task_with_rules_and_kpi(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-backfill-full"
    task = _scene_task(task_id)
    _write_scene(env, task, rules=[_rule(HIDDEN_CODE, order=0), _rule()], points=[_point(task_id, value=7)])

    assert task_db.get_task_summary(task_id) is None
    assert task_db.backfill_from_output(env.output) == 1

    summary = task_db.get_task_summary(task_id)
    assert summary is not None
    assert summary.status.value == "completed"
    assert summary.stats.pass_ == 1
    assert summary.device_id == "device-scene"
    assert summary.customer_province == "北京"
    assert summary.customer_version == "V3"
    assert summary.last_run_at == CREATED_AT
    assert summary.duration_ms == 240_000
    assert [result.code for result in task_db.list_rule_results(task_id)] == [HIDDEN_CODE, KPI_CODE]
    assert [point["value"] for point in task_db.list_kpi_points(task_id)] == [7.0]
    assert task_db.get_run_fields(task_id) == (CREATED_AT, 240_000, "c" * 64)


def test_backfill_streams_large_kpi_index_file(tmp_path, monkeypatch) -> None:
    """启动回填读取大索引时必须逐行消费，不能把整文件、行列表和全部对象同时留在内存。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-backfill-streaming"
    task = _scene_task(task_id)
    _write_scene(env, task, rules=[_rule()], points=[])
    index = env.task_dir(task_id) / "kpi" / "history" / "index.jsonl"
    with index.open("w", encoding="utf-8") as fh:
        for value in range(60_000):
            fh.write(json.dumps(_point(task_id, value=value), ensure_ascii=False) + "\n")

    tracemalloc.start()
    try:
        assert task_db.import_task_from_output(task_id, output=env.output)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 40 * 1024 * 1024
    assert _scene_rows(task_id) == (1, 60_000)


def test_backfill_skips_already_indexed_task(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-backfill-indexed"
    task = _scene_task(task_id)
    _write_scene(env, task, rules=[_rule()], points=[_point(task_id, value=1)])
    assert task_db.backfill_from_output(env.output) == 1

    changed = _scene_task(task_id, status="failed", visible=[_rule(), _rule(HIDDEN_CODE, order=0)])
    _write_scene(env, changed, rules=[_rule(), _rule(HIDDEN_CODE, order=0)], points=[_point(task_id, value=99)])

    assert task_db.backfill_from_output(env.output) == 0
    summary = task_db.get_task_summary(task_id)
    assert summary is not None
    assert summary.status.value == "completed"
    assert [result.code for result in task_db.list_rule_results(task_id)] == [KPI_CODE]
    assert [point["value"] for point in task_db.list_kpi_points(task_id)] == [1.0]


def test_backfill_skips_broken_files_without_interrupting(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    good_id = "task-backfill-good"
    task = _scene_task(good_id)
    _write_scene(env, task, rules=[_rule()], points=[_point(good_id, value=2)])
    broken_rule = env.rules_dir(good_id) / "broken.json"
    broken_rule.write_text("{broken", encoding="utf-8")

    bad_id = "task-backfill-bad"
    bad_dir = env.task_dir(bad_id)
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "task.json").write_text("{not-json", encoding="utf-8")

    empty_dir = env.task_dir("task-backfill-empty")
    empty_dir.mkdir(parents=True, exist_ok=True)

    assert task_db.backfill_from_output(env.output) == 1
    assert task_db.get_task_summary(good_id) is not None
    assert [result.code for result in task_db.list_rule_results(good_id)] == [KPI_CODE]
    assert task_db.get_task_summary(bad_id) is None
    assert task_db.get_task_summary("task-backfill-empty") is None


def test_backfill_is_idempotent(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-backfill-idempotent"
    task = _scene_task(task_id)
    _write_scene(env, task, rules=[_rule()], points=[_point(task_id, value=3)])

    assert task_db.backfill_from_output(env.output) == 1
    first_rows = _scene_rows(task_id)
    assert task_db.backfill_from_output(env.output) == 0
    assert task_db.backfill_from_output(env.output) == 0
    assert _scene_rows(task_id) == first_rows == (1, 1)


def test_backfill_recovers_terminal_scene_without_task_json(tmp_path, monkeypatch) -> None:
    """进程在写 task.json 前退出时，启动回填应从终态现场恢复任务。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-backfill-terminal"
    task = _scene_task(task_id)
    assert task.system is not None
    store.save_system(env.output, task_id, task.system)
    store.save_rule_result(env.output, task_id, _rule())
    (env.task_dir(task_id) / "execution.log").write_text(
        json.dumps({"ts": "2026-09-10T08:00:00+00:00", "level": "info", "message": "任务开始"})
        + "\n"
        + json.dumps({"ts": "2026-09-10T12:00:00+00:00", "level": "info", "message": "任务完成"})
        + "\n",
        encoding="utf-8",
    )
    with session_factory() as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                name=task.name,
                mode="online",
                status="running",
                trigger="api",
                package_file=task.system.package_file,
                customer=dict(task.system.customer),
                package_kind="inspection",
                version=task.system.version,
                stats={},
                created_at=CREATED_AT,
                last_run_at=datetime(2026, 9, 10, 11, 56, tzinfo=UTC),
            )
        )
        session.commit()

    def unexpected_kpi_read(_task_dir, _task_id):
        raise AssertionError("历史终态恢复不得等待 KPI 索引入库")

    monkeypatch.setattr(task_db, "_read_kpi_index", unexpected_kpi_read)

    assert task_db.backfill_from_output(env.output) == 1

    summary = task_db.get_task_summary(task_id)
    assert summary is not None
    assert summary.status.value == "completed"
    assert summary.completed_at == COMPLETED_AT
    assert summary.duration_ms == 240_000
    assert [result.code for result in task_db.list_rule_results(task_id)] == [KPI_CODE]
    assert task_db.list_kpi_points(task_id) == []
    saved = json.loads((env.task_dir(task_id) / "task.json").read_text(encoding="utf-8"))
    assert saved["status"] == "completed"
    assert task_db.backfill_from_output(env.output) == 0
