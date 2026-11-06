"""041 T006：v6 合成数据库与任务快照夹具可用性测试。"""

from __future__ import annotations

from app.models.db import (
    KpiTeamFocusItem,
    KpiV6MeasurementResource,
    TaskKpiMetricResultV6,
    TaskKpiScopeItem,
    TaskKpiScopeSnapshot,
    session_factory,
)


def test_kpi_v6_seed_exposes_type_isolated_shared_focus_and_failure_cases(kpi_v6_seed) -> None:
    seed = kpi_v6_seed
    assert seed.umf.network_element_type == "UMF"
    assert seed.csp.network_element_type == "CSP"
    assert len(seed.umf.metric_resource_ids) == 20
    assert len(seed.umf.team_focus_metric_resource_ids) == 10
    assert seed.umf.metric_resource_ids == seed.csp.metric_resource_ids
    assert seed.umf.team_focus_metric_resource_ids == seed.csp.team_focus_metric_resource_ids
    assert seed.umf.package_path.is_file()
    assert seed.csp.package_path.is_file()

    with session_factory() as session:
        for task in (seed.umf, seed.csp):
            resources = (
                session.query(KpiV6MeasurementResource)
                .filter_by(network_element_type=task.network_element_type, kind="me")
                .all()
            )
            focus_rows = session.query(KpiTeamFocusItem).filter_by(network_element_type=task.network_element_type).all()
            snapshot = session.get(TaskKpiScopeSnapshot, task.task_id)
            scope_items = (
                session.query(TaskKpiScopeItem)
                .filter_by(task_id=task.task_id, network_element_type=task.network_element_type)
                .all()
            )
            results = session.query(TaskKpiMetricResultV6).filter_by(task_id=task.task_id).all()

            assert {row.resource_id for row in resources} == set(task.metric_resource_ids)
            assert {(row.measurement_unit_id, row.metric_resource_id) for row in focus_rows} == {
                (task.measurement_unit_id, metric_id) for metric_id in task.team_focus_metric_resource_ids
            }
            assert snapshot is not None
            assert snapshot.network_element_type == task.network_element_type
            assert snapshot.team_focus_revision == task.team_focus_revision
            assert len(scope_items) == 20
            assert len(results) == 20
            assert task.stale_team_focus_revision != task.team_focus_revision

        failure_result = (
            session.query(TaskKpiMetricResultV6)
            .filter_by(
                task_id=seed.umf.task_id,
                network_element_type="UMF",
                metric_resource_id=seed.evidence_failure_metric_resource_id,
            )
            .one()
        )
        assert failure_result.result_payload["evidence_available"] is False
        assert failure_result.result_payload["missing_reason"] == "合成证据不可读"
