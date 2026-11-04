"""任务终态发布与 KPI 镜像解耦的回归测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.schemas import InspectionTask, RuleResult, Summary, SystemInspection, TaskStats
from app.services import store, task_db
from app.services.tasks import task_service
from tests.baseline_helpers import setup_env

CREATED_AT = datetime(2026, 9, 10, 8, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 9, 10, 12, tzinfo=UTC)
KPI_CODE = "kpi.measurement_units"


def _rule() -> RuleResult:
    return RuleResult(
        code=KPI_CODE,
        name="KPI 测量单元",
        category="kpi",
        priority=1,
        execution_order=1,
        status="pass",
        severity="medium",
        executed_at=COMPLETED_AT,
    )


def _task(task_id: str, rule: RuleResult) -> InspectionTask:
    summary = store.compute_summary([rule])
    return InspectionTask(
        task_id=task_id,
        name=task_id,
        mode="online",
        status="completed",
        trigger="api",
        created_at=CREATED_AT,
        completed_at=COMPLETED_AT,
        last_run_at=CREATED_AT,
        duration_ms=240_000,
        stats=TaskStats.model_validate({**summary.model_dump(by_alias=True), "systems": 1}),
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            package_checksum="a" * 64,
            version="V3",
            status="completed",
            summary=Summary.model_validate(summary.model_dump(by_alias=True)),
            rules=[rule],
            customer={"province": "北京"},
        ),
    )


@pytest.mark.parametrize("publisher", ["cli", "service"])
def test_kpi_mirror_failure_does_not_block_terminal_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publisher: str,
) -> None:
    """KPI 入库失败时，任务行、规则结果和 task.json 仍必须收敛到 completed。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = f"task-terminal-{publisher}"
    rule = _rule()
    task = _task(task_id, rule)
    store.save_system(env.output, task_id, task.system)
    store.save_rule_result(env.output, task_id, rule)

    def broken_kpi_index(_task_dir: Path, _task_id: str):
        raise OSError("KPI 索引读取失败")

    monkeypatch.setattr(task_db, "_read_kpi_index", broken_kpi_index)

    if publisher == "cli":
        from app.cli import _publish_terminal

        _publish_terminal(task, None)
    else:
        task_service._publish_terminal(task)

    summary = task_db.get_task_summary(task_id)
    assert summary is not None
    assert summary.status.value == "completed"
    assert summary.completed_at == COMPLETED_AT
    assert [result.code for result in task_db.list_rule_results(task_id)] == [KPI_CODE]
    saved = store.load_task_meta(env.output, task_id)
    assert saved is not None
    assert saved.status.value == "completed"
    assert task_db.list_kpi_points(task_id) == []
