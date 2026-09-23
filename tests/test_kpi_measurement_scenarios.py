"""测量单元管理的关键场景与回归用例。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db import AuthSession
from app.services.auth import get_current_user
from app.services.kpi_measurement_units import (
    KpiMeasurementError,
    create_measurement_derived,
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    list_measurement_bindings,
    list_measurement_units,
    set_measurement_binding_status,
)
from tests.baseline_helpers import load_rule, setup_env

HEADER = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"
RESOURCE_CSV = (
    "资源id,中文描述,英文描述\n"
    "MU_CALL,呼叫统计,Call Statistics\n"
    "ME_CALL,呼叫请求次数,Call Requests\n"
    "ME_RATE,呼叫成功率,Call Success Rate\n"
)


def _import_resources() -> None:
    import_resource_csv(io.StringIO(RESOURCE_CSV))


def _confirm(call_binding: bool = True) -> None:
    for binding in list_measurement_bindings()["items"]:
        if call_binding or binding["metric_resource_id"]:
            set_measurement_binding_status(binding["id"], "confirmed")


def test_resource_import_rejects_invalid_header() -> None:
    with pytest.raises(KpiMeasurementError) as exc_info:
        import_resource_csv(io.StringIO("id,name\nMU_CALL,呼叫统计\n"))
    assert exc_info.value.code == "kpi_resource_csv_invalid"


def test_binding_conflict_when_same_metric_belongs_to_other_unit(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "MU_API,接口统计,Api Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
        )
    )
    call_path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    call_path.write_text(HEADER, encoding="utf-8")
    discover_measurement_bindings("task-call", [("ne333_Call_Statistics_15_0_202609020000.csv", call_path)])
    binding_id = next(item["id"] for item in list_measurement_bindings()["items"] if item["metric_resource_id"])
    set_measurement_binding_status(binding_id, "confirmed")

    api_path = tmp_path / "ne333_Api_Statistics_15_0_202609020000.csv"
    api_path.write_text(HEADER, encoding="utf-8")
    result = discover_measurement_bindings("task-api", [("ne333_Api_Statistics_15_0_202609020000.csv", api_path)])
    assert result["files"][0]["status"] == "matched"
    assert list_measurement_bindings(measurement_unit_id="MU_API")["items"][0]["status"] == "conflict"

    with pytest.raises(KpiMeasurementError) as exc_info:
        conflict_id = list_measurement_bindings(measurement_unit_id="MU_API")["items"][0]["id"]
        set_measurement_binding_status(conflict_id, "confirmed")
    assert exc_info.value.code == "kpi_binding_conflict"


def test_multiple_period_files_aggregate_to_one_measurement_unit(tmp_path: Path) -> None:
    _import_resources()
    files: list[tuple[str, Path]] = []
    for index in range(2):
        path = tmp_path / f"ne333_Call_Statistics_15_{index}_202609020000.csv"
        body = f"pod-a,2026-09-02 00:{index * 15:02d}:00,2026-09-02 00:{index * 15 + 15:02d}:00,15,{index + 1}\n"
        path.write_text(HEADER + body, encoding="utf-8")
        files.append((f"ne333_Call_Statistics_15_{index}_202609020000.csv", path))
    discover_measurement_bindings("task-1", files)
    _confirm()
    result = inspect_measurement_files("task-1", files)
    unit = result["measurement_units"][0]
    assert unit["file_count"] == 2
    assert unit["objects"]["pod-a"]["row_count"] == 2
    assert unit["objects"]["pod-a"]["min_value"] == 1
    assert unit["objects"]["pod-a"]["max_value"] == 2


def test_invalid_and_valid_files_are_isolated(tmp_path: Path) -> None:
    _import_resources()
    invalid = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    invalid.write_text("not,a,kpi/header\n1,2,3\n", encoding="utf-8")
    valid = tmp_path / "ne333_Call_Statistics_15_1_202609020000.csv"
    valid.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="utf-8")
    files = [
        ("ne333_Call_Statistics_15_0_202609020000.csv", invalid),
        ("ne333_Call_Statistics_15_1_202609020000.csv", valid),
    ]
    discover_measurement_bindings("task-1", files)
    _confirm()
    result = inspect_measurement_files("task-1", files)
    by_name = {item["filename"]: item for item in result["files"]}
    assert by_name["ne333_Call_Statistics_15_0_202609020000.csv"]["status"] == "parse_error"
    unit = next(unit for unit in result["measurement_units"])
    assert unit["status"] == "error"
    assert unit["file_count"] == 2
    assert unit["metrics"][0]["read_status"] == "ok"


def test_derived_creation_requires_existing_metrics(tmp_path: Path) -> None:
    _import_resources()
    header = HEADER
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(header + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="utf-8")
    with pytest.raises(KpiMeasurementError) as unconfirmed_error:
        create_measurement_derived("MU_CALL", "ME_RATE", "ME_CALL", "ME_CALL")
    assert unconfirmed_error.value.status_code == 409

    discover_measurement_bindings("task-derived", [(path.name, path)])
    _confirm()
    create_measurement_derived("MU_CALL", "ME_RATE", "ME_CALL", "ME_CALL")
    with pytest.raises(KpiMeasurementError) as exc_info:
        create_measurement_derived("MU_MISSING", "ME_RATE", "ME_CALL", "ME_CALL")
    assert exc_info.value.status_code == 404


def test_all_zero_periods_are_pass_with_business_not_triggered(tmp_path: Path) -> None:
    _import_resources()
    files: list[tuple[str, Path]] = []
    for index in range(2):
        path = tmp_path / f"ne333_Call_Statistics_15_{index}_202609020000.csv"
        path.write_text(
            HEADER + f"pod-a,2026-09-02 00:{index * 15:02d}:00,2026-09-02 00:{index * 15 + 15:02d}:00,15,0\n",
            encoding="utf-8",
        )
        files.append((path.name, path))
    discover_measurement_bindings("task-zero", files)
    _confirm()
    result = inspect_measurement_files("task-zero", files)
    unit = result["measurement_units"][0]
    assert unit["status"] == "pass"
    assert unit["metrics"][0]["value_pattern"] == "all_zero"
    assert unit["objects"]["pod-a"]["zero_count"] == 2


def test_missing_metric_in_one_period_is_ignored_without_losing_readings(tmp_path: Path) -> None:
    _import_resources()
    first = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    second = tmp_path / "ne333_Call_Statistics_15_1_202609020000.csv"
    first.write_text(
        HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,3\n",
        encoding="utf-8",
    )
    second.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟)\npod-a,2026-09-02 00:15:00,2026-09-02 00:30:00,15\n",
        encoding="utf-8",
    )
    files = [(first.name, first), (second.name, second)]
    discover_measurement_bindings("task-missing", files)
    _confirm()
    result = inspect_measurement_files("task-missing", files)
    unit = result["measurement_units"][0]
    assert unit["status"] == "pass"
    assert unit["metrics"][0]["read_status"] == "ok"
    assert unit["metrics"][0]["observations"][0]["avg_value"] == 3.0
    assert unit["metrics"][0]["source_files"] == [first.name]


def test_measurement_rule_end_to_end_with_task_and_single_rerun(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _import_resources()
    package = tmp_path / "measurement-e2e.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "kpi/ne333_Call_Statistics_15_0_202609020000.csv",
            HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        )
    from app.cli import run_single_rule, run_task

    task_id = run_task(package).task_id
    first = load_rule(env, task_id, "kpi.measurement_units")
    assert first["status"] == "pass"
    assert first["metadata"]["measurement_units"][0]["objects"]["pod-a"]["avg_value"] == 100.0

    run_single_rule("kpi.measurement_units", package=package, task_id=task_id)
    second = load_rule(env, task_id, "kpi.measurement_units")
    assert second["status"] == "pass"
    assert [(metric["key"], metric["value"]) for metric in second["metrics"]] == [
        ("matched_files", 1),
        ("unmatched_files", 0),
        ("skipped_files", 0),
        ("measurement_units", 1),
    ]
    assert second["metadata"]["measurement_units"][0]["objects"]["pod-a"]["avg_value"] == 100.0


def test_measurement_mutation_api_requires_admin_and_reports_errors() -> None:
    client = TestClient(app)
    with client:
        assert (
            client.post(
                "/api/v5/kpi/measurement-units/import",
                files={"file": ("bad.csv", io.BytesIO(b"bad,header\n"), "text/csv")},
            ).status_code
            == 400
        )

        assert client.patch("/api/v5/kpi/measurement-units/MU_MISSING", json={"enabled": False}).status_code == 404

        app.dependency_overrides[get_current_user] = lambda: AuthSession(
            token="viewer-token", username="viewer", role="viewer"
        )
        response = client.patch("/api/v5/kpi/measurement-units/MU_CALL", json={"enabled": False})
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"


def test_resource_import_updates_measurement_unit_filename_fragment() -> None:
    import_resource_csv(io.StringIO(RESOURCE_CSV))
    result = import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call New Statistics\n"))
    assert result["updated"] == {"mu": 1, "me": 0, "unit": 0}
    assert list_measurement_units()["items"][0]["filename_fragment"] == "Call_New_Statistics"


def test_disabled_confirmed_binding_is_not_inspected(tmp_path: Path) -> None:
    _import_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="utf-8")
    discover_measurement_bindings("task-disabled", [(path.name, path)])
    binding_id = next(item["id"] for item in list_measurement_bindings()["items"] if item["metric_resource_id"])
    set_measurement_binding_status(binding_id, "confirmed")
    set_measurement_binding_status(binding_id, "confirmed", enabled=False)

    result = inspect_measurement_files("task-disabled", [(path.name, path)])
    assert result["measurement_units"][0]["status"] == "skip"
    assert result["measurement_units"][0]["reason"] == "未配置已确认指标绑定"


def test_row_value_quality_details_are_preserved(tmp_path: Path) -> None:
    _import_resources()
    first = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    first.write_text(
        HEADER
        + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n"
        + "pod-a,2026-09-02 00:15:00,2026-09-02 00:30:00,15,\n",
        encoding="utf-8",
    )
    second = tmp_path / "ne333_Call_Statistics_15_1_202609020000.csv"
    second.write_text(
        HEADER + "pod-a,2026-09-02 00:30:00,2026-09-02 00:45:00,15,bad\n",
        encoding="utf-8",
    )
    files = [(first.name, first), (second.name, second)]
    discover_measurement_bindings("task-quality", files)
    _confirm()

    result = inspect_measurement_files("task-quality", files)
    metric = result["measurement_units"][0]["metrics"][0]
    observation = metric["observations"][0]
    assert result["measurement_units"][0]["status"] == "fail"
    assert metric["read_status"] == "parse_error"
    assert metric["value_pattern"] == "normal"
    assert observation["row_count"] == 3
    assert observation["valid_count"] == 1
    assert observation["null_count"] == 1
    assert observation["parse_error_count"] == 1
    assert observation["min_value"] == 1
    assert observation["max_value"] == 1
    assert observation["avg_value"] == 1
    assert [(row["value"], row["line_number"]) for row in observation["source_rows"]] == [("", 3), ("bad", 2)]


def test_derived_success_rate_aggregates_objects_and_zero_denominator(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
            "ME_TOTAL,请求总数,Call Total Requests\n"
            "ME_RATE,呼叫成功率,Call Success Rate\n"
        )
    )
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次),请求总数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,80,100\n"
        "pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,0,0\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-rate", [(path.name, path)])
    _confirm()
    create_measurement_derived("MU_CALL", "ME_RATE", "ME_CALL", "ME_TOTAL")

    result = inspect_measurement_files("task-rate", [(path.name, path)])
    derived = result["measurement_units"][0]["derived_metrics"][0]
    assert derived["status"] == "pass"
    assert [(item["object_key"], item["value"], item["message"]) for item in derived["observations"]] == [
        ("pod-a", 80.0, None),
        ("pod-b", None, "疑似业务未触发"),
    ]


def test_derived_reverse_success_rate_complements_success_rate(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
            "ME_TOTAL,请求总数,Call Total Requests\n"
            "ME_REVERSE,反向成功率,Reverse Success Rate\n"
        )
    )
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次),请求总数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,80,100\n"
        "pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,0,0\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-reverse-rate", [(path.name, path)])
    _confirm()
    create_measurement_derived(
        "MU_CALL",
        "ME_REVERSE",
        "ME_CALL",
        "ME_TOTAL",
        template="reverse_success_rate",
    )

    result = inspect_measurement_files("task-reverse-rate", [(path.name, path)])
    derived = result["measurement_units"][0]["derived_metrics"][0]
    assert derived["metric_resource_name_zh"] == "反向成功率"
    assert result["measurement_units"][0]["metrics"][0]["metric_resource_name_zh"] == "呼叫请求次数"
    assert derived["template"] == "reverse_success_rate"
    assert derived["status"] == "pass"
    assert [(item["object_key"], item["value"], item["message"]) for item in derived["observations"]] == [
        ("pod-a", 20.0, None),
        ("pod-b", None, "疑似业务未触发"),
    ]


def test_derived_success_rate_fails_when_one_object_dependency_is_missing(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
            "ME_TOTAL,请求总数,Call Total Requests\n"
            "ME_RATE,呼叫成功率,Call Success Rate\n"
        )
    )
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次),请求总数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,80,\n"
        "pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,,100\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-rate-missing", [(path.name, path)])
    _confirm()
    create_measurement_derived("MU_CALL", "ME_RATE", "ME_CALL", "ME_TOTAL")

    result = inspect_measurement_files("task-rate-missing", [(path.name, path)])
    unit = result["measurement_units"][0]
    assert unit["status"] == "fail"
    assert unit["reason"] == "派生指标依赖缺失或不可读"
    assert all(item["status"] == "fail" for item in unit["derived_metrics"][0]["observations"])


def test_ignored_bindings_do_not_block_new_unit_candidate(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "MU_API,接口统计,Api Statistics\n"
            "MU_EXTRA,扩展统计,Extra Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
        )
    )
    call_path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    call_path.write_text(HEADER, encoding="utf-8")
    discover_measurement_bindings("task-call", [(call_path.name, call_path)])
    call_binding = list_measurement_bindings(measurement_unit_id="MU_CALL")["items"][0]
    set_measurement_binding_status(call_binding["id"], "ignored")

    api_path = tmp_path / "ne333_Api_Statistics_15_0_202609020000.csv"
    api_path.write_text(HEADER, encoding="utf-8")
    discover_measurement_bindings("task-api", [(api_path.name, api_path)])
    api_binding = list_measurement_bindings(measurement_unit_id="MU_API")["items"][0]
    set_measurement_binding_status(api_binding["id"], "ignored")

    extra_path = tmp_path / "ne333_Extra_Statistics_15_0_202609020000.csv"
    extra_path.write_text(HEADER, encoding="utf-8")
    discover_measurement_bindings("task-extra", [(extra_path.name, extra_path)])
    assert list_measurement_bindings(measurement_unit_id="MU_EXTRA")["items"][0]["status"] == "confirmed"


def test_multiple_units_are_inspected_independently(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "MU_API,接口统计,Api Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
            "ME_API,接口请求次数,Api Requests\n"
        )
    )
    call_path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    call_path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    api_path = tmp_path / "ne333_Api_Statistics_15_0_202609020000.csv"
    api_path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),接口请求次数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,2\n",
        encoding="utf-8",
    )
    files = [(call_path.name, call_path), (api_path.name, api_path)]
    discover_measurement_bindings("task-mixed", files)

    result = inspect_measurement_files("task-mixed", files)
    by_unit = {item["measurement_unit_id"]: item for item in result["measurement_units"]}
    assert by_unit["MU_CALL"]["status"] == "pass"
    assert by_unit["MU_API"]["status"] == "pass"


def test_header_beyond_read_window_marks_unit_error(tmp_path: Path) -> None:
    _import_resources()
    good_path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    good_path.write_text(HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n", encoding="utf-8")
    discover_measurement_bindings("task-header", [(good_path.name, good_path)])
    _confirm()

    bad_path = tmp_path / "ne333_Call_Statistics_15_1_202609020000.csv"
    bad_path.write_text("\n" * 30 + HEADER + "pod-a,2026-09-02 00:15:00,2026-09-02 00:30:00,15,2\n", encoding="utf-8")
    files = [(good_path.name, good_path), (bad_path.name, bad_path)]
    result = inspect_measurement_files("task-header", files)
    bad_file = next(item for item in result["files"] if item["filename"] == bad_path.name)
    assert bad_file["status"] == "parse_error"
    assert bad_file["reason"] == "header_not_found"
    assert result["measurement_units"][0]["status"] == "error"
    assert result["measurement_units"][0]["reason"] == "表头未找到"


def test_period_files_prefer_15_then_5_per_measurement_unit(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
            "MU_API,接口统计,Api Statistics\n"
            "ME_API,接口请求次数,Api Requests\n"
        )
    )
    call_15 = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    call_5 = tmp_path / "ne333_Call_Statistics_5_0_202609020000.csv"
    api_5 = tmp_path / "ne333_Api_Statistics_5_0_202609020000.csv"
    call_header = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数\n"
    api_header = "container,测量开始时间,测量结束时间,周期(分钟),接口请求次数\n"
    call_15.write_text(
        call_header + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,3\n",
        encoding="utf-8",
    )
    call_5.write_text(
        call_header + "pod-b,2026-09-02 00:00:00,2026-09-02 00:05:00,5,99\n",
        encoding="utf-8",
    )
    api_5.write_text(
        api_header + "pod-a,2026-09-02 00:00:00,2026-09-02 00:05:00,5,7\n",
        encoding="utf-8",
    )
    files = [(path.name, path) for path in (call_15, call_5, api_5)]

    result = inspect_measurement_files("task-period-priority", files)

    by_name = {item["filename"]: item for item in result["files"]}
    assert by_name[call_15.name]["status"] == "matched"
    assert by_name[call_5.name]["status"] == "skipped"
    assert by_name[call_5.name]["reason"] == "period_not_preferred"
    assert by_name[api_5.name]["status"] == "matched"

    assert [item["filename"] for item in result["unmatched_files"]] == []
    assert [item["filename"] for item in result["skipped_files"]] == [call_5.name]

    by_unit = {item["measurement_unit_id"]: item for item in result["measurement_units"]}
    assert by_unit["MU_CALL"]["source_files"] == [call_15.name]
    observations = {item["object_key"]: item for item in by_unit["MU_CALL"]["metrics"][0]["observations"]}
    assert set(observations) == {"pod-a"}
    assert observations["pod-a"]["avg_value"] == 3.0
    assert by_unit["MU_CALL"]["metrics"][0]["source_files"] == [call_15.name]
    assert by_unit["MU_API"]["source_files"] == [api_5.name]
    assert by_unit["MU_API"]["metrics"][0]["observations"][0]["avg_value"] == 7.0


def test_other_periods_are_kept_without_preferred_periods(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )
    header = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数\n"
    period_30 = tmp_path / "ne333_Call_Statistics_30_0_202609020000.csv"
    period_60 = tmp_path / "ne333_Call_Statistics_60_0_202609020000.csv"
    period_30.write_text(
        header + "pod-a,2026-09-02 00:00:00,2026-09-02 00:30:00,30,3\n",
        encoding="utf-8",
    )
    period_60.write_text(
        header + "pod-b,2026-09-02 01:00:00,2026-09-02 02:00:00,60,5\n",
        encoding="utf-8",
    )
    files = [(path.name, path) for path in (period_30, period_60)]

    result = inspect_measurement_files("task-other-periods", files)

    by_name = {item["filename"]: item for item in result["files"]}
    assert by_name[period_30.name]["status"] == "matched"
    assert by_name[period_60.name]["status"] == "matched"
    assert result["measurement_units"][0]["source_files"] == [period_30.name, period_60.name]
    assert {item["object_key"] for item in result["measurement_units"][0]["metrics"][0]["observations"]} == {
        "pod-a",
        "pod-b",
    }
