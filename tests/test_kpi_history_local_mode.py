"""本地/CLI KPI 历史索引一致性测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.kpi_history import get_history_trend, index_path
from app.services.kpi_measurement_units import (
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    io,
)
from app.services.store import save_task_meta
from tests.baseline_helpers import setup_env
from tests.test_kpi_device_history import _meta

HEADER = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"


def _prepare_resources() -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )


def _files(tmp_path: Path, task_id: str) -> list[tuple[str, Path]]:
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    files = [(path.name, path)]
    discover_measurement_bindings(task_id, files)
    return files


def test_local_inspection_writes_index_and_empty_device_is_degraded(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_resources()
    task_id = "task-local-history"
    meta = _meta(task_id)
    meta.system.customer["device_id"] = ""
    save_task_meta(env.output, meta)

    result = inspect_measurement_files(task_id, _files(tmp_path, task_id))
    assert result["measurement_units"][0]["status"] == "pass"
    records = [json.loads(line) for line in index_path(env.output, task_id).read_text(encoding="utf-8").splitlines()]
    assert records
    assert all(record["task_id"] == task_id for record in records)
    assert all("device_id" not in record for record in records)

    trend = get_history_trend(
        task_id,
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id=records[0]["metric_resource_id"],
        object_key="pod-a",
        period_minutes=15,
        output=env.output,
    )
    assert trend.match.status == "degraded"
    assert trend.match.reason_code == "device_id_missing"
