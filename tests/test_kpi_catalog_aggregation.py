"""KPI 目录指标聚合与阈值评估测试。"""

import pytest

from app.inspectors.kpi.catalog import (
    KpiAggregation,
    KpiMetricDefinition,
    KpiRatioFormula,
    KpiThreshold,
    aggregate_kpi_metric,
    evaluate_kpi_threshold,
)


def _metric(
    key: str,
    *,
    metric_type: str = "count",
    source_type: str = "raw",
    aggregation: str = "sum",
    quantile: float | None = None,
    formula: KpiRatioFormula | None = None,
) -> KpiMetricDefinition:
    return KpiMetricDefinition(
        key=key,
        name_zh=key,
        name_en=key,
        metric_type=metric_type,
        semantic_group="other",
        display_role="highlight",
        unit="",
        source_type=source_type,
        aggregation=KpiAggregation(kind=aggregation, quantile=quantile),
        aliases=[],
        formula=formula,
    )


def test_raw_count_and_capacity_metrics_aggregate_by_declared_kind() -> None:
    count = aggregate_kpi_metric(_metric("call_attempts"), {"call_attempts": [1, 2, 3]})
    capacity = aggregate_kpi_metric(
        _metric("stat_peak", metric_type="capacity", aggregation="max"),
        {"stat_peak": [10, 30, 20]},
    )
    assert count.value_available is True
    assert count.main_value == 6
    assert count.actual_aggregation == "sum"
    assert capacity.main_value == 30
    assert capacity.actual_aggregation == "max"


def test_latency_metric_supports_median_and_standard_deviation() -> None:
    median = aggregate_kpi_metric(
        _metric("latency_ms", metric_type="latency", aggregation="median"),
        {"latency_ms": [30, 10, 20]},
    )
    stddev = aggregate_kpi_metric(
        _metric("latency_ms", metric_type="latency", aggregation="stddev"),
        {"latency_ms": [10, 20, 30]},
    )
    assert median.main_value == 20
    assert median.actual_aggregation == "median"
    assert stddev.main_value == pytest.approx((200 / 3) ** 0.5)
    assert stddev.actual_aggregation == "stddev"


def test_ratio_aggregates_inputs_first_and_does_not_average_ratios() -> None:
    formula = KpiRatioFormula(
        numerator="call_success_count",
        denominator="call_attempts",
        scale=100,
    )
    metric = _metric(
        "call_success_rate",
        metric_type="rate",
        source_type="derived",
        aggregation="success_rate",
        formula=formula,
    )
    result = aggregate_kpi_metric(
        metric,
        {
            "call_success_count": [90, 180],
            "call_attempts": [100, 200],
        },
    )
    assert result.value_available is True
    assert result.main_value == pytest.approx(90.0)
    assert result.actual_aggregation == "success_rate"
    assert result.provenance["inputs"] == [
        {"key": "call_success_count", "aggregation": "sum", "value": 270},
        {"key": "call_attempts", "aggregation": "sum", "value": 300},
    ]
    assert result.provenance["denominator_zero"] is False
    assert result.provenance["fallback_used"] is False


def test_ratio_uses_declared_denominator_fallback_only_when_denominator_is_absent() -> None:
    formula = KpiRatioFormula(
        numerator="call_success_count",
        denominator="call_attempts",
        denominator_fallback_inputs=["call_success_count", "call_failure_count"],
        scale=100,
    )
    metric = _metric(
        "call_success_rate",
        metric_type="rate",
        source_type="derived",
        aggregation="success_rate",
        formula=formula,
    )
    result = aggregate_kpi_metric(
        metric,
        {
            "call_success_count": [95, 5],
            "call_failure_count": [5, 10],
        },
    )
    assert result.main_value == pytest.approx(100 / 115 * 100)
    assert result.provenance["fallback_used"] is True


def test_ratio_is_unavailable_for_zero_or_missing_formula_inputs() -> None:
    zero_formula = KpiRatioFormula(numerator="success", denominator="attempts", scale=100)
    zero_metric = _metric(
        "rate", metric_type="rate", source_type="derived", aggregation="success_rate", formula=zero_formula
    )
    zero = aggregate_kpi_metric(
        zero_metric,
        {"success": [10], "attempts": [0]},
    )
    missing = aggregate_kpi_metric(
        zero_metric,
        {"success": [10]},
    )
    assert zero.value_available is False
    assert zero.main_value is None
    assert zero.provenance["denominator_zero"] is True
    assert zero.unavailable_reason == "denominator_zero"
    assert missing.value_available is False
    assert missing.unavailable_reason == "missing_input: attempts"
    assert missing.provenance["missing_inputs"] == ["attempts"]


def test_threshold_evaluation_has_min_max_and_neutral_status() -> None:
    threshold = KpiThreshold(
        metric="call_success_rate",
        label="呼叫成功率",
        direction="min",
        unit="%",
        default=99.0,
        periods={"5": 98.0},
    )
    assert evaluate_kpi_threshold(98.5, threshold, 5) == "pass"
    assert evaluate_kpi_threshold(97.5, threshold, 5) == "fail"
    assert evaluate_kpi_threshold(98.5, threshold, 15) == "fail"
    assert evaluate_kpi_threshold(99.5, threshold, 15) == "pass"
    assert (
        evaluate_kpi_threshold(
            101.0,
            KpiThreshold(
                metric="call_failure_rate",
                label="失败率",
                direction="max",
                unit="%",
                default=1.0,
                periods={},
            ),
            5,
        )
        == "fail"
    )
    assert evaluate_kpi_threshold(1.0, None, 5) == "neutral"
    assert evaluate_kpi_threshold(None, threshold, 5) == "unavailable"


def test_inverse_ratio_aggregates_inputs_first_and_tracks_formula_kind() -> None:
    formula = KpiRatioFormula(
        numerator="call_failure_count",
        denominator="call_attempts",
        kind="inverse_ratio",
        scale=100,
    )
    metric = _metric(
        "call_success_rate",
        metric_type="rate",
        source_type="derived",
        aggregation="success_rate",
        formula=formula,
    )
    result = aggregate_kpi_metric(
        metric,
        {"call_failure_count": [5, 10], "call_attempts": [100, 200]},
    )
    assert result.value_available is True
    assert result.main_value == pytest.approx((1 - 15 / 300) * 100)
    assert result.provenance["formula"] == "(1 - call_failure_count / call_attempts) * 100"
    assert [item["key"] for item in result.provenance["inputs"]] == ["call_failure_count", "call_attempts"]
