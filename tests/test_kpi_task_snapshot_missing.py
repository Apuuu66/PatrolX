"""KPI 任务快照缺失与重跑边界测试。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.cli import run_single_rule, run_task
from app.services.kpi_catalog import KpiSnapshotError
from tests.baseline_helpers import setup_env


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "kpi.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "kpi/kpi-api-15.csv",
            "设备类型：XXX\n测量单元名称：API 统计\n"
            "服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),请求总数\n"
            "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15,100\n",
        )
    return package


def test_single_rule_rerun_without_snapshot_fails(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    package = _package(tmp_path)
    task_id = run_task(package).task_id
    snapshot_path = env.task_dir(task_id) / "kpi" / "kpi_catalog_snapshot.json"
    assert snapshot_path.is_file()
    snapshot_path.unlink()

    with pytest.raises(KpiSnapshotError, match="快照缺失"):
        run_single_rule("kpi.api", package=package, task_id=task_id)
    assert not snapshot_path.exists()


def test_full_rerun_without_snapshot_initializes_once(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = run_task(_package(tmp_path)).task_id
    snapshot_path = env.task_dir(task_id) / "kpi" / "kpi_catalog_snapshot.json"
    snapshot_path.unlink()
    from app.services.kpi_catalog import load_task_kpi_config

    load_task_kpi_config(task_id)
    assert snapshot_path.is_file()
    first = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot_path.unlink()
    load_task_kpi_config(task_id)
    second = json.loads(snapshot_path.read_text(encoding="utf-8"))
    first.pop("captured_at")
    second.pop("captured_at")
    assert first == second
