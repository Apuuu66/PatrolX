"""KPI 跨任务历史索引与单指标历史趋势服务。"""

from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.models.schemas import (
    MeasurementBaselineSignificance,
    MeasurementHistoryBaselinePoint,
    MeasurementHistoryCoverage,
    MeasurementHistoryDateSeries,
    MeasurementHistoryMatch,
    MeasurementHistoryMatchStatus,
    MeasurementHistoryPoint,
    MeasurementHistoryTrend,
    MeasurementHistoryWindow,
    MeasurementVersionCandidate,
    MeasurementVersionCandidateList,
    MeasurementVersionCandidateTask,
    MeasurementVersionComparison,
    MeasurementVersionComparisonSummary,
    MeasurementVersionComparisonTask,
    MeasurementVersionDirection,
)
from app.services.store import load_task_meta

KPI_RULE_CODE = "kpi.measurement_units"
HISTORY_WINDOW_DAYS = 7
MIN_BASELINE_SAMPLES = 3

IndexRecord = dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def index_path(output: Path | None = None, task_id: str | None = None) -> Path:
    """返回任务私有历史索引路径。"""
    if output is None or task_id is None:
        raise ValueError("output 和 task_id 不能为空")
    return output / task_id / "kpi" / "history" / "index.jsonl"


def _parse_index_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _valid_index_record(raw: object, expected_task_id: str) -> IndexRecord | None:
    """校验单行索引；坏行不阻断整个索引读取。"""
    if not isinstance(raw, dict):
        return None
    measured_at = _parse_index_time(raw.get("measured_at"))
    value = raw.get("value")
    required_strings = ("task_id", "measurement_unit_id", "metric_resource_id", "source_file")
    has_valid_strings = all(isinstance(raw.get(key), str) for key in required_strings)
    if measured_at is None or not isinstance(value, (int, float)) or not has_valid_strings:
        return None
    period = raw.get("period_minutes")
    if period is not None and not isinstance(period, int):
        return None
    line_number = raw.get("line_number")
    if line_number is not None and not isinstance(line_number, int):
        return None
    if raw.get("task_id") != expected_task_id:
        return None
    return {
        "task_id": raw["task_id"],
        "measurement_unit_id": raw["measurement_unit_id"],
        "metric_resource_id": raw["metric_resource_id"],
        "object_key": raw.get("object_key") or "__all__",
        "period_minutes": period,
        "measured_at": measured_at,
        "value": float(value),
        "source_file": raw["source_file"],
        "line_number": line_number,
    }


def _merge_duplicate_points(records: Iterable[IndexRecord]) -> list[IndexRecord]:
    """同一任务内同维度同时间点求均值，保证索引点稳定。"""
    grouped: dict[tuple[datetime, str, str, str, int | None], dict[str, Any]] = {}
    for record in records:
        key = (
            record["measured_at"],
            record["measurement_unit_id"],
            record["metric_resource_id"],
            record["object_key"],
            record["period_minutes"],
        )
        item = grouped.setdefault(
            key,
            {
                **record,
                "sum_value": 0.0,
                "count": 0,
                "source_lines": [],
            },
        )
        item["sum_value"] += record["value"]
        item["count"] += 1
        item["source_lines"].append((record.get("source_file"), record.get("line_number")))
    merged: list[IndexRecord] = []
    for item in grouped.values():
        source_file, line_number = item["source_lines"][0]
        merged.append(
            {
                "task_id": item["task_id"],
                "measurement_unit_id": item["measurement_unit_id"],
                "metric_resource_id": item["metric_resource_id"],
                "object_key": item["object_key"],
                "period_minutes": item["period_minutes"],
                "measured_at": item["measured_at"],
                "value": item["sum_value"] / item["count"],
                "source_file": source_file,
                "line_number": line_number,
            }
        )
    return sorted(merged, key=lambda item: item["measured_at"])


def write_history_index(
    task_id: str,
    records: Iterable[IndexRecord],
    *,
    output: Path | None = None,
) -> Path:
    """原子写任务私有历史索引；每行一个 JSON 点。"""
    target = index_path(output or settings.output, task_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    valid: list[IndexRecord] = []
    for raw in records:
        record = _valid_index_record(raw, task_id)
        if record is not None:
            valid.append(record)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            for record in _merge_duplicate_points(valid):
                payload = {
                    **record,
                    "measured_at": record["measured_at"].isoformat(),
                }
                fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def iter_history_index(
    task_id: str,
    *,
    output: Path | None = None,
) -> Iterator[IndexRecord]:
    """流式逐行读取并校验索引；索引缺失时抛出 FileNotFoundError。"""
    path = index_path(output or settings.output, task_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = _valid_index_record(raw, task_id)
            if record is not None:
                yield record


def _task_completed_at(task_id: str, output: Path) -> datetime:
    task = load_task_meta(output, task_id)
    if task is None:
        raise FileNotFoundError(output / task_id / "task.json")
    if task.completed_at is None:
        raise ValueError(f"任务 {task_id} 未完成")
    completed_at = task.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    return completed_at.astimezone(UTC)


def _task_device_id(task_id: str, output: Path) -> str | None:
    task = load_task_meta(output, task_id)
    if task is None:
        return None
    customer = task.system.customer if task.system else {}
    device_id = customer.get("device_id")
    return str(device_id).strip() if device_id else None


def _point_from_record(record: IndexRecord) -> MeasurementHistoryPoint:
    measured_at = record["measured_at"]
    return MeasurementHistoryPoint(
        measured_at=measured_at,
        date=measured_at.date().isoformat(),
        time_label=measured_at.strftime("%H:%M"),
        value=record["value"],
        task_id=record["task_id"],
        source_file=record["source_file"],
        line_number=record["line_number"],
    )


def _baseline_for_time(
    time_label: str,
    current_by_label: dict[str, float],
    history_by_label: dict[str, list[float]],
    history_dates_by_label: dict[str, set[str]],
) -> MeasurementHistoryBaselinePoint:
    samples = history_by_label.get(time_label, [])
    current_value = current_by_label.get(time_label)
    if len(samples) < MIN_BASELINE_SAMPLES:
        significance = MeasurementBaselineSignificance.INSUFFICIENT
        baseline_value = statistics.median(samples) if samples else None
    else:
        baseline_value = statistics.median(samples)
        deviation = current_value - baseline_value if current_value is not None else None
        abs_values = [abs(value - baseline_value) for value in samples]
        median_abs_dev = statistics.median(abs_values)
        threshold = max(
            3 * 1.4826 * median_abs_dev,
            0.1 * max(abs(baseline_value), median_abs_dev),
            1e-9,
        )
        if deviation is None or abs(deviation) <= threshold:
            significance = MeasurementBaselineSignificance.NORMAL
        else:
            significance = (
                MeasurementBaselineSignificance.HIGHER if deviation > 0 else MeasurementBaselineSignificance.LOWER
            )
    deviation = current_value - baseline_value if current_value is not None and baseline_value is not None else None
    deviation_ratio = (
        deviation / abs(baseline_value)
        if deviation is not None and baseline_value is not None and baseline_value != 0
        else None
    )
    return MeasurementHistoryBaselinePoint(
        time_label=time_label,
        baseline_value=baseline_value,
        current_value=current_value,
        deviation=deviation,
        deviation_ratio=deviation_ratio,
        sample_count=len(samples),
        date_count=len(history_dates_by_label.get(time_label, set())),
        significance=significance,
    )


def get_history_trend(
    task_id: str,
    *,
    rule_code: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    object_key: str,
    period_minutes: int | None,
    output: Path | None = None,
) -> MeasurementHistoryTrend:
    """组装单指标、单对象、单周期的 7 天历史趋势。"""
    output = output or settings.output
    current_task = load_task_meta(output, task_id)
    if current_task is None:
        raise FileNotFoundError(output / task_id / "task.json")
    device_id = _task_device_id(task_id, output)
    try:
        all_current = list(iter_history_index(task_id, output=output))
        current_index_available = True
    except FileNotFoundError:
        current_index_available = False
        all_current = []

    if current_index_available:
        current_records = [
            record
            for record in all_current
            if record["measurement_unit_id"] == measurement_unit_id
            and record["metric_resource_id"] == metric_resource_id
            and record["object_key"] == object_key
            and record["period_minutes"] == period_minutes
        ]
    else:
        current_records = []

    anchor = max((record["measured_at"] for record in current_records), default=None)
    if anchor is None:
        end_date = current_task.completed_at.date() if current_task.completed_at else datetime.now(UTC).date()
    else:
        end_date = anchor.date()
    start_date = end_date - timedelta(days=HISTORY_WINDOW_DAYS - 1)
    window = MeasurementHistoryWindow(
        end_date=end_date.isoformat(),
        start_date=start_date.isoformat(),
        days=HISTORY_WINDOW_DAYS,
        anchor_measured_at=anchor or (current_task.completed_at or _utc_now()),
    )

    reason_code: str | None = None
    match_status = MeasurementHistoryMatchStatus.MATCHED
    if not current_index_available:
        match_status = MeasurementHistoryMatchStatus.DEGRADED
        reason_code = "history_index_missing"
        message = "历史索引缺失，无法对比历史趋势"
    elif not device_id:
        match_status = MeasurementHistoryMatchStatus.DEGRADED
        reason_code = "device_id_missing"
        message = "当前任务未填写设备 ID，无法匹配历史任务"
    elif not current_records:
        match_status = MeasurementHistoryMatchStatus.DEGRADED
        reason_code = "metric_dimension_missing"
        message = "当前任务没有指定指标、对象和周期的有效趋势点"
    elif anchor is None:
        match_status = MeasurementHistoryMatchStatus.DEGRADED
        reason_code = "current_measurement_time_missing"
        message = "当前任务没有有效 KPI 测量时间"

    history_records: list[IndexRecord] = []
    source_tasks: list[str] = []
    history_task_count = 0
    outside_window_dates: list[date] = []
    candidate_reason_counts: dict[str, int] = defaultdict(int)
    if current_index_available and device_id and current_records:
        current_completed_at = _task_completed_at(task_id, output)
        seen_task_ids = {task_id}
        for candidate_dir in sorted((path for path in output.iterdir() if path.is_dir()), key=lambda path: path.name):
            candidate_id = candidate_dir.name
            if candidate_id in seen_task_ids:
                continue
            try:
                candidate = load_task_meta(output, candidate_id)
            except Exception:  # noqa: BLE001 - 单个坏任务不阻断历史读取
                continue
            if candidate is None:
                continue
            candidate_device_id = _task_device_id(candidate_id, output)
            if candidate_device_id != device_id:
                continue
            if candidate.status.value != "completed" or candidate.completed_at is None:
                candidate_reason_counts["not_completed"] += 1
                continue
            candidate_completed_at = candidate.completed_at
            if candidate_completed_at.tzinfo is None:
                candidate_completed_at = candidate_completed_at.replace(tzinfo=UTC)
            if candidate_completed_at > current_completed_at:
                candidate_reason_counts["after_current"] += 1
                continue
            try:
                candidate_records = list(iter_history_index(candidate_id, output=output))
            except FileNotFoundError:
                candidate_reason_counts["index_missing"] += 1
                continue
            if not candidate_records:
                candidate_reason_counts["index_empty"] += 1
                continue

            same_unit_metric = [
                record
                for record in candidate_records
                if record["measurement_unit_id"] == measurement_unit_id
                and record["metric_resource_id"] == metric_resource_id
            ]
            same_dimension = [
                record
                for record in same_unit_metric
                if record["object_key"] == object_key and record["period_minutes"] == period_minutes
            ]
            matched = [record for record in same_dimension if start_date <= record["measured_at"].date() <= end_date]
            if matched:
                history_records.extend(matched)
                source_tasks.append(candidate_id)
                history_task_count += 1
                seen_task_ids.add(candidate_id)
            elif same_dimension:
                outside_window_dates.extend(record["measured_at"].date() for record in same_dimension)
                candidate_reason_counts["time_outside_window"] += 1
            elif not same_unit_metric:
                candidate_reason_counts["unit_or_metric_missing"] += 1
            else:
                candidate_reason_counts["object_or_period_mismatch"] += 1

    # 跨任务同时间点保留完成时间最新的任务；完成时间相同按 task_id 倒序。
    completed_by_task: dict[str, datetime] = {}
    for candidate_id in set(record["task_id"] for record in history_records):
        completed_by_task[candidate_id] = _task_completed_at(candidate_id, output)
    grouped: dict[datetime, list[IndexRecord]] = defaultdict(list)
    for record in history_records:
        grouped[record["measured_at"]].append(record)
    deduped_history: list[IndexRecord] = []
    for measured_at in sorted(grouped):
        candidates = grouped[measured_at]
        winner = max(
            candidates,
            key=lambda item: (
                completed_by_task.get(item["task_id"], datetime.min.replace(tzinfo=UTC)),
                item["task_id"],
            ),
        )
        deduped_history.append(winner)

    source_tasks = sorted(set(record["task_id"] for record in deduped_history))
    history_task_count = len(source_tasks)
    history_by_date: dict[date, list[IndexRecord]] = defaultdict(list)
    for record in deduped_history:
        history_by_date[record["measured_at"].date()].append(record)
    history_series = [
        MeasurementHistoryDateSeries(
            date=day.isoformat(),
            source_task_ids=sorted(set(record["task_id"] for record in records)),
            points=[_point_from_record(record) for record in sorted(records, key=lambda item: item["measured_at"])],
        )
        for day, records in sorted(history_by_date.items())
    ]

    current_points = [
        _point_from_record(record) for record in sorted(current_records, key=lambda item: item["measured_at"])
    ]
    current_by_label: dict[str, float] = {}
    for point in current_points:
        current_by_label[point.time_label] = point.value
    history_by_label: dict[str, list[float]] = defaultdict(list)
    history_dates_by_label: dict[str, set[str]] = defaultdict(set)
    for point in (point for series in history_series for point in series.points):
        history_by_label[point.time_label].append(point.value)
        history_dates_by_label[point.time_label].add(point.date)
    baseline_points = [
        _baseline_for_time(label, current_by_label, history_by_label, history_dates_by_label)
        for label in sorted(set(current_by_label) | set(history_by_label))
    ]

    message = None
    if match_status == MeasurementHistoryMatchStatus.MATCHED and not history_task_count:
        match_status = MeasurementHistoryMatchStatus.NO_HISTORY
        if candidate_reason_counts:
            time_count = candidate_reason_counts.get("time_outside_window", 0)
            detail_by_cause = {
                "not_completed": "未完成或缺少完成时间",
                "after_current": "完成时间晚于当前任务",
                "index_missing": "历史索引缺失",
                "index_empty": "历史索引为空或无效",
                "unit_or_metric_missing": "没有该测量单元或指标",
                "object_or_period_mismatch": "对象或周期不一致",
            }
            details = [
                f"{label} {candidate_reason_counts[cause]} 个"
                for cause, label in detail_by_cause.items()
                if candidate_reason_counts.get(cause)
            ]
            if time_count:
                latest_outside_date = max(outside_window_dates).isoformat()
                details.append(
                    f"数据时间不在当前 {HISTORY_WINDOW_DAYS} 天窗口"
                    f"（{start_date.isoformat()} ~ {end_date.isoformat()}），"
                    f"最近为 {latest_outside_date}，共 {time_count} 个"
                )
            reason_codes = {
                "not_completed": "history_candidate_not_completed",
                "after_current": "history_candidate_after_current",
                "index_missing": "history_candidate_index_missing",
                "index_empty": "history_index_empty",
                "unit_or_metric_missing": "history_candidate_unit_or_metric_missing",
                "object_or_period_mismatch": "history_candidate_object_or_period_mismatch",
                "time_outside_window": "history_time_outside_window",
            }
            reason_code = (
                reason_codes[next(iter(candidate_reason_counts))]
                if len(candidate_reason_counts) == 1
                else "history_candidate_mismatch"
            )
            message = f"同设备有 {sum(candidate_reason_counts.values())} 个任务未进入对比：{'；'.join(details)}。"
        else:
            reason_code = None
            message = "未找到可对比的历史任务"

    match = MeasurementHistoryMatch(
        status=match_status,
        reason_code=reason_code,
        message=message or "",
    )
    coverage = MeasurementHistoryCoverage(
        history_task_count=history_task_count,
        history_date_count=len(history_by_date),
        history_point_count=len(deduped_history),
        current_point_count=len(current_points),
        latest_history_date=max(history_by_date).isoformat() if history_by_date else None,
    )
    return MeasurementHistoryTrend(
        task_id=task_id,
        rule_code=rule_code,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        device_id=device_id,
        object_key=object_key,
        period_minutes=period_minutes,
        window=window,
        match=match,
        coverage=coverage,
        current_points=current_points,
        history_series=history_series,
        baseline_points=baseline_points,
        source_tasks=source_tasks,
    )


def _task_version(task: object) -> str | None:
    """读取任务系统版本；空值统一为版本未知。"""
    version = getattr(getattr(task, "system", None), "version", None)
    if not isinstance(version, str) or not version.strip():
        return None
    return version.strip()


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _version_task(task_id: str, task: object) -> MeasurementVersionComparisonTask:
    return MeasurementVersionComparisonTask(
        task_id=task_id,
        completed_at=_ensure_utc(getattr(task, "completed_at", None)),
        version=_task_version(task),
        version_known=_task_version(task) is not None,
    )


def _dimension_records(
    task_id: str,
    *,
    measurement_unit_id: str,
    metric_resource_id: str,
    object_key: str,
    period_minutes: int | None,
    output: Path,
) -> list[IndexRecord]:
    """流式读取并过滤当前任务的单维度历史点。"""
    return [
        record
        for record in iter_history_index(task_id, output=output)
        if record["measurement_unit_id"] == measurement_unit_id
        and record["metric_resource_id"] == metric_resource_id
        and record["object_key"] == object_key
        and record["period_minutes"] == period_minutes
    ]


def _candidate_tasks_for_device(task_id: str, device_id: str, output: Path) -> list[tuple[object, str]]:
    """读取同设备已完成候选任务，不读取历史索引。"""
    candidates: list[tuple[object, str]] = []
    for candidate_dir in sorted((path for path in output.iterdir() if path.is_dir()), key=lambda path: path.name):
        candidate_id = candidate_dir.name
        if candidate_id == task_id:
            continue
        try:
            candidate = load_task_meta(output, candidate_id)
        except Exception:  # noqa: BLE001 - 单个坏任务不阻断候选读取
            continue
        if candidate is None or _task_device_id(candidate_id, output) != device_id:
            continue
        if candidate.status.value != "completed" or candidate.completed_at is None:
            continue
        candidates.append((candidate, candidate_id))
    return candidates


def get_version_candidates(
    task_id: str,
    *,
    rule_code: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    object_key: str,
    period_minutes: int | None,
    output: Path | None = None,
) -> MeasurementVersionCandidateList:
    """按设备读取已完成历史任务的系统版本候选。"""
    output = output or settings.output
    if rule_code != KPI_RULE_CODE:
        raise ValueError(f"不支持的规则: {rule_code}")
    current_task = load_task_meta(output, task_id)
    if current_task is None:
        raise FileNotFoundError(output / task_id / "task.json")
    device_id = _task_device_id(task_id, output)
    grouped: dict[str | None, list[tuple[object, str]]] = defaultdict(list)
    if device_id:
        for candidate, candidate_id in _candidate_tasks_for_device(task_id, device_id, output):
            grouped[_task_version(candidate)].append((candidate, candidate_id))

    items: list[MeasurementVersionCandidate] = []
    for version, candidates in grouped.items():
        ordered = sorted(
            candidates,
            key=lambda item: (
                _ensure_utc(item[0].completed_at) or datetime.min.replace(tzinfo=UTC),
                item[1],
            ),
            reverse=True,
        )
        candidate_models = [
            MeasurementVersionCandidateTask(
                task_id=candidate_id,
                completed_at=_ensure_utc(candidate.completed_at),
                version=version,
                version_known=version is not None,
            )
            for candidate, candidate_id in ordered
        ]
        items.append(
            MeasurementVersionCandidate(
                version=version,
                version_known=version is not None,
                latest_task_id=candidate_models[0].task_id,
                latest_completed_at=candidate_models[0].completed_at or _utc_now(),
                task_count=len(candidate_models),
                tasks=candidate_models,
            )
        )
    items.sort(key=lambda item: (item.version is None, item.version or ""))
    return MeasurementVersionCandidateList(
        task_id=task_id,
        rule_code=rule_code,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        device_id=device_id,
        current_version=_task_version(current_task),
        items=items,
    )


def _version_summary(
    current_records: list[IndexRecord],
    baseline_records: list[IndexRecord],
    *,
    current_version: str | None,
    baseline_version: str | None,
) -> MeasurementVersionComparisonSummary:
    """使用第一版均值口径输出版本涨跌摘要。"""
    current_value = statistics.mean(record["value"] for record in current_records) if current_records else None
    baseline_value = statistics.mean(record["value"] for record in baseline_records) if baseline_records else None
    absolute_change = (
        current_value - baseline_value if current_value is not None and baseline_value is not None else None
    )
    change_ratio = (
        absolute_change / abs(baseline_value)
        if absolute_change is not None and baseline_value is not None and baseline_value != 0
        else None
    )
    if absolute_change is None:
        direction = MeasurementVersionDirection.UNKNOWN
        message = "缺少当前或基线有效数据，无法计算版本对比摘要。"
    elif abs(absolute_change) <= 1e-9:
        direction = MeasurementVersionDirection.FLAT
        message = f"当前版本均值与基线版本均值基本持平，均为 {baseline_value:.4g}。"
    elif absolute_change > 0:
        direction = MeasurementVersionDirection.UP
        message = f"当前版本均值较基线版本均值上涨 {absolute_change:.4g}（{change_ratio * 100:.2f}%）。"
    else:
        direction = MeasurementVersionDirection.DOWN
        message = f"当前版本均值较基线版本均值下降 {abs(absolute_change):.4g}（{abs(change_ratio) * 100:.2f}%）。"

    unknown_parts = []
    if current_version is None:
        unknown_parts.append("当前任务")
    if baseline_version is None:
        unknown_parts.append("基线任务")
    if unknown_parts:
        message += f"{'、'.join(unknown_parts)}版本未知。"
    return MeasurementVersionComparisonSummary(
        current_value=current_value,
        baseline_value=baseline_value,
        absolute_change=absolute_change,
        change_ratio=change_ratio,
        direction=direction,
        sample_count=len(current_records) + len(baseline_records),
        message=message,
    )


def get_version_compare(
    task_id: str,
    *,
    rule_code: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    object_key: str,
    period_minutes: int | None,
    baseline_task_id: str,
    output: Path | None = None,
) -> MeasurementVersionComparison:
    """组装同设备、不同系统版本的单指标任务对比。"""
    output = output or settings.output
    if rule_code != KPI_RULE_CODE:
        raise ValueError(f"不支持的规则: {rule_code}")
    current_task = load_task_meta(output, task_id)
    if current_task is None:
        raise FileNotFoundError(output / task_id / "task.json")

    device_id = _task_device_id(task_id, output)
    current_version = _task_version(current_task)
    current_task_model = _version_task(task_id, current_task)
    current_records: list[IndexRecord] = []
    baseline_records: list[IndexRecord] = []
    baseline_task: object | None = None
    baseline_task_id_safe = baseline_task_id
    reason_code: str | None = None
    message = ""

    def finish(
        status: MeasurementHistoryMatchStatus,
        summary: MeasurementVersionComparisonSummary | None = None,
    ) -> MeasurementVersionComparison:
        nonlocal message
        if status == MeasurementHistoryMatchStatus.DEGRADED:
            label = {
                "device_id_missing": "当前任务设备 ID 缺失，无法进行同设备版本对比",
                "current_index_missing": "当前任务历史索引缺失",
                "current_metric_dimension_missing": "当前任务没有指定指标、对象和周期的有效趋势点",
                "baseline_task_not_found": "基线任务不存在或元数据无效",
                "baseline_device_mismatch": "基线任务设备 ID 与当前任务不一致",
                "baseline_task_not_completed": "基线任务未完成或缺少完成时间",
                "baseline_same_version": "版本相同，不能作为版本对比基线",
                "baseline_index_missing": "基线任务索引缺失",
                "baseline_index_empty": "基线任务历史索引为空或无效",
                "baseline_object_or_period_mismatch": "基线任务没有该测量单元、指标、对象或周期的有效数据",
            }.get(reason_code or "", "版本对比不可用")
            message = message or label
        elif status == MeasurementHistoryMatchStatus.NO_HISTORY and not message:
            message = "基线任务没有可对比的数据点"
        return MeasurementVersionComparison(
            task_id=task_id,
            baseline_task_id=baseline_task_id_safe,
            rule_code=rule_code,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            device_id=device_id,
            object_key=object_key,
            period_minutes=period_minutes,
            current_version=current_version,
            baseline_version=_task_version(baseline_task) if baseline_task is not None else None,
            current_task=current_task_model,
            baseline_task=_version_task(baseline_task_id_safe, baseline_task) if baseline_task is not None else None,
            current_points=[_point_from_record(record) for record in current_records],
            baseline_points=[_point_from_record(record) for record in baseline_records],
            summary=summary
            or MeasurementVersionComparisonSummary(
                direction=MeasurementVersionDirection.UNKNOWN,
                sample_count=0,
                message="版本对比不可用。",
            ),
            match=MeasurementHistoryMatch(
                status=status,
                reason_code=reason_code,
                message=message,
            ),
        )

    if not device_id:
        reason_code = "device_id_missing"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)

    baseline_task = load_task_meta(output, baseline_task_id_safe)
    if baseline_task is None:
        reason_code = "baseline_task_not_found"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)
    if _task_device_id(baseline_task_id_safe, output) != device_id:
        reason_code = "baseline_device_mismatch"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)
    if baseline_task.status.value != "completed" or baseline_task.completed_at is None:
        reason_code = "baseline_task_not_completed"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)

    baseline_version = _task_version(baseline_task)
    if current_version is not None and baseline_version is not None and current_version == baseline_version:
        reason_code = "baseline_same_version"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)

    try:
        current_records = _dimension_records(
            task_id,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            object_key=object_key,
            period_minutes=period_minutes,
            output=output,
        )
    except FileNotFoundError:
        reason_code = "current_index_missing"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)

    if not current_records:
        reason_code = "current_metric_dimension_missing"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)

    try:
        baseline_records = _dimension_records(
            baseline_task_id_safe,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            object_key=object_key,
            period_minutes=period_minutes,
            output=output,
        )
    except FileNotFoundError:
        reason_code = "baseline_index_missing"
        return finish(MeasurementHistoryMatchStatus.DEGRADED)

    if not baseline_records:
        reason_code = "baseline_object_or_period_mismatch"
        status = MeasurementHistoryMatchStatus.NO_HISTORY
        message = "基线任务没有该测量单元、指标、对象或周期的有效数据"
        return finish(status)

    summary = _version_summary(
        current_records,
        baseline_records,
        current_version=current_version,
        baseline_version=baseline_version,
    )
    if current_version is None or baseline_version is None:
        message = "当前或基线任务版本未知，以下为同设备任务级对比。"
        status = MeasurementHistoryMatchStatus.MATCHED
        return finish(status, summary)
    return finish(MeasurementHistoryMatchStatus.MATCHED, summary)


def validate_history_model(payload: MeasurementHistoryTrend) -> MeasurementHistoryTrend:
    """保留显式模型校验入口，避免服务测试绕过响应模型。"""
    try:
        return MeasurementHistoryTrend.model_validate(payload.model_dump(mode="json"))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
