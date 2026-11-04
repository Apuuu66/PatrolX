"""KPI 首屏摘要构造测试。"""

from __future__ import annotations

from typing import Any

from app.models.schemas import RuleResult
from app.services.results import summarize_kpi_result


class _NoDeepCopy:
    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise AssertionError("生成 KPI 摘要时不应深拷贝完整任务结果")


def _result() -> RuleResult:
    return RuleResult(
        code="kpi.measurement_units",
        name="测量单元",
        category="kpi",
        priority=1,
        execution_order=1,
        status="pass",
        severity="medium",
        metrics=[{"key": "metric", "label": "指标", "value": 1}],
        findings=[
            {
                "finding_id": "finding-1",
                "title": "发现",
                "severity": "low",
                "source_file": "metric.csv",
                "evidence": "证据",
            }
        ],
        metadata={
            "measurement_units": [
                {
                    "measurement_unit_id": "MU",
                    "name_zh": "单元",
                    "name_en": "Unit",
                    "status": "pass",
                    "file_count": 1,
                    "objects": {"pod-a": {"row_count": 1000}},
                    "metrics": [
                        {
                            "metric_resource_id": "ME",
                            "raw_source_name": "metric",
                            "read_status": "ok",
                            "value_pattern": "normal",
                            "trend_points": [
                                {
                                    "time": f"2026-01-01T00:{index:02d}:00Z",
                                    "value": index,
                                    "source_rows": [{"value": str(index)}],
                                }
                                for index in range(60)
                            ],
                            "observations": [{"object_key": "pod-a"}],
                            "trends": [{"label": "stable", "signal": "none"}],
                        }
                    ],
                }
            ],
            "unrelated_runtime_state": _NoDeepCopy(),
        },
    )


def test_summary_does_not_deep_copy_complete_kpi_result() -> None:
    summary = summarize_kpi_result(_result())

    assert summary.metrics == []
    assert summary.findings == []
    metric = summary.metadata["measurement_units"][0]["metrics"][0]
    assert "observations" not in metric
    assert "trends" not in metric
    assert "trend_points" not in metric
    assert metric["trend_point_count"] == 60


def test_summary_does_not_mutate_source_result() -> None:
    result = _result()
    summarize_kpi_result(result)

    unit = result.metadata["measurement_units"][0]
    metric = unit["metrics"][0]
    assert unit["objects"]
    assert len(metric["trend_points"]) == 60
    assert "source_rows" in metric["trend_points"][0]
    assert metric["observations"]
    assert metric["trends"]
    assert len(result.metrics) == 1
    assert len(result.findings) == 1
