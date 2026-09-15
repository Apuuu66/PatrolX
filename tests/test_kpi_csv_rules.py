"""KPI CSV 共享解析器、配置校验、关联派生和容量指标测试。"""

import shutil
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
    header = [
        "服务名",
        "实例",
        "可信度",
        "不可信原因",
        "测量开始时间",
        "测量结束时间",
        "周期(分钟)",
        *objects,
    ]
    lines = [
        "设备类型：XXX",
        f"测量单元名称：{measurement}",
        ",".join(header),
    ]
    for row in rows:
        period, start_at, end_at, *values = row
        data = ["BasicKpi", "", "可信", "", str(start_at), str(end_at), str(period), *values]
        lines.append(",".join(str(value) for value in data))
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
def test_parse_csv_file_reads_metadata_flexible_header_and_normalizes_utc_time(tmp_path: Path, period: int) -> None:
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
    assert record.line_number == 4
    assert record.period_minutes == period
    assert record.start_at.isoformat() == "2026-09-01T02:00:00+00:00"
    assert record.end_at.isoformat() == (f"2026-09-01T{end_hour - 8:02d}:{end_minute:02d}:00+00:00")
    assert record.values == {"呼叫请求": 100.0, "请求成功": 99.0, "请求失败": 1.0}
    assert not record.errors
    assert not parsed.errors


def test_parse_csv_file_skips_blank_metadata_rows(tmp_path: Path) -> None:
    content = _content(
        ["呼叫请求"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100]],
    ).replace("设备类型：XXX\n", "设备类型：XXX\n\n")
    parsed = _parse(tmp_path, "kpi/kpi-call-15.csv", content)
    assert parsed.status == "ok"
    assert parsed.measurement_set == "呼叫会话统计"
    assert parsed.record_count == 1


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
    content += "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15,100\n"
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


def _copy_kpi_config(tmp_path: Path) -> Path:
    target = tmp_path / "kpi"
    shutil.copytree(Path("deploy/config/kpi"), target)
    return target


def _read_domain(config_dir: Path, name: str = "call.yaml") -> dict:
    return yaml.safe_load((config_dir / name).read_text(encoding="utf-8"))


def _write_domain(config_dir: Path, raw: dict, name: str = "call.yaml") -> None:
    (config_dir / name).write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


def test_parse_csv_file_reports_row_count_limit(tmp_path: Path) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = yaml.safe_load((config_dir / "common.yaml").read_text(encoding="utf-8"))
    raw["budgets"]["max_rows_per_file"] = 4
    (config_dir / "common.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    config = load_kpi_config(config_dir)
    content = _content(
        ["呼叫请求"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100]],
    )
    content += "BasicKpi,,可信,,2026-09-01 10:15:00,2026-09-01 10:30:00,15,101\n"
    path = _write(tmp_path, "kpi/kpi-call-15.csv", content)
    parsed = parse_csv_file(path, "kpi/kpi-call-15.csv", "call", 15, config)
    assert parsed.status == "failed"
    assert parsed.errors[0].code == "resource_limit_exceeded"


def test_config_requires_complete_call_metrics_and_thresholds(tmp_path: Path) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = _read_domain(config_dir)
    raw["metrics"] = [metric for metric in raw["metrics"] if metric["key"] != "call_success_count"]
    _write_domain(config_dir, raw)
    with pytest.raises(KpiConfigError, match="引用未知输入"):
        load_kpi_config(config_dir)

    raw = _read_domain(config_dir)
    raw["metrics"].append(
        {
            "key": "call_success_count",
            "name_zh": "呼叫请求成功次数",
            "name_en": "Call Success Count",
            "metric_type": "count",
            "semantic_group": "traffic",
            "display_role": "context",
            "unit": "次",
            "source_type": "raw",
            "aggregation": {"kind": "sum"},
            "aliases": [{"language": "zh", "value": "呼叫请求成功次数"}],
        }
    )
    del raw["thresholds"]["call_failure_rate"]
    _write_domain(config_dir, raw)
    with pytest.raises(KpiConfigError, match="缺少必需阈值"):
        load_kpi_config(config_dir)


def test_config_rejects_alias_and_capacity_key_conflict(tmp_path: Path) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = _read_domain(config_dir)
    for metric in raw["metrics"]:
        if metric["key"] == "max_concurrency":
            metric["aliases"].append({"language": "zh", "value": "统计峰值"})
    _write_domain(config_dir, raw)
    with pytest.raises(KpiConfigError, match="已映射到"):
        load_kpi_config(config_dir)


@pytest.mark.parametrize(
    ("path", "match"),
    [
        (["metrics", 0, "aliases", 0, "value"], "value: 缺失或非法"),
        (["capacity_metrics", "统计峰值", "status"], "非法容量语义或状态"),
        (["thresholds", "call_success_rate", "direction"], "direction"),
    ],
)
def test_config_rejects_invalid_domain_fields(tmp_path: Path, path: list, match: str) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = _read_domain(config_dir)
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = None
    _write_domain(config_dir, raw)
    with pytest.raises(KpiConfigError, match=match):
        load_kpi_config(config_dir)


def test_config_rejects_invalid_budget(tmp_path: Path) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = yaml.safe_load((config_dir / "common.yaml").read_text(encoding="utf-8"))
    raw["budgets"]["max_file_bytes"] = None
    (config_dir / "common.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(KpiConfigError, match="必须为正整数"):
        load_kpi_config(config_dir)


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
    config_dir = _copy_kpi_config(tmp_path)
    raw = _read_domain(config_dir)
    raw["capacity_metrics"]["统计峰值"]["status"] = "unknown"
    raw["capacity_metrics"]["统计峰值"]["semantics"] = None
    _write_domain(config_dir, raw)
    content = _content(["统计峰值"], [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 101]])
    path = _write(tmp_path, "kpi/kpi-call-15.csv", content)
    parsed = parse_csv_file(path, "kpi/kpi-call-15.csv", "call", 15, load_kpi_config(config_dir))
    capacity = parsed.records[0].capacity_values[0]
    assert capacity.status == "unknown"
    assert capacity.reason == "capacity_semantics_unknown"
    assert not parsed.records[0].errors


def test_derive_rates_formula_priority_and_zero_denominator() -> None:
    from app.inspectors.kpi.call import _derive_rates

    alias = {
        "呼叫请求次数": "call_attempts",
        "呼叫请求成功次数": "call_success_count",
        "呼叫请求失败次数": "call_failure_count",
        "呼叫成功率": "call_success_rate",
        "呼叫失败率": "call_failure_rate",
    }
    record = KpiRecord(
        line_number=3,
        period_minutes=15,
        start_at=__import__("datetime").datetime(2026, 9, 1, tzinfo=__import__("datetime").UTC),
        end_at=__import__("datetime").datetime(2026, 9, 1, tzinfo=__import__("datetime").UTC),
        values={"呼叫请求次数": 0, "呼叫请求成功次数": 0, "呼叫请求失败次数": 0},
    )
    _derive_rates(record, alias)
    assert record.derived == {"call_count_difference": 0}

    record.values |= {"呼叫请求次数": 100, "呼叫请求成功次数": 90, "呼叫请求失败次数": 10}
    record.values |= {"呼叫成功率": 97.5, "呼叫失败率": 2.5}
    _derive_rates(record, alias)
    assert record.derived == {
        "call_count_difference": 0,
        "call_success_rate": 90.0,
        "call_failure_rate": 10.0,
    }


def test_direct_rate_columns_are_cross_reference_only(tmp_path: Path) -> None:
    from app.inspectors.registry import registry
    from app.services.executor import RuleContext

    content = _content(
        [
            "呼叫请求次数",
            "呼叫请求成功次数",
            "呼叫请求失败次数",
            "呼叫成功率",
            "呼叫失败率",
        ],
        [[5, "2026-09-01 10:00:00", "2026-09-01 10:05:00", 100, 90, 10, 99.9, 0.1]],
    )
    _write(tmp_path, "kpi/kpi-call-5.csv", content)
    ctx = RuleContext(task_id="kpi-direct-test", data_dir=tmp_path, log=lambda *args, **kwargs: None)
    ctx.files = [Path("kpi/kpi-call-5.csv")]
    result = registry.get("kpi.call").run(ctx)
    metadata = result.metadata
    rate = next(item for item in metadata["kpi_results"] if item["key"] == "call_success_rate")

    assert rate["main_value"] == 90.0
    assert rate["series"][0]["value"] == 90.0
    cross_reference = rate["provenance"]["direct_cross_reference"]
    assert cross_reference == [{"source_name": "呼叫成功率", "source_file": "kpi/kpi-call-5.csv", "value": 99.9}]
    assert next(item for item in result.metrics if item.key == "success_rate_min").value == 90.0


def test_parse_csv_file_reads_metadata_and_flexible_real_header(tmp_path: Path) -> None:
    content = """设备类型：XXX
测量单元名称：呼叫会话统计
服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数,呼叫请求成功次数,呼叫请求失败次数
BasicKpi,,可信,,2026-09-14 10:00:00,2026-09-14 10:05:00,5,100,100,0
"""
    parsed = _parse(tmp_path, "kpi/kpi-call-5.csv", content)
    assert parsed.status == "ok"
    assert parsed.measurement_set == "呼叫会话统计"
    assert parsed.objects == ["呼叫请求次数", "呼叫请求成功次数", "呼叫请求失败次数"]
    assert parsed.record_count == 1
    record = parsed.records[0]
    assert record.line_number == 4
    assert record.period_minutes == 5
    assert record.start_at.isoformat() == "2026-09-14T02:00:00+00:00"
    assert record.end_at.isoformat() == "2026-09-14T02:05:00+00:00"
    assert record.values == {
        "呼叫请求次数": 100.0,
        "呼叫请求成功次数": 100.0,
        "呼叫请求失败次数": 0.0,
    }


def test_kpi_call_emits_version_2_catalog_results_and_preserves_rule_status(tmp_path: Path) -> None:
    from app.inspectors.registry import registry
    from app.models.schemas import RuleStatus
    from app.services.executor import RuleContext

    content = _content(
        ["呼叫请求次数", "呼叫请求成功次数", "呼叫请求失败次数", "统计峰值", "最大并发"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100, 80, 20, 10, 8]],
        "呼叫会话统计",
    )
    _write(tmp_path, "kpi/kpi-call-15.csv", content)
    logs: list[dict] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append({"level": level, "message": message, **(detail or {})})

    ctx = RuleContext(task_id="kpi-test", data_dir=tmp_path, log=log)
    ctx.files = [Path("kpi/kpi-call-15.csv")]
    result = registry.get("kpi.call").run(ctx)
    metadata = result.metadata

    assert result.status == RuleStatus.FAIL
    assert metadata["version"] == 2
    assert metadata["config_source"] == "deploy/config/kpi"
    assert {"call_attempts", "call_success_rate"} <= {item["key"] for item in metadata["metric_catalog"]}
    results = {item["key"]: item for item in metadata["kpi_results"]}
    assert results["call_success_rate"]["main_value"] == pytest.approx(80.0)
    assert results["call_success_rate"]["display_status"] == "fail"
    assert results["call_success_rate"]["breach_count"] == 1
    assert results["call_attempts"]["display_status"] == "neutral"
    assert metadata["unclassified_metrics"] == []


def test_kpi_call_normalizes_synonyms_and_keeps_near_name_unclassified(tmp_path: Path) -> None:
    from app.inspectors.registry import registry
    from app.services.executor import RuleContext

    registered_content = _content(
        ["呼叫请求次数", "呼叫请求成功次数", "呼叫请求失败次数"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 100, 95, 5]],
    )
    synonym_content = _content(
        ["呼叫请求", "请求成功", "请求失败", "近似呼叫请求"],
        [[15, "2026-09-01 10:15:00", "2026-09-01 10:30:00", 40, 38, 2, 66]],
    )
    _write(tmp_path, "kpi/kpi-call-15.csv", registered_content)
    _write(tmp_path, "kpi/sub/kpi-call-15.csv", synonym_content)
    ctx = RuleContext(task_id="kpi-test", data_dir=tmp_path, log=lambda *args, **kwargs: None)
    ctx.files = [Path("kpi/kpi-call-15.csv"), Path("kpi/sub/kpi-call-15.csv")]
    result = registry.get("kpi.call").run(ctx)
    metadata = result.metadata
    results = {item["key"]: item for item in metadata["kpi_results"]}

    assert results["call_attempts"]["main_value"] == 140.0
    assert results["call_success_count"]["main_value"] == 133.0
    assert results["call_failure_count"]["main_value"] == 7.0
    unclassified = {item["source_name"]: item for item in metadata["unclassified_metrics"]}
    assert set(unclassified) == {"近似呼叫请求"}
    assert unclassified["近似呼叫请求"]["record_count"] == 1
    assert unclassified["近似呼叫请求"]["sample_values"] == [66.0]
    assert unclassified["近似呼叫请求"]["source_files"] == ["kpi/sub/kpi-call-15.csv"]
