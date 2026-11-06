"""KPI 结果工作台 v6 的三视图、汇总与源包指标口径测试（041 T016）。"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models.db import (
    KpiTeamFocusItem,
    TaskKpiMetricResultV6,
    TaskKpiPointV6,
    TaskKpiScopeItem,
    TaskKpiScopeSnapshot,
    TaskRecord,
    session_factory,
)

client = TestClient(app)


def _summary(task_id: str):
    return client.get(f"/api/v6/kpi/tasks/{task_id}/summary")


def _metrics(task_id: str, **params: object):
    return client.get(f"/api/v6/kpi/tasks/{task_id}/metrics", params=params)


def _evidence(task_id: str, measurement_unit_id: str, metric_resource_id: str):
    return client.get(f"/api/v6/kpi/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/evidence")


def _technical_analysis(
    task_id: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    **params: object,
):
    return client.get(
        f"/api/v6/kpi/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/technical-analysis",
        params=params,
    )


def _identity(item: dict[str, object]) -> tuple[str, str, str | None, str | None]:
    return (
        str(item["measurement_unit_id"]),
        str(item["metric_resource_id"]),
        item.get("needs_attention_group"),
        item.get("current_status"),
    )


def _seed_historical_task(
    *,
    task_id: str,
    network_element_type: str,
    device_id: str,
    version: str,
    data_date: date,
    completed_at: datetime,
    measurement_unit_id: str,
    metric_resource_id: str,
    value: float | None,
) -> None:
    """写入一条同设备技术分析候选任务，供真实服务查询而非 mock。"""
    measured_at = datetime.combine(data_date, datetime.min.time(), tzinfo=UTC).replace(hour=8)
    frozen_at = completed_at
    with session_factory() as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                name=f"{task_id} 历史合成任务",
                mode="online",
                status="completed",
                trigger="api",
                package_file=f"{task_id}.zip",
                customer={"product": network_element_type, "device_id": device_id},
                package_kind="inspection",
                rule_network_element_type=network_element_type,
                version=version,
                stats={},
                created_at=completed_at,
                completed_at=completed_at,
                last_run_at=completed_at,
            )
        )
        session.add(
            TaskKpiScopeSnapshot(
                task_id=task_id,
                network_element_type=network_element_type,
                team_focus_revision=0,
                config_fingerprint=hashlib.sha256(task_id.encode()).hexdigest(),
                data_date=data_date,
                frozen_at=frozen_at,
                snapshot_payload={"enabled_measurement_unit_ids": [measurement_unit_id], "metric_count": 1},
            )
        )
        session.add(
            TaskKpiScopeItem(
                task_id=task_id,
                network_element_type=network_element_type,
                measurement_unit_id=measurement_unit_id,
                metric_resource_id=metric_resource_id,
                metric_kind="base",
                config_snapshot={
                    "name_zh": metric_resource_id,
                    "role": "base",
                    "is_percentage": metric_resource_id.endswith("_RATE"),
                    "daily_aggregation": "latest",
                },
                scope_status="ready",
            )
        )
        session.add(
            TaskKpiMetricResultV6(
                task_id=task_id,
                network_element_type=network_element_type,
                measurement_unit_id=measurement_unit_id,
                metric_resource_id=metric_resource_id,
                source_rule_code="kpi.measurement_units",
                decision="pass" if value is not None else "error",
                special_state=None if value is not None else "no_data",
                yesterday_trend="stable" if value is not None else "no_baseline",
                needs_attention_group=None,
                today_value=value,
                yesterday_value=value,
                change=0 if value is not None else None,
                unit="%" if metric_resource_id.endswith("_RATE") else "times",
                importance="normal",
                reason="历史合成值" if value is not None else "历史任务缺少数据",
                effective_point_count=1,
                result_payload={
                    "metric_role": "base",
                    "is_percentage": metric_resource_id.endswith("_RATE"),
                    "evidence_available": True,
                    "current_status": "normal" if value is not None else "unable_to_judge",
                    "trend_status": "stable" if value is not None else "no_baseline",
                },
                result_fingerprint=hashlib.sha256(f"{task_id}:result".encode()).hexdigest(),
                published_at=frozen_at,
            )
        )
        session.add(
            TaskKpiPointV6(
                task_id=task_id,
                network_element_type=network_element_type,
                source_rule_code="kpi.measurement_units",
                measurement_unit_id=measurement_unit_id,
                metric_resource_id=metric_resource_id,
                object_key="__all__",
                period_minutes=1440,
                measured_at=measured_at,
                value=value,
                source_file=f"{task_id}.zip",
                line_number=1,
                point_fingerprint=hashlib.sha256(
                    f"{task_id}:{measurement_unit_id}:{metric_resource_id}".encode()
                ).hexdigest(),
            )
        )
        session.commit()


def _seed_derived_evidence(
    *,
    task_id: str,
    network_element_type: str,
    measurement_unit_id: str,
    today_numerator: int = 129,
    today_denominator: int = 180,
) -> str:
    """写入一个本地派生指标及其分子/分母依赖点。"""
    metric_id = "ME_DERIVED_MEDIA_CREATION_QUALITY"
    numerator_id = "ME_TEST_MEDIA_CREATION_SUCCESS_RESPONSES"
    denominator_id = "ME_TEST_MEDIA_CREATION_REQUESTS"
    today_value = round(today_numerator / today_denominator * 100, 2) if today_denominator else None
    daily_counts = {
        6: (63, 100),
        5: (64, 100),
        4: (65, 100),
        3: (66, 100),
        2: (68, 100),
        1: (150, 200),
        0: (today_numerator, today_denominator),
    }
    group_a_numerator = today_numerator // 2
    group_a_denominator = today_denominator // 2
    group_b_numerator = today_numerator - group_a_numerator
    group_b_denominator = today_denominator - group_a_denominator
    group_counts = {
        "site-a": (
            group_a_numerator,
            group_a_denominator,
            75,
            100,
        ),
        "site-b": (
            group_b_numerator,
            group_b_denominator,
            75,
            100,
        ),
    }

    with session_factory() as session:
        session.add(
            TaskKpiScopeItem(
                task_id=task_id,
                network_element_type=network_element_type,
                measurement_unit_id=measurement_unit_id,
                metric_resource_id=metric_id,
                metric_kind="derived",
                config_snapshot={
                    "name_zh": "媒体创建本地质量率",
                    "name_en": "Media Creation Local Quality Rate(%)",
                    "role": "derived",
                    "is_percentage": True,
                    "raw_source_names": ["Media Creation Local Quality Rate(%)"],
                    "direction": "higher_better",
                    "warning_threshold": 90,
                    "critical_threshold": 80,
                    "daily_aggregation": "latest",
                    "numerator_metric_id": numerator_id,
                    "denominator_metric_id": denominator_id,
                    "numerator_metric_name": "成功响应数",
                    "denominator_metric_name": "请求数",
                    "template": "success_rate",
                    "display_order": 20,
                    "config_revision": 4,
                    "config_fingerprint": "a" * 64,
                },
                scope_status="ready",
            )
        )
        session.add(
            TaskKpiMetricResultV6(
                task_id=task_id,
                network_element_type=network_element_type,
                measurement_unit_id=measurement_unit_id,
                metric_resource_id=metric_id,
                source_rule_code="kpi.measurement_units",
                decision="fail" if today_value is not None else "error",
                special_state=None if today_value is not None else "zero_denominator",
                yesterday_trend="worsened",
                needs_attention_group="failure" if today_value is not None else "unjudgeable",
                today_value=today_value,
                yesterday_value=75.0,
                change=round(today_value - 75.0, 2) if today_value is not None else None,
                unit="%",
                importance="normal",
                reason="低于严重阈值" if today_value is not None else "分母为零，无法计算",
                effective_point_count=3,
                result_payload={
                    "metric_role": "derived",
                    "is_percentage": True,
                    "evidence_available": True,
                    "current_status": "fail" if today_value is not None else "unable_to_judge",
                    "trend_status": "worsened",
                    "threshold_source": "custom",
                    "reason_codes": ["below_critical_threshold" if today_value is not None else "zero_denominator"],
                },
                result_fingerprint=hashlib.sha256(f"{task_id}:{network_element_type}:derived".encode()).hexdigest(),
                published_at=datetime(2026, 11, 5, 8, tzinfo=UTC),
            )
        )
        for days_ago in range(6, -1, -1):
            numerator, denominator = daily_counts[days_ago]
            measured_at = datetime(2026, 11, 5, 8, tzinfo=UTC) - timedelta(days=days_ago)
            value = round(numerator / denominator * 100, 2) if denominator else None
            scope_points = [
                (metric_id, value, "DerivedQuality.csv"),
                (numerator_id, float(numerator), "Counts.csv"),
                (denominator_id, float(denominator), "Counts.csv"),
            ]
            for metric_resource_id, point_value, source_file in scope_points:
                session.add(
                    TaskKpiPointV6(
                        task_id=task_id,
                        network_element_type=network_element_type,
                        source_rule_code="kpi.measurement_units",
                        measurement_unit_id=measurement_unit_id,
                        metric_resource_id=metric_resource_id,
                        object_key="__all__",
                        period_minutes=60,
                        measured_at=measured_at,
                        value=point_value,
                        source_file=source_file,
                        line_number=1,
                        point_fingerprint=hashlib.sha256(
                            f"{task_id}:{metric_resource_id}:__all__:{days_ago}".encode()
                        ).hexdigest(),
                    )
                )
        for object_key, (today_num, today_den, yesterday_num, yesterday_den) in group_counts.items():
            for days_ago, numerator, denominator in (
                (1, yesterday_num, yesterday_den),
                (0, today_num, today_den),
            ):
                measured_at = datetime(2026, 11, 5, 8, tzinfo=UTC) - timedelta(days=days_ago)
                value = round(numerator / denominator * 100, 2) if denominator else None
                for metric_resource_id, point_value, source_file in (
                    (metric_id, value, "DerivedQuality.csv"),
                    (numerator_id, float(numerator), "Counts.csv"),
                    (denominator_id, float(denominator), "Counts.csv"),
                ):
                    session.add(
                        TaskKpiPointV6(
                            task_id=task_id,
                            network_element_type=network_element_type,
                            source_rule_code="kpi.measurement_units",
                            measurement_unit_id=measurement_unit_id,
                            metric_resource_id=metric_resource_id,
                            object_key=object_key,
                            period_minutes=60,
                            measured_at=measured_at,
                            value=point_value,
                            source_file=source_file,
                            line_number=1,
                            point_fingerprint=hashlib.sha256(
                                f"{task_id}:{metric_resource_id}:{object_key}:{days_ago}".encode()
                            ).hexdigest(),
                        )
                    )
        session.commit()
    return metric_id


def test_summary_reports_global_counts_and_fixed_group_order(kpi_v6_seed) -> None:
    response = _summary(kpi_v6_seed.umf.task_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["task_id"] == kpi_v6_seed.umf.task_id
    assert payload["network_element_type"] == "UMF"
    assert payload["result_contract_version"] == "v6"
    assert payload["data_date"] == "2026-11-05"
    assert payload["previous_date"] == "2026-11-04"
    assert payload["latest_measured_at"].startswith("2026-11-05T08:00:00")
    assert payload["counts"] == {
        "enabled_measurement_unit_count": 1,
        "all_metric_count": 20,
        "team_focus_count": 10,
        "needs_attention_count": 10,
        "no_action_count": 0,
        "unavailable_focus_count": 0,
    }
    assert payload["needs_attention_groups"] == [
        {"group": "failure", "order": 1, "count": 3},
        {"group": "warning", "order": 2, "count": 2},
        {"group": "trend_degraded", "order": 3, "count": 3},
        {"group": "unjudgeable", "order": 4, "count": 1},
        {"group": "needs_config", "order": 5, "count": 1},
    ]
    assert payload["rule_scope"] == {
        "business_rule_count": 1,
        "has_executable_rules": True,
        "notice": None,
    }


def test_metrics_default_to_needs_attention_with_fixed_group_and_stable_order(kpi_v6_seed) -> None:
    response = _metrics(kpi_v6_seed.umf.task_id, page_size=20)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 10
    assert payload["view_total"] == 10
    assert payload["empty_state"] == "none"
    assert payload["applied_filters"] == {
        "search": None,
        "measurement_unit_id": None,
        "current_status": None,
        "yesterday_trend": None,
        "needs_attention_group": None,
    }
    assert [item["needs_attention_group"] for item in payload["items"]] == [
        "failure",
        "failure",
        "failure",
        "warning",
        "warning",
        "trend_degraded",
        "trend_degraded",
        "trend_degraded",
        "unjudgeable",
        "needs_config",
    ]
    assert [_identity(item) for item in payload["items"]] == [
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_CREATION_FAILURE_RESPONSES", "failure", "fail"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_CREATION_SUCCESS_RATE", "failure", "fail"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_DELETION_FAILURE_RESPONSES", "failure", "fail"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_CREATION_REQUESTS", "warning", "warn"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_MODIFICATION_SUCCESS_RESPONSES", "warning", "warn"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_CREATION_SUCCESS_RESPONSES", "trend_degraded", "normal"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_DELETION_SUCCESS_RESPONSES", "trend_degraded", "normal"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_MODIFICATION_FAILURE_RESPONSES", "trend_degraded", "normal"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_DELETION_REQUESTS", "unjudgeable", "unable_to_judge"),
        (kpi_v6_seed.umf.measurement_unit_id, "ME_MEDIA_MODIFICATION_REQUESTS", "needs_config", "pending_config"),
    ]


def test_team_focus_and_all_views_reconcile_with_filtered_totals(kpi_v6_seed) -> None:
    focus = _metrics(kpi_v6_seed.umf.task_id, view="team_focus", page_size=50)
    all_metrics = _metrics(kpi_v6_seed.umf.task_id, view="all", page_size=50)
    filtered = _metrics(
        kpi_v6_seed.umf.task_id,
        view="team_focus",
        needs_attention_group="failure",
        page=1,
        page_size=2,
    )

    assert focus.status_code == 200, focus.text
    assert focus.json()["total"] == focus.json()["view_total"] == 10
    assert all_metrics.status_code == 200, all_metrics.text
    assert all_metrics.json()["total"] == all_metrics.json()["view_total"] == 20
    assert filtered.status_code == 200, filtered.text
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 3
    assert filtered_payload["view_total"] == 10
    assert len(filtered_payload["items"]) == 2
    assert filtered_payload["applied_filters"]["needs_attention_group"] == "failure"


def test_empty_states_distinguish_no_matching_team_focus_empty_and_no_task_metrics(
    kpi_v6_seed,
) -> None:
    no_match = _metrics(kpi_v6_seed.umf.task_id, view="all", search="不存在的指标")
    assert no_match.status_code == 200, no_match.text
    assert no_match.json()["empty_state"] == "no_matching_metrics"
    assert no_match.json()["total"] == 0
    assert no_match.json()["view_total"] == 20

    with session_factory() as session:
        session.query(KpiTeamFocusItem).filter(KpiTeamFocusItem.network_element_type == "UMF").delete()
        session.commit()

    focus_empty = _metrics(kpi_v6_seed.umf.task_id, view="team_focus")
    assert focus_empty.status_code == 200, focus_empty.text
    assert focus_empty.json()["empty_state"] == "team_focus_empty"
    assert focus_empty.json()["total"] == focus_empty.json()["view_total"] == 0

    with session_factory() as session:
        session.query(TaskKpiScopeItem).filter(TaskKpiScopeItem.task_id == kpi_v6_seed.umf.task_id).delete()
        session.query(TaskKpiMetricResultV6).filter(TaskKpiMetricResultV6.task_id == kpi_v6_seed.umf.task_id).delete()
        session.commit()

    no_metrics = _metrics(kpi_v6_seed.umf.task_id, view="all")
    assert no_metrics.status_code == 200, no_metrics.text
    assert no_metrics.json()["empty_state"] == "no_task_metrics"
    assert no_metrics.json()["total"] == no_metrics.json()["view_total"] == 0


def test_legacy_task_without_v6_snapshot_requires_rebuild(kpi_v6_seed) -> None:
    with session_factory() as session:
        session.query(TaskKpiScopeSnapshot).filter(TaskKpiScopeSnapshot.task_id == kpi_v6_seed.umf.task_id).delete()
        session.commit()

    for response in (
        _summary(kpi_v6_seed.umf.task_id),
        _metrics(kpi_v6_seed.umf.task_id),
    ):
        assert response.status_code == 409, response.text
        payload = response.json()
        assert set(payload) == {"code", "message", "detail"}
        assert payload["code"] == "task_result_requires_rebuild"


def test_missing_task_uses_structured_not_found_error() -> None:
    response = _summary("KPI-V6-MISSING-TASK")

    assert response.status_code == 404
    assert response.json()["code"] == "task_not_found"
    assert set(response.json()) == {"code", "message", "detail"}


def test_umf_and_csp_results_and_team_focus_are_fully_isolated(kpi_v6_seed) -> None:
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    with session_factory() as session:
        row = (
            session.query(TaskKpiMetricResultV6)
            .filter(
                TaskKpiMetricResultV6.task_id == kpi_v6_seed.umf.task_id,
                TaskKpiMetricResultV6.metric_resource_id == metric_id,
            )
            .one()
        )
        row.reason = "仅属于 UMF 的任务结果"
        session.query(KpiTeamFocusItem).filter(KpiTeamFocusItem.network_element_type == "UMF").delete()
        session.commit()

    umf_all = _metrics(kpi_v6_seed.umf.task_id, view="all", search=metric_id)
    csp_all = _metrics(kpi_v6_seed.csp.task_id, view="all", search=metric_id)
    umf_focus = _metrics(kpi_v6_seed.umf.task_id, view="team_focus")
    csp_focus = _metrics(kpi_v6_seed.csp.task_id, view="team_focus")

    assert umf_all.status_code == csp_all.status_code == 200
    assert umf_all.json()["items"][0]["network_element_type"] == "UMF"
    assert umf_all.json()["items"][0]["reason"] == "仅属于 UMF 的任务结果"
    assert csp_all.json()["items"][0]["network_element_type"] == "CSP"
    assert csp_all.json()["items"][0]["reason"] != "仅属于 UMF 的任务结果"
    assert umf_focus.json()["empty_state"] == "team_focus_empty"
    assert csp_focus.json()["total"] == csp_focus.json()["view_total"] == 10


def test_media_success_rate_is_source_base_value_and_is_never_recomputed(kpi_v6_seed) -> None:
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    response = _metrics(kpi_v6_seed.umf.task_id, view="all", search=metric_id)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["metric_resource_id"] == metric_id
    assert item["role"] == "base"
    assert item["today_value"] == 63.7
    assert item["yesterday_value"] == 75
    assert item["today_value"] != 129 / 200 * 100
    assert "64.5" not in response.text


def test_csp_missing_success_rate_source_stays_missing_and_is_not_recomputed(kpi_v6_seed) -> None:
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    response = _metrics(kpi_v6_seed.csp.task_id, view="all", search=metric_id)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["metric_resource_id"] == metric_id
    assert item["role"] == "base"
    assert item["today_value"] is None
    assert item["special_state"] == "no_data"
    assert "63.7" not in response.text
    assert "64.5" not in response.text
    assert "129/200" not in response.text


def test_media_success_rate_evidence_is_source_base_without_formula_or_components(kpi_v6_seed) -> None:
    response = _evidence(
        kpi_v6_seed.umf.task_id,
        kpi_v6_seed.umf.measurement_unit_id,
        "ME_MEDIA_CREATION_SUCCESS_RATE",
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["network_element_type"] == "UMF"
    assert payload["measurement_unit_id"] == kpi_v6_seed.umf.measurement_unit_id
    assert payload["metric_resource_id"] == "ME_MEDIA_CREATION_SUCCESS_RATE"
    assert payload["metric"] == {
        "name": "媒体资源创建成功率",
        "role": "base",
        "is_percentage": True,
        "formula": None,
        "daily_aggregation": "latest",
        "current_status": "fail",
        "trend_status": "worsened",
    }
    assert payload["current"]["value"] == 63.7
    assert payload["current"]["numerator"] is None
    assert payload["current"]["denominator"] is None
    assert payload["previous"]["value"] == 75
    assert payload["previous"]["numerator"] is None
    assert payload["previous"]["denominator"] is None
    assert payload["components"] == []
    assert all(bucket["numerator"] is None and bucket["denominator"] is None for bucket in payload["seven_day_trend"])
    assert all(
        bucket["numerator"] is None and bucket["denominator"] is None
        for group in payload["groups"]
        for bucket in (group["today"], group["yesterday"])
        if bucket is not None
    )
    assert payload["sources"] == [
        {
            "file": "PerfResult_20261105000000.zip",
            "record_group": None,
            "raw_source_names": [
                "Media Resource Creation Success Rate(%)",
                "Media Resource Creation Requests Success Rate(%)",
            ],
        }
    ]
    assert "64.5" not in response.text
    assert "129 / 200" not in response.text


def test_derived_evidence_exposes_formula_components_and_grouped_daily_ratios(kpi_v6_seed) -> None:
    metric_id = _seed_derived_evidence(
        task_id=kpi_v6_seed.umf.task_id,
        network_element_type="UMF",
        measurement_unit_id=kpi_v6_seed.umf.measurement_unit_id,
    )
    _seed_derived_evidence(
        task_id=kpi_v6_seed.csp.task_id,
        network_element_type="CSP",
        measurement_unit_id=kpi_v6_seed.csp.measurement_unit_id,
        today_numerator=999,
        today_denominator=1000,
    )

    response = _evidence(
        kpi_v6_seed.umf.task_id,
        kpi_v6_seed.umf.measurement_unit_id,
        metric_id,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["metric"] == {
        "name": "媒体创建本地质量率",
        "role": "derived",
        "is_percentage": True,
        "formula": "成功响应数 ÷ 请求数 × 100%",
        "daily_aggregation": "latest",
        "current_status": "fail",
        "trend_status": "worsened",
    }
    assert payload["current"] == {
        "date": "2026-11-05",
        "value": 71.67,
        "numerator": 129.0,
        "denominator": 180.0,
        "valid_count": 1,
        "first_measured_at": "2026-11-05T08:00:00+00:00",
        "last_measured_at": "2026-11-05T08:00:00+00:00",
        "status": "ok",
    }
    assert payload["previous"] == {
        "date": "2026-11-04",
        "value": 75.0,
        "numerator": 150.0,
        "denominator": 200.0,
        "valid_count": 1,
        "first_measured_at": "2026-11-04T08:00:00+00:00",
        "last_measured_at": "2026-11-04T08:00:00+00:00",
        "status": "ok",
    }
    assert payload["change_value"] == -3.33
    assert payload["change_unit"] == "pp"
    assert payload["reason"] == "低于严重阈值"
    assert payload["reason_codes"] == ["below_critical_threshold"]
    assert payload["valid_count"] == 3
    assert payload["current_threshold"] == {
        "direction": "higher_better",
        "warning_threshold": 90,
        "critical_threshold": 80,
        "source": "custom",
    }
    assert payload["components"] == [
        {
            "metric_resource_id": "ME_TEST_MEDIA_CREATION_SUCCESS_RESPONSES",
            "name": "成功响应数",
            "role": "numerator",
            "value": 129.0,
        },
        {
            "metric_resource_id": "ME_TEST_MEDIA_CREATION_REQUESTS",
            "name": "请求数",
            "role": "denominator",
            "value": 180.0,
        },
    ]
    groups = {group["object_key"]: group for group in payload["groups"]}
    assert set(groups) == {"__all__", "site-a", "site-b"}
    assert groups["site-a"]["period_minutes"] == 60
    assert groups["site-a"]["today"]["numerator"] == 64.0
    assert groups["site-a"]["today"]["denominator"] == 90.0
    assert groups["site-a"]["yesterday"]["numerator"] == 75.0
    assert groups["site-a"]["yesterday"]["denominator"] == 100.0
    assert groups["site-b"]["today"]["numerator"] == 65.0
    assert groups["site-b"]["today"]["denominator"] == 90.0
    assert [bucket["value"] for bucket in payload["seven_day_trend"]] == [
        63.0,
        64.0,
        65.0,
        66.0,
        68.0,
        75.0,
        71.67,
    ]
    assert [bucket["numerator"] for bucket in payload["seven_day_trend"]] == [
        63.0,
        64.0,
        65.0,
        66.0,
        68.0,
        150.0,
        129.0,
    ]
    assert [bucket["denominator"] for bucket in payload["seven_day_trend"]] == [
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
        200.0,
        180.0,
    ]
    assert {source["file"] for source in payload["sources"]} == {
        "Counts.csv",
        "DerivedQuality.csv",
    }


def test_derived_evidence_keeps_zero_denominator_and_missing_reason(kpi_v6_seed) -> None:
    metric_id = _seed_derived_evidence(
        task_id=kpi_v6_seed.umf.task_id,
        network_element_type="UMF",
        measurement_unit_id=kpi_v6_seed.umf.measurement_unit_id,
    )
    with session_factory() as session:
        result = (
            session.query(TaskKpiMetricResultV6)
            .filter(
                TaskKpiMetricResultV6.task_id == kpi_v6_seed.umf.task_id,
                TaskKpiMetricResultV6.metric_resource_id == metric_id,
            )
            .one()
        )
        result.today_value = None
        result.special_state = "zero_denominator"
        result.decision = "error"
        result.reason = "分母为零，无法计算"
        result.result_payload = {
            **result.result_payload,
            "current_status": "unable_to_judge",
            "reason_codes": ["zero_denominator"],
        }
        session.query(TaskKpiPointV6).filter(
            TaskKpiPointV6.task_id == kpi_v6_seed.umf.task_id,
            TaskKpiPointV6.metric_resource_id == metric_id,
            TaskKpiPointV6.object_key == "__all__",
            TaskKpiPointV6.measured_at >= datetime(2026, 11, 5, tzinfo=UTC),
        ).update({TaskKpiPointV6.value: None})
        session.query(TaskKpiPointV6).filter(
            TaskKpiPointV6.task_id == kpi_v6_seed.umf.task_id,
            TaskKpiPointV6.metric_resource_id == "ME_TEST_MEDIA_CREATION_REQUESTS",
            TaskKpiPointV6.object_key == "__all__",
            TaskKpiPointV6.measured_at >= datetime(2026, 11, 5, tzinfo=UTC),
        ).update({TaskKpiPointV6.value: 0.0})
        session.commit()

    response = _evidence(
        kpi_v6_seed.umf.task_id,
        kpi_v6_seed.umf.measurement_unit_id,
        metric_id,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["current"]["value"] is None
    assert payload["current"]["numerator"] == 129.0
    assert payload["current"]["denominator"] == 0.0
    assert payload["current"]["status"] == "zero_denominator"
    assert payload["reason"] == "分母为零，无法计算"
    assert payload["reason_codes"] == ["zero_denominator"]
    assert payload["components"][1]["value"] == 0.0


def test_evidence_uses_stable_task_metric_and_unavailable_errors(kpi_v6_seed) -> None:
    missing_task = _evidence(
        "KPI-V6-MISSING-TASK",
        kpi_v6_seed.umf.measurement_unit_id,
        "ME_MEDIA_CREATION_SUCCESS_RATE",
    )
    missing_metric = _evidence(
        kpi_v6_seed.umf.task_id,
        kpi_v6_seed.umf.measurement_unit_id,
        "ME_NOT_IN_TASK_SNAPSHOT",
    )
    unavailable = _evidence(
        kpi_v6_seed.umf.task_id,
        kpi_v6_seed.umf.measurement_unit_id,
        kpi_v6_seed.evidence_failure_metric_resource_id,
    )

    assert missing_task.status_code == 404
    assert missing_task.json()["code"] == "task_not_found"
    assert missing_metric.status_code == 404
    assert missing_metric.json()["code"] == "kpi_metric_not_found"
    assert missing_metric.json()["detail"] == {
        "task_id": kpi_v6_seed.umf.task_id,
        "measurement_unit_id": kpi_v6_seed.umf.measurement_unit_id,
        "metric_resource_id": "ME_NOT_IN_TASK_SNAPSHOT",
    }
    assert unavailable.status_code == 424
    assert unavailable.json()["code"] == "kpi_evidence_unavailable"
    assert unavailable.json()["detail"] == {
        "retryable": True,
        "measurement_unit_id": kpi_v6_seed.umf.measurement_unit_id,
        "metric_resource_id": kpi_v6_seed.evidence_failure_metric_resource_id,
    }


def test_technical_analysis_without_historical_same_device_tasks_returns_empty_lists(kpi_v6_seed) -> None:
    response = _technical_analysis(
        kpi_v6_seed.umf.task_id,
        kpi_v6_seed.umf.measurement_unit_id,
        "ME_MEDIA_CREATION_SUCCESS_RATE",
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["task_id"] == kpi_v6_seed.umf.task_id
    assert payload["measurement_unit_id"] == kpi_v6_seed.umf.measurement_unit_id
    assert payload["metric_resource_id"] == "ME_MEDIA_CREATION_SUCCESS_RATE"
    assert payload["cross_task_history"] == []
    assert payload["version_comparisons"] == []


def test_technical_analysis_only_reads_same_device_type_unit_and_metric(kpi_v6_seed) -> None:
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    unit_id = kpi_v6_seed.umf.measurement_unit_id
    device_id = "UMF-DEVICE-001"
    with session_factory() as session:
        current = session.get(TaskRecord, kpi_v6_seed.umf.task_id)
        assert current is not None
        current.customer = {**current.customer, "device_id": device_id}
        session.commit()

    common = {
        "network_element_type": "UMF",
        "device_id": device_id,
        "measurement_unit_id": unit_id,
        "metric_resource_id": metric_id,
    }
    _seed_historical_task(
        task_id="KPI-V6-HISTORY-SAME-V5",
        version="V5",
        data_date=date(2026, 11, 3),
        completed_at=kpi_v6_seed.frozen_at - timedelta(days=2),
        value=61.0,
        **common,
    )
    _seed_historical_task(
        task_id="KPI-V6-HISTORY-OTHER-DEVICE",
        version="V5",
        device_id="UMF-DEVICE-002",
        data_date=date(2026, 11, 3),
        completed_at=kpi_v6_seed.frozen_at - timedelta(days=1, minutes=1),
        value=62.0,
        **{key: value for key, value in common.items() if key != "device_id"},
    )
    _seed_historical_task(
        task_id="KPI-V6-HISTORY-OTHER-TYPE",
        version="V5",
        network_element_type="CSP",
        data_date=date(2026, 11, 3),
        completed_at=kpi_v6_seed.frozen_at - timedelta(days=1, minutes=2),
        value=63.0,
        **{key: value for key, value in common.items() if key != "network_element_type"},
    )
    _seed_historical_task(
        task_id="KPI-V6-HISTORY-OTHER-UNIT",
        version="V5",
        measurement_unit_id="MU_OTHER",
        data_date=date(2026, 11, 3),
        completed_at=kpi_v6_seed.frozen_at - timedelta(days=1, minutes=3),
        value=64.0,
        **{key: value for key, value in common.items() if key != "measurement_unit_id"},
    )
    _seed_historical_task(
        task_id="KPI-V6-HISTORY-OTHER-METRIC",
        version="V5",
        metric_resource_id="ME_MEDIA_CREATION_REQUESTS",
        data_date=date(2026, 11, 3),
        completed_at=kpi_v6_seed.frozen_at - timedelta(days=1, minutes=4),
        value=65.0,
        **{key: value for key, value in common.items() if key != "metric_resource_id"},
    )
    _seed_historical_task(
        task_id="KPI-V6-HISTORY-FUTURE",
        version="V5",
        data_date=date(2026, 11, 3),
        completed_at=kpi_v6_seed.frozen_at + timedelta(minutes=1),
        value=66.0,
        **common,
    )

    response = _technical_analysis(kpi_v6_seed.umf.task_id, unit_id, metric_id, version_limit=10)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["task_id"] for item in payload["cross_task_history"]] == ["KPI-V6-HISTORY-SAME-V5"]
    assert [item["value"] for item in payload["cross_task_history"]] == [61.0]
    assert [item["task_id"] for item in payload["version_comparisons"]] == ["KPI-V6-HISTORY-SAME-V5"]
    assert [item["version"] for item in payload["version_comparisons"]] == ["V5"]


def test_version_comparisons_do_not_use_same_system_version_as_baseline(kpi_v6_seed) -> None:
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    unit_id = kpi_v6_seed.umf.measurement_unit_id
    device_id = "UMF-DEVICE-001"
    with session_factory() as session:
        current = session.get(TaskRecord, kpi_v6_seed.umf.task_id)
        assert current is not None
        current.customer = {**current.customer, "device_id": device_id}
        session.commit()

    _seed_historical_task(
        task_id="KPI-V6-HISTORY-SAME-VERSION",
        network_element_type="UMF",
        device_id=device_id,
        version="V6",
        data_date=date(2026, 11, 4),
        completed_at=kpi_v6_seed.frozen_at - timedelta(days=1),
        measurement_unit_id=unit_id,
        metric_resource_id=metric_id,
        value=65.0,
    )

    response = _technical_analysis(kpi_v6_seed.umf.task_id, unit_id, metric_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["task_id"] for item in payload["cross_task_history"]] == ["KPI-V6-HISTORY-SAME-VERSION"]
    assert payload["version_comparisons"] == []
