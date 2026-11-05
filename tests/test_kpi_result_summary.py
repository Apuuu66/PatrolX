"""KPI 规则摘要的日健康首屏契约测试。"""

from app.models.schemas import RuleResult
from app.services.results import summarize_kpi_result


def _result() -> RuleResult:
    return RuleResult(
        code="kpi.measurement_units",
        name="KPI 测量单元巡检",
        category="kpi",
        priority=1,
        execution_order=1,
        status="warn",
        severity="medium",
        metadata={
            "measurement_units": [
                {
                    "measurement_unit_id": "MU_CALL",
                    "metrics": [
                        {
                            "metric_resource_id": "ME_RATE",
                            "trend_points": [{"value": 72.0}],
                            "observations": [{"valid_count": 2}],
                        }
                    ],
                }
            ],
            "daily_health": {
                "schema_version": 1,
                "timezone": "Asia/Shanghai",
                "data_date": "2026-11-01",
                "previous_date": "2026-10-31",
                "latest_measured_at": "2026-11-01T23:45:00+08:00",
                "legacy_fallback": None,
                "current_counts": {
                    "fail": 1,
                    "warn": 0,
                    "unable_to_judge": 0,
                    "pending_config": 0,
                    "not_applicable": 0,
                    "normal": 0,
                },
                "trend_counts": {
                    "worsened": 1,
                    "improved": 0,
                    "observe": 0,
                    "no_baseline": 0,
                    "stable": 0,
                },
                "scope": {"expected_metric_count": 1},
                "metrics": [
                    {
                        "measurement_unit_id": "MU_CALL",
                        "measurement_unit_name_zh": "呼叫统计",
                        "metric_resource_id": "ME_RATE",
                        "metric_resource_name_zh": "呼叫成功率",
                        "role": "derived",
                        "current_status": "fail",
                        "current_reason": "critical_threshold",
                        "today_value": 72.0,
                        "yesterday_value": 99.0,
                        "delta": -27.0,
                        "trend_status": "worsened",
                        "objects": [
                            {
                                "object_key": "pod-a",
                                "numerator": 72,
                                "denominator": 100,
                                "valid_count": 2,
                            }
                        ],
                    }
                ],
            },
        },
    )


def test_kpi_summary_keeps_daily_health_counts_and_metric_conclusions() -> None:
    summary = summarize_kpi_result(_result())
    daily_health = summary.metadata["daily_health"]

    assert daily_health["data_date"] == "2026-11-01"
    assert daily_health["current_counts"]["fail"] == 1
    assert daily_health["trend_counts"]["worsened"] == 1
    assert daily_health["scope"] == {"expected_metric_count": 1}
    assert daily_health["metrics"][0]["metric_resource_id"] == "ME_RATE"
    assert daily_health["metrics"][0]["current_status"] == "fail"
    assert daily_health["metrics"][0]["today_value"] == 72.0
    assert daily_health["metrics"][0]["trend_status"] == "worsened"


def test_kpi_summary_drops_detail_evidence_but_keeps_counts() -> None:
    summary = summarize_kpi_result(_result())
    daily_metric = summary.metadata["daily_health"]["metrics"][0]

    assert "objects" not in daily_metric
    assert daily_metric["object_count"] == 1
    assert "seven_day_trend" not in summary.metadata["daily_health"]
    assert "trend_points" not in summary.metadata["measurement_units"][0]["metrics"][0]
    assert summary.metadata["measurement_units"][0]["metrics"][0]["trend_point_count"] == 1
