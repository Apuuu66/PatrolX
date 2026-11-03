"""alarm.recurrence 规则契约测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.inspectors.alarm.recurrence import inspector
from app.models.schemas import RuleStatus
from app.services.unit_runtime import RuleContext

HEADER = (
    "Serial No.,App Name,Alarm ID,Alarm Name,Alarm Severity,Raised Time,Cleared Time,"
    "Whether Cleared,Repeat Times,Location Info,Additional Information\n"
)
METRIC_KEYS = (
    "matched_files",
    "valid_lifecycles",
    "alarm_types",
    "multi_lifecycle_types",
    "repeat_reporting_types",
    "short_alarm_types",
    "rapid_recurrence_types",
    "reset_cleared_lifecycles",
    "repeat_positive_lifecycles",
    "raw_repeat_times_total",
    "estimated_reports_total",
)


def _ctx(tmp_path: Path, files: dict[str, str | bytes]) -> RuleContext:
    alarm_dir = tmp_path / "alarm"
    alarm_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, payload in files.items():
        path = alarm_dir / name
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(payload, encoding="utf-8")
        paths.append(Path("alarm") / name)
    ctx = RuleContext(task_id="task-recurrence", data_dir=tmp_path, log=lambda *args, **kwargs: None)
    ctx.files = paths
    return ctx


def _run(tmp_path: Path, files: dict[str, str | bytes]):
    return inspector.run(_ctx(tmp_path, files))


def test_recurrence_contract_aggregates_types_objects_flags_and_metrics(tmp_path: Path) -> None:
    payload = HEADER + (
        "1,App A,1001,Flapping A,Critical,2026-10-01 10:00:00,2026-10-01 10:01:00,Normal Cleared,2,Pod Name=pod-a,\n"
        "2,App A,1001,Flapping A,Critical,2026-10-01 10:02:00,2026-10-01 10:03:00,Normal Cleared,0,Pod Name=pod-a,\n"
        "3,App A,1001,Flapping A,Critical,2026-10-01 10:04:00,,Not Cleared,1,Pod Name=pod-b,\n"
        "4,App A,1002,Multi only,High,2026-10-01 10:00:00,,Not Cleared,0,Pod Name=pod-c,\n"
        "5,App A,1002,Multi only,High,2026-10-01 10:20:00,,Not Cleared,0,Pod Name=pod-c,\n"
        "6,App B,2001,Reset only,Low,2026-10-01 10:00:00,2026-10-01 10:00:10,Reset Cleared,0,Pod Name=pod-d,\n"
        "7,App B,2002,Stable,Medium,2026-10-01 10:00:00,2026-10-01 10:10:00,Normal Cleared,0,Pod Name=pod-e,\n"
    )
    result = _run(tmp_path, {"alarm.csv": payload})
    metadata = result.metadata["alarm_recurrence"]

    assert inspector.code == "alarm.recurrence"
    assert inspector.rule_version == "1.0.0"
    assert inspector.source_refs == ["alarm_all"]
    assert result.status == RuleStatus.FAIL
    assert tuple(metric.key for metric in result.metrics) == METRIC_KEYS
    assert {metric.key: metric.value for metric in result.metrics} == {
        "matched_files": 1,
        "valid_lifecycles": 7,
        "alarm_types": 4,
        "multi_lifecycle_types": 2,
        "repeat_reporting_types": 1,
        "short_alarm_types": 2,
        "rapid_recurrence_types": 1,
        "reset_cleared_lifecycles": 1,
        "repeat_positive_lifecycles": 2,
        "raw_repeat_times_total": 3,
        "estimated_reports_total": 10,
    }
    assert metadata["schema_version"] == 1
    assert metadata["scope"]["direct_alarm_csv_only"] is True
    assert metadata["scope"]["stable_recovery_inferred"] is False
    assert metadata["parameters"] == {
        "short_alarm_sec": 300,
        "rapid_recurrence_window_sec": 3600,
        "rapid_recurrence_min_count": 3,
        "parameter_source": "default",
    }
    assert metadata["status_counts"] == {
        "Not Cleared": 3,
        "Normal Cleared": 3,
        "Reset Cleared": 1,
        "Unknown": 0,
    }
    assert metadata["severity_counts"] == {
        "CRITICAL": 3,
        "HIGH": 2,
        "MEDIUM": 1,
        "LOW": 1,
        "UNKNOWN": 0,
    }
    assert [item["alarm_id"] for item in metadata["types"]] == ["1001", "1002", "2001", "2002"]
    first = metadata["types"][0]
    assert first["flags"] == {
        "multi_lifecycle": True,
        "repeat_reporting": True,
        "short_alarm": True,
        "rapid_recurrence": True,
        "reset_cleared": False,
    }
    assert first["lifecycle_count"] == 3
    assert first["raw_repeat_times_total"] == 3
    assert first["estimated_report_total"] == 6
    assert first["object_count"] == 2
    assert [item["object"] for item in first["objects"]] == ["pod-a", "pod-b"]
    assert first["min_adjacent_gap_sec"] == 120
    expected_type_key = "alarm.recurrence:" + hashlib.sha256(b"App A\0" + b"1001").hexdigest()[:16]
    assert first["type_key"] == expected_type_key
    assert metadata["quality"]["repeat_totals_complete"] is True
    assert len(result.findings) == 3
    first_finding = result.findings[0]
    assert "lifecycle_count=3" in (first_finding.evidence or "")
    assert "raw_repeat_times_total=3" in (first_finding.evidence or "")
    assert "short_alarm=true" in (first_finding.evidence or "")


def test_recurrence_invalid_repeat_values_remaining_records_still_contribute(tmp_path: Path) -> None:
    payload = HEADER + (
        "1,App A,3001,Unknown repetitions,High,2026-10-01 10:00:00,"
        "2026-10-01 10:00:10,Normal Cleared,not-int,Pod Name=pod-a,\n"
        "2,App A,3001,Unknown repetitions,High,2026-10-01 10:01:00,,Not Cleared,0,Pod Name=pod-a,\n"
    )
    result = _run(tmp_path, {"alarm.csv": payload})
    metadata = result.metadata["alarm_recurrence"]

    assert result.status == RuleStatus.WARN
    assert metadata["quality"]["invalid_repeat_times_rows"] == 1
    assert metadata["quality"]["repeat_totals_complete"] is False
    first = metadata["types"][0]
    assert first["lifecycle_count"] == 2
    assert first["repeat_totals_complete"] is False
    assert first["flags"]["multi_lifecycle"] is True
    assert first["flags"]["short_alarm"] is True


def test_recurrence_skip_for_no_files_or_no_valid_records(tmp_path: Path) -> None:
    no_files = inspector.run(RuleContext(task_id="empty", data_dir=tmp_path, log=lambda *args, **kwargs: None))
    assert no_files.status == RuleStatus.SKIP
    assert no_files.skip_reason == "未发现 alarm/ 直属 CSV 告警文件"

    invalid = _run(
        tmp_path / "invalid",
        {"alarm.csv": HEADER + "1,App A,1,Bad,High,not-a-time,,Not Cleared,0,Pod Name=pod-a,\n"},
    )
    assert invalid.status == RuleStatus.SKIP
    assert invalid.skip_reason == "告警 CSV 无可分析记录"
    assert invalid.metadata["alarm_recurrence"]["quality"]["invalid_raised_time_rows"] == 1

    inapplicable = _run(
        tmp_path / "inapplicable",
        {"alarm.csv": "not,an,alarm,header\n1,2,3,4\n"},
    )
    assert inapplicable.status == RuleStatus.SKIP
    assert inapplicable.skip_reason == "告警 CSV 格式不适用"
    assert inapplicable.metadata["alarm_recurrence"]["files"][0]["error_code"] == "format_invalid"


def test_recurrence_failed_file_degrades_to_warn_with_stable_metrics(tmp_path: Path) -> None:
    payload = HEADER + (
        "1,App A,1,Stable,High,2026-10-01 10:00:00,2026-10-01 10:10:00,Normal Cleared,0,Pod Name=pod-a,\n"
    )
    result = _run(tmp_path, {"good.csv": payload, "bad.csv": b"\xff\xfe\x00broken"})
    assert result.status == RuleStatus.WARN
    assert tuple(metric.key for metric in result.metrics) == METRIC_KEYS
    assert result.metadata["alarm_recurrence"]["totals"]["failed_files"] == 1


def test_recurrence_rapid_window_and_short_alarm_boundaries(tmp_path: Path) -> None:
    exactly_window = HEADER + (
        "1,App A,1,Boundary,High,2026-10-01 10:00:00,2026-10-01 10:05:00,Normal Cleared,0,Pod Name=pod-a,\n"
        "2,App A,1,Boundary,High,2026-10-01 10:30:00,2026-10-01 10:35:00,Normal Cleared,0,Pod Name=pod-a,\n"
        "3,App A,1,Boundary,High,2026-10-01 11:00:00,2026-10-01 11:05:00,Normal Cleared,0,Pod Name=pod-a,\n"
    )
    exact = _run(tmp_path / "exact", {"alarm.csv": exactly_window})
    exact_type = exact.metadata["alarm_recurrence"]["types"][0]
    assert exact_type["flags"]["rapid_recurrence"] is True
    assert exact_type["flags"]["short_alarm"] is True

    beyond_window = exactly_window.replace("2026-10-01 11:00:00", "2026-10-01 11:00:01").replace(
        "2026-10-01 11:05:00", "2026-10-01 11:05:01"
    )
    beyond = _run(tmp_path / "beyond", {"alarm.csv": beyond_window})
    assert beyond.metadata["alarm_recurrence"]["types"][0]["flags"]["rapid_recurrence"] is False

    just_over_short = HEADER + (
        "1,App A,2,Almost short,High,2026-10-01 10:00:00,2026-10-01 10:05:01,Normal Cleared,0,Pod Name=pod-a,\n"
    )
    over = _run(tmp_path / "over", {"alarm.csv": just_over_short})
    assert over.metadata["alarm_recurrence"]["types"][0]["flags"]["short_alarm"] is False


def test_recurrence_truncates_types_and_findings_but_keeps_totals(tmp_path: Path) -> None:
    rows = "".join(
        f"{index},App A,{5000 + index},Risky {index},High,2026-10-01 10:00:00,,Not Cleared,1,pod-{index},\n"
        for index in range(101)
    )
    result = _run(tmp_path, {"alarm.csv": HEADER + rows})
    metadata = result.metadata["alarm_recurrence"]

    assert metadata["totals"]["alarm_types"] == 101
    assert metadata["totals"]["types_truncated"] is True
    assert metadata["totals"]["findings_truncated"] is True
    assert len(metadata["types"]) == 100
    assert len(result.findings) == 100
    assert {metric.key: metric.value for metric in result.metrics}["alarm_types"] == 101


def test_recurrence_english_and_chinese_inputs_have_equivalent_semantics(tmp_path: Path) -> None:
    english = HEADER + (
        "1,App A,10,NTP sync failed,Critical,2026-10-01 10:00:00,,Not Cleared,5,Pod Name=pod-a,\n"
        "2,App A,11,Short reset,Major,2026-10-01 10:05:00,2026-10-01 10:10:00,Normal Cleared,0,Pod Name=pod-b,\n"
    )
    chinese = (
        "告警流水号,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,告警重复次数,定位信息,附加信息\n"
        "1,应用A,10,NTP同步失败,紧急,2026-10-01 10:00:00,,未清除,5,Pod Name=pod-a,\n"
        "2,应用A,11,短时复位,严重,2026-10-01 10:05:00,2026-10-01 10:10:00,正常清除,0,Pod Name=pod-b,\n"
    )
    en = _run(tmp_path / "en", {"alarm.csv": english})
    zh = _run(tmp_path / "zh", {"alarm.csv": chinese})

    assert {metric.key: metric.value for metric in en.metrics} == {metric.key: metric.value for metric in zh.metrics}
    assert en.status == zh.status
    assert en.metadata["alarm_recurrence"]["status_counts"] == zh.metadata["alarm_recurrence"]["status_counts"]
    assert en.metadata["alarm_recurrence"]["severity_counts"] == zh.metadata["alarm_recurrence"]["severity_counts"]
