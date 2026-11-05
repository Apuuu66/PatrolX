"""测量单元管理的关键场景与回归用例。"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db import (
    AuthSession,
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    KpiMetricMaintenanceConfig,
    TaskRecord,
    session_factory,
)
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


def _seed_daily_health_catalog(
    *,
    disabled_unit: bool = False,
    internal_rate_dependencies: bool = False,
) -> None:
    now = datetime(2026, 10, 31, 16, 0, tzinfo=UTC)
    numerator_id = "ME_SUCCESS_COUNT_NUMERATOR" if internal_rate_dependencies else "ME_SUCCESS_COUNT"
    denominator_id = "ME_TOTAL_COUNT_DENOMINATOR" if internal_rate_dependencies else "ME_TOTAL_COUNT"
    numerator_name = "成功请求次数分子" if internal_rate_dependencies else "成功请求次数"
    denominator_name = "请求总次数分母" if internal_rate_dependencies else "请求总次数"
    with session_factory() as session:
        session.add_all(
            [
                KpiMeasurementResource(
                    resource_id="MU_DAILY",
                    kind="mu",
                    name_zh="日健康测量单元",
                    name_en="Daily Health",
                    filename_fragment="Daily_Health",
                    enabled=not disabled_unit,
                    display_order=1,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id=numerator_id,
                    kind="me",
                    name_zh=numerator_name,
                    name_en="Success Requests",
                    enabled=True,
                    display_order=2,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id=denominator_id,
                    kind="me",
                    name_zh=denominator_name,
                    name_en="Total Requests",
                    enabled=True,
                    display_order=3,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id="ME_SUCCESS_RATE",
                    kind="me",
                    name_zh="请求成功率",
                    name_en="Requests Success Rate",
                    enabled=True,
                    display_order=4,
                    importance="P1",
                    direction="higher_better",
                    warning_threshold=90.0,
                    critical_threshold=80.0,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id="ME_NO_DATA",
                    kind="me",
                    name_zh="无导出指标",
                    name_en="No Export Metric",
                    enabled=True,
                    display_order=5,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.flush()
        for metric_id, raw_name in (
            (numerator_id, numerator_name),
            (denominator_id, denominator_name),
            ("ME_NO_DATA", "无导出指标"),
        ):
            session.add(
                KpiMeasurementBinding(
                    metric_resource_id=metric_id,
                    measurement_unit_id="MU_DAILY",
                    raw_source_name=raw_name,
                    base_source_name=raw_name,
                    status="confirmed",
                    enabled=True,
                    task_id="task-daily-health",
                    source_file="Daily_Health.csv",
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(
            KpiMeasurementDerived(
                measurement_unit_id="MU_DAILY",
                metric_resource_id="ME_SUCCESS_RATE",
                numerator_metric_id=numerator_id,
                denominator_metric_id=denominator_id,
                template="success_rate",
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            KpiMetricMaintenanceConfig(
                measurement_unit_id="MU_DAILY",
                metric_resource_id="ME_SUCCESS_RATE",
                role="derived",
                daily_aggregation="latest",
                daily_change_threshold=0.2,
                daily_change_threshold_unit="pp",
                is_percentage=True,
                zero_semantics="unknown",
                consistency_tolerance=0.2,
                object_match_mode="exact",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _daily_health_rate_csv(
    tmp_path: Path,
    *,
    numerator_name: str = "成功请求次数",
    denominator_name: str = "请求总次数",
) -> tuple[str, Path]:
    path = tmp_path / "ne333_Daily_Health_15_0_20261101000000.csv"
    path.write_text(
        f"container,测量开始时间,测量结束时间,周期(分钟),{numerator_name},{denominator_name}\n"
        "pod-a,2026-10-31 23:00:00,2026-10-31 23:15:00,15,99,100\n"
        "pod-a,2026-11-01 00:00:00,2026-11-01 00:15:00,15,1,100\n"
        "pod-a,2026-11-01 00:15:00,2026-11-01 00:30:00,15,90,100\n",
        encoding="utf-8",
    )
    return path.name, path


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
    performance_archive = io.BytesIO()
    with zipfile.ZipFile(performance_archive, "w") as archive:
        archive.writestr(
            "ne333_Call_Statistics_15_0_202609020000.csv",
            HEADER + "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        )
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "UMF Problem Scene/Basic Information About the UMF/version.ini",
            "[version]\nproduct=UMF\n",
        )
        archive.writestr(
            "UMF Problem Scene/Performance Measurement Results/PerfResult_20260902.zip",
            performance_archive.getvalue(),
        )
    from app.cli import run_single_rule, run_task

    task_id = run_task(package, customer={"product": "UMF"}).task_id
    first = load_rule(env, task_id, "kpi.measurement_units")
    assert first["status"] == "pass"
    assert first["metadata"]["measurement_units"][0]["objects"]["pod-a"]["avg_value"] == 100.0
    assert first["metadata"]["daily_health"]["schema_version"] == 1
    assert first["metadata"]["daily_health"]["metrics"][0]["metric_resource_id"] == "ME_CALL"

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
    assert result["measurement_units"][0]["reason"] == "未配置已确认且启用的指标绑定"


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


def test_inspection_emits_daily_health_with_official_success_rate_aggregation(tmp_path: Path) -> None:
    _seed_daily_health_catalog()
    files = [_daily_health_rate_csv(tmp_path)]

    result = inspect_measurement_files("task-daily-health", files)

    daily_health = result["daily_health"]
    assert daily_health["schema_version"] == 1
    assert daily_health["timezone"] == "Asia/Shanghai"
    assert daily_health["data_date"] == "2026-11-01"
    assert daily_health["previous_date"] == "2026-10-31"
    assert daily_health["scope"] == {
        "enabled_measurement_unit_count": 1,
        "confirmed_binding_metric_count": 3,
        "expected_metric_count": 4,
        "out_of_scope_file_count": 0,
        "unconfirmed_binding_count": 0,
        "out_of_scope_reason_counts": {},
    }
    assert daily_health["current_counts"] == {
        "fail": 1,
        "warn": 0,
        "unable_to_judge": 1,
        "pending_config": 2,
        "not_applicable": 0,
        "normal": 0,
    }
    assert daily_health["trend_counts"] == {
        "worsened": 1,
        "improved": 0,
        "observe": 0,
        "no_baseline": 3,
        "stable": 0,
    }
    assert len(daily_health["metrics"]) == daily_health["scope"]["expected_metric_count"]

    by_metric = {item["metric_resource_id"]: item for item in daily_health["metrics"]}
    rate = by_metric["ME_SUCCESS_RATE"]
    assert rate["measurement_unit_name_zh"] == "日健康测量单元"
    assert rate["metric_resource_name_zh"] == "请求成功率"
    assert rate["role"] == "derived"
    assert rate["importance"] == "P1"
    assert rate["current_status"] == "fail"
    assert rate["current_reason"] == "critical_threshold"
    assert rate["today_value"] == 45.5
    assert rate["today_display"] == "45.5%"
    assert rate["yesterday_value"] == 99.0
    assert rate["delta"] == -53.5
    assert rate["trend_status"] == "worsened"
    assert rate["daily_aggregation"] == "formula"
    assert rate["aggregation_source"] == "custom"
    assert rate["objects"][0]["numerator"] == 91.0
    assert rate["objects"][0]["denominator"] == 200.0
    assert rate["objects"][0]["valid_count"] == 2

    no_data = by_metric["ME_NO_DATA"]
    assert no_data["current_status"] == "unable_to_judge"
    assert no_data["current_reason"] == "no_current_data"
    assert no_data["trend_status"] == "no_baseline"


def test_internal_rate_dependencies_are_evidence_not_daily_health_metrics(tmp_path: Path) -> None:
    _seed_daily_health_catalog(internal_rate_dependencies=True)
    files = [
        _daily_health_rate_csv(
            tmp_path,
            numerator_name="成功请求次数分子",
            denominator_name="请求总次数分母",
        )
    ]

    result = inspect_measurement_files("task-daily-health", files)

    daily_health = result["daily_health"]
    assert daily_health["scope"]["expected_metric_count"] == 2
    assert {metric["metric_resource_id"] for metric in daily_health["metrics"]} == {
        "ME_SUCCESS_RATE",
        "ME_NO_DATA",
    }
    rate = next(metric for metric in daily_health["metrics"] if metric["metric_resource_id"] == "ME_SUCCESS_RATE")
    assert rate["today_value"] == 45.5
    assert rate["yesterday_value"] == 99.0


def test_derived_validation_uses_each_measurement_units_own_dependencies(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_ALPHA,Alpha 统计,Alpha Stats\n"
            "ME_ALPHA_NUM,Alpha 分子,Alpha Numerator\n"
            "ME_ALPHA_DEN,Alpha 分母,Alpha Denominator\n"
            "ME_ALPHA_RATE,Alpha 成功率,Alpha Success Rate\n"
            "MU_BETA,Beta 统计,Beta Stats\n"
            "ME_BETA_NUM,Beta 分子,Beta Numerator\n"
            "ME_BETA_DEN,Beta 分母,Beta Denominator\n"
            "ME_BETA_RATE,Beta 成功率,Beta Success Rate\n"
        )
    )
    files: list[tuple[str, Path]] = []
    for _unit_id, fragment, num_name, den_name in (
        ("alpha", "Alpha_Stats", "Alpha 分子", "Alpha 分母"),
        ("beta", "Beta_Stats", "Beta 分子", "Beta 分母"),
    ):
        path = tmp_path / f"ne333_{fragment}_15_0_20261101000000.csv"
        path.write_text(
            f"container,测量开始时间,测量结束时间,周期(分钟),{num_name},{den_name}\n"
            "pod-a,2026-11-01 00:00:00,2026-11-01 00:15:00,15,9,10\n",
            encoding="utf-8",
        )
        files.append((path.name, path))
    discover_measurement_bindings("task-derived-unit-scope", files)
    _confirm()
    create_measurement_derived("MU_ALPHA", "ME_ALPHA_RATE", "ME_ALPHA_NUM", "ME_ALPHA_DEN")
    create_measurement_derived("MU_BETA", "ME_BETA_RATE", "ME_BETA_NUM", "ME_BETA_DEN")

    result = inspect_measurement_files("task-derived-unit-scope", files)

    by_unit = {item["measurement_unit_id"]: item for item in result["measurement_units"]}
    assert [item["metric_resource_id"] for item in by_unit["MU_ALPHA"]["derived_metrics"]] == ["ME_ALPHA_RATE"]
    assert [item["metric_resource_id"] for item in by_unit["MU_BETA"]["derived_metrics"]] == ["ME_BETA_RATE"]
    assert all(item["status"] == "pass" for item in by_unit["MU_ALPHA"]["derived_metrics"])
    assert all(item["status"] == "pass" for item in by_unit["MU_BETA"]["derived_metrics"])
    assert by_unit["MU_ALPHA"]["status"] != "fail"
    assert by_unit["MU_BETA"]["status"] != "fail"


def test_inspection_daily_health_uses_utc_plus_8_calendar_boundary(tmp_path: Path) -> None:
    _seed_daily_health_catalog()
    path = tmp_path / "ne333_Daily_Health_15_1_20261101000000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),成功请求次数,请求总次数\n"
        "pod-a,2026-10-31 15:59:00+00:00,2026-10-31 16:00:00+00:00,15,9,10\n"
        "pod-a,2026-10-31 16:00:00+00:00,2026-10-31 16:15:00+00:00,15,1,10\n",
        encoding="utf-8",
    )

    result = inspect_measurement_files("task-daily-health", [(path.name, path)])

    daily_health = result["daily_health"]
    assert daily_health["data_date"] == "2026-11-01"
    rate = next(item for item in daily_health["metrics"] if item["metric_resource_id"] == "ME_SUCCESS_RATE")
    assert rate["today_value"] == 10.0
    assert rate["yesterday_value"] == 90.0


def test_disabled_unit_files_are_out_of_scope_not_unmatched(tmp_path: Path) -> None:
    _seed_daily_health_catalog(disabled_unit=True)
    files = [_daily_health_rate_csv(tmp_path)]

    result = inspect_measurement_files("task-disabled", files)

    assert result["files"][0]["status"] == "disabled"
    assert result["unmatched_files"] == []
    assert result["measurement_units"] == []
    scope = result["daily_health"]["scope"]
    assert scope["enabled_measurement_unit_count"] == 0
    assert scope["confirmed_binding_metric_count"] == 0
    assert scope["expected_metric_count"] == 0
    assert scope["out_of_scope_file_count"] == 1
    assert scope["out_of_scope_reason_counts"] == {"disabled_unit": 1}
    assert result["daily_health"]["metrics"] == []


def test_daily_health_falls_back_to_task_time_when_no_measurement_time_exists(tmp_path: Path) -> None:
    _seed_daily_health_catalog()
    with session_factory() as session:
        session.add(
            TaskRecord(
                task_id="task-no-time",
                name="无测量时间任务",
                mode="online",
                status="completed",
                trigger="upload",
                package_file="task.zip",
                customer={},
                stats={},
                created_at=datetime(2026, 10, 30, 16, 30, tzinfo=UTC),
                completed_at=None,
                last_run_at=None,
            )
        )
        session.commit()
    path = tmp_path / "ne333_Daily_Health_15_2_20261101000000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),成功请求次数,请求总次数\npod-a,,,,1,10\n",
        encoding="utf-8",
    )

    result = inspect_measurement_files("task-no-time", [(path.name, path)])

    daily_health = result["daily_health"]
    assert daily_health["data_date"] == "2026-10-31"
    assert daily_health["previous_date"] == "2026-10-30"
    assert daily_health["latest_measured_at"] is None
    assert len(daily_health["metrics"]) == 4
    assert all(item["current_status"] == "unable_to_judge" for item in daily_health["metrics"])
    assert all(item["trend_status"] == "no_baseline" for item in daily_health["metrics"])
