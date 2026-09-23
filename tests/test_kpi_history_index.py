"""KPI 历史索引生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.kpi_history import index_path
from app.services.kpi_measurement_units import (
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    io,
)
from tests.baseline_helpers import setup_env

HEADER = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"


def _prepare() -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )


def _files(tmp_path: Path, body: str):
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    files = [(path.name, path)]
    discover_measurement_bindings("task-index", files)
    return files


def test_inspection_writes_utf8_jsonl_index(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare()
    result = inspect_measurement_files(
        "task-index", _files(tmp_path, "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n")
    )
    assert result["measurement_units"][0]["status"] == "pass"

    path = index_path(env.output, "task-index")
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines
    records = [json.loads(line) for line in lines]
    assert all(record["task_id"] == "task-index" for record in records)
    assert all("device_id" not in record for record in records)
    assert {
        "task_id",
        "measurement_unit_id",
        "metric_resource_id",
        "object_key",
        "period_minutes",
        "measured_at",
        "value",
        "source_file",
    } <= set(records[0])
    assert records[0]["period_minutes"] == 15
    assert records[0]["object_key"] == "pod-a"


def test_invalid_values_and_duplicate_times_are_normalized(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare()
    inspect_measurement_files(
        "task-index",
        _files(
            tmp_path,
            "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,\n"
            "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n"
            "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,3\n"
            "pod-a,2026-09-02 00:15:00,2026-09-02 00:30:00,15,bad\n",
        ),
    )
    records = [
        json.loads(line) for line in index_path(env.output, "task-index").read_text(encoding="utf-8").splitlines()
    ]
    print(records)
    assert len(records) == 1
    assert records[0]["value"] == 2


def test_index_rebuild_replaces_old_points(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare()
    inspect_measurement_files("task-index", _files(tmp_path, "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n"))
    inspect_measurement_files("task-index", _files(tmp_path, "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,9\n"))
    records = [
        json.loads(line) for line in index_path(env.output, "task-index").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["value"] for record in records] == [9]
