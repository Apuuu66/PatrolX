"""解析 ``LST ME.txt`` 并生成任务级台账证据。

该解析器不是巡检规则；只作为全量任务完成后的台账归档服务。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from unicodedata import normalize

from app.core.encoding import decode_text_with_fallback
from app.models.schemas import PackageKind

PARSER_ID = "site_device_lst_me"
PARSER_VERSION = "4"
SCHEMA_VERSION = 3
SOURCE_PATTERN = re.compile(r"^config/(?:.*/)?LST ME\.txt$", re.IGNORECASE)
HEADER_TIME_PATTERN = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s*$")
BEIJING_TZ = timezone(timedelta(hours=8))
TIME_FUTURE_TOLERANCE = timedelta(minutes=5)
TIME_SOURCE_LST_ME = "lst_me"
TIME_SOURCE_TASK = "task"
REASON_HEADER_TIME_MISSING = "header_time_missing"
REASON_HEADER_TIME_INVALID = "header_time_invalid"
REASON_TIME_IN_FUTURE = "time_in_future"
REASON_BY_STATUS = {
    "missing": REASON_HEADER_TIME_MISSING,
    "invalid": REASON_HEADER_TIME_INVALID,
    "time_in_future": REASON_TIME_IN_FUTURE,
}
EMPTY_EXECUTION_TIME: dict[str, Any] = {"status": "missing", "source": TIME_SOURCE_TASK, "per_file": []}
DEVICE_ALIASES = {"ne name", "me name", "网元名称", "设备名称"}
NETWORK_ELEMENT_TYPE_ALIASES = {"me type", "ne type", "网元类型"}
VERSION_ALIASES = {"software version", "sw version", "软件版本"}


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    """返回 UTC ISO-8601 字符串。"""
    return (value or utc_now()).isoformat()


def normalize_device_name(value: str) -> str:
    """按契约规范化设备名和网元类型：NFC、去首尾空白、合并空白。"""
    return re.sub(r"\s+", " ", normalize("NFC", value)).strip()


def device_identity(province: str, normalized_name: str) -> tuple[str, str]:
    """返回确定性 ``device_key`` 和 ``device_id``。"""
    device_key = sha256(normalized_name.encode("utf-8")).hexdigest()
    device_id = sha256(f"{province}\n{device_key}".encode()).hexdigest()
    return device_key, device_id


def observation_id(task_id: str, device_id: str) -> str:
    """返回任务内唯一观测 ID。"""
    return sha256(f"{task_id}\n{device_id}".encode()).hexdigest()


def _archive(
    status: str = "not_applicable",
    reason: str | None = None,
    *,
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "archived": status == "archived",
        "device_id": None,
        "observation_id": None,
        "reason": reason,
    }
    if devices is not None:
        result["devices"] = devices
    return result


def _empty_evidence(task_id: str, package_kind: PackageKind, *, now: datetime) -> dict[str, Any]:
    timestamp = iso_utc(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "package_kind": package_kind.value,
        "status": "not_applicable",
        "parser_id": PARSER_ID,
        "parser_version": PARSER_VERSION,
        "not_applicable_reason": None,
        "not_archived_reason": None,
        "network_element_type_filter": None,
        "site": None,
        "device": None,
        "version": None,
        "records": [],
        "devices": [],
        "source_files": [],
        "execution_time": {"status": "missing", "source": TIME_SOURCE_TASK, "per_file": []},
        "conflicts": [],
        "errors": [],
        "archived": _archive(),
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _as_utc(value: datetime) -> datetime:
    """把可能为 naive 的时间按 UTC 归一，便于比较。"""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_header_time(raw_line: str) -> dict[str, Any] | None:
    """解析头部行尾的 ``YYYY-MM-DD  HH:MM:SS``；未命中返回 None。"""
    match = HEADER_TIME_PATTERN.search(raw_line)
    if match is None:
        return None
    raw_text = raw_line.strip()
    try:
        parsed = datetime.strptime(f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return {
            "raw_text": raw_text,
            "parsed_at": None,
            "status": "invalid",
            "reason": REASON_HEADER_TIME_INVALID,
        }
    return {
        "raw_text": raw_text,
        "parsed_at": parsed.replace(tzinfo=BEIJING_TZ).astimezone(UTC).replace(microsecond=0),
        "status": "ok",
        "reason": None,
    }


def _missing_header_time() -> dict[str, Any]:
    return {
        "raw_text": None,
        "line": None,
        "parsed_at": None,
        "status": "missing",
        "reason": REASON_HEADER_TIME_MISSING,
    }


def _execution_time_evidence(
    file_times: list[dict[str, Any]],
    *,
    completed_at: datetime | None,
) -> dict[str, Any]:
    """构造 ``execution_time`` 证据段，并按任务完成时间校验上界。"""
    boundary = _as_utc(completed_at) + TIME_FUTURE_TOLERANCE if completed_at is not None else None
    entries: list[dict[str, Any]] = []
    for item in file_times:
        parsed_at = item.get("parsed_at")
        status = str(item.get("status") or "missing")
        reason = item.get("reason")
        if status == "ok" and isinstance(parsed_at, datetime) and boundary is not None:
            if _as_utc(parsed_at) > boundary:
                status = "time_in_future"
                reason = REASON_TIME_IN_FUTURE
        entries.append(
            {
                "source_file": str(item["source_file"]),
                "raw_text": item.get("raw_text"),
                "line": item.get("line"),
                "parsed_at": iso_utc(parsed_at) if isinstance(parsed_at, datetime) else None,
                "status": status,
                "reason": reason,
            }
        )
    statuses = [str(entry["status"]) for entry in entries]
    if entries and all(item == "ok" for item in statuses):
        overall, source = "ok", TIME_SOURCE_LST_ME
    elif any(item == "ok" for item in statuses):
        overall, source = "partial", TIME_SOURCE_TASK
    else:
        overall, source = "missing", TIME_SOURCE_TASK
    return {"status": overall, "source": source, "per_file": entries}


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def resolve_observation_time(
    *,
    source_files: list[str],
    execution_time: object,
    completed_at: datetime,
) -> tuple[datetime, str, str | None]:
    """按设备命中的来源文件解析观测时间。

    返回 ``(观测时间, 时间来源, 回退原因)``：命中可用的执行时间时取其中最近的一个；
    否则回退任务完成时间并给出原因；历史证据（无 ``execution_time``）回退且不带原因。
    """
    wanted = [str(item) for item in source_files]
    entries = execution_time.get("per_file") if isinstance(execution_time, dict) else None
    if not wanted or not isinstance(entries, list) or not entries:
        return completed_at, TIME_SOURCE_TASK, None
    boundary = _as_utc(completed_at) + TIME_FUTURE_TOLERANCE
    candidates: list[datetime] = []
    reasons: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("source_file")) not in wanted:
            continue
        status = str(entry.get("status") or "missing")
        parsed_at = _parse_iso(entry.get("parsed_at"))
        if status == "ok" and parsed_at is not None:
            if parsed_at > boundary:
                reasons.append(REASON_TIME_IN_FUTURE)
                continue
            candidates.append(parsed_at)
            continue
        reason = entry.get("reason") or REASON_BY_STATUS.get(status)
        if reason:
            reasons.append(str(reason))
    if candidates:
        return max(candidates), TIME_SOURCE_LST_ME, None
    return completed_at, TIME_SOURCE_TASK, reasons[0] if reasons else REASON_HEADER_TIME_MISSING


def _upsert_conflict(
    conflicts: list[dict[str, Any]],
    kind: str,
    value: object,
    source_file: str,
    line_no: int,
) -> None:
    conflict = next((item for item in conflicts if item.get("type") == kind), None)
    if conflict is None:
        conflict = {"type": kind, "values": []}
        conflicts.append(conflict)
    entries = conflict["values"]
    if not isinstance(entries, list):  # pragma: no cover - JSON 契约保证列表
        return
    if not any(item.get("value") == value for item in entries):
        entries.append({"value": value, "source_file": source_file, "line": line_no})


def _new_record(relative: str) -> dict[str, Any]:
    return {
        "source_file": relative,
        "names": [],
        "types": [],
        "versions": [],
    }


def _parse_file(
    path: Path,
    relative: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """解析一个来源文件，返回记录列表、解码/游离字段错误和头部执行时间。"""
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    header_time = _missing_header_time()
    try:
        text = decode_text_with_fallback(path.read_bytes())[0]
    except (OSError, UnicodeDecodeError) as exc:
        return [], [{"reason_code": "decode_failed", "message": str(exc), "source_file": relative}], header_time

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        # 头部区域：第一条设备记录之前，命中即锁定并停止扫描，且不参与键值字段解析。
        if current is None and header_time["line"] is None:
            matched_time = _parse_header_time(raw_line)
            if matched_time is not None:
                header_time = {**matched_time, "line": line_no}
                continue
        line = raw_line.strip()
        if not line or ":" not in line and "=" not in line:
            continue
        separator = ":" if ":" in line else "="
        key, value = line.split(separator, 1)
        normalized_key = key.strip().lower()
        value = value.strip()
        if not value:
            continue
        if normalized_key in DEVICE_ALIASES:
            current = _new_record(relative)
            current["names"].append((value, line_no))
            records.append(current)
            continue
        if normalized_key in NETWORK_ELEMENT_TYPE_ALIASES or normalized_key in VERSION_ALIASES:
            if current is None:
                errors.append(
                    {
                        "reason_code": "orphan_record_field",
                        "field": (
                            "network_element_type" if normalized_key in NETWORK_ELEMENT_TYPE_ALIASES else "version"
                        ),
                        "message": "字段位于设备名之前，无法归属到设备记录",
                        "value": value,
                        "source_file": relative,
                        "line": line_no,
                        "recoverable": True,
                    }
                )
                continue
            key_name = "types" if normalized_key in NETWORK_ELEMENT_TYPE_ALIASES else "versions"
            current[key_name].append((value, line_no))
    return records, errors, header_time


def _record_output(
    record: dict[str, Any],
    *,
    normalized_product: str | None,
) -> dict[str, Any]:
    source_file = str(record["source_file"])
    name, name_line = record["names"][0]
    normalized_name = normalize_device_name(name)

    type_values = [value for value, _ in record["types"]]
    unique_type_values = list(dict.fromkeys(type_values))
    if not unique_type_values:
        type_status = "missing"
    elif len(unique_type_values) == 1:
        type_status = "ok"
    else:
        type_status = "conflict"

    version_values = [value for value, _ in record["versions"]]
    unique_version_values = list(dict.fromkeys(version_values))
    if not unique_version_values:
        version_status = "missing"
    elif len(unique_version_values) == 1:
        version_status = "ok"
    else:
        version_status = "conflict"

    normalized_type = normalize_device_name(unique_type_values[0]) if type_status == "ok" else None
    matched = bool(normalized_name and normalized_product and normalized_type and normalized_type == normalized_product)
    return {
        "raw_name": name,
        "normalized_name": normalized_name or None,
        "raw_network_element_type": unique_type_values[0] if type_status == "ok" else None,
        "normalized_network_element_type": normalized_type,
        "network_element_type_status": type_status,
        "raw_version": unique_version_values[0] if version_status == "ok" else None,
        "version_candidates": unique_version_values if version_status == "conflict" else [],
        "version_status": version_status,
        "matched": matched,
        "source_file": source_file,
        "name_source_lines": [line for _, line in record["names"]],
        "type_source_lines": [line for _, line in record["types"]],
        "version_source_lines": [line for _, line in record["versions"]],
    }


def parse_inventory(
    task_dir: Path,
    *,
    task_id: str,
    province: str | None,
    operator: str | None,
    product: str | None = None,
    package_kind: PackageKind | str = PackageKind.INSPECTION,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """解析任务解压现场并返回可写入 ``inventory.json`` 的证据。

    ``completed_at`` 用于执行时间的可信性上界校验；缺省时不做上界校验。
    """
    kind = PackageKind(package_kind)
    now = utc_now()
    evidence = _empty_evidence(task_id, kind, now=now)
    if kind == PackageKind.LOG_SUPPLEMENT:
        evidence["not_applicable_reason"] = "log_supplement_package"
        evidence["site"] = {
            "status": "not_applicable",
            "source": "none",
            "province": None,
            "operator": None,
            "site_key": None,
        }
        evidence["device"] = {
            "status": "not_applicable",
            "raw_names": [],
            "normalized_name": None,
            "reason_code": None,
            "source_lines": [],
        }
        evidence["version"] = {"status": "not_applicable", "raw_version": None, "candidates": [], "source_lines": []}
        evidence["archived"]["reason"] = "not_applicable"
        return evidence

    site_ok = bool(province and province.strip() and operator and operator.strip())
    province_value = province.strip() if province else None
    operator_value = operator.strip() if operator else None
    evidence["site"] = {
        "status": "ok" if site_ok else "missing",
        "source": "upload_metadata" if site_ok else "none",
        "province": province_value,
        "operator": operator_value,
        "site_key": f"{province_value}:{operator_value}" if site_ok else None,
    }

    requested_product = product.strip() if product and product.strip() else None
    normalized_product = normalize_device_name(requested_product) if requested_product else None

    sources: list[tuple[Path, str]] = []
    for path in sorted(task_dir.rglob("*")):
        if not path.is_file() or path.name == ".patrolx-extracted.json":
            continue
        relative = path.relative_to(task_dir).as_posix()
        if SOURCE_PATTERN.fullmatch(relative):
            sources.append((path, relative))

    if not sources:
        evidence["network_element_type_filter"] = {
            "requested": requested_product,
            "normalized": normalized_product,
            "status": "missing" if not normalized_product else "no_match",
            "matched_count": 0,
            "unmatched_count": 0,
        }
        evidence["device"] = {
            "status": "missing",
            "raw_names": [],
            "normalized_name": None,
            "reason_code": "source_file_missing",
            "source_lines": [],
        }
        evidence["version"] = {"status": "not_applicable", "raw_version": None, "candidates": [], "source_lines": []}
        evidence["status"] = "not_archived"
        evidence["not_archived_reason"] = "source_file_missing" if site_ok else "missing_site"
        evidence["archived"]["reason"] = evidence["not_archived_reason"]
        return evidence

    evidence["source_files"] = [relative for _, relative in sources]
    raw_records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    file_times: list[dict[str, Any]] = []
    for path, relative in sources:
        parsed_records, parsed_errors, header_time = _parse_file(path, relative)
        raw_records.extend(parsed_records)
        errors.extend(parsed_errors)
        file_times.append({"source_file": relative, **header_time})

    evidence["execution_time"] = _execution_time_evidence(file_times, completed_at=completed_at)

    all_records = [_record_output(record, normalized_product=normalized_product) for record in raw_records]
    # 只识别所选网元类型：其它类型的记录仅保留数量，不进入任务证据明细。
    unmatched_count = sum(1 for record in all_records if not record["matched"])
    records = [record for record in all_records if record["matched"]]
    for record in records:
        if record["version_status"] == "conflict":
            source_file = str(record["source_file"])
            for line in record["version_source_lines"]:
                _upsert_conflict(conflicts, "version", record["raw_version"], source_file, line)

    fatal_errors = [error for error in errors if not error.get("recoverable")]
    if requested_product:
        filter_status = "ok" if records else "no_match"
    else:
        filter_status = "missing"
    evidence["network_element_type_filter"] = {
        "requested": requested_product,
        "normalized": normalized_product,
        "status": filter_status,
        "matched_count": len(records),
        "unmatched_count": unmatched_count,
    }

    # 匹配设备按规范化设备名去重；同名记录版本一致时合并，版本冲突时保留冲突观测。
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["normalized_name"]), []).append(record)

    devices: list[dict[str, Any]] = []
    for _normalized_name, group in grouped.items():
        version_status = "missing"
        version_values = [str(item["raw_version"]) for item in group if item["raw_version"]]
        unique_versions = list(dict.fromkeys(version_values))
        conflict_candidates = [candidate for item in group for candidate in item.get("version_candidates", [])]
        if any(item["version_status"] == "conflict" for item in group) or len(unique_versions) > 1:
            version_status = "conflict"
        elif unique_versions:
            version_status = "ok"
        name = group[0]["normalized_name"]
        devices.append(
            {
                "status": "ok",
                "raw_name": group[0]["raw_name"],
                "normalized_name": name,
                "network_element_type": group[0]["normalized_network_element_type"],
                "version": {
                    "status": version_status,
                    "raw_version": unique_versions[0] if version_status == "ok" else None,
                    "candidates": list(dict.fromkeys(conflict_candidates)) if version_status == "conflict" else [],
                    "source_lines": [line for item in group for line in item["version_source_lines"]],
                },
                "source_file": group[0]["source_file"],
                "source_files": list(dict.fromkeys(str(item["source_file"]) for item in group)),
            }
        )

    if fatal_errors:
        evidence["status"] = "failed"
        evidence["device"] = {
            "status": "error",
            "raw_names": [str(item["raw_name"]) for item in records if item["raw_name"]],
            "normalized_name": None,
            "reason_code": "parse_error",
            "source_lines": [line for item in records for line in item["name_source_lines"]],
        }
        evidence["version"] = {"status": "error", "raw_version": None, "candidates": [], "source_lines": []}
        evidence["errors"] = errors
        evidence["conflicts"] = conflicts
        evidence["archived"]["reason"] = "parse_error"
        return evidence

    device_status = "ok"
    normalized_name = None
    raw_names = [str(item["raw_name"]) for item in records if item["raw_name"]]
    if not devices:
        device_status = "missing"
        reason_code = (
            "network_element_type_filter_missing" if not normalized_product else "network_element_type_no_match"
        )
    elif len(devices) == 1:
        normalized_name = devices[0]["normalized_name"]
        reason_code = None
    else:
        device_status = "matched_multiple"
        reason_code = "matched_multiple"
    evidence["device"] = {
        "status": device_status,
        "raw_names": raw_names,
        "normalized_name": normalized_name,
        "reason_code": reason_code,
        "source_lines": [line for item in records for line in item["name_source_lines"]],
    }

    if len(devices) == 1:
        evidence["version"] = devices[0]["version"]
    elif len(devices) > 1:
        evidence["version"] = {
            "status": "not_applicable",
            "raw_version": None,
            "candidates": [],
            "source_lines": [line for item in records for line in item["version_source_lines"]],
        }
    else:
        evidence["version"] = {
            "status": "not_applicable",
            "raw_version": None,
            "candidates": [],
            "source_lines": [line for item in records for line in item["version_source_lines"]],
        }

    evidence["conflicts"] = conflicts
    evidence["errors"] = errors
    evidence["records"] = records
    evidence["devices"] = devices

    if not site_ok:
        evidence["status"] = "not_archived"
        evidence["not_archived_reason"] = "missing_site"
        evidence["archived"]["reason"] = "missing_site"
        return evidence
    if not normalized_product:
        evidence["status"] = "not_archived"
        evidence["not_archived_reason"] = "network_element_type_filter_missing"
        evidence["archived"]["reason"] = "network_element_type_filter_missing"
        return evidence
    if not devices:
        evidence["status"] = "not_archived"
        evidence["not_archived_reason"] = "network_element_type_no_match"
        evidence["archived"]["reason"] = "network_element_type_no_match"
        return evidence
    if any(device["version"]["status"] == "conflict" for device in devices):
        evidence["status"] = "not_archived"
        evidence["not_archived_reason"] = "matched_device_version_conflict"
        evidence["archived"]["reason"] = "matched_device_version_conflict"
        return evidence

    archived_devices: list[dict[str, Any]] = []
    for device in devices:
        if device["version"]["status"] == "conflict":
            continue
        device_id_value = device_identity(str(province_value), str(device["normalized_name"]))[1]
        archived_devices.append(
            {
                "device_id": device_id_value,
                "observation_id": observation_id(task_id, device_id_value),
                "normalized_name": device["normalized_name"],
                "network_element_type": device["network_element_type"],
            }
        )
    evidence["status"] = "archived"
    evidence["archived"] = _archive(
        "archived",
        None,
        devices=archived_devices,
    )
    if len(archived_devices) == 1:
        evidence["archived"]["device_id"] = archived_devices[0]["device_id"]
        evidence["archived"]["observation_id"] = archived_devices[0]["observation_id"]
    return evidence
