"""KPI 同快照重跑确定性回归。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.cli import run_single_rule, run_task
from tests.baseline_helpers import setup_env, strip_volatile


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "kpi-deterministic.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "kpi/kpi-api-15.csv",
            "设备类型：XXX\n测量单元名称：API 统计\n"
            "服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),请求总数\n"
            "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15,100\n",
        )
    return package


def test_same_snapshot_produces_same_rule_result(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    package = _package(tmp_path)
    task_id = run_task(package).task_id
    before = json.loads((env.task_dir(task_id) / "rules" / "kpi.api.json").read_text(encoding="utf-8"))
    run_single_rule("kpi.api", package=package, task_id=task_id)
    after = json.loads((env.task_dir(task_id) / "rules" / "kpi.api.json").read_text(encoding="utf-8"))
    assert strip_volatile(after) == strip_volatile(before)
