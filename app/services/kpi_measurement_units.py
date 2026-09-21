"""基于测量单元的 KPI 资源目录与任务文件归属服务。"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_

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


_RESOURCE_PREFIXES = {"MU__": "mu", "ME_": "me", "UNIT_": "unit"}


def resource_kind(resource_id: str) -> str | None:
    """根据资源 ID 前缀识别资源类型。"""
    for prefix, kind in _RESOURCE_PREFIXES.items():
        if resource_id.startswith(prefix):
            return kind
    return None


def filename_fragment(name_en: str) -> str:
    """测量单元英文名转大小写敏感文件名片段。"""
    return "_".join(name_en.strip().split())


def _utc_now() -> datetime:
    return datetime.now(UTC)


def import_resource_csv(text_or_file: io.StringIO | str | Path) -> dict[str, Any]:
    """按资源 ID upsert 资源目录；不删除 CSV 中缺失的资源。"""
    init_db()
    if isinstance(text_or_file, io.StringIO):
        raw = text_or_file.getvalue()
    else:
        raw = Path(text_or_file).read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        raise KpiMeasurementError("kpi_resource_csv_invalid", "资源目录缺少表头", 400)
    required = {"资源id", "中文描述", "英文描述"}
    if not required.issubset({name.strip() for name in reader.fieldnames}):
        raise KpiMeasurementError("kpi_resource_csv_invalid", "资源目录表头必须是资源id/中文描述/英文描述", 400)

    added = {"mu": 0, "me": 0, "unit": 0}
    updated = {"mu": 0, "me": 0, "unit": 0}
    errors: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    with session_factory() as session:
        for line_number, row in enumerate(reader, start=2):
            resource_id = str(row.get("资源id") or "").strip()
            name_zh = str(row.get("中文描述") or "").strip()
            name_en = str(row.get("英文描述") or "").strip()
            kind = resource_kind(resource_id)
            if not kind or not name_zh or not name_en:
                errors.append(
                    {
                        "resource_id": resource_id or None,
                        "line_number": line_number,
                        "reason": "invalid_resource" if kind else "unknown_resource_prefix",
                    }
                )
                continue
            existing = session.get(KpiMeasurementResource, resource_id)
            if existing:
                changed = existing.name_zh != name_zh or existing.name_en != name_en
                existing.name_zh = name_zh
                existing.name_en = name_en
                if kind == "mu":
                    existing.filename_fragment = filename_fragment(name_en)
                existing.updated_at = _utc_now()
                if changed:
                    updated[kind] += 1
                else:
                    skipped.append({"resource_id": resource_id, "reason": "unchanged"})
            else:
                session.add(
                    KpiMeasurementResource(
                        resource_id=resource_id,
                        kind=kind,
                        name_zh=name_zh,
                        name_en=name_en,
                        filename_fragment=filename_fragment(name_en) if kind == "mu" else None,
                        enabled=True,
                        created_at=_utc_now(),
                        updated_at=_utc_now(),
                    )
                )
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
                rows = list(csv.reader(path.open("r", encoding="utf-8-sig", newline="")))
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


def _binding_dict(row: KpiMeasurementBinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "metric_resource_id": row.metric_resource_id,
        "measurement_unit_id": row.measurement_unit_id,
        "raw_source_name": row.raw_source_name,
        "base_source_name": row.base_source_name,
        "display_unit": row.display_unit,
        "status": row.status,
        "enabled": row.enabled,
        "task_id": row.task_id,
        "source_file": row.source_file,
    }


def list_measurement_bindings(
    measurement_unit_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """列出指标绑定候选。"""
    init_db()
    with session_factory() as session:
        query = session.query(KpiMeasurementBinding)
        if measurement_unit_id:
            query = query.filter(KpiMeasurementBinding.measurement_unit_id == measurement_unit_id)
        if status:
            query = query.filter(KpiMeasurementBinding.status == status)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    KpiMeasurementBinding.raw_source_name.like(like),
                    KpiMeasurementBinding.base_source_name.like(like),
                )
            )
        rows = query.order_by(KpiMeasurementBinding.id.desc()).all()
        return {"total": len(rows), "items": [_binding_dict(row) for row in rows]}


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
                rows = list(csv.reader(Path(file_result["source_file"]).open("r", encoding="utf-8-sig", newline="")))
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
                    observations.append(
                        {
                            "object_key": object_key,
                            "status": "pass",
                            "message": None,
                            "value": round(numerator_value / denominator_value * 100, 2),
                        }
                    )
                if derived_failed:
                    result["status"] = "fail"
                    result["reason"] = "派生指标依赖缺失或不可读"
                result["derived_metrics"].append(
                    {
                        "metric_resource_id": derived.metric_resource_id,
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
) -> dict[str, Any]:
    """创建成功率派生指标定义。"""
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
                template="success_rate",
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
