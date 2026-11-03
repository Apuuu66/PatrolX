"""告警公共纯解析器契约测试。"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from app.inspectors.alarm.common import (
    OBJECT_UNKNOWN,
    SEVERITY_ORDER,
    STATE_ORDER,
    normalize_object,
    parse_alarm_files,
)

HEADER_EN = (
    "Serial No.,App Name,Alarm ID,Alarm Name,Alarm Severity,Raised Time,Cleared Time,"
    "Whether Cleared,Repeat Times,Location Info,Additional Information\n"
)
HEADER_ZH = "告警流水号,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,告警重复次数,定位信息,附加信息\n"


def _write(path: Path, payload: str | bytes, *, encoding: str = "utf-8") -> Path:
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding=encoding)
    return path


def _rows(result, field: str) -> list[object]:
    return [getattr(record, field) for record in result.records]


def test_headers_bom_language_time_and_object_are_normalized(tmp_path: Path) -> None:
    english = _write(
        tmp_path / "english.csv",
        "\ufeff  sErIaL nO.  , app name ,ALARM ID,Alarm Name, Alarm Severity ,Raised Time,Cleared Time,"
        "Whether Cleared,Repeat Times,Location Info,Additional Information\n"
        "1,App A,10,NTP sync failed,Critical,2026-10-01 10:00:00,,Not Cleared,5,"
        "Pod Name=pod-a; Located Device=node-a,Service Name=svc-a\n"
        "2,App A,11,Short reset,Major,2026-10-01T02:05:00Z,2026-10-01T02:10:00Z,Normal Cleared,0,"
        "Located Device=node-b,\n"
        "3,App A,12,Unknown object,Minor,2026-10-01 10:15:00,,Reset Cleared,1,,free text only\n",
        encoding="utf-8-sig",
    )
    chinese = _write(
        tmp_path / "chinese.csv",
        HEADER_ZH
        + "1,应用A,10,NTP同步失败,紧急,2026-10-01 10:00:00,,未清除,5,Pod Name=Pod-A,Service Name=服务A\n"
        + "2,应用A,11,短时复位,严重,2026-10-01 10:05:00,2026-10-01 10:10:00,正常清除,0,定位设备=节点B,\n"
        + "3,应用A,12,对象缺失,次要,2026-10-01 10:15:00,,重置清除,1,,\n",
    )

    en = parse_alarm_files([("alarm/english.csv", english)])
    zh = parse_alarm_files([("alarm/chinese.csv", chinese)])

    assert en.records[0].raised_at.isoformat() == "2026-10-01T02:00:00+00:00"
    assert en.records[1].raised_at.isoformat() == "2026-10-01T02:05:00+00:00"
    assert _rows(en, "state") == ["Not Cleared", "Normal Cleared", "Reset Cleared"]
    assert _rows(en, "severity") == ["CRITICAL", "HIGH", "LOW"]
    assert _rows(en, "object_key") == ["pod-a", "node-b", OBJECT_UNKNOWN]
    assert _rows(zh, "state") == ["Not Cleared", "Normal Cleared", "Reset Cleared"]
    assert _rows(zh, "severity") == ["CRITICAL", "HIGH", "LOW"]
    assert _rows(zh, "object_key") == ["pod-a", "节点B", OBJECT_UNKNOWN]
    assert set(en.quality.unknown_headers) == set()
    assert set(zh.quality.unknown_headers) == set()
    assert tuple(SEVERITY_ORDER) == ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
    assert tuple(STATE_ORDER) == ("Not Cleared", "Normal Cleared", "Reset Cleared", "Unknown")


def test_header_aliases_with_internal_spaces_are_normalized_before_matching(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "spaced-chinese-headers.csv",
        "告警流水号,应用 ID,应用名称,告警 ID,告警名称,告警级别,发生时间,清除时间,"
        "清除类型,告警重复次数,定位信息,附加信息\n"
        "1,app-a,应用A,10,NTP同步失败,紧急,2026-10-01 10:00:00,,未清除,0,Pod Name=pod-a,\n",
    )

    result = parse_alarm_files([("alarm/spaced-chinese-headers.csv", path)])

    assert result.files[0].status == "matched"
    assert [record.alarm_id for record in result.records] == ["10"]
    assert set(result.quality.unknown_headers) == set()


def test_unknown_state_is_excluded_and_unknown_values_are_audited(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "unknown.csv",
        HEADER_EN.replace(",Additional Information", ",Custom Column,Additional Information")
        + "1,App A,10,Known alarm,提示,2026-10-01 10:00:00,,Not Cleared,1,Pod Name=pod-a,,x\n"
        + "2,App A,11,Unknown state,Critical,2026-10-01 10:01:00,,已恢复,1,Pod Name=pod-a,,x\n",
    )

    result = parse_alarm_files([("alarm/unknown.csv", path)])

    assert len(result.records) == 1
    assert result.records[0].severity == "UNKNOWN"
    assert result.quality.excluded_rows == 1
    assert result.quality.invalid_status_rows == 1
    assert result.quality.unknown_status_values == {"已恢复": 1}
    assert result.quality.unknown_severity_values == {"提示": 1}
    assert result.quality.unknown_headers == {"Custom Column": 1}
    assert result.quality.repeat_totals_complete
    assert STATE_ORDER[-1] in result.status_counts


def test_cross_file_exact_duplicates_are_removed_but_lifecycle_differences_are_kept(tmp_path: Path) -> None:
    duplicate = "1,App A,10,Repeated alarm,Critical,2026-10-01 10:00:00,,Not Cleared,2,pod-a\n"
    first = _write(tmp_path / "first.csv", HEADER_EN + duplicate + duplicate)
    second = _write(
        tmp_path / "second.csv",
        HEADER_EN + duplicate + "2,App A,10,Repeated alarm,Critical,2026-10-01 10:03:00,,Not Cleared,0,pod-a\n",
    )

    result = parse_alarm_files([("alarm/first.csv", first), ("alarm/second.csv", second)])

    assert result.raw_rows == 4
    assert result.valid_records == 2
    assert result.duplicate_rows == 2
    assert result.quality.excluded_rows == 0
    assert result.files[0].duplicate_rows == 1
    assert result.files[1].duplicate_rows == 1
    assert [record.raised_at.minute for record in result.records] == [0, 3]


def test_bad_times_and_repeat_values_are_counted_without_guessing(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "quality.csv",
        HEADER_EN
        + "1,,,,Critical,not-a-time,,Not Cleared,1,pod-a\n"
        + "2,App A,10,Invalid clear,Normal,2026-10-01 10:00:00,not-a-time,Normal Cleared,1,pod-a\n"
        + "3,App A,11,Backwards,High,2026-10-01 10:05:00,2026-10-01 10:04:00,Normal Cleared,-1,pod-a\n"
        + "4,App A,12,Missing repeats,Medium,2026-10-01 10:06:00,,Normal Cleared,,pod-a\n",
    )

    result = parse_alarm_files([("alarm/quality.csv", path)])

    assert len(result.records) == 3
    assert result.quality.excluded_rows == 1
    assert result.quality.invalid_raised_time_rows == 1
    assert result.quality.invalid_cleared_time_rows == 1
    assert result.quality.cleared_before_raised_rows == 1
    assert result.quality.invalid_repeat_times_rows == 1
    assert result.quality.missing_repeat_times_rows == 1
    assert result.quality.repeat_totals_complete is False
    assert result.quality.estimated_report_totals_complete is False
    assert result.records[0].duration_sec is None
    assert result.records[1].duration_sec is None
    assert result.records[1].repeat_times is None
    assert result.records[2].repeat_times is None


def test_out_of_range_repeat_digits_are_audited_as_invalid(tmp_path: Path) -> None:
    oversized_repeat = "9" * 5000
    path = _write(
        tmp_path / "oversized-repeat.csv",
        HEADER_EN + f"1,App A,10,Oversized repeat,High,2026-10-01 10:00:00,,Not Cleared,{oversized_repeat},pod-a\n",
    )

    result = parse_alarm_files([("alarm/oversized-repeat.csv", path)])

    assert len(result.records) == 1
    assert result.records[0].repeat_times is None
    assert result.quality.invalid_repeat_times_rows == 1
    assert result.quality.repeat_totals_complete is False


def test_single_file_failure_is_isolated_and_format_errors_are_explicit(tmp_path: Path) -> None:
    good = _write(
        tmp_path / "good.csv",
        HEADER_EN + "1,App A,10,Good alarm,High,2026-10-01 10:00:00,,Not Cleared,0,pod-a\n",
    )
    bad = _write(tmp_path / "bad.csv", b"\xff\xfe\x00broken")
    invalid = _write(tmp_path / "invalid.csv", "not,an,alarm,header\n1,2,3,4\n")

    result = parse_alarm_files([("alarm/bad.csv", bad), ("alarm/invalid.csv", invalid), ("alarm/good.csv", good)])

    assert [record.alarm_id for record in result.records] == ["10"]
    statuses = {item.source_file: item.status for item in result.files}
    assert statuses == {
        "alarm/bad.csv": "failed",
        "alarm/invalid.csv": "failed",
        "alarm/good.csv": "matched",
    }
    assert result.files[0].error_code == "encoding_error"
    assert result.files[1].error_code == "format_invalid"


def test_csv_reader_error_is_isolated_as_format_failure(tmp_path: Path) -> None:
    good = _write(
        tmp_path / "good.csv",
        HEADER_EN + "1,App A,10,Good alarm,High,2026-10-01 10:00:00,,Not Cleared,0,pod-a\n",
    )
    oversized_cell = "x" * (csv.field_size_limit() + 1)
    malformed = _write(
        tmp_path / "malformed.csv",
        HEADER_EN + f"1,App A,11,Malformed,High,2026-10-01 10:00:00,,Not Cleared,0,{oversized_cell}\n",
    )

    result = parse_alarm_files([("alarm/malformed.csv", malformed), ("alarm/good.csv", good)])

    assert [record.alarm_id for record in result.records] == ["10"]
    assert result.files[0].status == "failed"
    assert result.files[0].error_code == "format_invalid"
    assert result.files[1].status == "matched"


def test_file_and_task_budgets_stop_resource_use_and_report_degradation(tmp_path: Path) -> None:
    rows = "".join(
        f"{index},App A,10,Alarm,High,2026-10-01 10:00:{index % 60:02d},,Not Cleared,0,pod-a\n" for index in range(1, 4)
    )
    limited = _write(tmp_path / "limited.csv", HEADER_EN + rows)
    result = parse_alarm_files([("alarm/limited.csv", limited)], max_file_rows=2)
    assert len(result.records) == 2
    assert result.budget_exceeded
    assert result.files[0].status == "budget_exceeded"
    assert result.files[0].error_code == "row_budget_exceeded"

    second = _write(tmp_path / "second.csv", HEADER_EN + rows)
    task_limited = parse_alarm_files(
        [("alarm/limited.csv", limited), ("alarm/second.csv", second)],
        max_file_rows=100,
        max_task_rows=2,
    )
    assert len(task_limited.records) == 2
    assert task_limited.budget_exceeded
    assert sum(item.rows for item in task_limited.files) == 2

    oversized = tmp_path / "oversized.csv"
    oversized.write_bytes(HEADER_EN.encode("utf-8"))
    with oversized.open("ab") as handle:
        handle.truncate(32 * 1024 * 1024 + 1)
    size_limited = parse_alarm_files([("alarm/oversized.csv", oversized)])
    assert size_limited.records == []
    assert size_limited.files[0].status == "budget_exceeded"
    assert size_limited.files[0].error_code == "file_too_large"


def test_5000_row_parse_stays_within_guardrail(tmp_path: Path) -> None:
    path = tmp_path / "large.csv"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(HEADER_EN)
        for index in range(5000):
            handle.write(
                f"{index},App A,{index % 50},Alarm {index % 50},High,2026-10-01 10:00:00,,Not Cleared,0,pod-a\n"
            )

    started = time.perf_counter()
    result = parse_alarm_files([("alarm/large.csv", path)])
    elapsed = time.perf_counter() - started

    assert len(result.records) == 5000
    assert elapsed < 5.0


def test_object_alarm_source_is_supported_and_free_text_uses_stable_placeholder() -> None:
    assert normalize_object("Alarm Source=bmc-1", "") == "bmc-1"
    assert normalize_object("告警源=告警源A", "") == "告警源A"
    assert normalize_object("", "Alarm Source=bmc-2") == "bmc-2"
    assert normalize_object("free-form mutable location", "some additional text") == OBJECT_UNKNOWN


def test_comma_separated_object_fields_are_parsed_as_independent_pairs() -> None:
    location = "Located Device=chassis-0/SMM,DeviceType=Blade,EventName=Failed to Interconnect with device"

    assert normalize_object(location, "") == "chassis-0/smm"


def test_free_text_prefix_does_not_hide_comma_separated_object_field() -> None:
    location = "umfservice,pod name=umf-pod-1,alarm cause=some failure"

    assert normalize_object(location, "") == "umf-pod-1"


def test_commas_inside_an_object_value_are_not_treated_as_field_boundaries() -> None:
    location = "Located Device=chassis-0/SMM, backplane,DeviceType=Blade"

    assert normalize_object(location, "") == "chassis-0/smm, backplane"


def test_direct_object_columns_follow_structured_priority_and_chinese_aliases(tmp_path: Path) -> None:
    english = _write(
        tmp_path / "direct-objects.csv",
        "Serial No.,App Name,Alarm ID,Alarm Name,Alarm Severity,Raised Time,Cleared Time,"
        "Whether Cleared,Repeat Times,Location Info,Additional Information,"
        "Pod Name,Located Device,Service Name,Alarm Source\n"
        "1,App A,10,Pod and source,Critical,2026-10-01 10:00:00,,Not Cleared,0,,,pod-a,,,bmc-1\n"
        "2,App A,11,Device only,High,2026-10-01 10:01:00,,Not Cleared,0,,, ,node-b,,\n"
        "3,App A,12,Service only,Medium,2026-10-01 10:02:00,,Not Cleared,0,,,,svc-c,\n"
        "4,App A,13,Source only,Low,2026-10-01 10:03:00,,Not Cleared,0,,,,,bmc-2\n",
    )
    chinese = _write(
        tmp_path / "direct-chinese.csv",
        "告警流水号,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,"
        "告警重复次数,定位信息,附加信息,告警源\n"
        "1,应用A,10,中文告警源,紧急,2026-10-01 10:00:00,,未清除,0,,,告警源A\n",
    )

    en = parse_alarm_files([("alarm/direct-objects.csv", english)])
    zh = parse_alarm_files([("alarm/direct-chinese.csv", chinese)])

    assert _rows(en, "object_key") == ["pod-a", "node-b", "svc-c", "bmc-2"]
    assert _rows(zh, "object_key") == ["告警源A"]
    assert en.quality.missing_object_rows == 0
    assert zh.quality.missing_object_rows == 0
    assert set(en.quality.unknown_headers) == set()
    assert set(zh.quality.unknown_headers) == set()
