"""解析 ``LST ME.txt`` 并生成任务级台账证据。

该解析器不是巡检规则；只作为全量任务完成后的台账归档服务。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from unicodedata import normalize

from app.core.encoding import decode_text_with_fallback
from app.models.schemas import PackageKind

PARSER_ID = "site_device_lst_me"
PARSER_VERSION = "1"
SCHEMA_VERSION = 1
SOURCE_PATTERN = re.compile(r"^config/(?:.*/)?LST ME\.txt$", re.IGNORECASE)
DEVICE_ALIASES = {"ne name", "me name", "网元名称", "设备名称"}
VERSION_ALIASES = {"software version", "sw version", "软件版本"}


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    """返回 UTC ISO-8601 字符串。"""
    return (value or utc_now()).isoformat()


def normalize_device_name(value: str) -> str:
    """按契约规范化设备名：NFC、去首尾空白、合并空白。"""
    return re.sub(r"\s+", " ", normalize("NFC", value)).strip()


def device_identity(province: str, normalized_name: str) -> tuple[str, str]:
    """返回确定性 ``device_key`` 和 ``device_id``。"""
    device_key = sha256(normalized_name.encode("utf-8")).hexdigest()
    device_id = sha256(f"{province}\n{device_key}".encode()).hexdigest()
    return device_key, device_id


def observation_id(task_id: str, device_id: str) -> str:
    """返回任务唯一观测 ID。"""
    return sha256(f"{task_id}\n{device_id}".encode()).hexdigest()


def _archive(status: str = "not_applicable", reason: str | None = None) -> dict[str, object]:
    return {"archived": status == "archived", "device_id": None, "observation_id": None, "reason": reason}


def _empty_evidence(task_id: str, package_kind: PackageKind, *, now: datetime) -> dict[str, object]:
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
        "site": None,
        "device": None,
        "version": None,
        "source_files": [],
        "conflicts": [],
        "errors": [],
        "archived": _archive(),
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _upsert_conflict(
    conflicts: list[dict[str, object]],
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
    assert isinstance(entries, list)
    if not any(item.get("value") == value for item in entries):
        entries.append({"value": value, "source_file": source_file, "line": line_no})


def _parse_file(path: Path, relative: str) -> dict[str, object]:
    """解析一个来源文件，返回原始值、行号和解码错误。"""
    names: list[tuple[str, int]] = []
    versions: list[tuple[str, int]] = []
    errors: list[dict[str, object]] = []
    try:
        text = decode_text_with_fallback(path.read_bytes())[0]
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "names": names,
            "versions": versions,
            "errors": [{"reason_code": "decode_failed", "message": str(exc), "source_file": relative}],
        }
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or ":" not in line and "=" not in line:
            continue
        separator = ":" if ":" in line else "="
        key, value = line.split(separator, 1)
        normalized_key = key.strip().lower()
        if normalized_key in DEVICE_ALIASES and value.strip():
            names.append((value.strip(), line_no))
        elif normalized_key in VERSION_ALIASES and value.strip():
            versions.append((value.strip(), line_no))
    return {"names": names, "versions": versions, "errors": errors}


def parse_inventory(
    task_dir: Path,
    *,
    task_id: str,
    province: str | None,
    operator: str | None,
    package_kind: PackageKind | str = PackageKind.INSPECTION,
) -> dict[str, object]:
    """解析任务解压现场并返回可写入 ``inventory.json`` 的证据。"""
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

    sources: list[tuple[Path, str]] = []
    for path in sorted(task_dir.rglob("*")):
        if not path.is_file() or path.name == ".patrolx-extracted.json":
            continue
        relative = path.relative_to(task_dir).as_posix()
        if SOURCE_PATTERN.fullmatch(relative):
            sources.append((path, relative))

    if not sources:
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
    all_names: list[tuple[str, int, str]] = []
    all_versions: list[tuple[str, int, str]] = []
    errors: list[dict[str, object]] = []
    for path, relative in sources:
        parsed = _parse_file(path, relative)
        errors.extend(parsed["errors"])  # type: ignore[arg-type]
        for name, line_no in parsed["names"]:  # type: ignore[union-attr]
            all_names.append((name, line_no, relative))
        for version, line_no in parsed["versions"]:  # type: ignore[union-attr]
            all_versions.append((version, line_no, relative))

    unique_names = list(dict.fromkeys(name for name, _, _ in all_names))
    normalized_names = list(dict.fromkeys(normalize_device_name(name) for name in unique_names))
    conflicts: list[dict[str, object]] = []
    device_status = "ok"
    normalized_name = normalized_names[0] if normalized_names else None
    if not normalized_name:
        device_status = "missing"
    elif len(normalized_names) > 1:
        device_status = "conflict"
        for name, line_no, source in all_names:
            _upsert_conflict(conflicts, "device_identity", name, source, line_no)

    device_id_value: str | None = None
    if device_status == "ok" and site_ok and normalized_name and province_value:
        _, device_id_value = device_identity(province_value, normalized_name)

    unique_versions = list(dict.fromkeys(version for version, _, _ in all_versions))
    if not unique_versions:
        version_status = "missing"
    elif len(unique_versions) == 1:
        version_status = "ok"
    else:
        version_status = "conflict"
    if version_status == "conflict":
        for version, line_no, source in all_versions:
            _upsert_conflict(conflicts, "version", version, source, line_no)

    evidence["conflicts"] = conflicts
    evidence["errors"] = errors
    evidence["device"] = {
        "status": device_status,
        "raw_names": unique_names,
        "normalized_name": normalized_name,
        "reason_code": None if device_status == "ok" else device_status,
        "source_lines": [line_no for _, line_no, _ in all_names],
    }
    evidence["version"] = {
        "status": version_status,
        "raw_version": unique_versions[0] if version_status == "ok" else None,
        "candidates": unique_versions if version_status == "conflict" else [],
        "source_lines": [line_no for _, line_no, _ in all_versions],
    }

    if errors:
        evidence["status"] = "failed"
        evidence["device"]["status"] = "error"
        evidence["archived"]["reason"] = "parse_error"
        return evidence
    if not site_ok:
        evidence["status"] = "not_archived"
        evidence["not_archived_reason"] = "missing_site"
        evidence["archived"]["reason"] = "missing_site"
        return evidence
    if device_status != "ok":
        evidence["status"] = "not_archived"
        evidence["not_archived_reason"] = (
            "device_identity_conflict" if device_status == "conflict" else "missing_device_identity"
        )
        evidence["archived"]["reason"] = evidence["not_archived_reason"]
        return evidence

    evidence["status"] = "archived"
    evidence["archived"] = {
        "archived": True,
        "device_id": device_id_value,
        "observation_id": observation_id(task_id, device_id_value) if device_id_value else None,
        "reason": None,
    }
    return evidence
