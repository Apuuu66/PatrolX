"""基于测量单元的 KPI 资源目录与任务文件归属服务。"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import exists, or_

from app.core.encoding import decode_text_with_fallback, read_text_with_fallback
from app.core.logging import get_logger
from app.models.db import (
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    init_db,
    session_factory,
)


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
    """按同类资源中文名合并资源目录；资源 ID 仅作存储主键，不删除 CSV 外资源。"""
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
    # 兼容现场导出的表头前后空格；必须同步修正 DictReader 的实际取值键。
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
                # 同一个资源 ID 被不同中文名复用时，不覆盖已有资源；
                # 为后续行生成稳定的新 ID，重复导入仍能合并到同一条资源。
                resource_id = conflict_resource_id(resource_id, name_zh)
                existing_by_id = resources_by_id.get(resource_id)
                if existing_by_id is None:
                    existing_by_id = session.get(KpiMeasurementResource, resource_id)

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
                changed = existing_by_name.name_en != name_en
                existing_by_name.name_en = name_en
                if kind == "mu":
                    existing_by_name.filename_fragment = filename_fragment(name_en)
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

            row_resource = KpiMeasurementResource(
                resource_id=resource_id,
                kind=kind,
                name_zh=name_zh,
                name_en=name_en,
                filename_fragment=filename_fragment(name_en) if kind == "mu" else None,
                enabled=True,
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
                        "source_file": str(path),
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
                "source_file": str(path),
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


def discover_measurement_bindings(task_id: str, files: Iterable[tuple[str, Path]]) -> dict[str, Any]:
    """扫描任务 CSV 表头，发现指标候选绑定。"""
    init_db()
    matched_files = match_measurement_files(files)
    with session_factory() as session:
        for file_result in matched_files["files"]:
            if file_result["status"] != "matched":
                continue
            path = Path(file_result["source_file"])
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
            unknown: list[str] = []
            for raw_name in metric_columns:
                base_name, display_unit = _split_source_name(raw_name)
                metric = (
                    session.query(KpiMeasurementResource)
                    .filter(
                        KpiMeasurementResource.kind == "me",
                        or_(KpiMeasurementResource.name_zh == base_name, KpiMeasurementResource.name_en == base_name),
                    )
                    .first()
                )
                metric_id = metric.resource_id if metric else None
                if metric_id is None:
                    unknown.append(raw_name)
                existing = (
                    session.query(KpiMeasurementBinding)
                    .filter(
                        KpiMeasurementBinding.measurement_unit_id == file_result["measurement_unit_id"],
                        KpiMeasurementBinding.raw_source_name == raw_name,
                    )
                    .one_or_none()
                )
                if existing:
                    candidates.append(_binding_dict(existing))
                    continue
                conflict = (
                    metric_id is not None
                    and session.query(KpiMeasurementBinding)
                    .filter(
                        KpiMeasurementBinding.metric_resource_id == metric_id,
                        KpiMeasurementBinding.measurement_unit_id != file_result["measurement_unit_id"],
                        KpiMeasurementBinding.status != "ignored",
                    )
                    .first()
                    is not None
                )
                row = KpiMeasurementBinding(
                    metric_resource_id=metric_id,
                    measurement_unit_id=file_result["measurement_unit_id"],
                    raw_source_name=raw_name,
                    base_source_name=base_name,
                    display_unit=display_unit,
                    status="conflict" if conflict else "candidate",
                    enabled=True,
                    task_id=task_id,
                    source_file=file_result["source_file"],
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
                session.add(row)
                session.flush()
                candidates.append(_binding_dict(row))
            file_result["binding_candidates"] = len(candidates)
            file_result["unknown_columns"] = unknown
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
) -> dict[str, Any]:
    """编辑人工注册 ME 指标；资源 ID 与绑定来源不可修改。"""
    if name_zh is None and name_en is None and enabled is None:
        raise KpiMeasurementError("kpi_metric_no_fields", "至少提供一个可编辑字段", 400)
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
        if not is_manual_metric_id(row.resource_id):
            raise KpiMeasurementError("kpi_metric_not_manual", "仅人工注册指标支持编辑", 409)
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
        rows = query.order_by(KpiMeasurementResource.resource_id.asc()).all()
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


def inspect_measurement_files(task_id: str, files: Iterable[tuple[str, Path]]) -> dict[str, Any]:
    """执行测量单元可读性巡检并返回通用结构。"""
    init_db()
    # 巡检前先做一次绑定发现，保证新任务表头能进入候选确认流程。
    # 发现返回值会把解析失败文件降级，巡检需要重新按 matched 文件汇总错误。
    discover_measurement_bindings(task_id, files)
    discovered = match_measurement_files(files)
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for file_result in discovered["files"]:
        if file_result["status"] == "matched":
            matched.append(file_result)
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
                rows = _read_csv_rows(Path(file_result["source_file"]))
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
                if binding.raw_source_name not in column_index:
                    metric_key = (binding.metric_resource_id, binding.raw_source_name)
                    metric_result = result["metric_results"].get(metric_key)
                    if metric_result is None:
                        result["metric_results"][metric_key] = {
                            "metric_resource_id": binding.metric_resource_id,
                            "metric_resource_name_zh": resource_names.get(binding.metric_resource_id or ""),
                            "raw_source_name": binding.raw_source_name,
                            "base_source_name": binding.base_source_name,
                            "display_unit": binding.display_unit,
                            "observations": {},
                            "source_files": [file_result["source_file"]],
                            "errors": [{"reason": "column_missing"}],
                        }
                    else:
                        metric_result.setdefault("errors", []).append({"reason": "column_missing"})
                        metric_result["source_files"].append(file_result["source_file"])
                    result["status"] = "fail"
                    result["reason"] = "已确认指标列缺失"
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
                    raw_value = data_row[column_index[binding.raw_source_name]]
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
                        "source_files": [file_result["source_file"]],
                    }
                else:
                    for object_key, observation in observations.items():
                        if object_key in metric_result["observations"]:
                            _merge_observation(metric_result["observations"][object_key], observation)
                        else:
                            metric_result["observations"][object_key] = observation
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
                finalized_metrics.append(
                    {
                        "metric_resource_id": metric_result["metric_resource_id"],
                        "metric_resource_name_zh": metric_result.get("metric_resource_name_zh"),
                        "raw_source_name": metric_result["raw_source_name"],
                        "base_source_name": metric_result["base_source_name"],
                        "display_unit": metric_result["display_unit"],
                        "read_status": (
                            "missing"
                            if any(error.get("reason") == "column_missing" for error in metric_result.get("errors", []))
                            else "parse_error"
                            if any(item["read_status"] != "ok" for item in observations)
                            else "ok"
                        ),
                        "value_pattern": (
                            "unknown"
                            if not observations
                            else "all_zero"
                            if all(item["value_pattern"] == "all_zero" for item in observations)
                            else "normal"
                        ),
                        "observations": observations,
                        "source_files": metric_result["source_files"],
                        "errors": metric_result.get("errors"),
                    }
                )
            if any(metric["read_status"] != "ok" for metric in finalized_metrics):
                result["status"] = "fail"
                result["reason"] = "指标存在缺失、空值或解析错误"
            result["metrics"] = finalized_metrics
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
    return {
        "task_id": task_id,
        "measurement_units": list(unit_results.values()),
        "files": discovered["files"],
        "unmatched_files": unmatched,
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
