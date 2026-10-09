"""alarm.flapping（P1）：告警生命周期与闪断检测。

规则只依赖自身 source_patterns 匹配到的告警文件：按 ``alarm_code + object`` 分组，
计算出现次数、首末时间、持续时长、复发间隔与闪断事件，并输出六态主状态。
恢复结论只基于清除时间与观察窗，``status`` 字段仅作展示。
"""

from __future__ import annotations

import csv
import io
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.encoding import read_text_with_fallback
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.unit_runtime import RuleContext, make_result

ASSUMED_LOCAL_TZ = timezone(timedelta(hours=8))

FINDINGS_MAX = 20
GROUPS_MAX = 500

# 参数默认值唯一事实来源；inspector.params 与运行时策略都由该表生成。
# 参数默认值必须是字符串：`InspectorInfo.params` 契约为 list[dict[str, str]]，
# 类型化取值统一由 `resolve_policy()` 解析，避免 API 序列化 InspectorInfo 时失败。
FLAPPING_PARAM_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("short_alarm_sec", "短告警阈值（秒）", "300"),
    ("repeat_window_sec", "复发窗口（秒）", "3600"),
    ("min_repeat_count", "最小复发次数", "3"),
    ("flap_gap_sec", "闪断间隔阈值（秒）", "1800"),
    ("stable_observation_sec", "稳定观察窗（秒）", "1800"),
    ("operation_window", "操作窗（本地时间）", "00:00-02:00"),
    ("operation_window_enabled", "操作窗标注开关", "true"),
)

METRIC_LABELS: tuple[tuple[str, str, str], ...] = (
    ("alarm_groups", "告警分组数", "个"),
    ("flapping_groups", "闪断分组数", "个"),
    ("uncleared_repeated_groups", "未清除反复分组数", "个"),
    ("short_alarm_groups", "短告警分组数", "个"),
    ("stable_groups", "稳定分组数", "个"),
    ("observation_insufficient_groups", "观察窗不足分组数", "个"),
    ("out_of_window_groups", "窗口外再现分组数", "个"),
    ("unrecovered_after_window_groups", "窗口后仍未恢复分组数", "个"),
    ("excluded_rows", "被排除行数", "行"),
    ("duplicate_rows", "重复行数", "行"),
    ("failed_files", "解析失败文件数", "个"),
)

STATES: tuple[str, ...] = (
    "uncleared_repeated",
    "uncleared_single",
    "cleared_repeated",
    "cleared_short",
    "observation_insufficient",
    "cleared_stable",
)

STATE_LABELS: dict[str, str] = {
    "uncleared_repeated": "未清除且反复",
    "uncleared_single": "未清除未反复",
    "cleared_repeated": "已清除但反复",
    "cleared_short": "已清除但短告警",
    "observation_insufficient": "观察窗不足",
    "cleared_stable": "已清除且稳定",
}

FINDING_SEVERITY: dict[str, Severity] = {
    "uncleared_repeated": Severity.CRITICAL,
    "cleared_repeated": Severity.HIGH,
    "cleared_short": Severity.MEDIUM,
}

inspector = Inspector(
    code="alarm.flapping",
    name="告警闪断检测",
    category=RuleCategory.ALARM,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description=(
        "按 alarm_code + object 分组计算告警生命周期：识别短告警、反复闪断与未清除告警，"
        "并只在清除后观察窗充足且无复发时判为稳定恢复"
    ),
    recommendation="优先处置未清除且反复的告警，其次核查清除后闪断再现的分组，确认根因消除后再关闭",
    source_refs=["alarm_all"],
    outputs_metrics=[{"key": key, "label": label, "unit": unit} for key, label, unit in METRIC_LABELS],
    params=[{"key": key, "label": label, "default": default} for key, label, default in FLAPPING_PARAM_DEFAULTS],
)


@dataclass(slots=True, frozen=True)
class FlappingPolicy:
    """判定策略；取值来自 ``inspector.params`` 默认表。"""

    short_alarm_sec: int
    repeat_window_sec: int
    min_repeat_count: int
    flap_gap_sec: int
    stable_observation_sec: int
    operation_window: str
    operation_window_enabled: bool

    @property
    def parameter_source(self) -> str:
        return "inspector_default"


@dataclass(slots=True)
class AlarmRecord:
    """解析后的单条告警记录（内部实体）。"""

    alarm_id: str
    created_at: datetime
    cleared_at: datetime | None
    alarm_code: str
    object: str
    severity: str
    status: str
    description: str
    source_file: str
    line_no: int
    source_format: str


@dataclass(slots=True)
class ParseOutcome:
    """解析结果与行级/文件级隔离计数。"""

    records: list[AlarmRecord] = field(default_factory=list)
    total_rows: int = 0
    excluded_rows: int = 0
    duplicate_rows: int = 0
    failed_files: int = 0
    excluded_reasons: dict[str, int] = field(default_factory=dict)

    def exclude(self, reason: str) -> None:
        self.excluded_rows += 1
        self.excluded_reasons[reason] = self.excluded_reasons.get(reason, 0) + 1


def resolve_policy() -> FlappingPolicy:
    """从规则参数声明解析本次生效策略。"""
    defaults: dict[str, Any] = {item["key"]: item["default"] for item in inspector.params}
    enabled = defaults["operation_window_enabled"]
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}
    return FlappingPolicy(
        short_alarm_sec=int(defaults["short_alarm_sec"]),
        repeat_window_sec=int(defaults["repeat_window_sec"]),
        min_repeat_count=int(defaults["min_repeat_count"]),
        flap_gap_sec=int(defaults["flap_gap_sec"]),
        stable_observation_sec=int(defaults["stable_observation_sec"]),
        operation_window=str(defaults["operation_window"]),
        operation_window_enabled=bool(enabled),
    )


def _parse_time(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    candidate = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(candidate, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ASSUMED_LOCAL_TZ)
    return parsed


_CSV_ALIASES: dict[str, tuple[str, ...]] = {
    "alarm_id": ("alarm_id", "id"),
    "created_time": ("created_time", "first_occurrence_time", "created_at"),
    "cleared_time": ("cleared_time", "clear_time", "cleared_at"),
    "alarm_code": ("alarm_code", "code"),
    "object": ("object", "object_name"),
    "severity": ("severity",),
    "status": ("status",),
    "description": ("description",),
}


def _pick(fields: dict[str, str], key: str) -> str:
    for alias in _CSV_ALIASES[key]:
        value = fields.get(alias)
        if value:
            return value
    return ""


def _parse_csv_rows(text: str, source_file: str) -> list[tuple[int, dict[str, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    reader = csv.reader(io.StringIO(text))
    header: list[str] = []
    for index, raw in enumerate(reader):
        if index == 0:
            header = [cell.strip().lower() for cell in raw]
            continue
        if not any(cell.strip() for cell in raw):
            continue
        fields = {
            name: (raw[position] if position < len(raw) else "").strip() for position, name in enumerate(header) if name
        }
        rows.append((index + 1, fields))
    return rows


def _parse_text_rows(text: str, source_file: str) -> list[tuple[int, dict[str, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() != "ALARM":
            continue
        severity = parts[-2] if len(parts) >= 6 else ""
        status = parts[-1] if len(parts) >= 6 else ""
        description = " ".join(parts[4:-2]) if len(parts) > 6 else ""
        rows.append(
            (
                line_no,
                {
                    "alarm_id": parts[3],
                    "created_time": f"{parts[1]} {parts[2]}",
                    "cleared_time": "",
                    "alarm_code": parts[3],
                    "object": "",
                    "severity": severity,
                    "status": status,
                    "description": description,
                },
            )
        )
    return rows


def _build_record(
    fields: dict[str, str], source_file: str, line_no: int, source_format: str, outcome: ParseOutcome
) -> AlarmRecord | None:
    alarm_code = _pick(fields, "alarm_code")
    if not alarm_code:
        outcome.exclude("missing_alarm_code")
        return None
    created_raw = _pick(fields, "created_time")
    created_at = _parse_time(created_raw)
    if created_at is None:
        outcome.exclude("unparseable_created_time")
        return None
    cleared_raw = _pick(fields, "cleared_time")
    cleared_at: datetime | None = None
    if cleared_raw:
        cleared_at = _parse_time(cleared_raw)
        if cleared_at is None:
            outcome.exclude("unparseable_cleared_time")
            return None
        if cleared_at < created_at:
            outcome.exclude("cleared_before_created")
            return None
    return AlarmRecord(
        alarm_id=_pick(fields, "alarm_id"),
        created_at=created_at,
        cleared_at=cleared_at,
        alarm_code=alarm_code,
        object=_pick(fields, "object"),
        severity=_pick(fields, "severity"),
        status=_pick(fields, "status"),
        description=_pick(fields, "description"),
        source_file=source_file,
        line_no=line_no,
        source_format=source_format,
    )


def _parse_files(files: list[Path], ctx: RuleContext) -> ParseOutcome:
    outcome = ParseOutcome()
    seen: set[tuple[str, str, str, str]] = set()
    for path in sorted(files):
        try:
            text, encoding = read_text_with_fallback(path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            outcome.failed_files += 1
            ctx.log("warning", "告警文件解析失败，已隔离", file=str(path), error=str(exc))
            continue
        ctx.log("debug", "告警文件解码完成", file=str(path), encoding=encoding)
        try:
            relative = path.relative_to(ctx.data_dir).as_posix()
        except ValueError:
            relative = path.as_posix()
        raw_rows = (
            _parse_csv_rows(text, relative) if path.suffix.lower() == ".csv" else _parse_text_rows(text, relative)
        )
        for line_no, fields in raw_rows:
            outcome.total_rows += 1
            source_format = "csv" if path.suffix.lower() == ".csv" else "text"
            record = _build_record(fields, relative, line_no, source_format, outcome)
            if record is None:
                continue
            key = (record.alarm_id, record.created_at.isoformat(), record.alarm_code, record.object)
            if key in seen:
                outcome.duplicate_rows += 1
                continue
            seen.add(key)
            outcome.records.append(record)
    return outcome


def _group_records(records: list[AlarmRecord]) -> dict[tuple[str, str], list[AlarmRecord]]:
    grouped: dict[tuple[str, str], list[AlarmRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.alarm_code, record.object)].append(record)
    for group in grouped.values():
        group.sort(key=lambda item: item.created_at)
    return dict(grouped)


def _coverage(records: list[AlarmRecord]) -> tuple[datetime, datetime, int]:
    start_at = min(record.created_at for record in records)
    end_at = max(record.cleared_at or record.created_at for record in records)
    return start_at, end_at, int((end_at - start_at).total_seconds())


def _local(value: datetime) -> datetime:
    return value.astimezone(ASSUMED_LOCAL_TZ)


def _iso(value: datetime) -> str:
    """统一按包内假定时区序列化，保证同一任务内偏移一致。"""
    return _local(value).isoformat()


def _duration_sec(record: AlarmRecord) -> int:
    if record.cleared_at is None:
        return 0
    return int((record.cleared_at - record.created_at).total_seconds())


@dataclass(slots=True, frozen=True)
class OperationWindow:
    """本地时间操作窗；支持跨自然日（如 23:00-01:00）。"""

    start_min: int
    end_min: int

    @property
    def label(self) -> str:
        return f"{self.start_min // 60:02d}:{self.start_min % 60:02d}-{self.end_min // 60:02d}:{self.end_min % 60:02d}"

    @property
    def wraps(self) -> bool:
        return self.end_min <= self.start_min

    def contains(self, local: datetime) -> bool:
        minutes = local.hour * 60 + local.minute
        if self.wraps:
            return minutes >= self.start_min or minutes < self.end_min
        return self.start_min <= minutes < self.end_min

    def ends_at(self, local: datetime) -> datetime:
        """记录所属操作窗的结束时刻（本地时区）。"""
        minutes = local.hour * 60 + local.minute
        end = local.replace(hour=self.end_min // 60, minute=self.end_min % 60, second=0, microsecond=0)
        if self.wraps and minutes >= self.start_min:
            end += timedelta(days=1)
        return end


def _parse_operation_window(text: str) -> OperationWindow | None:
    start_text, _, end_text = text.partition("-")
    try:
        start_hour, start_minute = (int(part) for part in start_text.strip().split(":"))
        end_hour, end_minute = (int(part) for part in end_text.strip().split(":"))
    except ValueError:
        return None
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23 and 0 <= start_minute <= 59 and 0 <= end_minute <= 59):
        return None
    if (start_hour, start_minute) == (end_hour, end_minute):
        return None
    return OperationWindow(start_min=start_hour * 60 + start_minute, end_min=end_hour * 60 + end_minute)


def _repeat_window_hit(records: list[AlarmRecord], policy: FlappingPolicy) -> tuple[datetime, datetime, int] | None:
    """滑动窗口：命中跨度为 ≤ repeat_window_sec 且出现次数最多的复发窗口。"""
    best: tuple[datetime, datetime, int] | None = None
    left = 0
    for right, record in enumerate(records):
        while (record.created_at - records[left].created_at).total_seconds() > policy.repeat_window_sec:
            left += 1
        count = right - left + 1
        if count < policy.min_repeat_count:
            continue
        if best is None or count > best[2]:
            best = (records[left].created_at, record.created_at, count)
    return best


def _min_repeat_gap_sec(records: list[AlarmRecord]) -> int | None:
    gaps = [
        int((current.created_at - previous.cleared_at).total_seconds())
        for previous, current in zip(records, records[1:], strict=False)
        if previous.cleared_at is not None
    ]
    return min(gaps) if gaps else None


def _flap_events(records: list[AlarmRecord], policy: FlappingPolicy) -> list[dict[str, Any]]:
    """按 flap_gap_sec 串联闪断事件；前一条未清除时后续出现一律并入。"""
    events: list[list[AlarmRecord]] = []
    current: list[AlarmRecord] = []
    for record in records:
        if current:
            previous = current[-1]
            gap = None if previous.cleared_at is None else (record.created_at - previous.cleared_at).total_seconds()
            if gap is not None and gap > policy.flap_gap_sec:
                events.append(current)
                current = []
        current.append(record)
    if current:
        events.append(current)

    payload: list[dict[str, Any]] = []
    for event in events:
        if len(event) < 2:
            continue
        gaps = [
            int((current.created_at - previous.cleared_at).total_seconds())
            for previous, current in zip(event, event[1:], strict=False)
            if previous.cleared_at is not None
        ]
        last = event[-1]
        ended_at = last.cleared_at
        has_uncleared = any(record.cleared_at is None for record in event)
        is_flap = has_uncleared or (bool(gaps) and min(gaps) <= policy.flap_gap_sec)
        payload.append(
            {
                "started_at": _iso(event[0].created_at),
                "last_seen_at": _iso(last.created_at),
                "ended_at": None if ended_at is None else _iso(ended_at),
                "occurrences": len(event),
                "duration_sec": None if ended_at is None else int((ended_at - event[0].created_at).total_seconds()),
                "gaps_sec": gaps,
                "is_flap": is_flap,
            }
        )
    return payload


def _window_facts(records: list[AlarmRecord], window: OperationWindow | None) -> tuple[int, int, bool, bool]:
    """返回（窗口内出现数、窗口外出现数、窗口外再现、窗口后仍未恢复）。"""
    if window is None:
        return 0, 0, False, False
    in_window = 0
    out_of_window = 0
    earliest_in_window: datetime | None = None
    latest_out_of_window: datetime | None = None
    unrecovered = False
    for record in records:
        local = _local(record.created_at)
        if window.contains(local):
            in_window += 1
            if earliest_in_window is None or local < earliest_in_window:
                earliest_in_window = local
            if record.cleared_at is None or _local(record.cleared_at) > window.ends_at(local):
                unrecovered = True
        else:
            out_of_window += 1
            if latest_out_of_window is None or local > latest_out_of_window:
                latest_out_of_window = local
    reappear = (
        earliest_in_window is not None
        and latest_out_of_window is not None
        and latest_out_of_window > earliest_in_window
    )
    return in_window, out_of_window, reappear, unrecovered


@dataclass(slots=True)
class GroupFacts:
    """分组生命周期判定结果（内部实体，对外经 metadata.groups 展示）。"""

    alarm_code: str
    object: str
    records: list[AlarmRecord]
    state: str
    occurrence_count: int
    cleared_count: int
    uncleared_count: int
    first_seen_at: datetime
    recent_seen_at: datetime
    recent_cleared_at: datetime | None
    max_duration_sec: int
    total_duration_sec: int
    min_repeat_gap_sec: int | None
    repeated: bool
    is_short: bool
    observation_insufficient: bool
    observation_gap_sec: int | None
    in_window_occurrences: int
    out_of_window_occurrences: int
    out_of_window_reappear: bool
    unrecovered_after_window: bool
    repeat_window: tuple[datetime, datetime, int] | None
    flap_events: list[dict[str, Any]]
    flap_event_count: int

    def detail(self) -> dict[str, Any]:
        return {
            "alarm_code": self.alarm_code,
            "object": self.object,
            "state": self.state,
            "occurrence_count": self.occurrence_count,
            "cleared_count": self.cleared_count,
            "uncleared_count": self.uncleared_count,
            "first_seen_at": _iso(self.first_seen_at),
            "recent_seen_at": _iso(self.recent_seen_at),
            "recent_cleared_at": (None if self.recent_cleared_at is None else _iso(self.recent_cleared_at)),
            "max_duration_sec": self.max_duration_sec,
            "total_duration_sec": self.total_duration_sec,
            "min_repeat_gap_sec": self.min_repeat_gap_sec,
            "repeated": self.repeated,
            "is_short": self.is_short,
            "observation_insufficient": self.observation_insufficient,
            "observation_gap_sec": self.observation_gap_sec,
            "in_window_occurrences": self.in_window_occurrences,
            "out_of_window_occurrences": self.out_of_window_occurrences,
            "out_of_window_reappear": self.out_of_window_reappear,
            "unrecovered_after_window": self.unrecovered_after_window,
            "flap_event_count": self.flap_event_count,
            "flap_events": [dict(event) for event in self.flap_events],
            "evidence_records": [
                {"source_file": record.source_file, "line_no": record.line_no} for record in self.records
            ],
        }


def _main_state(*, uncleared_count: int, repeated: bool, is_short: bool, observation_insufficient: bool) -> str:
    """主状态互斥判定；反复优先于短告警，观察窗不足只作兜底。"""
    if uncleared_count > 0:
        return "uncleared_repeated" if repeated else "uncleared_single"
    if repeated:
        return "cleared_repeated"
    if is_short:
        return "cleared_short"
    if observation_insufficient:
        return "observation_insufficient"
    return "cleared_stable"


def _build_group(
    alarm_code: str,
    object_name: str,
    records: list[AlarmRecord],
    coverage_end: datetime,
    policy: FlappingPolicy,
    window: OperationWindow | None,
) -> GroupFacts:
    cleared = [record for record in records if record.cleared_at is not None]
    uncleared_count = len(records) - len(cleared)
    recent_cleared_at = max((record.cleared_at for record in cleared), default=None)
    observation_gap_sec = None if recent_cleared_at is None else int((coverage_end - recent_cleared_at).total_seconds())
    max_duration_sec = max((_duration_sec(record) for record in cleared), default=0)
    is_short = uncleared_count == 0 and max_duration_sec <= policy.short_alarm_sec
    repeat_window = _repeat_window_hit(records, policy)
    repeated = repeat_window is not None
    observation_insufficient = (
        uncleared_count > 0 or observation_gap_sec is None or observation_gap_sec < policy.stable_observation_sec
    )
    events = _flap_events(records, policy)
    in_window, out_of_window, reappear, unrecovered = _window_facts(records, window)
    return GroupFacts(
        alarm_code=alarm_code,
        object=object_name,
        records=records,
        state=_main_state(
            uncleared_count=uncleared_count,
            repeated=repeated,
            is_short=is_short,
            observation_insufficient=observation_insufficient,
        ),
        occurrence_count=len(records),
        cleared_count=len(cleared),
        uncleared_count=uncleared_count,
        first_seen_at=records[0].created_at,
        recent_seen_at=records[-1].created_at,
        recent_cleared_at=recent_cleared_at,
        max_duration_sec=max_duration_sec,
        total_duration_sec=sum(_duration_sec(record) for record in cleared),
        min_repeat_gap_sec=_min_repeat_gap_sec(records),
        repeated=repeated,
        is_short=is_short,
        observation_insufficient=observation_insufficient,
        observation_gap_sec=observation_gap_sec,
        in_window_occurrences=in_window,
        out_of_window_occurrences=out_of_window,
        out_of_window_reappear=reappear,
        unrecovered_after_window=unrecovered,
        repeat_window=repeat_window,
        flap_events=events,
        flap_event_count=sum(1 for event in events if event["is_flap"]),
    )


def _group_sort_key(facts: GroupFacts) -> tuple[int, float]:
    """风险优先：状态优先级升序，同状态按最近出现时间倒序。"""
    return STATES.index(facts.state), -facts.recent_seen_at.timestamp()


FINDING_STATES: tuple[str, ...] = ("uncleared_repeated", "cleared_repeated", "cleared_short")

FINDING_TITLES: dict[str, str] = {
    "uncleared_repeated": "未清除且反复的告警",
    "cleared_repeated": "清除后仍反复闪断的告警",
    "cleared_short": "已清除的单次短告警",
}


def _finding_id(facts: GroupFacts) -> str:
    return f"alarm.flapping-{facts.state}-{facts.alarm_code}-{facts.object or 'unknown'}"


def _finding_evidence(facts: GroupFacts, policy: FlappingPolicy, window: OperationWindow | None) -> str:
    label = facts.object or "对象未知"
    if facts.repeat_window is None:
        trigger = "未触发复发窗口"
    else:
        started_at, ended_at, count = facts.repeat_window
        trigger = f"触发复发窗口 {_iso(started_at)} → {_iso(ended_at)}（{count} 次）"
    window_text = (
        "操作窗未启用"
        if window is None
        else f"操作窗 {window.label} 内 {facts.in_window_occurrences} 次 / 窗外 {facts.out_of_window_occurrences} 次"
    )
    parts = [
        f"分组 {facts.alarm_code} / {label}",
        f"出现 {facts.occurrence_count} 次（已清除 {facts.cleared_count} / 未清除 {facts.uncleared_count}）",
        f"首次出现 {_iso(facts.first_seen_at)}",
        f"最近出现 {_iso(facts.recent_seen_at)}",
        f"最近清除 {'无' if facts.recent_cleared_at is None else _iso(facts.recent_cleared_at)}",
        f"最短复发间隔 {'无' if facts.min_repeat_gap_sec is None else f'{facts.min_repeat_gap_sec} 秒'}",
        trigger,
        "本次阈值："
        f"短告警 {policy.short_alarm_sec} 秒、复发窗口 {policy.repeat_window_sec} 秒/≥{policy.min_repeat_count} 次、"
        f"闪断间隔 {policy.flap_gap_sec} 秒、稳定观察窗 {policy.stable_observation_sec} 秒",
        window_text,
    ]
    if facts.out_of_window_reappear:
        parts.append("窗口外再现")
    if facts.unrecovered_after_window:
        parts.append("窗口后仍未恢复")
    first = facts.records[0]
    parts.append(f"来源 {first.source_file}:{first.line_no}（共 {facts.occurrence_count} 条）")
    return "；".join(parts)


def _build_findings(facts: list[GroupFacts], policy: FlappingPolicy, window: OperationWindow | None) -> list[Finding]:
    """按状态优先级 + recent_seen_at 倒序生成 Finding，最多 FINDINGS_MAX 条。"""
    ordered = [item for item in facts if item.state in FINDING_STATES]
    ordered.sort(key=_group_sort_key)
    return [
        Finding(
            finding_id=_finding_id(item),
            title=f"{FINDING_TITLES[item.state]}：{item.alarm_code} / {item.object or '对象未知'}",
            severity=FINDING_SEVERITY[item.state],
            source_file=item.records[0].source_file,
            evidence=_finding_evidence(item, policy, window),
            details=f"告警分组 {item.alarm_code} / {item.object or '对象未知'} 判定为 {STATE_LABELS[item.state]}",
            recommendation=inspector.recommendation,
        )
        for item in ordered[:FINDINGS_MAX]
    ]


def _policy_payload(policy: FlappingPolicy) -> dict[str, Any]:
    return {
        "short_alarm_sec": policy.short_alarm_sec,
        "repeat_window_sec": policy.repeat_window_sec,
        "min_repeat_count": policy.min_repeat_count,
        "flap_gap_sec": policy.flap_gap_sec,
        "stable_observation_sec": policy.stable_observation_sec,
        "operation_window": policy.operation_window,
        "operation_window_enabled": policy.operation_window_enabled,
        "parameter_source": policy.parameter_source,
    }


def _build_notes(
    outcome: ParseOutcome,
    *,
    window: OperationWindow | None,
    groups_truncated: bool,
    findings_truncated: bool,
) -> list[str]:
    notes = [
        "恢复结论只基于清除时间与观察窗，status 字段仅作展示，不作为恢复证据",
        (
            f"操作窗 {window.label}（本地时间）仅作证据标注，不参与主状态判定，窗口结束后未清除的告警显式标注"
            if window is not None
            else "操作窗未启用，窗口内/外计数与窗口标记均为 false"
        ),
    ]
    if outcome.excluded_rows:
        reasons = "、".join(f"{reason}={count}" for reason, count in sorted(outcome.excluded_reasons.items()))
        notes.append(f"排除 {outcome.excluded_rows} 行（{reasons}）")
    if outcome.duplicate_rows:
        notes.append(f"去重 {outcome.duplicate_rows} 行（键 alarm_id+created_time+alarm_code+object）")
    if outcome.failed_files:
        notes.append(f"{outcome.failed_files} 个告警文件解析失败并已隔离，不影响其他文件")
    if groups_truncated:
        notes.append(
            f"分组明细超过 {GROUPS_MAX} 个，仅保留风险优先的前 {GROUPS_MAX} 个；完整计数见 totals 与 state_counts"
        )
    if findings_truncated:
        notes.append(f"Finding 超过 {FINDINGS_MAX} 条，仅输出风险优先的前 {FINDINGS_MAX} 条；完整计数见 state_counts")
    return notes


def _build_metrics(metrics: dict[str, int], outcome: ParseOutcome) -> list[dict[str, Any]]:
    values = {**{key: 0 for key, _, _ in METRIC_LABELS}, **metrics}
    values["excluded_rows"] = outcome.excluded_rows
    values["duplicate_rows"] = outcome.duplicate_rows
    values["failed_files"] = outcome.failed_files
    return [{"key": key, "label": label, "value": values[key], "unit": unit} for key, label, unit in METRIC_LABELS]


def _run(ctx: RuleContext) -> object:
    files = sorted(ctx.resolved_files())
    policy = resolve_policy()
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未匹配到告警文件",
            skip_reason="未匹配到 alarm_all 组告警文件，无法进行告警生命周期判定",
        )
    outcome = _parse_files(files, ctx)
    if not outcome.records:
        reasons = "、".join(f"{reason}={count}" for reason, count in sorted(outcome.excluded_reasons.items()))
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary=f"告警记录不可用：排除 {outcome.excluded_rows} 行",
            skip_reason=(
                f"全部告警记录时间或关键字段不可解析，排除 {outcome.excluded_rows} 行"
                + (f"（{reasons}）" if reasons else "")
            ),
            metrics=_build_metrics({}, outcome),
            metadata={
                "alarm_flapping": {
                    "schema_version": 1,
                    "policy": _policy_payload(policy),
                    "totals": {
                        "rows": outcome.total_rows,
                        "valid_rows": 0,
                        "groups": 0,
                        "excluded_rows": outcome.excluded_rows,
                        "duplicate_rows": outcome.duplicate_rows,
                        "failed_files": outcome.failed_files,
                        "findings_truncated": False,
                        "groups_truncated": False,
                    },
                    "state_counts": {state: 0 for state in STATES},
                    "groups": [],
                    "notes": ["全部告警行被排除，规则返回 skip；原因分类见 skip_reason 与 excluded_rows"],
                }
            },
        )

    window = _parse_operation_window(policy.operation_window) if policy.operation_window_enabled else None
    grouped = _group_records(outcome.records)
    start_at, end_at, span_sec = _coverage(outcome.records)
    facts = [
        _build_group(alarm_code, object_name, records, end_at, policy, window)
        for (alarm_code, object_name), records in sorted(grouped.items())
    ]
    facts.sort(key=_group_sort_key)

    state_counts = {state: 0 for state in STATES}
    for fact in facts:
        state_counts[fact.state] += 1
    findings = _build_findings(facts, policy, window)
    flapping_count = state_counts["uncleared_repeated"] + state_counts["cleared_repeated"]
    unrecovered_count = sum(1 for fact in facts if fact.unrecovered_after_window)
    if flapping_count:
        status = RuleStatus.FAIL
    elif any(state_counts[state] for state in ("cleared_short", "uncleared_single", "observation_insufficient")):
        status = RuleStatus.WARN
    else:
        status = RuleStatus.PASS
    summary = (
        f"告警生命周期判定完成：{len(facts)} 个分组，反复闪断 {flapping_count} 个，"
        f"未清除 {sum(1 for fact in facts if fact.uncleared_count)} 个，短告警 {state_counts['cleared_short']} 个，"
        f"Finding {len(findings)} 条"
    )
    groups_truncated = len(facts) > GROUPS_MAX
    findings_truncated = sum(1 for fact in facts if fact.state in FINDING_STATES) > FINDINGS_MAX
    return make_result(
        inspector,
        status=status,
        summary=summary,
        findings=findings,
        metrics=_build_metrics(
            {
                "alarm_groups": len(facts),
                "flapping_groups": flapping_count,
                "uncleared_repeated_groups": state_counts["uncleared_repeated"],
                "short_alarm_groups": state_counts["cleared_short"],
                "stable_groups": state_counts["cleared_stable"],
                "observation_insufficient_groups": sum(1 for fact in facts if fact.observation_insufficient),
                "out_of_window_groups": sum(1 for fact in facts if fact.out_of_window_reappear),
                "unrecovered_after_window_groups": unrecovered_count,
            },
            outcome,
        ),
        metadata={
            "alarm_flapping": {
                "schema_version": 1,
                "policy": _policy_payload(policy),
                "coverage": {
                    "start_at": _iso(start_at),
                    "end_at": _iso(end_at),
                    "span_sec": span_sec,
                },
                "totals": {
                    "rows": outcome.total_rows,
                    "valid_rows": len(outcome.records),
                    "groups": len(facts),
                    "excluded_rows": outcome.excluded_rows,
                    "duplicate_rows": outcome.duplicate_rows,
                    "failed_files": outcome.failed_files,
                    "findings_truncated": findings_truncated,
                    "groups_truncated": groups_truncated,
                },
                "state_counts": state_counts,
                "groups": [fact.detail() for fact in facts[:GROUPS_MAX]],
                "notes": _build_notes(
                    outcome,
                    window=window,
                    groups_truncated=groups_truncated,
                    findings_truncated=findings_truncated,
                ),
            }
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
