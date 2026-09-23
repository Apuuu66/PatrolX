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
    update_manual_metric,
)

HEADER = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


def _prepare_resources() -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )


def _task(tmp_path: Path, body: str) -> list[tuple[str, Path]]:
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    files = [("ne333_Call_Statistics_15_0_202609020000.csv", path)]
    discover_measurement_bindings("task-1", files)
    return files


def test_inspection_auto_confirms_binding_and_result(tmp_path: Path) -> None:
    _prepare_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        encoding="utf-8",
    )
    files = [("ne333_Call_Statistics_15_0_202609020000.csv", path)]

    inspect_measurement_files("task-1", files)

    bindings = list_measurement_bindings()["items"]
    assert len(bindings) == 1
    assert bindings[0]["status"] == "confirmed"
    assert bindings[0]["measurement_unit_id"] == "MU_CALL"


def test_unknown_column_auto_registers_with_defaults_and_rerun_is_idempotent(tmp_path: Path) -> None:
    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),异常请求次数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,3\n",
        encoding="utf-8",
    )
    files = [(path.name, path)]
    result = inspect_measurement_files("task-defaults", files)

    from app.services.kpi_measurement_units import list_measurement_resources

    metric = list_measurement_resources(kind="me", search="异常请求次数")["items"][0]
    assert metric["enabled"] is True
    assert metric["direction"] == "neutral"
    assert metric["importance"] == "normal"
    assert metric["metric_group"] == "未分组"
    assert metric["warning_threshold"] is None
    assert metric["critical_threshold"] is None
    assert metric["source"] == "discovered"
    assert metric["origin_task_id"] == "task-defaults"
    assert metric["display_order"] == 1
    assert result["measurement_units"][0]["metrics"][0]["metric_resource_id"] == metric["resource_id"]

    inspect_measurement_files("task-defaults", files)
    from app.models.db import KpiMeasurementResource, session_factory

    with session_factory() as session:
        assert session.query(KpiMeasurementResource).filter(KpiMeasurementResource.kind == "me").count() == 1


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


def test_missing_confirmed_column_is_ignored(tmp_path: Path) -> None:
    _prepare_resources()
    good = tmp_path / "ne333_Call_Statistics_15_1_202609020000.csv"
    good.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="utf-8")
    files = [("ne333_Call_Statistics_15_1_202609020000.csv", good)]
    discover_measurement_bindings("task-1", files)
    missing = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    missing.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),其他列\npod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    files.append(("ne333_Call_Statistics_15_0_202609020000.csv", missing))
    result = inspect_measurement_files("task-1", files)
    unit = result["measurement_units"][0]
    assert unit["status"] == "pass"
    assert unit["metric_coverage"] == "2/2"
    call_metric = next(item for item in unit["metrics"] if item["raw_source_name"] == "呼叫请求次数(次)")
    assert call_metric["source_files"] == [good.name]
    assert call_metric["observations"][0]["avg_value"] == 1.0


def test_duplicate_column_diagnostic_is_isolated(tmp_path: Path) -> None:
    _prepare_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次),呼叫请求次数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1,2\n",
        encoding="utf-8",
    )
    files = [(path.name, path)]
    result = inspect_measurement_files("task-duplicate", files)
    file_result = next(item for item in result["files"] if item["source_file"] == path.name)
    assert file_result["status"] == "matched"
    assert file_result["duplicate_columns"] == ["呼叫请求次数(次)"]
    assert len(result["measurement_units"][0]["metrics"]) == 1


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
    result = inspect_measurement_files("task-1", files)
    assert set(result["measurement_units"][0]["objects"]) == {"__all__"}


def test_gbk_measurement_csv_is_supported(tmp_path: Path) -> None:
    _prepare_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="gb18030")
    files = [(path.name, path)]
    discover_measurement_bindings("task-gbk", files)

    result = inspect_measurement_files("task-gbk", files)
    assert result["measurement_units"][0]["status"] == "pass"


def test_threshold_status_and_risk_summary(tmp_path: Path) -> None:
    _prepare_resources()
    update_manual_metric("ME_CALL", direction="higher_better", warning_threshold=80, critical_threshold=50)
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        HEADER
        + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,60\n"
        + "pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,30\n",
        encoding="utf-8",
    )
    result = inspect_measurement_files("task-threshold", [(path.name, path)])
    metric = result["measurement_units"][0]["metrics"][0]
    statuses = {item["object_key"]: item["business_status"] for item in metric["observations"]}
    assert statuses == {"pod-a": "warn", "pod-b": "fail"}
    assert metric["business_status"] == "fail"
    unit = result["measurement_units"][0]
    assert unit["status"] == "fail"
    assert unit["risk_summary"]["business_fail_count"] == 1
    assert unit["risk_summary"]["health_score"] == 75
    overview = result["kpi_overview"]
    assert overview["business_fail_count"] == 1
    assert overview["health_score"] == 75


def test_trend_labels_are_isolated_by_object_and_period(tmp_path: Path) -> None:
    _prepare_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        HEADER
        + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n"
        + "pod-a,2026-09-02 00:15:00,2026-09-02 00:30:00,15,1.2\n"
        + "pod-a,2026-09-02 00:30:00,2026-09-02 00:45:00,15,1.4\n"
        + "pod-b,2026-09-02 00:00:00,2026-09-02 00:15:00,30,3\n"
        + "pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,30,2.6\n",
        encoding="utf-8",
    )
    result = inspect_measurement_files("task-trend", [(path.name, path)])
    metric = result["measurement_units"][0]["metrics"][0]
    trends = {(item["object_key"], item["period_minutes"]): item for item in metric["trends"]}
    assert trends[("pod-a", 15)]["label"] == "rising"
    assert trends[("pod-b", 30)]["label"] == "falling"
    # 趋势明细只保留主趋势一份，避免 570 指标场景被趋势数组重复放大。
    assert all("points" not in trend for trend in metric["trends"])
    assert trends[("pod-a", 15)]["point_count"] == 3
    assert trends[("pod-b", 30)]["point_count"] == 2
    assert len(metric["trend_points"]) == 3
    assert result["measurement_units"][0]["risk_summary"]["trend_worsened_count"] == 0


def test_primary_trend_points_are_sampled_for_storage(tmp_path: Path) -> None:
    """主趋势只保留图表采样点，避免 570 指标规则结果继续膨胀。"""
    _prepare_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    rows = "".join(
        f"pod-a,2026-09-02 {minute // 60:02d}:{minute % 60:02d}:00,"
        f"2026-09-02 {(minute + 1) // 60:02d}:{(minute + 1) % 60:02d}:00,15,{minute}\n"
        for minute in range(220)
    )
    path.write_text(HEADER + rows, encoding="utf-8")

    result = inspect_measurement_files("task-trend-sample", [(path.name, path)])
    metric = result["measurement_units"][0]["metrics"][0]

    assert metric["trends"][0]["point_count"] == 220
    assert len(metric["trend_points"]) == 200
    assert metric["trend_points"][0]["value"] == 0
    assert metric["trend_points"][-1]["value"] == 219
