"""测量单元可读性巡检测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.db import init_db
from app.services.kpi_measurement_units import (
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    io,
    set_measurement_binding_status,
)

HEADER = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


def _prepare_resources() -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU__CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )


def _task(tmp_path: Path, body: str) -> list[tuple[str, Path]]:
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    files = [("ne333_Call_Statistics_15_0_202609020000.csv", path)]
    discover_measurement_bindings("task-1", files)
    binding_id = next(item["id"] for item in list_measurement_bindings()["items"] if item["metric_resource_id"])
    set_measurement_binding_status(binding_id, "confirmed")
    return files


def list_measurement_bindings():
    from app.services.kpi_measurement_units import list_measurement_bindings as function

    return function()


def test_all_readings_pass(tmp_path: Path) -> None:
    _prepare_resources()
    files = _task(
        tmp_path,
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\npod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,20\n",
    )
    result = inspect_measurement_files("task-1", files)
    unit = result["measurement_units"][0]
    assert unit["status"] == "pass"
    assert unit["metric_coverage"] == "1/1"
    assert set(unit["objects"]) == {"pod-a", "pod-b"}


def test_missing_confirmed_column_fails(tmp_path: Path) -> None:
    _prepare_resources()
    good = tmp_path / "ne333_Call_Statistics_15_1_202609020000.csv"
    good.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="utf-8")
    files = [("ne333_Call_Statistics_15_1_202609020000.csv", good)]
    discover_measurement_bindings("task-1", files)
    binding_id = next(item["id"] for item in list_measurement_bindings()["items"] if item["metric_resource_id"])
    set_measurement_binding_status(binding_id, "confirmed")
    missing = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    missing.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),其他列\npod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    files.append(("ne333_Call_Statistics_15_0_202609020000.csv", missing))
    result = inspect_measurement_files("task-1", files)
    assert result["measurement_units"][0]["status"] == "fail"


def test_null_and_parse_errors_fail(tmp_path: Path) -> None:
    _prepare_resources()
    files = _task(
        tmp_path,
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,\npod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,bad\n",
    )
    result = inspect_measurement_files("task-1", files)
    unit = result["measurement_units"][0]
    assert unit["status"] == "fail"
    observations = unit["metrics"][0]["observations"]
    assert {item["read_status"] for item in observations} == {"null", "parse_error"}
    assert all(item["source_rows"] for item in observations)


def test_all_zero_is_pass_with_pattern(tmp_path: Path) -> None:
    _prepare_resources()
    files = _task(
        tmp_path,
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,0\npod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,0\n",
    )
    result = inspect_measurement_files("task-1", files)
    metric = result["measurement_units"][0]["metrics"][0]
    assert result["measurement_units"][0]["status"] == "pass"
    assert metric["value_pattern"] == "all_zero"


def test_header_parse_error_is_isolated(tmp_path: Path) -> None:
    _prepare_resources()
    bad = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    bad.write_text("not,a,csv\n", encoding="utf-8")
    good = tmp_path / "ne333_Call_Statistics_15_1_202609020000.csv"
    good.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="utf-8")
    files = [
        ("ne333_Call_Statistics_15_2_202609020000.csv", bad),
        ("ne333_Call_Statistics_15_1_202609020000.csv", good),
    ]
    discover_measurement_bindings("task-1", files)
    binding_id = next(item["id"] for item in list_measurement_bindings()["items"] if item["metric_resource_id"])
    set_measurement_binding_status(binding_id, "confirmed")
    result = inspect_measurement_files("task-1", files)
    assert result["files"][0]["status"] == "parse_error"
    assert result["measurement_units"][0]["status"] == "error"


def test_row_objects_have_independent_statistics(tmp_path: Path) -> None:
    _prepare_resources()
    files = _task(
        tmp_path,
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n"
        "pod-a,2026-09-02 00:15:00,2026-09-02 00:30:00,15,3\n"
        "pod-b,2026-09-02 00:30:00,2026-09-02 00:45:00,15,5\n",
    )
    result = inspect_measurement_files("task-1", files)
    objects = result["measurement_units"][0]["objects"]
    assert objects["pod-a"]["row_count"] == 2
    assert objects["pod-a"]["min_value"] == 1
    assert objects["pod-a"]["max_value"] == 3
    assert objects["pod-b"]["valid_count"] == 1


def test_no_dimension_uses_default_object(tmp_path: Path) -> None:
    _prepare_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    files = [("ne333_Call_Statistics_15_0_202609020000.csv", path)]
    discover_measurement_bindings("task-1", files)
    binding_id = next(item["id"] for item in list_measurement_bindings()["items"] if item["metric_resource_id"])
    set_measurement_binding_status(binding_id, "confirmed")
    result = inspect_measurement_files("task-1", files)
    assert set(result["measurement_units"][0]["objects"]) == {"__all__"}


def test_gbk_measurement_csv_is_supported(tmp_path: Path) -> None:
    _prepare_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="gb18030")
    files = [(path.name, path)]
    discover_measurement_bindings("task-gbk", files)
    binding_id = next(item["id"] for item in list_measurement_bindings()["items"] if item["metric_resource_id"])
    set_measurement_binding_status(binding_id, "confirmed")

    result = inspect_measurement_files("task-gbk", files)
    assert result["measurement_units"][0]["status"] == "pass"
