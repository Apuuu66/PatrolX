"""告警 CSV 的集中映射与纯解析能力。

本模块只读取规则已匹配到的任务内文件并产出规范化记录；不构造
``RuleResult``、不写 prepared 数据，也不依赖任何其他告警规则。
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

OBJECT_UNKNOWN = "对象未识别"
APP_UNKNOWN = "应用未识别"
ALARM_ID_UNKNOWN = "告警ID未识别"
ALARM_NAME_UNKNOWN = "告警名称未识别"

SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
STATE_ORDER = ("Not Cleared", "Normal Cleared", "Reset Cleared", "Unknown")
ALARM_FLAGS = (
    "multi_lifecycle",
    "repeat_reporting",
    "short_alarm",
    "rapid_recurrence",
    "reset_cleared",
)

DEFAULT_MAX_FILE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_FILE_ROWS = 100_000
DEFAULT_MAX_TASK_ROWS = 250_000

_UTC_PLUS_8 = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class SourceRef:
    """任务内可追溯来源，不携带任务根目录或绝对路径。"""

    source_file: str
    line_no: int

    def as_dict(self) -> dict[str, str | int]:
        return {"source_file": self.source_file, "line_no": self.line_no}


@dataclass(slots=True)
class AlarmRecord:
    """一条有效告警生命周期。"""

    app_name: str
    alarm_id: str
    alarm_name: str
    severity: str
    state: str
    raised_at: datetime
    cleared_at: datetime | None
    duration_sec: int | None
    repeat_times: int | None
    object_key: str
    serial_no: str | None
    source_file: str
    line_no: int
    location_info: str | None = None
    additional_info: str | None = None

    @property
    def is_active(self) -> bool:
        return self.state == "Not Cleared"

    @property
    def estimated_report_count(self) -> int | None:
        return None if self.repeat_times is None else 1 + self.repeat_times

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(self.source_file, self.line_no)


@dataclass(frozen=True, slots=True)
class AlarmFileResult:
    """单文件解析结果；单文件失败不影响其他文件。"""

    source_file: str
    status: str
    rows: int
    valid_rows: int
    excluded_rows: int
    duplicate_rows: int
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "source_file": self.source_file,
            "status": self.status,
            "rows": self.rows,
            "valid_rows": self.valid_rows,
            "excluded_rows": self.excluded_rows,
            "duplicate_rows": self.duplicate_rows,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class AlarmQuality:
    """影响判定可信度的行级质量统计。"""

    excluded_rows: int = 0
    invalid_status_rows: int = 0
    unknown_status_values: Counter[str] = field(default_factory=Counter)
    unknown_severity_values: Counter[str] = field(default_factory=Counter)
    unknown_headers: Counter[str] = field(default_factory=Counter)
    invalid_raised_time_rows: int = 0
    invalid_cleared_time_rows: int = 0
    missing_cleared_time_rows: int = 0
    cleared_before_raised_rows: int = 0
    invalid_repeat_times_rows: int = 0
    missing_repeat_times_rows: int = 0
    missing_app_name_rows: int = 0
    missing_alarm_id_rows: int = 0
    missing_alarm_name_rows: int = 0
    missing_object_rows: int = 0
    repeat_totals_complete: bool = True
    estimated_report_totals_complete: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "excluded_rows": self.excluded_rows,
            "invalid_status_rows": self.invalid_status_rows,
            "unknown_status_values": dict(sorted(self.unknown_status_values.items())),
            "unknown_severity_values": dict(sorted(self.unknown_severity_values.items())),
            "unknown_headers": dict(sorted(self.unknown_headers.items())),
            "invalid_raised_time_rows": self.invalid_raised_time_rows,
            "invalid_cleared_time_rows": self.invalid_cleared_time_rows,
            "missing_cleared_time_rows": self.missing_cleared_time_rows,
            "cleared_before_raised_rows": self.cleared_before_raised_rows,
            "invalid_repeat_times_rows": self.invalid_repeat_times_rows,
            "missing_repeat_times_rows": self.missing_repeat_times_rows,
            "missing_app_name_rows": self.missing_app_name_rows,
            "missing_alarm_id_rows": self.missing_alarm_id_rows,
            "missing_alarm_name_rows": self.missing_alarm_name_rows,
            "missing_object_rows": self.missing_object_rows,
            "repeat_totals_complete": self.repeat_totals_complete,
            "estimated_report_totals_complete": self.estimated_report_totals_complete,
        }


@dataclass(frozen=True, slots=True)
class AlarmCoverage:
    """有效告警时间覆盖；末刻不是任务执行或恢复时刻。"""

    start_at: datetime | None
    end_at: datetime | None
    span_sec: int
    end_basis: str = "max_valid_alarm_timestamp"
    timezone_policy: str = "naive_as_utc+08:00_then_utc"
    observation_note: str = "coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻"

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "start_at": iso_or_none(self.start_at),
            "end_at": iso_or_none(self.end_at),
            "span_sec": self.span_sec,
            "end_basis": self.end_basis,
            "timezone_policy": self.timezone_policy,
            "observation_note": self.observation_note,
        }


@dataclass(slots=True)
class AlarmParseResult:
    """全部匹配文件的规范化解析结果。"""

    records: list[AlarmRecord]
    coverage: AlarmCoverage
    quality: AlarmQuality
    files: list[AlarmFileResult]
    raw_rows: int
    duplicate_rows: int
    budget_exceeded: bool
    budget_message: str | None
    status_counts: Counter[str]

    @property
    def valid_records(self) -> int:
        return len(self.records)


@dataclass(frozen=True, slots=True)
class _Header:
    positions: dict[str, int]
    unknown: tuple[str, ...]


# 表头映射是唯一扩展点。比较前会统一大小写、空白和常见分隔符。
def _normalize_token(value: str) -> str:
    return " ".join(value.replace("\ufeff", "").strip().lower().split())


_HEADER_ALIASES: dict[str, frozenset[str]] = {
    "serial_no": frozenset(
        {
            "serial no.",
            "serial no",
            "serial number",
            "serial",
            "告警流水号",
            "流水号",
            "序列号",
        }
    ),
    "app_id": frozenset({"app id", "应用id", "应用 ID"}),
    "app_name": frozenset({"app name", "application name", "应用名称", "应用名", "appname"}),
    "alarm_id": frozenset({"alarm id", "alarmid", "告警id", "告警 ID"}),
    "alarm_name": frozenset({"alarm name", "alarmname", "告警名称", "告警名", "告警标题"}),
    "severity": frozenset(
        {
            "alarm severity",
            "severity",
            "level",
            "alarm level",
            "告警级别",
            "告警等级",
            "级别",
        }
    ),
    "raised_at": frozenset(
        {
            "raised time",
            "raise time",
            "alarm time",
            "occurred time",
            "发生时间",
            "上报时间",
            "告警时间",
        }
    ),
    "cleared_at": frozenset(
        {
            "cleared time",
            "clear time",
            "recovered time",
            "清除时间",
            "恢复时间",
        }
    ),
    "state": frozenset(
        {
            "whether cleared",
            "cleared status",
            "alarm status",
            "status",
            "清除类型",
            "告警状态",
            "清除状态",
            "状态",
        }
    ),
    "repeat_times": frozenset(
        {
            "repeat times",
            "repeat count",
            "repetition times",
            "告警重复次数",
            "重复次数",
        }
    ),
    "location_info": frozenset({"location info", "location information", "location", "定位信息", "位置信息"}),
    "additional_info": frozenset(
        {
            "additional information",
            "additional info",
            "extra information",
            "附加信息",
            "扩展信息",
        }
    ),
    "pod_name": frozenset({"pod name", "pod", "podname", "pod名称", "实例名称"}),
    "located_device": frozenset({"located device", "device", "device name", "定位设备", "设备", "设备名称"}),
    "service_name": frozenset({"service name", "service", "服务名称", "服务"}),
    "alarm_source": frozenset({"alarm source", "alarm source name", "告警源", "告警来源", "告警源名称"}),
    "event_type": frozenset({"event type", "事件类型", "告警类型"}),
}

_KNOWN_HEADERS = frozenset(_normalize_token(alias) for aliases in _HEADER_ALIASES.values() for alias in aliases)
_REQUIRED_FIELDS = frozenset({"app_name", "alarm_id", "alarm_name", "severity", "raised_at", "state"})

_STATE_ALIASES = {
    "not cleared": "Not Cleared",
    "uncleared": "Not Cleared",
    "active": "Not Cleared",
    "未清除": "Not Cleared",
    "未恢复": "Not Cleared",
    "活动": "Not Cleared",
    "normal cleared": "Normal Cleared",
    "cleared": "Normal Cleared",
    "自动清除": "Normal Cleared",
    "手动清除": "Normal Cleared",
    "正常清除": "Normal Cleared",
    "已清除": "Normal Cleared",
    "reset cleared": "Reset Cleared",
    "reset": "Reset Cleared",
    "重置清除": "Reset Cleared",
    "清除重置": "Reset Cleared",
}

_SEVERITY_ALIASES = {
    "critical": "CRITICAL",
    "紧急": "CRITICAL",
    "致命": "CRITICAL",
    "major": "HIGH",
    "high": "HIGH",
    "严重": "HIGH",
    "重要": "MEDIUM",
    "medium": "MEDIUM",
    "minor": "LOW",
    "low": "LOW",
    "warning": "LOW",
    "warn": "LOW",
    "次要": "LOW",
}

_DIRECT_OBJECT_FIELDS = (
    ("pod_name", "Pod Name"),
    ("located_device", "Located Device"),
    ("service_name", "Service Name"),
    ("alarm_source", "Alarm Source"),
)

_OBJECT_KEY_PRIORITY = (
    _HEADER_ALIASES["pod_name"],
    _HEADER_ALIASES["located_device"],
    _HEADER_ALIASES["service_name"],
    _HEADER_ALIASES["alarm_source"],
)

_STRUCTURED_PAIR_BOUNDARY = re.compile(r"[;,]\s*(?=[\w][\w ()/.:%+-]{0,79}\s*=)")


def _resolve_header(raw_headers: Iterable[str]) -> _Header:
    positions: dict[str, int] = {}
    unknown: list[str] = []
    for index, raw in enumerate(raw_headers):
        display = raw.replace("\ufeff", "").strip()
        token = _normalize_token(display)
        if not token:
            continue
        if token not in _KNOWN_HEADERS:
            unknown.append(display)
            continue
        for field_name, aliases in _HEADER_ALIASES.items():
            if token in {_normalize_token(alias) for alias in aliases}:
                positions.setdefault(field_name, index)
                break
    return _Header(positions=positions, unknown=tuple(unknown))


def _cell(row: list[str], header: _Header, field_name: str) -> str:
    index = header.positions.get(field_name)
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def parse_alarm_time(value: str) -> datetime | None:
    """解析告警时间；无时区按 UTC+8 解释，输出统一为 UTC。"""
    text = value.strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in (
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M",
            "%Y%m%d%H%M%S",
        ):
            try:
                parsed = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC_PLUS_8)
    return parsed.astimezone(UTC)


def parse_repeat_times(value: str) -> int | None:
    """解析非负整数；空值和非法值均返回 ``None``，不猜 0。"""
    text = value.strip()
    if not text:
        return None
    if not text.isascii() or not text.isdigit():
        return None
    try:
        return int(text)
    except ValueError:
        return None


def normalize_object(
    location_info: str,
    additional_info: str,
    direct_objects: Iterable[tuple[str, str]] = (),
) -> str:
    """按 Pod → 设备 → 服务 → 告警源优先级解析结构化对象。"""
    pairs = list(direct_objects) + _object_pairs(location_info) + _object_pairs(additional_info)
    for aliases in _OBJECT_KEY_PRIORITY:
        for key, value in pairs:
            if _normalize_token(key) in aliases and value.strip():
                return _normalize_object_value(value)
    return OBJECT_UNKNOWN


def _object_pairs(value: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in _STRUCTURED_PAIR_BOUNDARY.split(value.replace("\n", ";")):
        if "=" not in part:
            continue
        key, item = part.split("=", 1)
        pairs.append((key.strip(), item.strip()))
    return pairs


def _normalize_object_value(value: str) -> str:
    normalized = value.strip()
    if normalized.isascii():
        return normalized.lower()
    return normalized


def _empty_quality() -> AlarmQuality:
    return AlarmQuality()


def _coverage(records: list[AlarmRecord]) -> AlarmCoverage:
    timestamps: list[datetime] = []
    for record in records:
        timestamps.append(record.raised_at)
        if record.cleared_at is not None:
            timestamps.append(record.cleared_at)
    if not timestamps:
        return AlarmCoverage(start_at=None, end_at=None, span_sec=0)
    start_at = min(record.raised_at for record in records)
    end_at = max(timestamps)
    return AlarmCoverage(
        start_at=start_at,
        end_at=end_at,
        span_sec=max(0, int((end_at - start_at).total_seconds())),
    )


def _read_text(path: Path) -> str:
    payload = path.read_bytes()
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as utf8_error:
        try:
            return payload.decode("gb18030")
        except UnicodeDecodeError:
            raise utf8_error from None


def parse_alarm_files(
    files: Iterable[tuple[str, Path]],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_file_rows: int = DEFAULT_MAX_FILE_ROWS,
    max_task_rows: int = DEFAULT_MAX_TASK_ROWS,
) -> AlarmParseResult:
    """解析匹配的告警 CSV；单文件失败、预算和质量问题均显式记录。"""
    records: list[AlarmRecord] = []
    files_result: list[AlarmFileResult] = []
    quality = _empty_quality()
    seen_rows: set[tuple[tuple[str, str], ...]] = set()
    raw_rows = 0
    duplicate_rows = 0
    task_rows = 0
    budget_exceeded = False
    budget_messages: list[str] = []
    task_stopped = False

    for source_file, path in files:
        if task_stopped:
            files_result.append(
                AlarmFileResult(
                    source_file=source_file,
                    status="budget_exceeded",
                    rows=0,
                    valid_rows=0,
                    excluded_rows=0,
                    duplicate_rows=0,
                    error_code="row_budget_exceeded",
                    error_message="任务累计行数达到预算，未继续读取",
                )
            )
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                files_result.append(
                    AlarmFileResult(
                        source_file=source_file,
                        status="budget_exceeded",
                        rows=0,
                        valid_rows=0,
                        excluded_rows=0,
                        duplicate_rows=0,
                        error_code="file_too_large",
                        error_message="告警文件超过单文件大小预算",
                    )
                )
                budget_exceeded = True
                budget_messages.append(f"{source_file} 超过单文件大小预算")
                continue
            text = _read_text(path)
            reader = csv.reader(io.StringIO(text, newline=""))
            raw_headers = next(reader, None)
            if raw_headers is None:
                raise ValueError("format_invalid")
            header = _resolve_header(raw_headers)
            missing = sorted(_REQUIRED_FIELDS - header.positions.keys())
            if missing:
                raise ValueError("format_invalid")
        except UnicodeDecodeError:
            files_result.append(
                AlarmFileResult(
                    source_file=source_file,
                    status="failed",
                    rows=0,
                    valid_rows=0,
                    excluded_rows=0,
                    duplicate_rows=0,
                    error_code="encoding_error",
                    error_message="告警文件编码无法解析",
                )
            )
            continue
        except (OSError, ValueError, csv.Error):
            files_result.append(
                AlarmFileResult(
                    source_file=source_file,
                    status="failed",
                    rows=0,
                    valid_rows=0,
                    excluded_rows=0,
                    duplicate_rows=0,
                    error_code="format_invalid",
                    error_message="告警 CSV 缺少必要表头或格式不适用",
                )
            )
            continue

        for unknown_header in header.unknown:
            quality.unknown_headers[unknown_header] += 1

        file_rows = 0
        file_valid = 0
        file_excluded = 0
        file_duplicates = 0
        file_budget_code: str | None = None

        try:
            for row in reader:
                if not row or all(not cell.strip() for cell in row):
                    continue
                if file_rows >= max_file_rows:
                    file_budget_code = "row_budget_exceeded"
                    budget_exceeded = True
                    budget_messages.append(f"{source_file} 超过单文件行数预算")
                    break
                if task_rows >= max_task_rows:
                    file_budget_code = "row_budget_exceeded"
                    budget_exceeded = True
                    budget_messages.append("任务累计告警行数超过预算")
                    task_stopped = True
                    break

                raw_rows += 1
                task_rows += 1
                file_rows += 1
                line_no = reader.line_num
                canonical = tuple(
                    sorted(
                        (
                            _normalize_token(raw_headers[index]) if index < len(raw_headers) else "",
                            value.strip(),
                        )
                        for index, value in enumerate(row)
                    )
                )
                if canonical in seen_rows:
                    duplicate_rows += 1
                    file_duplicates += 1
                    continue

                record, excluded = _parse_row(row, header, source_file, line_no, quality)
                if record is None or excluded:
                    file_excluded += 1
                    continue
                seen_rows.add(canonical)
                records.append(record)
                file_valid += 1
        except csv.Error:
            files_result.append(
                AlarmFileResult(
                    source_file=source_file,
                    status="failed",
                    rows=file_rows,
                    valid_rows=file_valid,
                    excluded_rows=file_excluded,
                    duplicate_rows=file_duplicates,
                    error_code="format_invalid",
                    error_message="告警 CSV 读取格式错误",
                )
            )
            continue

        status = "budget_exceeded" if file_budget_code else "matched"
        files_result.append(
            AlarmFileResult(
                source_file=source_file,
                status=status,
                rows=file_rows,
                valid_rows=file_valid,
                excluded_rows=file_excluded,
                duplicate_rows=file_duplicates,
                error_code=file_budget_code,
                error_message=("告警文件达到行数预算，已停止继续读取" if file_budget_code else None),
            )
        )

    status_counts = Counter({state: 0 for state in STATE_ORDER})
    status_counts.update(record.state for record in records)
    quality.repeat_totals_complete = not (quality.invalid_repeat_times_rows or quality.missing_repeat_times_rows)
    quality.estimated_report_totals_complete = quality.repeat_totals_complete
    return AlarmParseResult(
        records=records,
        coverage=_coverage(records),
        quality=quality,
        files=files_result,
        raw_rows=raw_rows,
        duplicate_rows=duplicate_rows,
        budget_exceeded=budget_exceeded,
        budget_message="；".join(dict.fromkeys(budget_messages)) or None,
        status_counts=status_counts,
    )


def _parse_row(
    row: list[str],
    header: _Header,
    source_file: str,
    line_no: int,
    quality: AlarmQuality,
) -> tuple[AlarmRecord | None, bool]:
    state_raw = _cell(row, header, "state")
    state = _STATE_ALIASES.get(_normalize_token(state_raw))
    if state is None:
        quality.invalid_status_rows += 1
        quality.excluded_rows += 1
        if state_raw:
            quality.unknown_status_values[state_raw] += 1
        return None, True

    severity_raw = _cell(row, header, "severity")
    severity = _SEVERITY_ALIASES.get(_normalize_token(severity_raw), "UNKNOWN")
    if severity == "UNKNOWN" and severity_raw:
        quality.unknown_severity_values[severity_raw] += 1

    raised_raw = _cell(row, header, "raised_at")
    raised_at = parse_alarm_time(raised_raw)
    if raised_at is None:
        quality.invalid_raised_time_rows += 1
        quality.excluded_rows += 1
        return None, True

    cleared_raw = _cell(row, header, "cleared_at")
    cleared_at = parse_alarm_time(cleared_raw)
    if cleared_raw and cleared_at is None:
        quality.invalid_cleared_time_rows += 1
    if state != "Not Cleared" and not cleared_raw:
        quality.missing_cleared_time_rows += 1

    duration_sec: int | None = None
    if cleared_at is not None:
        if cleared_at < raised_at:
            quality.cleared_before_raised_rows += 1
        else:
            duration_sec = int((cleared_at - raised_at).total_seconds())

    repeat_raw = _cell(row, header, "repeat_times")
    if repeat_raw:
        repeat_times = parse_repeat_times(repeat_raw)
        if repeat_times is None:
            quality.invalid_repeat_times_rows += 1
    elif "repeat_times" in header.positions:
        repeat_times = None
        quality.missing_repeat_times_rows += 1
    else:
        repeat_times = None
        quality.missing_repeat_times_rows += 1

    app_name = _cell(row, header, "app_name")
    if not app_name:
        app_name = APP_UNKNOWN
        quality.missing_app_name_rows += 1
    alarm_id = _cell(row, header, "alarm_id")
    if not alarm_id:
        alarm_id = ALARM_ID_UNKNOWN
        quality.missing_alarm_id_rows += 1
    alarm_name = _cell(row, header, "alarm_name")
    if not alarm_name:
        alarm_name = ALARM_NAME_UNKNOWN
        quality.missing_alarm_name_rows += 1

    location_info = _cell(row, header, "location_info")
    additional_info = _cell(row, header, "additional_info")
    direct_objects = tuple(
        (canonical_key, value)
        for field_name, canonical_key in _DIRECT_OBJECT_FIELDS
        if (value := _cell(row, header, field_name))
    )
    object_key = normalize_object(location_info, additional_info, direct_objects)
    if object_key == OBJECT_UNKNOWN:
        quality.missing_object_rows += 1

    serial_no = _cell(row, header, "serial_no") or None
    record = AlarmRecord(
        app_name=app_name,
        alarm_id=alarm_id,
        alarm_name=alarm_name,
        severity=severity,
        state=state,
        raised_at=raised_at,
        cleared_at=cleared_at,
        duration_sec=duration_sec,
        repeat_times=repeat_times,
        object_key=object_key,
        serial_no=serial_no,
        source_file=source_file,
        line_no=line_no,
        location_info=location_info or None,
        additional_info=additional_info or None,
    )
    return record, False


def iso_or_none(value: datetime | None) -> str | None:
    """输出稳定 UTC ISO-8601 字符串。"""
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def stable_hash(*values: str, prefix: str) -> str:
    """生成跨运行稳定、不含任务现场的身份键。"""
    import hashlib

    digest = hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}{digest}"
