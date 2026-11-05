"""KPI 日健康纯业务判定测试。"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.kpi_daily_health import (
    CURRENT_STATUS_PRIORITY,
    TREND_STATUS_PRIORITY,
    DailyPoint,
    MetricDailyHealthConfig,
    aggregate_current_statuses,
    aggregate_daily_bucket,
    aggregate_trend_statuses,
    build_metric_daily_health,
    classify_daily_trend,
    date_in_utc8,
    judge_current_status,
)


def _config(**overrides: object) -> MetricDailyHealthConfig:
    values: dict[str, object] = {
        "measurement_unit_id": "MU",
        "metric_resource_id": "ME",
        "name_zh": "测试指标",
        "role": "base",
        "direction": "higher_better",
        "warning_threshold": 90.0,
        "critical_threshold": 80.0,
        "daily_aggregation": "mean",
        "daily_change_threshold": 0.2,
        "daily_change_threshold_unit": "pp",
        "is_percentage": True,
        "zero_semantics": "unknown",
        "consistency_tolerance": 0.2,
    }
    values.update(overrides)
    return MetricDailyHealthConfig(**values)


def _point(
    measured_at: datetime,
    value: float,
    *,
    object_key: str = "pod-a",
    period_minutes: int = 15,
    numerator: float | None = None,
    denominator: float | None = None,
    raw_value: float | None = None,
    source_file: str = "metric.csv",
) -> DailyPoint:
    return DailyPoint(
        object_key=object_key,
        measured_at=measured_at,
        period_minutes=period_minutes,
        value=value,
        numerator=numerator,
        denominator=denominator,
        raw_value=raw_value,
        source_file=source_file,
    )


def test_utc_plus_8_day_boundary_and_yesterday_bucket() -> None:
    assert date_in_utc8(datetime(2026, 10, 31, 15, 59, tzinfo=UTC)) == date(2026, 10, 31)
    assert date_in_utc8(datetime(2026, 10, 31, 16, 0, tzinfo=UTC)) == date(2026, 11, 1)

    result = build_metric_daily_health(
        _config(),
        [
            _point(datetime(2026, 10, 31, 15, 59, tzinfo=UTC), 10.0),
            _point(datetime(2026, 10, 31, 16, 0, tzinfo=UTC), 20.0),
        ],
    )

    assert result["metric"]["data_date"] == date(2026, 11, 1)
    assert result["metric"]["previous_date"] == date(2026, 10, 31)
    group = result["groups"][0]
    assert group["today"]["value"] == 20.0
    assert group["yesterday"]["value"] == 10.0


def test_status_priority_is_explicit_and_downstream_never_masks_failure() -> None:
    assert CURRENT_STATUS_PRIORITY == (
        "fail",
        "warn",
        "unable_to_judge",
        "pending_config",
        "not_applicable",
        "normal",
    )
    assert (
        aggregate_current_statuses(["normal", "not_applicable", "pending_config", "unable_to_judge", "warn", "fail"])
        == "fail"
    )
    assert TREND_STATUS_PRIORITY == ("worsened", "improved", "observe", "no_baseline", "stable")
    assert aggregate_trend_statuses(["stable", "no_baseline", "observe", "improved", "worsened"]) == "worsened"


@pytest.mark.parametrize(
    ("value", "direction", "warning", "critical", "expected"),
    [
        (95.0, "higher_better", 90.0, 80.0, ("normal", "threshold_satisfied")),
        (90.0, "higher_better", 90.0, 80.0, ("warn", "warning_threshold")),
        (80.0, "higher_better", 90.0, 80.0, ("fail", "critical_threshold")),
        (5.0, "lower_better", 10.0, 20.0, ("normal", "threshold_satisfied")),
        (10.0, "lower_better", 10.0, 20.0, ("warn", "warning_threshold")),
        (20.0, "lower_better", 10.0, 20.0, ("fail", "critical_threshold")),
        (95.0, None, 90.0, 80.0, ("pending_config", "direction_missing")),
        (95.0, "higher_better", None, None, ("pending_config", "threshold_missing")),
    ],
)
def test_current_status_threshold_semantics(
    value: float,
    direction: str | None,
    warning: float | None,
    critical: float | None,
    expected: tuple[str, str],
) -> None:
    assert (
        judge_current_status(
            value,
            direction=direction,  # type: ignore[arg-type]
            warning_threshold=warning,
            critical_threshold=critical,
            valid_count=1,
        )
        == expected
    )


def test_zero_semantics_and_zero_denominator_are_not_normal() -> None:
    assert judge_current_status(
        0.0,
        direction="higher_better",
        warning_threshold=90.0,
        critical_threshold=80.0,
        valid_count=2,
        all_zero=True,
        zero_semantics="unknown",
    ) == ("pending_config", "all_zero_unconfirmed")
    assert judge_current_status(
        0.0,
        direction="higher_better",
        warning_threshold=90.0,
        critical_threshold=80.0,
        valid_count=2,
        all_zero=True,
        zero_semantics="business_not_triggered",
    ) == ("not_applicable", "business_not_triggered")
    assert judge_current_status(
        0.0,
        direction="higher_better",
        warning_threshold=90.0,
        critical_threshold=80.0,
        valid_count=2,
        all_zero=True,
        zero_semantics="expected_zero",
    ) == ("fail", "critical_threshold")
    assert judge_current_status(
        None,
        direction="higher_better",
        warning_threshold=90.0,
        critical_threshold=80.0,
        valid_count=1,
        denominator=0.0,
    ) == ("not_applicable", "zero_denominator")
    assert judge_current_status(
        None,
        direction="higher_better",
        warning_threshold=90.0,
        critical_threshold=80.0,
        valid_count=0,
    ) == ("unable_to_judge", "no_current_data")


def test_pp_trend_uses_points_and_default_tolerance() -> None:
    improved = classify_daily_trend(
        99.3,
        99.0,
        direction="higher_better",
        is_percentage=True,
        change_threshold=None,
    )
    assert improved["status"] == "improved"
    assert improved["delta"] == pytest.approx(0.3)
    assert improved["unit"] == "pp"
    assert improved["threshold_source"] == "default"

    stable = classify_daily_trend(
        99.1,
        99.0,
        direction="higher_better",
        is_percentage=True,
        change_threshold=None,
    )
    assert stable["status"] == "stable"
    assert (
        classify_daily_trend(98.0, 99.0, direction="lower_better", is_percentage=True, change_threshold=None)["status"]
        == "improved"
    )
    assert (
        classify_daily_trend(100.0, 99.0, direction="neutral", is_percentage=True, change_threshold=None)["status"]
        == "observe"
    )
    assert (
        classify_daily_trend(100.0, None, direction="higher_better", is_percentage=True, change_threshold=None)[
            "status"
        ]
        == "no_baseline"
    )


def test_object_and_period_are_never_mixed_for_daily_trend() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    result = build_metric_daily_health(
        _config(warning_threshold=None, critical_threshold=None),
        [
            _point(anchor - timedelta(days=1), 91.0, object_key="pod-a", period_minutes=15),
            _point(anchor, 92.0, object_key="pod-a", period_minutes=15),
            _point(anchor, 40.0, object_key="pod-a", period_minutes=60),
            _point(anchor, 30.0, object_key="pod-b", period_minutes=15),
        ],
    )

    assert [(group["object_key"], group["period_minutes"]) for group in result["groups"]] == [
        ("pod-a", 15),
        ("pod-a", 60),
        ("pod-b", 15),
    ]
    assert result["groups"][0]["trend_status"] in {"improved", "stable"}
    assert result["groups"][1]["yesterday"] is None
    assert result["groups"][1]["trend_status"] == "no_baseline"
    assert result["groups"][2]["trend_status"] == "no_baseline"


def test_success_rate_uses_sum_over_sum_not_mean_of_rates() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    numerator = [
        _point(anchor, 1.0, numerator=1.0, denominator=100.0),
        _point(anchor + timedelta(hours=15), 50.0, numerator=50.0, denominator=10000.0),
    ]
    denominator = [
        _point(anchor, 100.0, numerator=1.0, denominator=100.0),
        _point(anchor + timedelta(hours=15), 10000.0, numerator=100.0, denominator=10000.0),
    ]
    result = build_metric_daily_health(
        _config(
            role="derived",
            numerator_metric_id="ME_SUCCESS",
            denominator_metric_id="ME_TOTAL",
            template="success_rate",
            warning_threshold=None,
            critical_threshold=None,
        ),
        [],
        numerator_points=numerator,
        denominator_points=denominator,
    )

    group = result["groups"][0]
    assert group["today"]["numerator"] == 51.0
    assert group["today"]["denominator"] == 10100.0
    assert group["today"]["value"] == pytest.approx(51 / 10100 * 100, abs=0.0001)
    mean_of_point_rates = ((1.0 / 100.0 * 100.0) + (50.0 / 10000.0 * 100.0)) / 2
    assert group["today"]["value"] != pytest.approx(mean_of_point_rates, abs=0.0001)


def test_reverse_success_rate_and_weighted_raw_consistency() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    numerator = [_point(anchor, 1.0, numerator=1.0, denominator=4.0)]
    denominator = [_point(anchor, 4.0, numerator=1.0, denominator=4.0)]
    reverse = build_metric_daily_health(
        _config(
            role="derived",
            numerator_metric_id="ME_FAIL",
            denominator_metric_id="ME_TOTAL",
            template="reverse_success_rate",
            warning_threshold=None,
            critical_threshold=None,
        ),
        [],
        numerator_points=numerator,
        denominator_points=denominator,
    )
    assert reverse["groups"][0]["today"]["value"] == 75.0

    forward = build_metric_daily_health(
        _config(
            role="derived",
            numerator_metric_id="ME_SUCCESS",
            denominator_metric_id="ME_TOTAL",
            template="success_rate",
            warning_threshold=None,
            critical_threshold=None,
        ),
        [],
        numerator_points=[
            _point(anchor, 1.0, numerator=1.0, denominator=50.0, raw_value=2.0),
            _point(anchor + timedelta(minutes=15), 1.0, numerator=1.0, denominator=50.0, raw_value=2.0),
        ],
        denominator_points=[
            _point(anchor, 50.0, numerator=1.0, denominator=50.0),
            _point(anchor + timedelta(minutes=15), 50.0, numerator=1.0, denominator=50.0),
        ],
    )
    assert forward["metric"]["consistency"]["status"] == "within_tolerance"
    assert forward["metric"]["consistency"]["difference_pp"] == pytest.approx(0.0)


def test_daily_bucket_supports_all_base_aggregations() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    points = [
        _point(anchor, 1.0),
        _point(anchor + timedelta(minutes=15), 3.0),
        _point(anchor + timedelta(minutes=30), 2.0),
    ]
    assert aggregate_daily_bucket(points, "latest")["value"] == 2.0
    assert aggregate_daily_bucket(points, "mean")["value"] == 2.0
    assert aggregate_daily_bucket(points, "sum")["value"] == 6.0
    assert aggregate_daily_bucket(points, "max")["value"] == 3.0
    assert aggregate_daily_bucket(points, "min")["value"] == 1.0
    assert aggregate_daily_bucket([], "mean")["status"] == "no_data"


def test_seven_day_trend_is_a_fixed_window_ending_on_anchor() -> None:
    anchor = date(2026, 11, 2)
    points = [
        _point(datetime(2026, 10, 25, 17, 0, tzinfo=UTC), 100.0),
        _point(datetime(2026, 10, 26, 16, 0, tzinfo=UTC), 90.0),
        _point(datetime(2026, 10, 31, 16, 0, tzinfo=UTC), 91.0),
        _point(datetime(2026, 11, 1, 16, 0, tzinfo=UTC), 92.0),
    ]
    result = build_metric_daily_health(_config(), points)
    assert result["metric"]["data_date"] == anchor
    assert [item["date"] for item in result["seven_day_trend"]] == [
        date(2026, 10, 27),
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 30),
        date(2026, 10, 31),
        date(2026, 11, 1),
        date(2026, 11, 2),
    ]
    assert result["seven_day_trend"][0]["value"] == 90.0
    assert result["seven_day_trend"][1]["status"] == "no_data"
    assert result["seven_day_trend"][-1]["value"] == 92.0


def test_success_rate_requires_same_object_and_period_for_numerator_and_denominator() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    result = build_metric_daily_health(
        _config(role="derived", numerator_metric_id="ME_SUCCESS", denominator_metric_id="ME_TOTAL"),
        [],
        numerator_points=[_point(anchor, 10.0, object_key="pod-a", period_minutes=15)],
        denominator_points=[_point(anchor, 100.0, object_key="pod-b", period_minutes=15)],
    )

    group = result["groups"][0]
    assert group["current_status"] == "unable_to_judge"
    assert "对象/周期" in group["reason"]
    assert group["today"]["value"] is None


def test_success_rate_reports_missing_dependency_without_zero_filling() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    result = build_metric_daily_health(
        _config(role="derived", numerator_metric_id="ME_SUCCESS", denominator_metric_id="ME_TOTAL"),
        [],
        numerator_points=[_point(anchor, 1.0)],
        denominator_points=[],
    )

    group = result["groups"][0]
    assert group["current_status"] == "unable_to_judge"
    assert "依赖" in group["reason"]
    assert group["today"]["value"] is None


def test_similar_success_rate_names_remain_independent_by_metric_id() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    metric_ids = (
        "ME_MEDIA_RESOURCE_CREATION_SUCCESS_RATE",
        "ME_MEDIA_RESOURCE_CREATION_REQUESTS_SUCCESS_RATE",
        "ME_DC_RESOURCE_UPDATE_SUCCESS_RATE",
        "ME_DATA_CHANNEL_RESOURCE_UPDATE_REQUESTS_SUCCESS_RATE",
    )
    results = [
        build_metric_daily_health(
            _config(
                metric_resource_id=metric_id,
                name_zh=metric_id,
                role="derived",
                numerator_metric_id=f"{metric_id}_NUM",
                denominator_metric_id=f"{metric_id}_DEN",
            ),
            [],
            numerator_points=[_point(anchor, value)],
            denominator_points=[_point(anchor, 100.0)],
        )
        for metric_id, value in zip(metric_ids, (99.0, 98.0, 97.0, 96.0), strict=True)
    ]

    assert [result["metric"]["name_zh"] for result in results] == list(metric_ids)
    assert [result["groups"][0]["today"]["value"] for result in results] == [99.0, 98.0, 97.0, 96.0]


def test_consistency_exceeded_prevents_silent_normal_result() -> None:
    anchor = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    result = build_metric_daily_health(
        _config(
            role="derived",
            numerator_metric_id="ME_SUCCESS",
            denominator_metric_id="ME_TOTAL",
            warning_threshold=90.0,
            critical_threshold=80.0,
        ),
        [],
        numerator_points=[_point(anchor, 99.0, raw_value=50.0)],
        denominator_points=[_point(anchor, 100.0)],
    )

    assert result["metric"]["consistency"]["status"] == "exceeded"
    assert result["metric"]["current_status"] == "pending_config"


def test_seven_day_trend_keeps_zero_denominator_as_not_applicable_evidence() -> None:
    anchor = date(2026, 11, 2)
    point_at = datetime(2026, 11, 1, 16, 30, tzinfo=UTC)
    result = build_metric_daily_health(
        _config(
            role="derived",
            numerator_metric_id="ME_SUCCESS",
            denominator_metric_id="ME_TOTAL",
            daily_change_threshold_unit="pp",
            is_percentage=True,
        ),
        [],
        numerator_points=[_point(point_at, 0.0)],
        denominator_points=[_point(point_at, 0.0)],
    )

    today = result["seven_day_trend"][-1]
    assert result["metric"]["data_date"] == anchor
    assert today["status"] == "zero_denominator"
    assert today["value"] is None
    assert today["numerator"] == 0.0
    assert today["denominator"] == 0.0
    assert result["groups"][0]["current_status"] == "not_applicable"


def test_missing_direction_does_not_claim_a_directional_or_stable_trend() -> None:
    yesterday = datetime(2026, 11, 1, 16, 0, tzinfo=UTC)
    today = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)
    result = build_metric_daily_health(
        _config(direction=None),
        [_point(yesterday, 100.0), _point(today, 101.0)],
    )

    assert result["metric"]["trend_status"] == "no_baseline"
    assert result["groups"][0]["trend_status"] == "no_baseline"
    assert result["groups"][0]["trend_reason_code"] == "direction_missing"
