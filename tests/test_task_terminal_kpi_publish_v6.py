"""任务终态必须发布当前现场生成的 v6 KPI 工作台结果。"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.db import (
    KpiMeasurementBinding,
    KpiMeasurementResource,
    TaskKpiMetricResultV6,
    TaskKpiPoint,
    TaskKpiPointV6,
    session_factory,
)
from app.services import task_db
from tests.baseline_helpers import assign_rules_to_network_element
from tests.fixtures import make_real_package as fixture_module


def _seed_legacy_runtime_catalog(seed, now: datetime) -> None:
    """补齐当前巡检器仍读取的 v5 执行目录，日健康与终态发布继续使用 v6 配置。"""
    with zipfile.ZipFile(seed.package_path) as archive:
        manifest = json.loads(archive.read(fixture_module.KPI_V6_WORKBENCH_MANIFEST_PATH))
    metrics = manifest["metrics"]

    def base_source_name(raw_name: str) -> str:
        return raw_name.split("(", 1)[0].strip()

    with session_factory() as session:
        session.add(
            KpiMeasurementResource(
                resource_id=seed.measurement_unit_id,
                kind="mu",
                name_zh=seed.measurement_unit_id,
                name_en="Media and Data Channel Call Statistics",
                filename_fragment="Call_Media",
                enabled=True,
                display_order=0,
                source="preset",
                created_at=now,
                updated_at=now,
            )
        )
        for display_order, metric in enumerate(metrics, start=1):
            raw_source_names = [str(name) for name in metric["raw_source_names"]]
            metric_id = str(metric["metric_resource_id"])
            session.add(
                KpiMeasurementResource(
                    resource_id=metric_id,
                    kind="me",
                    name_zh=base_source_name(raw_source_names[0]),
                    name_en=raw_source_names[0],
                    enabled=True,
                    display_order=display_order,
                    metric_group=str(metric.get("metric_group") or ""),
                    direction=metric.get("direction"),
                    importance="P1" if bool(metric.get("team_focus")) else "normal",
                    warning_threshold=metric.get("warning_threshold"),
                    critical_threshold=metric.get("critical_threshold"),
                    source="preset",
                    created_at=now,
                    updated_at=now,
                )
            )
            for raw_source_name in raw_source_names:
                session.add(
                    KpiMeasurementBinding(
                        metric_resource_id=metric_id,
                        measurement_unit_id=seed.measurement_unit_id,
                        raw_source_name=raw_source_name,
                        base_source_name=base_source_name(raw_source_name),
                        display_unit="%" if bool(metric.get("is_percentage")) else "times",
                        status="confirmed",
                        enabled=True,
                        task_id=seed.task_id,
                        source_file=str(manifest["source_file"]),
                        created_at=now,
                        updated_at=now,
                    )
                )
        session.commit()


def _run_terminal_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seed,
    *,
    network_element_type: str = "UMF",
    task_id: str = "task-terminal-kpi-v6",
):
    from app.cli import run_task

    output = tmp_path / f"terminal-output-{task_id}"
    uploads = tmp_path / f"terminal-uploads-{task_id}"
    output.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(settings, "output_dir", output)
    monkeypatch.setattr(settings, "uploads_dir", uploads)
    monkeypatch.chdir(tmp_path)
    assign_rules_to_network_element(["kpi.measurement_units"], network_element_type)
    _seed_legacy_runtime_catalog(seed, datetime(2026, 11, 5, 8, tzinfo=UTC))
    task = run_task(
        seed.package_path,
        task_id=task_id,
        customer={"product": network_element_type},
    )
    return task, output


def test_completed_task_publishes_v6_results_from_current_scene(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    from app.cli import run_task

    output = tmp_path / "terminal-output"
    uploads = tmp_path / "terminal-uploads"
    output.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(settings, "output_dir", output)
    monkeypatch.setattr(settings, "uploads_dir", uploads)
    monkeypatch.chdir(tmp_path)
    assign_rules_to_network_element(["kpi.measurement_units"], "UMF")
    _seed_legacy_runtime_catalog(kpi_v6_seed.umf, datetime(2026, 11, 5, 8, tzinfo=UTC))

    task = run_task(
        kpi_v6_seed.umf.package_path,
        task_id="task-terminal-kpi-v6",
        customer={"product": "UMF"},
    )

    assert task.status.value == "completed"
    results = task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF")
    assert len(results) == 20
    success_rate = next(item for item in results if item["metric_resource_id"] == "ME_MEDIA_CREATION_SUCCESS_RATE")
    assert success_rate["today_value"] == 63.7
    assert success_rate["yesterday_value"] == 75.0
    assert success_rate["result_payload"]["metric_role"] == "base"
    assert success_rate["result_payload"]["formula"] is None
    assert "numerator" not in success_rate["result_payload"]
    assert "denominator" not in success_rate["result_payload"]
    assert "components" not in success_rate["result_payload"]


def test_terminal_v6_publish_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    from app.services.kpi_v6_terminal_publish import publish_kpi_v6_from_scene

    task, output = _run_terminal_task(tmp_path, monkeypatch, kpi_v6_seed.umf)
    before_results = task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF")
    before_points = task_db.list_kpi_points_v6(task.task_id, network_element_type="UMF")

    assert publish_kpi_v6_from_scene(task, output=output) == len(before_results)
    assert publish_kpi_v6_from_scene(task, output=output) == len(before_results)

    after_results = task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF")
    after_points = task_db.list_kpi_points_v6(task.task_id, network_element_type="UMF")
    assert len(after_results) == len(before_results)
    assert len(after_points) == len(before_points)
    assert [item["result_fingerprint"] for item in after_results] == [
        item["result_fingerprint"] for item in before_results
    ]
    assert [item["point_fingerprint"] for item in after_points] == [item["point_fingerprint"] for item in before_points]


def test_v5_mirror_failure_does_not_block_v6_terminal_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    def fail_mirror(*args, **kwargs):
        raise RuntimeError("v5 mirror unavailable")

    monkeypatch.setattr(task_db, "publish_kpi_from_scene", fail_mirror)
    task, _ = _run_terminal_task(tmp_path, monkeypatch, kpi_v6_seed.umf)

    assert task.status.value == "completed"
    assert len(task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF")) == 20


def test_v6_publish_failure_keeps_task_completed_and_still_runs_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    from app.services import retention

    publish_calls: list[tuple[object, ...]] = []

    def fail_v6(*args, **kwargs):
        publish_calls.append(args)
        raise RuntimeError("v6 publish unavailable")

    retention_calls: list[dict[str, object]] = []
    monkeypatch.setattr(task_db, "publish_kpi_v6_snapshot", fail_v6)
    monkeypatch.setattr(retention, "cleanup_safely", lambda **kwargs: retention_calls.append(kwargs))
    task, _ = _run_terminal_task(tmp_path, monkeypatch, kpi_v6_seed.umf)

    assert task.status.value == "completed"
    assert publish_calls
    assert retention_calls
    assert task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF") == []


def test_task_service_terminal_publishes_v6_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    from app.services.tasks import task_service

    task, _ = _run_terminal_task(tmp_path, monkeypatch, kpi_v6_seed.umf)
    with session_factory() as session:
        session.query(TaskKpiMetricResultV6).filter(TaskKpiMetricResultV6.task_id == task.task_id).delete()
        session.query(TaskKpiPointV6).filter(TaskKpiPointV6.task_id == task.task_id).delete()
        session.commit()
    assert task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF") == []

    task_service._publish_terminal(task)

    assert len(task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF")) == 20
    assert task_db.list_kpi_points_v6(task.task_id, network_element_type="UMF")


def test_terminal_publish_uses_current_scene_instead_of_stale_v5_mirror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    from app.services.kpi_v6_terminal_publish import publish_kpi_v6_from_scene

    task, output = _run_terminal_task(tmp_path, monkeypatch, kpi_v6_seed.umf)
    with session_factory() as session:
        session.query(TaskKpiPoint).filter(TaskKpiPoint.task_id == task.task_id).update({"value": 999.0})
        session.commit()

    publish_kpi_v6_from_scene(task, output=output)

    points = task_db.list_kpi_points_v6(
        task.task_id,
        network_element_type="UMF",
        metric_resource_id="ME_MEDIA_CREATION_SUCCESS_RATE",
    )
    assert [point["value"] for point in points] == [75.0, 63.7]


def test_missing_csp_success_rate_source_publishes_null_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    task, _ = _run_terminal_task(
        tmp_path,
        monkeypatch,
        kpi_v6_seed.csp,
        network_element_type="CSP",
        task_id="task-terminal-kpi-v6-csp",
    )

    results = task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="CSP")
    success_rate = next(item for item in results if item["metric_resource_id"] == "ME_MEDIA_CREATION_SUCCESS_RATE")
    assert success_rate["today_value"] is None
    assert success_rate["yesterday_value"] is None
    assert success_rate["result_payload"]["metric_role"] == "base"
    assert success_rate["result_payload"]["formula"] is None


def test_terminal_publish_without_scope_is_a_safe_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kpi_v6_seed,
) -> None:
    from app.models.db import TaskKpiScopeItem, TaskKpiScopeSnapshot
    from app.services.kpi_v6_terminal_publish import publish_kpi_v6_from_scene

    task, output = _run_terminal_task(tmp_path, monkeypatch, kpi_v6_seed.umf)
    with session_factory() as session:
        session.query(TaskKpiScopeItem).filter(TaskKpiScopeItem.task_id == task.task_id).delete()
        session.query(TaskKpiScopeSnapshot).filter(TaskKpiScopeSnapshot.task_id == task.task_id).delete()
        session.commit()

    assert publish_kpi_v6_from_scene(task, output=output) == 0
    assert len(task_db.list_kpi_metric_results_v6(task.task_id, network_element_type="UMF")) == 20
