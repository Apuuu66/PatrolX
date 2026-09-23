"""基于测量单元的 KPI 资源目录与任务文件归属服务。"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import exists, func, or_

from app.core.encoding import decode_text_with_fallback, read_text_with_fallback
from app.core.logging import get_logger
from app.models.db import (
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    init_db,
    session_factory,
)
from app.services.kpi_history import write_history_index


class KpiMeasurementError(Exception):
    """测量单元业务错误。"""

    def __init__(self, code: str, message: str, status_code: int = 400, detail: Any = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


_RESOURCE_PREFIXES = {"MU_": "mu", "ME_": "me", "UNIT_": "unit"}
logger = get_logger("patrolx.kpi_measurement_units")
MANUAL_METRIC_PREFIX = "ME__MANUAL_"


def is_manual_metric_id(resource_id: str | None) -> bool:
    """判断 ME 资源 ID 是否来自人工注册。"""
    return bool(resource_id and resource_id.upper().startswith(MANUAL_METRIC_PREFIX))


def resource_kind(resource_id: str) -> str | None:
    """根据资源 ID 前缀识别资源类型；前缀大小写不敏感。"""
    normalized_id = resource_id.upper()
    for prefix, kind in _RESOURCE_PREFIXES.items():
        if normalized_id.startswith(prefix):
            return kind
    return None


def filename_fragment(name_en: str) -> str:
    """测量单元英文名转大小写敏感文件名片段。"""
    return "_".join(name_en.strip().split())


def conflict_resource_id(resource_id: str, name_zh: str) -> str:
    """为同 ID 不同中文名的资源生成稳定冲突键 ID。"""
    digest = hashlib.sha256(f"{resource_id}\x00{name_zh}".encode()).hexdigest()[:8]
    conflict_id = f"{resource_id}__CONFLICT_{digest}"
    if len(conflict_id) <= 128:
        return conflict_id
    return f"{resource_id[:110]}__CONFLICT_{digest}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def import_resource_csv(text_or_file: io.StringIO | io.BytesIO | str | Path) -> dict[str, Any]:
    """增量导入资源目录；同中文名的自动指标会被合并，不删除已有资源。"""
    init_db()
    try:
        if isinstance(text_or_file, io.BytesIO):
            raw, _ = decode_text_with_fallback(text_or_file.getvalue())
        elif isinstance(text_or_file, io.StringIO):
            raw = text_or_file.getvalue()
        else:
            raw, _ = read_text_with_fallback(text_or_file)
    except UnicodeDecodeError as exc:
        raise KpiMeasurementError(
            "kpi_resource_csv_encoding",
            "资源 CSV 编码无法识别；支持 UTF-8 和 GB18030（含 GBK/GB2312）",
            400,
        ) from exc
    except OSError as exc:
        raise KpiMeasurementError("kpi_resource_csv_unreadable", f"资源 CSV 读取失败: {exc}", 400) from exc
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        raise KpiMeasurementError("kpi_resource_csv_invalid", "资源目录缺少表头", 400)
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    required = {"资源id", "中文描述", "英文描述"}
    if not required.issubset(set(reader.fieldnames)):
        raise KpiMeasurementError("kpi_resource_csv_invalid", "资源目录表头必须是资源id/中文描述/英文描述", 400)

    added = {"mu": 0, "me": 0, "unit": 0}
    updated = {"mu": 0, "me": 0, "unit": 0}
    errors: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    resources_by_name: dict[tuple[str, str], KpiMeasurementResource] = {}
    resources_by_id: dict[str, KpiMeasurementResource] = {}
    with session_factory() as session:
        for line_number, row in enumerate(reader, start=2):
            resource_id = str(row.get("资源id") or "").strip()
            name_zh = str(row.get("中文描述") or "").strip()
            name_en = str(row.get("英文描述") or "").strip()
            kind = resource_kind(resource_id)
            if not kind:
                skipped.append(
                    {
                        "resource_id": resource_id or None,
                        "line_number": line_number,
                        "reason": "unsupported_resource_prefix",
                    }
                )
                continue
            if not name_zh or not name_en:
                errors.append(
                    {
                        "resource_id": resource_id or None,
                        "line_number": line_number,
                        "reason": "invalid_resource",
                    }
                )
                continue
            if kind == "me":
                owner_id = str(row.get("所属测量单元id") or "").strip()
                if owner_id:
                    owner = session.get(KpiMeasurementResource, owner_id)
                    if owner is None or owner.kind != "mu":
                        errors.append(
                            {
                                "resource_id": resource_id,
                                "line_number": line_number,
                                "reason": "measurement_unit_not_found",
                            }
                        )
                        continue
                display_order_raw = str(row.get("显示顺序") or "").strip()
                try:
                    display_order = int(display_order_raw) if display_order_raw else None
                except ValueError:
                    errors.append(
                        {
                            "resource_id": resource_id,
                            "line_number": line_number,
                            "reason": "invalid_display_order",
                        }
                    )
                    continue
                direction = str(row.get("方向") or "").strip() or None
                if direction and direction not in {"higher_better", "lower_better", "neutral"}:
                    errors.append(
                        {
                            "resource_id": resource_id,
                            "line_number": line_number,
                            "reason": "invalid_direction",
                        }
                    )
                    continue
                importance = str(row.get("重要级别") or "").strip() or None
                if importance and importance not in {"P0", "P1", "P2", "normal"}:
                    errors.append(
                        {
                            "resource_id": resource_id,
                            "line_number": line_number,
                            "reason": "invalid_importance",
                        }
                    )
                    continue
                warning_threshold, threshold_errors = _parse_threshold(
                    row.get("预警阈值"),
                    "warning_threshold",
                    line_number,
                )
                critical_threshold, more_errors = _parse_threshold(
                    row.get("失败阈值"),
                    "critical_threshold",
                    line_number,
                )
                errors.extend(threshold_errors)
                errors.extend(more_errors)
                errors.extend(
                    _threshold_policy_errors(
                        direction,
                        warning_threshold,
                        critical_threshold,
                        line_number=line_number,
                        resource_id=resource_id,
                    )
                )
                if any(
                    error.get("reason")
                    in {
                        "invalid_warning_threshold",
                        "invalid_critical_threshold",
                        "threshold_direction_conflict",
                    }
                    for error in errors
                ):
                    continue
                metric_group = str(row.get("指标分组") or "").strip() or None
            else:
                owner_id = None
                display_order = None
                metric_group = None
                direction = None
                importance = None
                warning_threshold = None
                critical_threshold = None

            name_key = (kind, name_zh)
            existing_by_name = resources_by_name.get(name_key)
            if existing_by_name is None:
                existing_by_name = (
                    session.query(KpiMeasurementResource)
                    .filter(KpiMeasurementResource.kind == kind, KpiMeasurementResource.name_zh == name_zh)
                    .one_or_none()
                )
            existing_by_id = resources_by_id.get(resource_id)
            if existing_by_id is None:
                existing_by_id = session.get(KpiMeasurementResource, resource_id)
            if existing_by_id is not None and existing_by_id.name_zh != name_zh:
                resource_id = conflict_resource_id(resource_id, name_zh)
                existing_by_id = resources_by_id.get(resource_id) or session.get(KpiMeasurementResource, resource_id)

            if existing_by_name is not None:
                resources_by_name[name_key] = existing_by_name
                resources_by_id.setdefault(existing_by_name.resource_id, existing_by_name)
                if existing_by_id is not None and existing_by_id is not existing_by_name:
                    errors.append(
                        {
                            "resource_id": resource_id,
                            "line_number": line_number,
                            "reason": "resource_id_conflict",
                            "existing_name_zh": existing_by_id.name_zh,
                            "name_zh": name_zh,
                        }
                    )
                    continue
                if kind == "me" and owner_id:
                    current_owner = _metric_ownership_unit(session, existing_by_name.resource_id)
                    if current_owner and current_owner != owner_id:
                        errors.append(
                            {
                                "resource_id": existing_by_name.resource_id,
                                "line_number": line_number,
                                "reason": "metric_owner_conflict",
                                "existing_measurement_unit_id": current_owner,
                                "requested_measurement_unit_id": owner_id,
                            }
                        )
                        continue
                changed = existing_by_name.name_en != name_en
                existing_by_name.name_en = name_en
                if kind == "mu":
                    existing_by_name.filename_fragment = filename_fragment(name_en)
                if kind == "me":
                    if owner_id:
                        existing_by_name.source = "preset"
                        existing_by_name.origin_task_id = None
                        existing_by_name.origin_file = None
                    defaults = {
                        "display_order": display_order
                        if display_order is not None
                        else (
                            None
                            if getattr(existing_by_name, "display_order", None) is not None
                            else _next_display_order(session)
                        ),
                        "metric_group": metric_group or "未分组",
                        "direction": direction or "neutral",
                        "importance": importance or "normal",
                    }
                    for field, value in defaults.items():
                        if getattr(existing_by_name, field, None) is None:
                            setattr(existing_by_name, field, value)
                            changed = True
                    # 增量导入只补充缺失治理字段；已有值必须通过资源编辑显式调整。
                existing_by_name.updated_at = _utc_now()
                if changed:
                    updated[kind] += 1
                else:
                    skipped.append({"resource_id": existing_by_name.resource_id, "reason": "unchanged"})
                continue

            if existing_by_id is not None and existing_by_id.name_zh != name_zh:
                resources_by_id[resource_id] = existing_by_id
                errors.append(
                    {
                        "resource_id": resource_id,
                        "line_number": line_number,
                        "reason": "resource_id_conflict",
                        "existing_name_zh": existing_by_id.name_zh,
                        "name_zh": name_zh,
                    }
                )
                continue

            if kind == "me":
                if display_order is None:
                    display_order = _next_display_order(session)
                metric_group = metric_group or "未分组"
                direction = direction or "neutral"
                importance = importance or "normal"
            row_resource = KpiMeasurementResource(
                resource_id=resource_id,
                kind=kind,
                name_zh=name_zh,
                name_en=name_en,
                filename_fragment=filename_fragment(name_en) if kind == "mu" else None,
                enabled=True,
                display_order=display_order,
                metric_group=metric_group,
                direction=direction,
                importance=importance,
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
                source="preset",
                origin_task_id=None,
                origin_file=None,
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
            session.add(row_resource)
            resources_by_name[name_key] = row_resource
            resources_by_id[resource_id] = row_resource
            added[kind] += 1
        session.commit()

    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}


def list_measurement_units(search: str | None = None, enabled: bool | None = None) -> dict[str, Any]:
    """返回测量单元目录及资源/绑定统计。"""
    init_db()
    with session_factory() as session:
        query = session.query(KpiMeasurementResource).filter(KpiMeasurementResource.kind == "mu")
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(KpiMeasurementResource.name_zh.like(like), KpiMeasurementResource.name_en.like(like))
            )
        if enabled is not None:
            query = query.filter(KpiMeasurementResource.enabled.is_(enabled))
        rows = query.order_by(KpiMeasurementResource.resource_id).all()
        all_resources = session.query(KpiMeasurementResource).all()
        metric_count = sum(1 for row in all_resources if row.kind == "me")
        unit_count = sum(1 for row in all_resources if row.kind == "unit")
        items = [
            {
                "resource_id": row.resource_id,
                "name_zh": row.name_zh,
                "name_en": row.name_en,
                "filename_fragment": row.filename_fragment,
                "enabled": row.enabled,
                "metric_count": metric_count,
                "unit_count": unit_count,
                "confirmed_binding_count": 0,
                "candidate_binding_count": 0,
                "derived_count": 0,
            }
            for row in rows
        ]
        return {"total": len(items), "items": items}


def set_measurement_unit_enabled(resource_id: str, enabled: bool) -> dict[str, Any]:
    """启用或停用测量单元。"""
    init_db()
    with session_factory() as session:
        row = session.get(KpiMeasurementResource, resource_id)
        if row is None or row.kind != "mu":
            raise KpiMeasurementError("kpi_measurement_unit_not_found", f"测量单元不存在: {resource_id}", 404)
        row.enabled = enabled
        row.updated_at = _utc_now()
        session.commit()
        return {"resource_id": resource_id, "enabled": row.enabled}


def _file_stem(filename: str) -> str:
    return Path(filename).stem


def match_measurement_files(files: Iterable[tuple[str, Path]]) -> dict[str, Any]:
    """把任务 CSV 文件归属到大小写敏感的测量单元片段。"""
    init_db()
    candidates: list[tuple[str, Path]] = [(name, Path(path)) for name, path in files]
    with session_factory() as session:
        units = session.query(KpiMeasurementResource).filter(KpiMeasurementResource.kind == "mu").all()
    fragments = [(unit, unit.filename_fragment or "") for unit in units]

    matched: list[dict[str, Any]] = []
    for filename, path in candidates:
        stem = _file_stem(filename)
        hits = [unit for unit, fragment in fragments if fragment and fragment in stem]
        if len(hits) > 1:
            hits = sorted(hits, key=lambda unit: len(unit.filename_fragment or ""), reverse=True)
            if len(hits) > 1 and len(hits[0].filename_fragment or "") == len(hits[1].filename_fragment or ""):
                matched.append(
                    {
                        "filename": filename,
                        "source_file": filename,
                        "source_path": str(path),
                        "status": "ambiguous",
                        "measurement_unit_id": None,
                        "reason": "multiple_measurement_units",
                    }
                )
                continue
            hits = [hits[0]]
        if not hits:
            matched.append(
                {
                    "filename": filename,
                    "source_file": str(path),
                    "status": "unmatched",
                    "measurement_unit_id": None,
                    "reason": "no_measurement_unit_match",
                }
            )
            continue
        unit = hits[0]
        matched.append(
            {
                "filename": filename,
                "source_file": filename,
                "source_path": str(path),
                "status": "matched" if unit.enabled else "disabled",
                "measurement_unit_id": unit.resource_id,
                "reason": None if unit.enabled else "measurement_unit_disabled",
            }
        )
    return {"files": matched}


_UNIT_PATTERN = re.compile(r"^(.*?)\s*[（(]([^()（）]*)[）)]\s*$")
_HEADER_ANCHORS = ("测量开始时间", "测量结束时间", "周期(分钟)")


def _split_source_name(raw_name: str) -> tuple[str, str | None]:
    match = _UNIT_PATTERN.match(raw_name.strip())
    if not match:
        return raw_name.strip(), None
    return match.group(1).strip(), match.group(2).strip()


def _find_header(rows: list[list[str]]) -> tuple[int, list[str]] | None:
    for index, row in enumerate(rows[:30]):
        if all(anchor in row for anchor in _HEADER_ANCHORS):
            return index, row
    return None


def _read_csv_rows(path: Path) -> list[list[str]]:
    """读取任务 CSV，兼容 UTF-8 与 GB18030 系列。"""
    text, _ = read_text_with_fallback(path)
    return list(csv.reader(io.StringIO(text, newline="")))


def _next_display_order(session: Any) -> int:
    """返回下一个资源显示顺序；空目录从 1 开始。"""
    current = session.query(func.max(KpiMeasurementResource.display_order)).scalar()
    return int(current or 0) + 1


def _parse_threshold(value: Any, field: str, line_number: int) -> tuple[Any, list[dict[str, Any]]]:
    """解析可选阈值；非法值返回错误明细而不中断整份目录导入。"""
    text_value = str(value or "").strip()
    if not text_value:
        return None, []
    try:
        return float(text_value), []
    except ValueError:
        return None, [{"resource_id": None, "line_number": line_number, "reason": f"invalid_{field}"}]


def _threshold_policy_errors(
    direction: str | None,
    warning_threshold: float | None,
    critical_threshold: float | None,
    *,
    line_number: int | None = None,
    resource_id: str | None = None,
) -> list[dict[str, Any]]:
    """校验方向和预警/失败阈值的方向性关系。"""
    if not direction or direction == "neutral" or warning_threshold is None or critical_threshold is None:
        return []
    invalid = (direction == "higher_better" and critical_threshold >= warning_threshold) or (
        direction == "lower_better" and critical_threshold <= warning_threshold
    )
    if not invalid:
        return []
    item: dict[str, Any] = {"reason": "threshold_direction_conflict", "direction": direction}
    if line_number is not None:
        item["line_number"] = line_number
    if resource_id is not None:
        item["resource_id"] = resource_id
    return [item]


def _metric_ownership_unit(session: Any, metric_id: str, exclude_unit_id: str | None = None) -> str | None:
    """返回指标当前的唯一启用归属测量单元。"""
    row = (
        session.query(KpiMeasurementBinding)
        .filter(
            KpiMeasurementBinding.metric_resource_id == metric_id,
            KpiMeasurementBinding.status == "confirmed",
            KpiMeasurementBinding.enabled.is_(True),
        )
        .filter(KpiMeasurementBinding.measurement_unit_id != exclude_unit_id if exclude_unit_id else True)
        .first()
    )
    return row.measurement_unit_id if row else None


def _ensure_metric_for_column(
    session: Any,
    *,
    task_id: str,
    source_file: str,
    measurement_unit_id: str,
    raw_name: str,
    base_name: str,
    display_unit: str | None,
) -> tuple[KpiMeasurementResource, str]:
    """复用或自动创建指标，并返回资源与匹配结果。"""
    metric = (
        session.query(KpiMeasurementResource)
        .filter(
            KpiMeasurementResource.kind == "me",
            or_(KpiMeasurementResource.name_zh == base_name, KpiMeasurementResource.name_en == base_name),
        )
        .first()
    )
    if metric is not None:
        owner = _metric_ownership_unit(session, metric.resource_id, exclude_unit_id=measurement_unit_id)
        if owner is not None:
            return metric, "conflict"
        return metric, "preset_hit" if getattr(metric, "source", "preset") == "preset" else "reuse"

    suffix = hashlib.sha256(f"{measurement_unit_id}\x00{raw_name}".encode()).hexdigest()[:6].upper()
    slug = _manual_metric_slug(base_name)[:24] or "AUTO"
    resource_id = f"ME__AUTO_{slug}_{suffix}"
    attempt = 0
    while session.get(KpiMeasurementResource, resource_id) is not None:
        attempt += 1
        resource_id = f"ME__AUTO_{slug}_{suffix}_{attempt}"
    metric = KpiMeasurementResource(
        resource_id=resource_id,
        kind="me",
        name_zh=base_name,
        name_en="",
        filename_fragment=None,
        enabled=True,
        display_order=_next_display_order(session),
        metric_group="未分组",
        direction="neutral",
        importance="normal",
        source="discovered",
        origin_task_id=task_id,
        origin_file=source_file,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(metric)
    session.flush()
    return metric, "auto_registered"


PREFERRED_PERIOD_MINUTES = (15, 5)


def _file_period_minutes(path: Path) -> int | None:
    """从 CSV 周期列读取文件粒度；解析失败时不参与周期优先级。"""
    try:
        rows = _read_csv_rows(path)
    except (OSError, UnicodeError, csv.Error):
        return None
    header = _find_header(rows)
    if header is None or "周期(分钟)" not in header[1]:
        return None
    period_index = header[1].index("周期(分钟)")
    for row in rows[header[0] + 1 :]:
        if len(row) > period_index and row[period_index].strip():
            return _parse_period_minutes(row[period_index])
    return None


def _select_preferred_period_files(file_results: list[dict[str, Any]]) -> None:
    """按测量单元选择 15/5 分钟周期，避免不同粒度互相污染。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for file_result in file_results:
        if file_result.get("status") != "matched":
            continue
        file_result["period_minutes"] = _file_period_minutes(Path(file_result["source_path"]))
        unit_id = file_result.get("measurement_unit_id")
        if unit_id:
            groups.setdefault(unit_id, []).append(file_result)

    for unit_files in groups.values():
        periods = {item["period_minutes"] for item in unit_files}
        selected_periods: set[int] | None = None
        for preferred_period in PREFERRED_PERIOD_MINUTES:
            if preferred_period in periods:
                selected_periods = {preferred_period}
                break
        if selected_periods is None:
            continue
        for file_result in unit_files:
            period = file_result["period_minutes"]
            if period is not None and period not in selected_periods:
                file_result.update({"status": "skipped", "reason": "period_not_preferred"})


def discover_measurement_bindings(task_id: str, files: Iterable[tuple[str, Path]]) -> dict[str, Any]:
    """扫描任务 CSV 表头，发现指标候选绑定。"""
    init_db()
    matched_files = match_measurement_files(files)
    _select_preferred_period_files(matched_files["files"])
    with session_factory() as session:
        for file_result in matched_files["files"]:
            if file_result["status"] != "matched":
                continue
            path = Path(file_result["source_path"])
            try:
                rows = _read_csv_rows(path)
            except (OSError, UnicodeError, csv.Error) as exc:
                file_result.update({"status": "parse_error", "reason": "csv_read_error", "detail": str(exc)})
                continue
            header = _find_header(rows)
            if header is None:
                file_result.update({"status": "parse_error", "reason": "header_not_found"})
                continue
            anchor_index = header[1].index("周期(分钟)")
            metric_columns = header[1][anchor_index + 1 :]
            candidates: list[dict[str, Any]] = []
            matched_metrics: list[str] = []
            auto_registered: list[str] = []
            conflicts: list[str] = []
            duplicate_columns = [name for name, count in Counter(metric_columns).items() if count > 1]
            for raw_name in metric_columns:
                base_name, display_unit = _split_source_name(raw_name)
                metric, outcome = _ensure_metric_for_column(
                    session,
                    task_id=task_id,
                    source_file=file_result["filename"],
                    measurement_unit_id=file_result["measurement_unit_id"],
                    raw_name=raw_name,
                    base_name=base_name,
                    display_unit=display_unit,
                )
                metric_id = metric.resource_id
                if outcome == "auto_registered":
                    auto_registered.append(raw_name)
                    matched_metrics.append(raw_name)
                elif outcome == "conflict":
                    conflicts.append(raw_name)
                else:
                    matched_metrics.append(raw_name)
                existing = (
                    session.query(KpiMeasurementBinding)
                    .filter(
                        KpiMeasurementBinding.measurement_unit_id == file_result["measurement_unit_id"],
                        KpiMeasurementBinding.raw_source_name == raw_name,
                    )
                    .one_or_none()
                )
                if existing:
                    if outcome == "auto_registered" or existing.metric_resource_id is None:
                        existing.metric_resource_id = metric_id
                        existing.updated_at = _utc_now()
                    if outcome != "conflict" and existing.status != "confirmed":
                        existing.status = "confirmed"
                        existing.updated_at = _utc_now()
                    candidates.append(_binding_dict(existing))
                    continue
                row = KpiMeasurementBinding(
                    metric_resource_id=metric_id,
                    measurement_unit_id=file_result["measurement_unit_id"],
                    raw_source_name=raw_name,
                    base_source_name=base_name,
                    display_unit=display_unit,
                    status="conflict" if outcome == "conflict" else "confirmed",
                    enabled=True,
                    task_id=task_id,
                    source_file=file_result["filename"],
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
                session.add(row)
                session.flush()
                candidates.append(_binding_dict(row))
            file_result["binding_candidates"] = len(candidates)
            file_result["unknown_columns"] = []
            file_result["matched_metrics"] = matched_metrics
            file_result["auto_registered_metrics"] = auto_registered
            file_result["conflict_metrics"] = conflicts
            file_result["duplicate_columns"] = duplicate_columns
        session.commit()
    return matched_files


def _metric_resource_dict(row: KpiMeasurementResource) -> dict[str, Any]:
    """返回 ME/MU/UNIT 资源公共契约字典。"""
    return {
        "resource_id": row.resource_id,
        "kind": row.kind,
        "name_zh": row.name_zh,
        "name_en": row.name_en,
        "enabled": row.enabled,
        "is_manual": is_manual_metric_id(row.resource_id),
        "display_order": getattr(row, "display_order", None),
        "metric_group": getattr(row, "metric_group", None),
        "direction": getattr(row, "direction", None),
        "importance": getattr(row, "importance", None),
        "warning_threshold": getattr(row, "warning_threshold", None),
        "critical_threshold": getattr(row, "critical_threshold", None),
        "source": getattr(row, "source", "preset"),
        "origin_task_id": getattr(row, "origin_task_id", None),
        "origin_file": getattr(row, "origin_file", None),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _manual_metric_slug(name_en: str | None) -> str:
    """把英文名转为 ID 中的可读片段，避免生成完全随机的资源 ID。"""
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", (name_en or "").strip()).strip("_").upper()
    # 连续重复字符会消耗 ID 长度但降低可读性，保留四位即可区分常见缩写。
    normalized = re.sub(r"(.)\1{4,}", r"\1\1\1\1", normalized)
    return normalized or "UNNAMED"


def _generate_manual_metric_id(session: Any, name_en: str | None) -> str:
    """生成前缀、英文可读片段和短随机后缀组成的人工指标 ID。"""
    suffix_length = 6
    slug = _manual_metric_slug(name_en)
    max_slug_length = 128 - len(MANUAL_METRIC_PREFIX) - suffix_length - 1
    prefix = f"{MANUAL_METRIC_PREFIX}{slug[:max_slug_length]}_"
    for _ in range(16):
        resource_id = f"{prefix}{uuid.uuid4().hex[:suffix_length].upper()}"
        if session.get(KpiMeasurementResource, resource_id) is None:
            return resource_id
    raise KpiMeasurementError("kpi_metric_id_generate_failed", "人工指标资源 ID 生成失败", 500)


def register_metric_for_binding(
    binding_id: int,
    *,
    name_zh: str | None = None,
    name_en: str | None = None,
    bind_existing_resource_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """为未注册绑定创建人工 ME 指标或关联既有 ME 指标。"""
    init_db()
    normalized_zh = None if name_zh is None else str(name_zh).strip()
    normalized_en = None if name_en is None else str(name_en).strip()
    existing_id = None if bind_existing_resource_id is None else str(bind_existing_resource_id).strip()
    if existing_id:
        if normalized_zh is not None or normalized_en is not None:
            raise KpiMeasurementError("invalid_request", "绑定既有指标时不能提交中文名或英文名", 400)
    elif not normalized_zh:
        raise KpiMeasurementError("invalid_request", "注册新指标时中文名必填", 400)
    if normalized_zh and len(normalized_zh) > 256:
        raise KpiMeasurementError("invalid_request", "指标中文名长度不能超过 256", 400)
    if normalized_en and len(normalized_en) > 256:
        raise KpiMeasurementError("invalid_request", "指标英文名长度不能超过 256", 400)

    with session_factory() as session:
        binding = session.get(KpiMeasurementBinding, binding_id)
        if binding is None:
            raise KpiMeasurementError("kpi_binding_not_found", f"绑定不存在: {binding_id}", 404)
        if binding.metric_resource_id is not None:
            raise KpiMeasurementError(
                "kpi_binding_already_registered", f"绑定已关联指标: {binding.metric_resource_id}", 409
            )
        if binding.status != "candidate":
            raise KpiMeasurementError("kpi_binding_not_unregistered", "只有候选绑定可以注册指标", 409)

        if existing_id:
            metric = session.get(KpiMeasurementResource, existing_id)
            if metric is None:
                raise KpiMeasurementError("kpi_metric_not_found", f"指标不存在: {existing_id}", 404)
            if metric.kind != "me":
                raise KpiMeasurementError("kpi_metric_kind_invalid", f"资源不是 ME 指标: {existing_id}", 409)
            binding.metric_resource_id = metric.resource_id
            binding.status = "candidate"
            binding.updated_at = _utc_now()
            session.commit()
            return _binding_dict(binding), _metric_resource_dict(metric)

        duplicate = (
            session.query(KpiMeasurementResource)
            .filter(KpiMeasurementResource.kind == "me", KpiMeasurementResource.name_zh == normalized_zh)
            .one_or_none()
        )
        if duplicate is not None:
            raise KpiMeasurementError(
                "kpi_metric_name_conflict",
                f"同类指标中文名已存在: {normalized_zh}",
                409,
                {"existing_resource_id": duplicate.resource_id},
            )
        metric = KpiMeasurementResource(
            resource_id=_generate_manual_metric_id(session, normalized_en),
            kind="me",
            name_zh=normalized_zh or "",
            name_en=normalized_en or "",
            filename_fragment=None,
            enabled=True,
            display_order=_next_display_order(session),
            metric_group="未分组",
            direction="neutral",
            importance="normal",
            source="manual",
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        session.add(metric)
        session.flush()
        binding.metric_resource_id = metric.resource_id
        binding.status = "candidate"
        binding.updated_at = _utc_now()
        session.commit()
        return _binding_dict(binding), _metric_resource_dict(metric)


def update_manual_metric(
    resource_id: str,
    *,
    name_zh: str | None = None,
    name_en: str | None = None,
    enabled: bool | None = None,
    display_order: int | None = None,
    metric_group: str | None = None,
    direction: str | None = None,
    importance: str | None = None,
    warning_threshold: float | None = None,
    critical_threshold: float | None = None,
) -> dict[str, Any]:
    """编辑 ME 指标口径、默认值和阈值；资源 ID 与绑定来源不可修改。"""
    provided = {
        name_zh,
        name_en,
        enabled,
        display_order,
        metric_group,
        direction,
        importance,
        warning_threshold,
        critical_threshold,
    }
    if all(value is None for value in provided):
        raise KpiMeasurementError("kpi_metric_no_fields", "至少提供一个可编辑字段", 400)
    if direction is not None and direction not in {"higher_better", "lower_better", "neutral"}:
        raise KpiMeasurementError("kpi_metric_direction_invalid", f"指标方向非法: {direction}", 400)
    if importance is not None and importance not in {"P0", "P1", "P2", "normal"}:
        raise KpiMeasurementError("kpi_metric_importance_invalid", f"重要级别非法: {importance}", 400)
    if display_order is not None and display_order < 0:
        raise KpiMeasurementError("kpi_metric_display_order_invalid", "显示顺序不能小于 0", 400)
    normalized_zh = None if name_zh is None else str(name_zh).strip()
    normalized_en = None if name_en is None else str(name_en).strip()
    if normalized_zh == "":
        raise KpiMeasurementError("invalid_request", "指标中文名不能为空", 400)
    if normalized_zh and len(normalized_zh) > 256:
        raise KpiMeasurementError("invalid_request", "指标中文名长度不能超过 256", 400)
    if normalized_en and len(normalized_en) > 256:
        raise KpiMeasurementError("invalid_request", "指标英文名长度不能超过 256", 400)

    init_db()
    with session_factory() as session:
        row = session.get(KpiMeasurementResource, resource_id)
        if row is None or row.kind != "me":
            raise KpiMeasurementError("kpi_metric_not_found", f"指标不存在: {resource_id}", 404)
        if normalized_zh:
            conflict = (
                session.query(KpiMeasurementResource)
                .filter(
                    KpiMeasurementResource.kind == "me",
                    KpiMeasurementResource.name_zh == normalized_zh,
                    KpiMeasurementResource.resource_id != row.resource_id,
                )
                .one_or_none()
            )
            if conflict is not None:
                raise KpiMeasurementError(
                    "kpi_metric_name_conflict",
                    f"同类指标中文名已存在: {normalized_zh}",
                    409,
                    {"existing_resource_id": conflict.resource_id},
                )
            row.name_zh = normalized_zh
        if normalized_en is not None:
            row.name_en = normalized_en
        if enabled is not None:
            row.enabled = enabled
        if display_order is not None:
            row.display_order = display_order
        if metric_group is not None:
            row.metric_group = metric_group or "未分组"
        if direction is not None:
            row.direction = direction
        if importance is not None:
            row.importance = importance
        if warning_threshold is not None:
            row.warning_threshold = warning_threshold
        if critical_threshold is not None:
            row.critical_threshold = critical_threshold
        policy_errors = _threshold_policy_errors(
            row.direction, row.warning_threshold, row.critical_threshold, resource_id=row.resource_id
        )
        if policy_errors:
            raise KpiMeasurementError(
                "kpi_metric_threshold_conflict",
                "预警阈值和失败阈值与指标方向矛盾",
                400,
                {"errors": policy_errors},
            )
        row.updated_at = _utc_now()
        session.commit()
        return _metric_resource_dict(row)


def list_measurement_resources(
    kind: str | None = None,
    search: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """分页查询资源目录，供人工注册时选择已有 ME 指标。"""
    if page < 1 or page_size < 1:
        raise KpiMeasurementError("invalid_page", "分页参数非法", 400)
    init_db()
    with session_factory() as session:
        query = session.query(KpiMeasurementResource)
        if kind:
            query = query.filter(KpiMeasurementResource.kind == kind)
        if enabled is not None:
            query = query.filter(KpiMeasurementResource.enabled == enabled)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    KpiMeasurementResource.resource_id.like(like),
                    KpiMeasurementResource.name_zh.like(like),
                    KpiMeasurementResource.name_en.like(like),
                )
            )
        rows = query.order_by(
            KpiMeasurementResource.display_order.asc().nullslast(),
            KpiMeasurementResource.resource_id.asc(),
        ).all()
        start = (page - 1) * page_size
        return {
            "total": len(rows),
            "items": [_metric_resource_dict(row) for row in rows[start : start + page_size]],
        }


def _resource_name_map(session: Any, resource_ids: Iterable[str | None]) -> dict[str, str]:
    """加载指定资源的中文名映射，供列表展示时避免逐行查询。"""
    normalized_ids = sorted({resource_id for resource_id in resource_ids if resource_id})
    if not normalized_ids:
        return {}
    rows = session.query(KpiMeasurementResource).filter(KpiMeasurementResource.resource_id.in_(normalized_ids)).all()
    return {row.resource_id: row.name_zh for row in rows}


def _binding_dict(
    row: KpiMeasurementBinding,
    resource_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    names = resource_names or {}
    return {
        "id": row.id,
        "metric_resource_id": row.metric_resource_id,
        "metric_resource_name_zh": names.get(row.metric_resource_id or ""),
        "measurement_unit_id": row.measurement_unit_id,
        "measurement_unit_name_zh": names.get(row.measurement_unit_id),
        "raw_source_name": row.raw_source_name,
        "base_source_name": row.base_source_name,
        "display_unit": row.display_unit,
        "status": row.status,
        "enabled": row.enabled,
        "task_id": row.task_id,
        "source_file": row.source_file,
        "metric_is_manual": is_manual_metric_id(row.metric_resource_id),
    }


def list_measurement_bindings(
    measurement_unit_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    unit_search: str | None = None,
) -> dict[str, Any]:
    """列出指标绑定候选；unit_search 支持测量单元 ID 和名称模糊匹配。"""
    init_db()
    with session_factory() as session:
        query = session.query(KpiMeasurementBinding)
        if measurement_unit_id:
            query = query.filter(KpiMeasurementBinding.measurement_unit_id == measurement_unit_id)
        if unit_search:
            like = f"%{unit_search}%"
            query = query.filter(
                or_(
                    KpiMeasurementBinding.measurement_unit_id.like(like),
                    exists().where(
                        KpiMeasurementResource.resource_id == KpiMeasurementBinding.measurement_unit_id,
                        or_(
                            KpiMeasurementResource.name_zh.like(like),
                            KpiMeasurementResource.name_en.like(like),
                        ),
                    ),
                )
            )
        if status:
            query = query.filter(KpiMeasurementBinding.status == status)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    KpiMeasurementBinding.metric_resource_id.like(like),
                    KpiMeasurementBinding.base_source_name.like(like),
                    KpiMeasurementBinding.measurement_unit_id.like(like),
                    KpiMeasurementBinding.task_id.like(like),
                    KpiMeasurementBinding.source_file.like(like),
                    exists().where(
                        KpiMeasurementResource.resource_id == KpiMeasurementBinding.measurement_unit_id,
                        or_(
                            KpiMeasurementResource.name_zh.like(like),
                            KpiMeasurementResource.name_en.like(like),
                        ),
                    ),
                )
            )
        rows = query.order_by(KpiMeasurementBinding.id.desc()).all()
        names = _resource_name_map(
            session,
            [row.metric_resource_id for row in rows] + [row.measurement_unit_id for row in rows],
        )
        return {"total": len(rows), "items": [_binding_dict(row, names) for row in rows]}


def set_measurement_binding_status(binding_id: int, status: str, enabled: bool | None = None) -> dict[str, Any]:
    """确认、忽略或更新绑定状态；不允许自动改绑冲突指标。"""
    if status not in {"candidate", "confirmed", "ignored"}:
        raise KpiMeasurementError("kpi_binding_status_invalid", f"绑定状态非法: {status}", 400)
    init_db()
    with session_factory() as session:
        row = session.get(KpiMeasurementBinding, binding_id)
        if row is None:
            raise KpiMeasurementError("kpi_binding_not_found", f"绑定不存在: {binding_id}", 404)
        if row.metric_resource_id and status == "confirmed":
            conflict = (
                session.query(KpiMeasurementBinding)
                .filter(
                    KpiMeasurementBinding.metric_resource_id == row.metric_resource_id,
                    KpiMeasurementBinding.measurement_unit_id != row.measurement_unit_id,
                    KpiMeasurementBinding.status == "confirmed",
                    KpiMeasurementBinding.id != row.id,
                )
                .first()
            )
            if conflict:
                raise KpiMeasurementError(
                    "kpi_binding_conflict",
                    "指标已绑定到其他测量单元",
                    409,
                    {"metric_resource_id": row.metric_resource_id, "measurement_unit_id": conflict.measurement_unit_id},
                )
        row.status = status
        if enabled is not None:
            row.enabled = enabled
        row.updated_at = _utc_now()
        session.commit()
        return _binding_dict(row)


def batch_confirm_measurement_bindings(binding_ids: list[int]) -> dict[str, Any]:
    """批量确认指标绑定；失败项不影响其他独立可确认项。"""
    init_db()
    unique_ids = list(dict.fromkeys(binding_ids))
    if not unique_ids:
        raise KpiMeasurementError("kpi_binding_batch_empty", "批量确认绑定列表不能为空", 400)
    if len(unique_ids) > 200:
        raise KpiMeasurementError("kpi_binding_batch_too_large", "单次批量确认最多 200 条绑定", 400)

    with session_factory() as session:
        rows = session.query(KpiMeasurementBinding).filter(KpiMeasurementBinding.id.in_(unique_ids)).all()
        rows_by_id = {row.id: row for row in rows}
        items: list[dict[str, Any]] = []
        candidates_by_metric: dict[str, list[KpiMeasurementBinding]] = {}

        for binding_id in unique_ids:
            row = rows_by_id.get(binding_id)
            if row is None:
                items.append(
                    {
                        "binding_id": binding_id,
                        "outcome": "failed",
                        "error_code": "kpi_binding_not_found",
                        "message": f"绑定不存在: {binding_id}",
                    }
                )
            elif row.status == "confirmed":
                items.append({"binding_id": binding_id, "outcome": "already_confirmed"})
            elif row.status != "candidate":
                items.append(
                    {
                        "binding_id": binding_id,
                        "outcome": "failed",
                        "error_code": "kpi_binding_status_not_confirmable",
                        "message": f"绑定状态 {row.status} 不允许批量确认",
                    }
                )
            elif row.metric_resource_id is None:
                items.append(
                    {
                        "binding_id": binding_id,
                        "outcome": "failed",
                        "error_code": "kpi_binding_metric_missing",
                        "message": "绑定缺少 ME 指标，不能确认",
                    }
                )
            else:
                candidates_by_metric.setdefault(row.metric_resource_id, []).append(row)
                items.append({"binding_id": binding_id, "outcome": "confirmed"})

        confirmed_by_metric: dict[str, dict[int, KpiMeasurementBinding]] = {}
        candidate_metric_ids = list(candidates_by_metric)
        if candidate_metric_ids:
            existing_confirmed = (
                session.query(KpiMeasurementBinding)
                .filter(
                    KpiMeasurementBinding.metric_resource_id.in_(candidate_metric_ids),
                    KpiMeasurementBinding.status == "confirmed",
                )
                .all()
            )
            for row in existing_confirmed:
                confirmed_by_metric.setdefault(row.metric_resource_id, {})[row.measurement_unit_id] = row

        for item in items:
            if item["outcome"] != "confirmed":
                continue
            row = rows_by_id[item["binding_id"]]
            metric_id = row.metric_resource_id
            assert metric_id is not None
            selected_units = {candidate.measurement_unit_id for candidate in candidates_by_metric[metric_id]}
            existing_units = set(confirmed_by_metric.get(metric_id, {})) - {row.measurement_unit_id}
            if len(selected_units) > 1 or existing_units:
                item.update(
                    {
                        "outcome": "failed",
                        "error_code": "kpi_binding_conflict",
                        "message": "指标已绑定到其他测量单元",
                    }
                )
                continue
            row.status = "confirmed"
            row.updated_at = _utc_now()

        session.commit()
        for item in items:
            if item["outcome"] in {"confirmed", "already_confirmed"}:
                item["binding"] = _binding_dict(rows_by_id[item["binding_id"]])

    succeeded = sum(item["outcome"] in {"confirmed", "already_confirmed"} for item in items)
    result = {
        "total": len(items),
        "succeeded": succeeded,
        "failed": len(items) - succeeded,
        "items": items,
    }
    logger.info(
        "kpi_measurement_bindings_batch_confirmed",
        requested=len(binding_ids),
        unique=len(unique_ids),
        succeeded=result["succeeded"],
        failed=result["failed"],
    )
    return result


def _parse_number(value: str) -> tuple[bool, float | None]:
    if value is None or not str(value).strip():
        return False, None
    try:
        return True, float(value)
    except ValueError:
        return False, None


def _merge_observation(target: dict[str, Any], source: dict[str, Any]) -> None:
    """按行对象聚合多个周期文件的观测值。"""
    target["row_count"] += source["row_count"]
    target["valid_count"] += source["valid_count"]
    target["null_count"] += source["null_count"]
    target["parse_error_count"] += source["parse_error_count"]
    target["zero_count"] += source["zero_count"]
    if source["min_value"] is not None:
        target["min_value"] = (
            source["min_value"] if target["min_value"] is None else min(target["min_value"], source["min_value"])
        )
    if source["max_value"] is not None:
        target["max_value"] = (
            source["max_value"] if target["max_value"] is None else max(target["max_value"], source["max_value"])
        )
    target["sum_value"] += source["sum_value"]
    target["source_rows"].extend(source["source_rows"])


def _parse_measurement_time(value: str) -> datetime | None:
    """解析 CSV 中的测量时间；无法解析时返回 None。"""
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_period_minutes(value: str) -> int | None:
    """解析周期分钟数，用于避免混合不同粒度的时间序列。"""
    valid, number = _parse_number(value)
    if not valid or number is None or number <= 0:
        return None
    return int(number)


def _deduplicate_series(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一对象/周期/时间的重复值求均值，并保留来源证据。"""
    grouped: dict[tuple[str, int | None], dict[str, Any]] = {}
    for point in points:
        key = (point["time"], point["period_minutes"])
        target = grouped.setdefault(
            key,
            {
                "time": point["time"],
                "period_minutes": point["period_minutes"],
                "object_key": point["object_key"],
                "value": 0.0,
                "count": 0,
                "source_rows": [],
            },
        )
        target["value"] += point["value"]
        target["count"] += 1
        target["source_rows"].extend(point["source_rows"])
    result = []
    for item in grouped.values():
        result.append(
            {
                "time": item["time"],
                "period_minutes": item["period_minutes"],
                "object_key": item["object_key"],
                "value": round(item["value"] / item["count"], 6),
                "source_rows": item["source_rows"],
            }
        )
    return sorted(result, key=lambda item: (item["time"], item["period_minutes"] is None, item["period_minutes"] or 0))


KPI_TREND_SAMPLE_MAX_POINTS = 200


def _sample_trend_points(
    points: list[dict[str, Any]], limit: int = KPI_TREND_SAMPLE_MAX_POINTS
) -> list[dict[str, Any]]:
    """按等距采样保留趋势形态，避免每个指标保存全量明细。"""
    if len(points) <= limit:
        return points
    if limit < 2:
        return points[:limit]
    indexes = sorted({round(index * (len(points) - 1) / (limit - 1)) for index in range(limit)})
    return [points[index] for index in indexes]


def _classify_trend(points: list[dict[str, Any]], direction: str | None) -> dict[str, Any]:
    """按规则生成单对象、单周期的趋势标签和方向信号。"""
    if len(points) < 2:
        return {
            "label": "cannot_determine",
            "signal": "none",
            "reason": "insufficient_points",
            "points": points,
        }
    values = [point["value"] for point in points]
    if all(value == 0 for value in values):
        label = "all_zero"
    else:
        mean = sum(values) / len(values)
        tolerance = max(abs(mean) * 0.05, 1e-9)
        if max(values) - min(values) <= tolerance:
            label = "stable"
        else:
            previous = values[:-1]
            baseline = sum(previous) / len(previous)
            change = values[-1] - baseline
            change_tolerance = max(abs(baseline) * 0.3, 1e-9)
            if abs(change) > change_tolerance:
                label = "spike" if change > 0 else "plunge"
            elif all(values[i] <= values[i + 1] + tolerance for i in range(len(values) - 1)):
                label = "rising"
            elif all(values[i] >= values[i + 1] - tolerance for i in range(len(values) - 1)):
                label = "falling"
            else:
                lower = min(values)
                lower_index = values.index(lower)
                if 0 < lower_index < len(values) - 1 and values[-1] > values[lower_index] + tolerance:
                    label = "recovering"
                else:
                    label = "fluctuating"
    signal = "none"
    if direction == "higher_better":
        if label in {"falling", "plunge", "all_zero"}:
            signal = "worsened"
        elif label in {"rising", "spike"}:
            signal = "improved"
    elif direction == "lower_better":
        if label in {"rising", "spike"}:
            signal = "worsened"
        elif label in {"falling", "plunge"}:
            signal = "improved"
    return {"label": label, "signal": signal, "reason": None, "points": points}


def _business_status(
    value: float | None,
    direction: str | None,
    warning_threshold: float | None,
    critical_threshold: float | None,
) -> str:
    """按方向输出独立于可读性的业务状态；等于阈值视为触发。"""
    if value is None:
        return "not_judgeable"
    if not direction or direction == "neutral":
        return "not_applicable"
    if warning_threshold is None and critical_threshold is None:
        return "unconfigured"
    if direction == "higher_better":
        if critical_threshold is not None and value <= critical_threshold:
            return "fail"
        if warning_threshold is not None and value <= warning_threshold:
            return "warn"
        return "normal"
    if critical_threshold is not None and value >= critical_threshold:
        return "fail"
    if warning_threshold is not None and value >= warning_threshold:
        return "warn"
    return "normal"


def _metric_business_status(statuses: list[str]) -> str:
    """聚合同一指标多个行对象的业务状态，失败优先于预警。"""
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if statuses and all(status == "normal" for status in statuses):
        return "normal"
    if "not_applicable" in statuses:
        return "not_applicable"
    if "unconfigured" in statuses:
        return "unconfigured"
    return "not_judgeable"


def _unit_risk_summary(unit: dict[str, Any]) -> dict[str, Any]:
    """汇总测量单元健康分与诊断数量，健康分只用于排序定位。"""
    score = 100
    business_fail = 0
    business_warn = 0
    data_error = 0
    trend_worsened = 0
    unconfigured = 0
    for metric in unit.get("metrics", []):
        status = metric.get("business_status")
        if status == "fail":
            business_fail += 1
            score -= 25
        elif status == "warn":
            business_warn += 1
            score -= 12
        elif metric.get("read_status") in {"missing", "parse_error"}:
            data_error += 1
            score -= 10
        elif status == "unconfigured":
            unconfigured += 1
        if metric.get("trend_signal") == "worsened":
            trend_worsened += 1
            score -= 5
    health_score = max(0, min(100, score))
    return {
        "health_score": health_score,
        "business_fail_count": business_fail,
        "business_warn_count": business_warn,
        "data_error_count": data_error,
        "trend_worsened_count": trend_worsened,
        "unconfigured_count": unconfigured,
    }


RISK_COUNT_KEYS = (
    "business_fail_count",
    "business_warn_count",
    "data_error_count",
    "trend_worsened_count",
    "unconfigured_count",
)


def _kpi_overview(units: list[dict[str, Any]]) -> dict[str, Any]:
    """生成任务级 KPI 总览，所有数量都能下钻到对应单元和指标。"""
    status_counts = {"pass": 0, "warn": 0, "fail": 0, "error": 0, "skip": 0}
    summary = {
        "unit_count": len(units),
        "status_counts": status_counts,
        "health_score": 100,
        "business_fail_count": 0,
        "business_warn_count": 0,
        "data_error_count": 0,
        "trend_worsened_count": 0,
        "unconfigured_count": 0,
        "metric_count": 0,
    }
    scores: list[int] = []
    for unit in units:
        status_counts[unit.get("status", "skip")] = status_counts.get(unit.get("status", "skip"), 0) + 1
        risk = unit.get("risk_summary", _unit_risk_summary(unit))
        unit["risk_summary"] = risk
        scores.append(risk["health_score"])
        for key in RISK_COUNT_KEYS:
            summary[key] += risk[key]
        summary["metric_count"] += len(unit.get("metrics", []))
    summary["health_score"] = min(scores) if scores else 100
    return summary


def inspect_measurement_files(task_id: str, files: Iterable[tuple[str, Path]]) -> dict[str, Any]:
    """执行测量单元可读性巡检并返回通用结构。"""
    init_db()
    # 绑定发现复用文件归属结果，并保留自动注册、冲突、重复列和解析失败诊断。
    discovered = discover_measurement_bindings(task_id, files)
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    history_records: list[dict[str, Any]] = []
    for file_result in discovered["files"]:
        if file_result["status"] == "matched":
            matched.append(file_result)
        elif file_result.get("reason") == "period_not_preferred":
            skipped.append(file_result)
        else:
            unmatched.append(file_result)

    unit_results: dict[str, dict[str, Any]] = {}
    with session_factory() as session:
        bindings = session.query(KpiMeasurementBinding).filter_by(status="confirmed", enabled=True).all()
        by_unit: dict[str, list[KpiMeasurementBinding]] = {}
        for binding in bindings:
            by_unit.setdefault(binding.measurement_unit_id, []).append(binding)
        derived_metric_ids = (
            session.query(KpiMeasurementDerived.metric_resource_id)
            .filter(
                KpiMeasurementDerived.measurement_unit_id.in_(list(by_unit)),
                KpiMeasurementDerived.enabled.is_(True),
            )
            .all()
        )
        resource_names = _resource_name_map(
            session,
            [binding.metric_resource_id for binding in bindings]
            + list(by_unit)
            + [row[0] for row in derived_metric_ids],
        )
        # 发现阶段失败也要传导到所属单元；后续同单元正常文件不覆盖 error。
        for file_result in discovered["files"]:
            unit_id = file_result.get("measurement_unit_id")
            if file_result.get("status") != "parse_error" or not unit_id or unit_id in unit_results:
                continue
            unit = session.get(KpiMeasurementResource, unit_id)
            if unit is None:
                continue
            if file_result.get("reason") == "header_not_found":
                parse_reason = "表头未找到"
            elif file_result.get("reason") == "csv_read_error":
                parse_reason = f"CSV 读取失败: {file_result.get('detail', '')}"
            else:
                parse_reason = "任务文件解析失败"
            unit_results[unit_id] = {
                "measurement_unit_id": unit_id,
                "name_zh": unit.name_zh,
                "name_en": unit.name_en,
                "status": "error",
                "reason": parse_reason,
                "file_count": 1,
                "object_count": 0,
                "metric_coverage": "0/0",
                "metrics": [],
                "metric_results": {},
                "object_results": {},
                "objects": {},
                "source_files": [file_result["source_file"]],
            }
        metric_resource_rows = (
            session.query(KpiMeasurementResource)
            .filter(
                KpiMeasurementResource.resource_id.in_(
                    [binding.metric_resource_id for binding in bindings if binding.metric_resource_id],
                ),
                KpiMeasurementResource.kind == "me",
            )
            .all()
        )
        metric_resources = {row.resource_id: row for row in metric_resource_rows}
        for file_result in matched:
            unit_id = file_result["measurement_unit_id"]
            unit = session.get(KpiMeasurementResource, unit_id)
            if unit is None:
                file_result["status"] = "unmatched"
                unmatched.append(file_result)
                continue
            result = unit_results.setdefault(
                unit_id,
                {
                    "measurement_unit_id": unit_id,
                    "name_zh": unit.name_zh,
                    "name_en": unit.name_en,
                    "status": "pass",
                    "reason": None,
                    "file_count": 0,
                    "object_count": 0,
                    "metric_coverage": "0/0",
                    "metrics": [],
                    "metric_results": {},
                    "object_results": {},
                    "objects": {},
                    "source_files": [],
                },
            )
            if not by_unit.get(unit_id):
                result["status"] = "skip"
                result["reason"] = "未配置已确认指标绑定"
                continue
            result["file_count"] += 1
            result["source_files"].append(file_result["source_file"])
            try:
                rows = _read_csv_rows(Path(file_result["source_path"]))
            except (OSError, UnicodeError, csv.Error) as exc:
                result["status"] = "error"
                result["reason"] = f"CSV 读取失败: {exc}"
                continue
            header = _find_header(rows)
            if header is None:
                file_result["status"] = "parse_error"
                file_result["reason"] = "header_not_found"
                result["status"] = "error"
                result["reason"] = "表头未找到"
                continue
            header_index, header_row = header
            start_index = header_row.index("测量开始时间")
            column_index = {name: index for index, name in enumerate(header_row)}
            confirmed_bindings = by_unit[unit_id]
            for binding in confirmed_bindings:
                series_points: list[dict[str, Any]] = []
                # CSV 中实际存在的列才参与巡检；历史确认但本次未导出的列直接忽略。
                if binding.raw_source_name not in column_index:
                    continue
                observations: dict[str, dict[str, Any]] = {}
                for line_number, data_row in enumerate(rows[header_index + 1 :], start=header_index + 2):
                    if not data_row or all(not cell.strip() for cell in data_row):
                        continue
                    object_key = data_row[0].strip() if start_index > 0 and data_row else "__all__"
                    observation = observations.setdefault(
                        object_key,
                        {
                            "object_key": object_key,
                            "row_count": 0,
                            "valid_count": 0,
                            "null_count": 0,
                            "parse_error_count": 0,
                            "zero_count": 0,
                            "min_value": None,
                            "max_value": None,
                            "sum_value": 0.0,
                            "source_rows": [],
                        },
                    )
                    observation["row_count"] += 1
                    value_index = column_index[binding.raw_source_name]
                    # 兼容真实包中表头列数和部分数据行列数不一致的情况；缺列按解析异常统计。
                    raw_value = data_row[value_index] if len(data_row) > value_index else ""
                    valid, number = _parse_number(raw_value)
                    if not valid and number is None:
                        if raw_value.strip():
                            observation["parse_error_count"] += 1
                        else:
                            observation["null_count"] += 1
                        observation["source_rows"].append(
                            {"source_file": file_result["source_file"], "line_number": line_number, "value": raw_value}
                        )
                        continue
                    assert number is not None
                    observation["valid_count"] += 1
                    observation["zero_count"] += int(number == 0)
                    observation["min_value"] = (
                        number if observation["min_value"] is None else min(observation["min_value"], number)
                    )
                    observation["max_value"] = (
                        number if observation["max_value"] is None else max(observation["max_value"], number)
                    )
                    observation["sum_value"] += number
                    measured_at = _parse_measurement_time(data_row[start_index])
                    period_minutes = _parse_period_minutes(
                        data_row[column_index["周期(分钟)"]] if "周期(分钟)" in column_index else ""
                    )
                    if measured_at is not None:
                        series_points.append(
                            {
                                "object_key": object_key,
                                "time": measured_at.isoformat(),
                                "period_minutes": period_minutes,
                                "value": number,
                                "source_rows": [
                                    {
                                        "source_file": file_result["source_file"],
                                        "line_number": line_number,
                                        "value": raw_value,
                                    }
                                ],
                            }
                        )
                        history_records.append(
                            {
                                "task_id": task_id,
                                "measurement_unit_id": unit_id,
                                "metric_resource_id": binding.metric_resource_id,
                                "object_key": object_key,
                                "period_minutes": period_minutes,
                                "measured_at": measured_at.isoformat(),
                                "value": number,
                                "source_file": file_result["source_file"],
                                "line_number": line_number,
                            }
                        )
                metric_key = (binding.metric_resource_id, binding.raw_source_name)
                metric_result = result["metric_results"].get(metric_key)
                if metric_result is None:
                    result["metric_results"][metric_key] = {
                        "metric_resource_id": binding.metric_resource_id,
                        "metric_resource_name_zh": resource_names.get(binding.metric_resource_id or ""),
                        "raw_source_name": binding.raw_source_name,
                        "base_source_name": binding.base_source_name,
                        "display_unit": binding.display_unit,
                        "observations": observations,
                        "time_series": series_points,
                        "source_files": [file_result["source_file"]],
                    }
                else:
                    for object_key, observation in observations.items():
                        if object_key in metric_result["observations"]:
                            _merge_observation(metric_result["observations"][object_key], observation)
                        else:
                            metric_result["observations"][object_key] = observation
                    metric_result.setdefault("time_series", []).extend(series_points)
                    metric_result["source_files"].append(file_result["source_file"])
                for object_key, observation in observations.items():
                    if object_key in result["object_results"]:
                        _merge_observation(result["object_results"][object_key], observation)
                    else:
                        result["object_results"][object_key] = {
                            **observation,
                            "source_rows": list(observation["source_rows"]),
                        }
        for result in unit_results.values():
            finalized_metrics: list[dict[str, Any]] = []
            for metric_result in result["metric_results"].values():
                observations = list(metric_result["observations"].values())
                for observation in observations:
                    observation["read_status"] = (
                        "parse_error"
                        if observation["parse_error_count"]
                        else "null"
                        if observation["null_count"]
                        else "ok"
                    )
                    observation["value_pattern"] = (
                        "all_zero"
                        if observation["valid_count"] and observation["zero_count"] == observation["valid_count"]
                        else "unknown"
                        if not observation["valid_count"]
                        else "normal"
                    )
                    observation["avg_value"] = (
                        observation["sum_value"] / observation["valid_count"] if observation["valid_count"] else None
                    )
                    observation.pop("sum_value", None)
                resource = metric_resources.get(metric_result["metric_resource_id"])
                direction = getattr(resource, "direction", None)
                warning_threshold = getattr(resource, "warning_threshold", None)
                critical_threshold = getattr(resource, "critical_threshold", None)
                for observation in observations:
                    observation["business_status"] = _business_status(
                        observation.get("avg_value"), direction, warning_threshold, critical_threshold
                    )
                business_status = _metric_business_status([item["business_status"] for item in observations])

                trend_groups: dict[tuple[str, int | None], list[dict[str, Any]]] = {}
                for point in metric_result.get("time_series", []):
                    trend_groups.setdefault((point["object_key"], point["period_minutes"]), []).append(point)
                trends = [
                    _classify_trend(_deduplicate_series(points), direction)
                    for _, points in sorted(
                        trend_groups.items(),
                        key=lambda item: (item[0][0], item[0][1] is None, item[0][1] or 0),
                    )
                ]
                for trend in trends:
                    points = trend.get("points", [])
                    first_point = points[0] if points else {}
                    trend["object_key"] = first_point.get("object_key")
                    trend["period_minutes"] = first_point.get("period_minutes")
                for trend in trends:
                    trend["point_count"] = len(trend.get("points", []))
                primary_trend = max(trends, key=lambda item: item["point_count"]) if trends else None
                primary_points = (
                    _sample_trend_points(primary_trend.pop("points", [])) if primary_trend is not None else []
                )
                for trend in trends:
                    trend.pop("points", None)
                finalized_metrics.append(
                    {
                        "metric_resource_id": metric_result["metric_resource_id"],
                        "metric_resource_name_zh": metric_result.get("metric_resource_name_zh"),
                        "raw_source_name": metric_result["raw_source_name"],
                        "base_source_name": metric_result["base_source_name"],
                        "display_unit": metric_result["display_unit"],
                        "read_status": (
                            "parse_error" if any(item["read_status"] != "ok" for item in observations) else "ok"
                        ),
                        "business_status": business_status,
                        "direction": direction or "neutral",
                        "importance": getattr(resource, "importance", None) or "normal",
                        "metric_group": getattr(resource, "metric_group", None) or "未分组",
                        "warning_threshold": warning_threshold,
                        "critical_threshold": critical_threshold,
                        "value_pattern": (
                            "unknown"
                            if not observations
                            else "all_zero"
                            if all(item["value_pattern"] == "all_zero" for item in observations)
                            else "normal"
                        ),
                        "trend_label": primary_trend["label"] if primary_trend else "cannot_determine",
                        "trend_signal": primary_trend["signal"] if primary_trend else "none",
                        "trend_reason": primary_trend["reason"] if primary_trend else "no_time_series",
                        "trend_points": primary_points,
                        "trends": trends,
                        "observations": observations,
                        "source_files": metric_result["source_files"],
                        "errors": metric_result.get("errors"),
                    }
                )
            if any(metric["read_status"] != "ok" for metric in finalized_metrics):
                result["status"] = "fail"
                result["reason"] = "指标存在缺失、空值或解析错误"
            result["metrics"] = finalized_metrics
            result["risk_summary"] = _unit_risk_summary(result)
            if result["status"] != "error" and result["risk_summary"]["business_fail_count"]:
                result["status"] = "fail"
                result["reason"] = "指标存在业务阈值失败"
            elif result["status"] == "pass" and result["risk_summary"]["business_warn_count"]:
                result["status"] = "warn"
                result["reason"] = "指标存在业务阈值预警"
            result["objects"] = {}
            for object_key, observation in result["object_results"].items():
                observation["read_status"] = (
                    "parse_error" if observation["parse_error_count"] else "null" if observation["null_count"] else "ok"
                )
                observation["value_pattern"] = (
                    "all_zero"
                    if observation["valid_count"] and observation["zero_count"] == observation["valid_count"]
                    else "unknown"
                    if not observation["valid_count"]
                    else "normal"
                )
                observation["avg_value"] = (
                    observation["sum_value"] / observation["valid_count"] if observation["valid_count"] else None
                )
                observation.pop("sum_value", None)
                result["objects"][object_key] = observation
            result["object_count"] = len(result["objects"])
            result["metric_coverage"] = (
                f"{sum(1 for metric in finalized_metrics if metric['read_status'] == 'ok')}/{len(finalized_metrics)}"
            )
            derived_rows = (
                session.query(KpiMeasurementDerived).filter_by(measurement_unit_id=unit_id, enabled=True).all()
            )
            result["derived_metrics"] = []
            for derived in derived_rows:
                dependencies = {
                    derived.numerator_metric_id: None,
                    derived.denominator_metric_id: None,
                }
                for metric_result in result["metrics"]:
                    if metric_result["metric_resource_id"] in dependencies and "observations" in metric_result:
                        dependencies[metric_result["metric_resource_id"]] = {
                            item["object_key"]: item for item in metric_result["observations"]
                        }
                if any(value is None for value in dependencies.values()):
                    result["derived_metrics"].append(
                        {
                            "metric_resource_id": derived.metric_resource_id,
                            "metric_resource_name_zh": resource_names.get(derived.metric_resource_id),
                            "template": derived.template,
                            "status": "fail",
                            "message": "依赖指标缺失",
                            "observations": [],
                        }
                    )
                    result["status"] = "fail"
                    result["reason"] = "派生指标依赖缺失"
                    continue
                numerator_map = dependencies[derived.numerator_metric_id]
                denominator_map = dependencies[derived.denominator_metric_id]
                observations = []
                derived_failed = False
                for object_key in sorted(set(numerator_map) | set(denominator_map)):
                    numerator = numerator_map.get(object_key)
                    denominator = denominator_map.get(object_key)
                    if numerator is None or denominator is None:
                        observations.append(
                            {"object_key": object_key, "status": "fail", "message": "依赖指标缺失", "value": None}
                        )
                        derived_failed = True
                        continue
                    numerator_value = numerator.get("avg_value")
                    denominator_value = denominator.get("avg_value")
                    if denominator_value == 0:
                        observations.append(
                            {"object_key": object_key, "status": "pass", "message": "疑似业务未触发", "value": None}
                        )
                        continue
                    if numerator_value is None or denominator_value is None:
                        observations.append(
                            {"object_key": object_key, "status": "fail", "message": "依赖指标不可读", "value": None}
                        )
                        derived_failed = True
                        continue
                    value = round(numerator_value / denominator_value * 100, 2)
                    if derived.template == "reverse_success_rate":
                        value = round(100 - value, 2)
                    observations.append(
                        {
                            "object_key": object_key,
                            "status": "pass",
                            "message": None,
                            "value": value,
                        }
                    )
                if derived_failed:
                    result["status"] = "fail"
                    result["reason"] = "派生指标依赖缺失或不可读"
                result["derived_metrics"].append(
                    {
                        "metric_resource_id": derived.metric_resource_id,
                        "metric_resource_name_zh": resource_names.get(derived.metric_resource_id),
                        "template": derived.template,
                        "status": "fail" if derived_failed else "pass",
                        "message": "依赖指标缺失或不可读" if derived_failed else None,
                        "observations": observations,
                    }
                )
            if result["status"] == "pass":
                result["reason"] = None
            result.pop("metric_results", None)
            result.pop("object_results", None)
    # KPI 结果组织完成后立即生成任务私有历史索引；失败不影响规则结果由调用方统一处理。
    write_history_index(task_id, history_records)
    final_units = list(unit_results.values())
    kpi_overview = _kpi_overview(final_units)
    kpi_overview["auto_registered_count"] = sum(
        len(item.get("auto_registered_metrics", [])) for item in discovered["files"]
    )
    kpi_overview["conflict_count"] = sum(len(item.get("conflict_metrics", [])) for item in discovered["files"])
    kpi_overview["unmatched_file_count"] = len(unmatched)
    kpi_overview["skipped_file_count"] = len(skipped)
    return {
        "task_id": task_id,
        "kpi_overview": kpi_overview,
        "measurement_units": final_units,
        "files": discovered["files"],
        "unmatched_files": unmatched,
        "skipped_files": skipped,
    }


def create_measurement_derived(
    measurement_unit_id: str,
    metric_resource_id: str,
    numerator_metric_id: str,
    denominator_metric_id: str,
    template: Literal["success_rate", "reverse_success_rate"] = "success_rate",
) -> dict[str, Any]:
    """创建正向或反向成功率派生指标定义。"""
    init_db()
    with session_factory() as session:
        unit = session.get(KpiMeasurementResource, measurement_unit_id)
        if unit is None or unit.kind != "mu":
            raise KpiMeasurementError("kpi_measurement_unit_not_found", f"测量单元不存在: {measurement_unit_id}", 404)
        resource_ids = {metric_resource_id, numerator_metric_id, denominator_metric_id}
        resources = (
            session.query(KpiMeasurementResource).filter(KpiMeasurementResource.resource_id.in_(resource_ids)).all()
        )
        if len(resources) != len(resource_ids) or any(row.kind != "me" for row in resources):
            raise KpiMeasurementError("kpi_metric_not_found", "派生指标依赖的资源指标不存在", 404)
        for dependency_id in (numerator_metric_id, denominator_metric_id):
            binding = (
                session.query(KpiMeasurementBinding)
                .filter_by(
                    metric_resource_id=dependency_id,
                    measurement_unit_id=measurement_unit_id,
                    status="confirmed",
                    enabled=True,
                )
                .first()
            )
            if binding is None:
                raise KpiMeasurementError("kpi_binding_not_confirmed", f"依赖指标未确认绑定: {dependency_id}", 409)
        existing = (
            session.query(KpiMeasurementDerived)
            .filter_by(measurement_unit_id=measurement_unit_id, metric_resource_id=metric_resource_id)
            .first()
        )
        if existing:
            existing.numerator_metric_id = numerator_metric_id
            existing.denominator_metric_id = denominator_metric_id
            existing.enabled = True
            existing.updated_at = _utc_now()
            row = existing
        else:
            row = KpiMeasurementDerived(
                measurement_unit_id=measurement_unit_id,
                metric_resource_id=metric_resource_id,
                numerator_metric_id=numerator_metric_id,
                denominator_metric_id=denominator_metric_id,
                template=template,
                enabled=True,
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
            session.add(row)
        session.flush()
        derived = {
            "id": row.id,
            "measurement_unit_id": row.measurement_unit_id,
            "metric_resource_id": row.metric_resource_id,
            "numerator_metric_id": row.numerator_metric_id,
            "denominator_metric_id": row.denominator_metric_id,
            "template": row.template,
            "enabled": row.enabled,
        }
        session.commit()
        return derived
