"""测量单元指标绑定发现与确认测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.db import init_db
from app.services.kpi_measurement_units import (
    KpiMeasurementError,
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    io,
    list_measurement_bindings,
    set_measurement_binding_status,
)

CSV_TEXT = """container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)
pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100
pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,0
"""


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


@pytest.fixture
def call_file(tmp_path: Path) -> tuple[str, Path]:
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return "ne333_Call_Statistics_15_0_202609020000.csv", path


def _import_call_resources() -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU__CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )


def test_discover_binding_strips_display_unit(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    result = discover_measurement_bindings("task-1", [call_file])
    assert result["files"][0]["binding_candidates"] == 1
    bindings = list_measurement_bindings()["items"]
    assert bindings[0]["status"] == "candidate"
    assert bindings[0]["raw_source_name"] == "呼叫请求次数(次)"
    assert bindings[0]["base_source_name"] == "呼叫请求次数"
    assert bindings[0]["display_unit"] == "次"
    assert bindings[0]["metric_resource_id"] == "ME_CALL"
    assert bindings[0]["measurement_unit_id"] == "MU__CALL"


def test_unconfirmed_binding_is_not_inspected(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    discover_measurement_bindings("task-1", [call_file])
    result = inspect_measurement_files("task-1", [call_file])
    assert result["measurement_units"][0]["status"] == "skip"
    assert "未配置已确认指标绑定" in result["measurement_units"][0]["reason"]


def test_confirm_binding_enables_inspection(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    discover_measurement_bindings("task-1", [call_file])
    binding_id = list_measurement_bindings()["items"][0]["id"]
    set_measurement_binding_status(binding_id, "confirmed")
    result = inspect_measurement_files("task-1", [call_file])
    assert result["measurement_units"][0]["status"] == "pass"
    assert result["measurement_units"][0]["metric_coverage"] == "1/1"


def test_conflicting_metric_binding_is_not_auto_rebound(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    discover_measurement_bindings("task-1", [call_file])
    first_id = list_measurement_bindings()["items"][0]["id"]
    set_measurement_binding_status(first_id, "confirmed")
    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU__OTHER,其他统计,Other Statistics\n"))
    other_path = call_file[1].with_name("ne333_Other_Statistics_15_0_202609020000.csv")
    other_path.write_text(CSV_TEXT, encoding="utf-8")
    discover_measurement_bindings("task-2", [("ne333_Other_Statistics_15_0_202609020000.csv", other_path)])
    second = next(item for item in list_measurement_bindings()["items"] if item["measurement_unit_id"] == "MU__OTHER")
    assert second["status"] == "conflict"
    with pytest.raises(KpiMeasurementError):
        set_measurement_binding_status(second["id"], "confirmed")


def test_unknown_column_is_reported(tmp_path: Path) -> None:
    _import_call_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),未注册指标(个)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    result = discover_measurement_bindings("task-1", [("ne333_Call_Statistics_15_0_202609020000.csv", path)])
    assert result["files"][0]["unknown_columns"] == ["未注册指标(个)"]
    assert list_measurement_bindings()["items"][0]["metric_resource_id"] is None
