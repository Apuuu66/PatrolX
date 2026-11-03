"""alarm.active_state 规则契约测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.inspectors.alarm.active_state import inspector
from app.models.schemas import RuleStatus
from app.services.unit_runtime import RuleContext

HEADER = (
    "Serial No.,App Name,Alarm ID,Alarm Name,Alarm Severity,Raised Time,Cleared Time,"
    "Whether Cleared,Repeat Times,Location Info,Additional Information\n"
)
METRIC_KEYS = (
    "active_alarm_records",
    "active_alarm_groups",
    "critical_active",
    "high_active",
    "medium_active",
    "low_active",
    "unknown_active",
    "active_repeat_times_total",
    "max_single_repeat_times",
    "active_estimated_reports_total",
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
    ctx = RuleContext(task_id="task-active", data_dir=tmp_path, log=lambda *args, **kwargs: None)
    ctx.files = paths
    return ctx


def _run(tmp_path: Path, files: dict[str, str | bytes]):
    return inspector.run(_ctx(tmp_path, files))


def test_active_rule_contract_metrics_summary_and_sorting(tmp_path: Path) -> None:
    payload = HEADER + (
        "1,App A,10,Low active,Minor,2026-10-01 10:20:00,,Not Cleared,0,Pod Name=pod-low,\n"
        "2,App A,11,Critical active,Critical,2026-10-01 10:00:00,,Not Cleared,5,Pod Name=pod-a,\n"
        "3,App A,12,High active,Major,2026-10-01 10:05:00,,Not Cleared,2,Located Device=node-b,\n"
        "4,App A,13,Cleared,Major,2026-10-01 10:10:00,2026-10-01 10:12:00,Normal Cleared,1,Located Device=node-c,\n"
        "5,App A,14,Reset,Minor,2026-10-01 10:01:00,2026-10-01 10:02:00,Reset Cleared,0,Located Device=node-d,\n"
        "6,App A,15,Unknown state,Major,2026-10-01 10:03:00,,已恢复,0,Located Device=node-e,\n"
        "7,App A,16,Bad raised,Critical,not-a-time,,Not Cleared,2,Located Device=node-f,\n"
    )
    result = _run(tmp_path, {"active.csv": payload})
    metadata = result.metadata["alarm_active"]

    assert inspector.code == "alarm.active_state"
    assert inspector.rule_version == "1.0.0"
    assert inspector.source_refs == ["alarm_all"]
    assert result.status == RuleStatus.FAIL
    assert tuple(metric.key for metric in result.metrics) == METRIC_KEYS
    assert {metric.unit for metric in result.metrics} == {"个", "次"}
    assert {metric.key: metric.value for metric in result.metrics} == {
        "active_alarm_records": 3,
        "active_alarm_groups": 3,
        "critical_active": 1,
        "high_active": 1,
        "medium_active": 0,
        "low_active": 1,
        "unknown_active": 0,
        "active_repeat_times_total": 7,
        "max_single_repeat_times": 5,
        "active_estimated_reports_total": 10,
    }
    assert metadata["schema_version"] == 1
    assert metadata["scope"] == {
        "source_patterns": [r"^alarm/[^/]+\.csv$"],
        "direct_alarm_csv_only": True,
        "operation_log_used": False,
        "cross_task_data_used": False,
    }
    assert metadata["coverage"]["end_at"] == "2026-10-01T02:20:00+00:00"
    assert metadata["coverage"]["end_basis"] == "max_valid_alarm_timestamp"
    assert metadata["totals"]["failed_files"] == 0
    assert metadata["totals"]["active_records"] == 3
    assert metadata["totals"]["active_groups"] == 3
    assert metadata["status_counts"] == {
        "Not Cleared": 3,
        "Normal Cleared": 1,
        "Reset Cleared": 1,
        "Unknown": 0,
    }
    assert metadata["active_severity_counts"] == {
        "CRITICAL": 1,
        "HIGH": 1,
        "MEDIUM": 0,
        "LOW": 1,
        "UNKNOWN": 0,
    }
    assert [group["alarm_id"] for group in metadata["groups"]] == ["11", "12", "10"]
    assert [record["alarm_id"] for record in metadata["records"]] == ["11", "12", "10"]
    assert metadata["groups"][0]["duration_sec"] == 1200
    assert metadata["active_summary"] == {
        "highest_severity": "CRITICAL",
        "raw_repeat_times_total": 7,
        "max_single_repeat_times": 5,
        "estimated_report_total": 10,
        "estimated_total_is_estimate": True,
    }
    assert metadata["quality"]["invalid_status_rows"] == 1
    assert metadata["quality"]["unknown_status_values"] == {"已恢复": 1}
    assert metadata["quality"]["invalid_raised_time_rows"] == 1
    assert len(result.findings) == 3
    assert result.findings[0].finding_id.startswith("alarm.active_state:")
    expected_finding_id = (
        "alarm.active_state:" + hashlib.sha256(metadata["groups"][0]["group_key"].encode("utf-8")).hexdigest()[:16]
    )
    assert result.findings[0].finding_id == expected_finding_id
    assert result.findings[0].source_file == "alarm/active.csv"
    assert "line_no=3" in (result.findings[0].evidence or "")
    assert "estimated_report_count=6" in (result.findings[0].evidence or "")


def test_active_rule_pass_below_threshold_and_quality_degrade(tmp_path: Path) -> None:
    medium = HEADER + "1,App A,20,Medium active,Medium,2026-10-01 10:00:00,,Not Cleared,0,Pod Name=pod-a,\n"
    medium_result = _run(tmp_path / "medium", {"alarm.csv": medium})
    assert medium_result.status == RuleStatus.WARN
    assert medium_result.metadata["alarm_active"]["active_summary"]["highest_severity"] == "MEDIUM"

    cleared = HEADER + (
        "1,App A,21,Cleared,High,2026-10-01 10:00:00,2026-10-01 10:01:00,Normal Cleared,0,Pod Name=pod-a,\n"
    )
    pass_result = _run(tmp_path / "pass", {"alarm.csv": cleared})
    assert pass_result.status == RuleStatus.PASS
    assert {metric.key: metric.value for metric in pass_result.metrics}["active_alarm_records"] == 0

    quality_result = _run(
        tmp_path / "quality",
        {
            "alarm.csv": cleared,
            "bad.csv": b"\xff\xfe\x00broken",
        },
    )
    assert quality_result.status == RuleStatus.WARN
    assert quality_result.metadata["alarm_active"]["totals"]["failed_files"] == 1
    assert "失败文件 1" in (quality_result.summary or "")


def test_active_rule_skip_for_no_files_or_no_valid_records(tmp_path: Path) -> None:
    no_files = inspector.run(RuleContext(task_id="empty", data_dir=tmp_path, log=lambda *args, **kwargs: None))
    assert no_files.status == RuleStatus.SKIP
    assert no_files.skip_reason == "未发现 alarm/ 直属 CSV 告警文件"

    no_valid = _run(
        tmp_path / "invalid",
        {"alarm.csv": HEADER + "1,App A,30,Bad,Major,not-a-time,,Not Cleared,0,Pod Name=pod-a,\n"},
    )
    assert no_valid.status == RuleStatus.SKIP
    assert no_valid.skip_reason == "告警 CSV 无可分析记录"
    assert no_valid.metadata["alarm_active"]["files"][0]["excluded_rows"] == 1

    inapplicable = _run(
        tmp_path / "inapplicable",
        {"alarm.csv": "not,an,alarm,header\n1,2,3,4\n"},
    )
    assert inapplicable.status == RuleStatus.SKIP
    assert inapplicable.skip_reason == "告警 CSV 格式不适用"
    assert inapplicable.metadata["alarm_active"]["files"][0]["error_code"] == "format_invalid"


def test_active_rule_truncates_details_and_findings_without_changing_totals(tmp_path: Path) -> None:
    rows = "".join(
        f"{index},App A,{1000 + index},Alarm {index},Critical,2026-10-01 10:00:00,,Not Cleared,0,pod-{index},\n"
        for index in range(101)
    )
    result = _run(tmp_path, {"alarm.csv": HEADER + rows})
    metadata = result.metadata["alarm_active"]

    assert metadata["totals"]["active_records"] == 101
    assert metadata["totals"]["active_groups"] == 101
    assert metadata["totals"]["details_truncated"] is True
    assert metadata["totals"]["findings_truncated"] is True
    assert len(metadata["groups"]) == 100
    assert len(metadata["records"]) == 100
    assert len(result.findings) == 100
    assert {metric.key: metric.value for metric in result.metrics}["active_alarm_records"] == 101


def test_active_rule_english_and_chinese_inputs_have_equivalent_semantics(tmp_path: Path) -> None:
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
    assert (
        en.metadata["alarm_active"]["active_severity_counts"] == zh.metadata["alarm_active"]["active_severity_counts"]
    )
    assert en.metadata["alarm_active"]["status_counts"] == zh.metadata["alarm_active"]["status_counts"]
