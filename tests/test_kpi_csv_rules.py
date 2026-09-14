"""KPI CSV 共享解析器、配置校验、关联派生和容量指标测试。"""

from pathlib import Path

import pytest
import yaml

from app.inspectors.kpi.common import (
    KpiConfigError,
    KpiRecord,
    load_kpi_config,
    parse_csv_file,
    parse_kpi_path,
)


def _content(objects: list[str], rows: list[list[object]], measurement: str = "呼叫会话统计") -> str:
    lines = [measurement, "测量周期,开始时间,结束时间," + ",".join(objects)]
    for row in rows:
        lines.append(",".join(str(value) for value in row))
    return "\n".join(lines) + "\n"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _parse(tmp_path: Path, name: str, content: str, domain: str = "call"):
    path = _write(tmp_path, name, content)
    domain_from_name, period = parse_kpi_path(name)  # type: ignore[assignment]
    assert domain_from_name == domain
    return parse_csv_file(path, name, domain, period, load_kpi_config())


@pytest.mark.parametrize(
    ("name", "domain", "period"),
    [
        ("kpi/kpi-api-5.csv", "api", 5),
        ("kpi/kpi-media-15.csv", "media", 15),
        ("kpi/kpi-call-30.csv", "call", 30),
        ("kpi/sub/kpi-call-60.csv", "call", 60),
    ],
)
def test_parse_kpi_path_supports_all_domains_and_periods(name: str, domain: str, period: int) -> None:
    assert parse_kpi_path(name) == (domain, period)


@pytest.mark.parametrize(
    "name",
    ["kpi/kpi-other-15.csv", "kpi/kpi-call-20.csv", "kpi/kpi-call-15.CSV", "kpi/kpi-call.csv"],
)
def test_parse_kpi_path_rejects_unknown_names(name: str) -> None:
    assert parse_kpi_path(name) is None


@pytest.mark.parametrize("period", [5, 15, 30, 60])
def test_parse_csv_file_reads_two_row_header_and_normalizes_utc_time(tmp_path: Path, period: int) -> None:
    end_hour = 10 + period // 60
    end_minute = period % 60
    content = _content(
        ["呼叫请求", "请求成功", "请求失败"],
        [[period, "2026-09-01 10:00:00", f"2026-09-01 {end_hour:02d}:{end_minute:02d}:00", 100, 99, 1]],
    )
    parsed = _parse(tmp_path, f"kpi/kpi-call-{period}.csv", content)
    assert parsed.status == "ok"
    assert parsed.measurement_set == "呼叫会话统计"
    assert parsed.objects == ["呼叫请求", "请求成功", "请求失败"]
    assert parsed.record_count == 1
    record = parsed.records[0]
    assert record.line_number == 3
    assert record.period_minutes == period
    assert record.start_at.isoformat() == "2026-09-01T02:00:00+00:00"
    assert record.end_at.isoformat() == (f"2026-09-01T{end_hour - 8:02d}:{end_minute:02d}:00+00:00")
    assert record.values == {"呼叫请求": 100.0, "请求成功": 99.0, "请求失败": 1.0}
    assert not record.errors
    assert not parsed.errors


def test_parse_csv_file_preserves_nested_relative_path(tmp_path: Path) -> None:
    content = _content(["请求总数"], [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 1]])
    path = _write(tmp_path, "kpi/sub/kpi-api-15.csv", content)
    parsed = parse_csv_file(path, "kpi/sub/kpi-api-15.csv", "api", 15, load_kpi_config())
    assert parsed.path == "kpi/sub/kpi-api-15.csv"
    assert parsed.status == "ok"


def test_parse_csv_file_reports_period_mismatch(tmp_path: Path) -> None:
    content = _content(["呼叫请求"], [[5, "2026-09-01 10:00:00", "2026-09-01 10:05:00", 100]])
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.status == "failed"
    assert parsed.records[0].errors[0].code == "period_mismatch"


def test_parse_csv_file_reports_time_range_mismatch(tmp_path: Path) -> None:
    content = _content(["呼叫请求"], [[15, "2026-09-01 10:00:00", "2026-09-01 10:30:00", 100]])
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.records[0].errors[0].code == "time_range_mismatch"
    assert parsed.status == "failed"


def test_parse_csv_file_reports_invalid_time_and_continues_next_row(tmp_path: Path) -> None:
    content = _content(
        ["呼叫请求"],
        [
            [15, "bad-time", "2026-09-01 10:15:00", 100],
            [15, "2026-09-01 10:15:00", "2026-09-01 10:30:00", 101],
        ],
    )
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.record_count == 1
    assert parsed.records[0].errors[0].code == "invalid_time"
    assert not parsed.records[1].errors
    assert parsed.records[1].values["呼叫请求"] == 101.0


def test_parse_csv_file_reports_column_count_mismatch(tmp_path: Path) -> None:
    content = _content(["呼叫请求", "请求成功"], [])
    content += "15,2026-09-01 10:00:00,2026-09-01 10:15:00,100\n"
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.status == "failed"
    assert parsed.records[0].errors[0].code == "column_count_mismatch"


def test_parse_csv_file_reports_invalid_value_and_keeps_parseable_value(tmp_path: Path) -> None:
    content = _content(
        ["呼叫请求", "请求成功"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", "bad", 99]],
    )
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.records[0].errors[0].code == "invalid_value"
    assert parsed.records[0].values == {"请求成功": 99.0}


def test_parse_csv_file_reports_empty_measurement_set(tmp_path: Path) -> None:
    content = _content(
        ["呼叫请求"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100]],
        measurement="",
    )
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.errors[0].code == "missing_measurement_set"
    assert parsed.status == "failed"


def test_parse_csv_file_reports_duplicate_objects(tmp_path: Path) -> None:
    content = _content(
        ["呼叫请求", "呼叫请求"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100, 99]],
    )
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.errors[0].code == "duplicate_object"


def test_parse_csv_file_reports_row_count_limit(tmp_path: Path) -> None:
    config_path = Path("deploy/config/kpi_rules.yaml")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["budgets"]["max_rows_per_file"] = 2
    config_file = tmp_path / "kpi_rules.yaml"
    config_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    config = load_kpi_config(config_file)
    content = _content(
        ["呼叫请求"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100]],
    )
    path = _write(tmp_path, "kpi/kpi-call-15.csv", content)
    parsed = parse_csv_file(path, "kpi/kpi-call-15.csv", "call", 15, config)
    assert parsed.status == "failed"
    assert parsed.errors[0].code == "resource_limit_exceeded"


def test_config_requires_complete_call_aliases_and_limits(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("deploy/config/kpi_rules.yaml").read_text(encoding="utf-8"))
    del raw["aliases"]["call"]["请求成功"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(KpiConfigError, match="缺少必需映射"):
        load_kpi_config(path)

    raw = yaml.safe_load(Path("deploy/config/kpi_rules.yaml").read_text(encoding="utf-8"))
    del raw["limits"]["call"]["call_failure_rate"]
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(KpiConfigError, match="缺少必需阈值"):
        load_kpi_config(path)


def test_config_rejects_alias_and_capacity_key_conflict(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("deploy/config/kpi_rules.yaml").read_text(encoding="utf-8"))
    raw["aliases"]["call"]["统计峰值"] = "max_concurrency"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(KpiConfigError, match="冲突"):
        load_kpi_config(path)


@pytest.mark.parametrize(
    ("path", "match"),
    [
        (["aliases", "call", "呼叫请求"], "非法"),
        (["capacity_metrics", "call", "统计峰值", "status"], "status 非法"),
        (["limits", "call", "call_success_rate", "direction"], "direction 非法"),
        (["budgets", "max_file_bytes"], "必须为正整数"),
    ],
)
def test_config_rejects_invalid_fields(tmp_path: Path, path: list[str], match: str) -> None:
    raw = yaml.safe_load(Path("deploy/config/kpi_rules.yaml").read_text(encoding="utf-8"))
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = None
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(KpiConfigError, match=match):
        load_kpi_config(config_file)


def test_capacity_metrics_are_mapped_per_record(tmp_path: Path) -> None:
    content = _content(
        ["呼叫请求", "统计峰值", "最大并发"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100, 101, 88]],
    )
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    record = parsed.records[0]
    assert [item.metric for item in record.capacity_values or []] == [
        "stat_peak",
        "max_concurrency",
    ]
    assert all(item.status == "confirmed" for item in record.capacity_values or [])


def test_unknown_capacity_semantics_is_display_only(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("deploy/config/kpi_rules.yaml").read_text(encoding="utf-8"))
    raw["capacity_metrics"]["call"]["统计峰值"]["status"] = "unknown"
    raw["capacity_metrics"]["call"]["统计峰值"]["semantics"] = None
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    content = _content(["统计峰值"], [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 101]])
    path = _write(tmp_path, "kpi/kpi-call-15.csv", content)
    parsed = parse_csv_file(path, "kpi/kpi-call-15.csv", "call", 15, load_kpi_config(config_file))
    capacity = parsed.records[0].capacity_values[0]
    assert capacity.status == "unknown"
    assert capacity.reason == "capacity_semantics_unknown"
    assert not parsed.records[0].errors


def test_derive_rates_explicit_rates_priority_and_zero_denominator() -> None:
    from app.inspectors.kpi.call import _derive_rates

    alias = {
        "呼叫请求": "call_attempts",
        "请求成功": "call_success_count",
        "请求失败": "call_failure_count",
        "呼叫成功率": "call_success_rate",
        "呼叫失败率": "call_failure_rate",
    }
    record = KpiRecord(
        line_number=3,
        period_minutes=15,
        start_at=__import__("datetime").datetime(2026, 9, 1, tzinfo=__import__("datetime").UTC),
        end_at=__import__("datetime").datetime(2026, 9, 1, tzinfo=__import__("datetime").UTC),
        values={"呼叫请求": 0, "请求成功": 0, "请求失败": 0},
    )
    _derive_rates(record, alias)
    assert record.derived == {"call_count_difference": 0}

    record.values |= {"呼叫成功率": 97.5, "呼叫失败率": 2.5}
    _derive_rates(record, alias)
    assert record.derived == {
        "call_count_difference": 0,
        "call_success_rate": 97.5,
        "call_failure_rate": 2.5,
    }
