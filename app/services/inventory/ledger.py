"""台账证据写入、观测覆盖和设备状态重算。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from app.core.config import settings
from app.models.db import (
    InventoryChangeAudit,
    InventoryDevice,
    InventoryObservation,
    InventoryParseResult,
    session_factory,
)
from app.models.schemas import InventoryParseStatus, PackageKind
from app.services.inventory.parser import iso_utc, utc_now
from app.services.store import write_json_atomic


def evidence_path(task_id: str) -> Path:
    """返回任务台账证据文件路径。"""
    return settings.output / task_id / "inventory.json"


def load_evidence(task_id: str) -> dict | None:
    """读取任务台账证据。"""
    path = evidence_path(task_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _observation_snapshot(observation: InventoryObservation) -> dict[str, object]:
    return {
        "observation_id": observation.observation_id,
        "task_id": observation.task_id,
        "device_id": observation.device_id,
        "province": observation.province,
        "operator": observation.operator,
        "site_key": observation.site_key,
        "observed_at": iso_utc(_ensure_utc(observation.observed_at)),
        "task_status": observation.task_status,
        "device_name": observation.device_name,
        "identity_status": observation.identity_status,
        "version_status": observation.version_status,
        "raw_version": observation.raw_version,
        "version_key": observation.version_key,
        "version_source_files": observation.version_source_files,
        "device_snapshot": observation.device_snapshot,
        "status": observation.status,
        "created_at": iso_utc(_ensure_utc(observation.created_at)),
        "updated_at": iso_utc(_ensure_utc(observation.updated_at)),
    }


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _audit_id(task_id: str | None, observation_id_value: str | None, action: str, before: object, after: object) -> str:
    payload = json.dumps(
        {
            "task_id": task_id,
            "observation_id": observation_id_value,
            "action": action,
            "before": before,
            "after": after,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _write_parse_result(evidence: dict[str, object], now: datetime) -> None:
    with session_factory() as session:
        existing = session.get(InventoryParseResult, str(evidence["task_id"]))
        created = existing.created_at if existing else now
        result = InventoryParseResult(
            task_id=str(evidence["task_id"]),
            package_kind=str(evidence["package_kind"]),
            status=str(evidence["status"]),
            parser_id=str(evidence["parser_id"]),
            parser_version=str(evidence["parser_version"]),
            schema_version=int(evidence["schema_version"]),
            site_status=str(evidence["site"]["status"]) if evidence["site"] else "missing",
            site_source=str(evidence["site"]["source"]) if evidence["site"] else "none",
            site_key=evidence["site"].get("site_key") if evidence["site"] else None,
            province=evidence["site"].get("province") if evidence["site"] else None,
            operator=evidence["site"].get("operator") if evidence["site"] else None,
            device_status=str(evidence["device"]["status"]) if evidence["device"] else "missing",
            version_status=str(evidence["version"]["status"]) if evidence["version"] else "not_applicable",
            source_files=list(evidence["source_files"]),
            conflicts=list(evidence["conflicts"]),
            errors=list(evidence["errors"]),
            snapshot=evidence,
            created_at=created,
            updated_at=now,
        )
        session.merge(result)
        session.commit()


def _recalculate_device(session, device: InventoryDevice, now: datetime) -> None:
    """从 active 观测重算设备当前状态。"""
    observations = (
        session.query(InventoryObservation)
        .filter(InventoryObservation.device_id == device.device_id, InventoryObservation.status == "active")
        .order_by(InventoryObservation.observed_at.desc(), InventoryObservation.task_id.asc())
        .all()
    )
    ascending = list(reversed(observations))
    device.observation_count = len(observations)
    device.latest_status = "archived" if observations else "retired"
    device.updated_at = now
    if not observations:
        return
    latest = observations[0]
    device.current_device_name = latest.device_name
    device.current_site_key = latest.site_key
    device.current_operator = latest.operator
    device.current_observation_id = latest.observation_id
    device.last_seen_at = latest.observed_at
    device.latest_task_id = latest.task_id
    device.first_seen_at = min(_ensure_utc(item.observed_at) for item in observations)
    versioned = [item for item in observations if item.version_status == "ok" and item.raw_version]
    if versioned:
        current_version = versioned[0]
        device.current_version_raw = current_version.raw_version
        device.current_version_observed_at = current_version.observed_at
        device.current_version_task_id = current_version.task_id
    else:
        device.current_version_raw = None
        device.current_version_observed_at = None
        device.current_version_task_id = None
        device.current_observation_id = latest.observation_id
    changes = sum(
        1 for previous, current in zip(ascending, ascending[1:], strict=False) if previous.operator != current.operator
    )
    device.site_change_count = changes
    device.has_site_conflict = len({item.operator for item in observations}) > 1


def _observation_values(
    *,
    device_info: dict[str, object],
    site: dict[str, object],
    source_files: list[str],
    conflicts: list[object],
    errors: list[object],
    completed_at: datetime,
    now: datetime,
) -> dict[str, object]:
    """从匹配设备证据构造一条台账观测。"""
    version = device_info.get("version") if isinstance(device_info.get("version"), dict) else {}
    raw_version = version.get("raw_version")
    version_source_files = device_info.get("source_files") or source_files
    return {
        "province": str(site["province"]),
        "operator": str(site["operator"]),
        "site_key": str(site["site_key"]),
        "observed_at": completed_at,
        "task_status": "completed",
        "device_name": str(device_info["normalized_name"]),
        "identity_status": "ok",
        "version_status": str(version.get("status") or "missing"),
        "raw_version": str(raw_version) if raw_version is not None else None,
        "version_key": str(raw_version) if raw_version is not None else None,
        "version_source_files": [str(item) for item in version_source_files],
        "device_snapshot": {
            "device": device_info,
            "version": version,
            "site": site,
            "conflicts": conflicts,
            "errors": errors,
        },
        "status": "active",
        "updated_at": now,
    }


def archive_inventory(
    evidence: dict[str, object],
    *,
    task_id: str,
    package_kind: PackageKind | str,
    completed_at: datetime,
) -> dict[str, object]:
    """写入可重建证据并按任务、按设备覆盖台账观测；台账数据本身持久保留。"""
    kind = PackageKind(package_kind)
    now = utc_now()
    path = evidence_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, evidence)
    _write_parse_result(evidence, now)
    actions: list[str] = []
    if kind == PackageKind.LOG_SUPPLEMENT:
        return {"status": InventoryParseStatus.NOT_APPLICABLE.value, "archived": False, "audits": actions}

    with session_factory() as session:
        legacy_device = evidence.get("device") if isinstance(evidence.get("device"), dict) else {}
        archived = evidence.get("archived") if isinstance(evidence.get("archived"), dict) else {}
        archived_devices = archived.get("devices") if isinstance(archived.get("devices"), list) else []
        if evidence.get("status") == "archived" and archived.get("device_id") and not archived_devices:
            # 兼容 027 旧证据：旧版本仅写入单设备归档字段，也允许重跑恢复。
            archived_devices = [
                {
                    "device_id": archived.get("device_id"),
                    "observation_id": archived.get("observation_id"),
                    "normalized_name": legacy_device.get("normalized_name"),
                }
            ]
        device_infos = {
            str(item.get("normalized_name")): item
            for item in evidence.get("devices", [])
            if isinstance(item, dict) and item.get("normalized_name")
        }
        if not device_infos and legacy_device.get("normalized_name"):
            device_infos[str(legacy_device["normalized_name"])] = legacy_device

        existing_observations = (
            session.query(InventoryObservation).filter(InventoryObservation.task_id == task_id).all()
        )
        target_observation_ids = {
            str(item.get("observation_id")) for item in archived_devices if item.get("observation_id")
        }
        can_archive = evidence.get("status") == "archived" and bool(archived_devices)
        if not can_archive:
            target_observation_ids = set()

        for existing_observation in existing_observations:
            if existing_observation.observation_id in target_observation_ids:
                continue
            before = _observation_snapshot(existing_observation)
            existing_observation.status = "retired"
            existing_observation.updated_at = now
            after = _observation_snapshot(existing_observation)
            audit_id = _audit_id(task_id, existing_observation.observation_id, "retire", before, after)
            if not session.get(InventoryChangeAudit, audit_id):
                session.add(
                    InventoryChangeAudit(
                        audit_id=audit_id,
                        task_id=task_id,
                        device_id=existing_observation.device_id,
                        observation_id=existing_observation.observation_id,
                        action="retire",
                        before_snapshot=before,
                        after_snapshot=after,
                        changed_at=now,
                    )
                )
                actions.append("retire")

        if can_archive:
            site = evidence.get("site") or {}
            source_files = [str(item) for item in evidence.get("source_files", [])]
            conflicts = list(evidence.get("conflicts", []))
            errors = list(evidence.get("errors", []))
            for archived_device in archived_devices:
                device_id = str(archived_device["device_id"])
                obs_id = str(archived_device["observation_id"])
                normalized_name = str(archived_device.get("normalized_name") or "")
                device_info = device_infos.get(normalized_name, legacy_device)
                values = _observation_values(
                    device_info=device_info,
                    site=site,
                    source_files=source_files,
                    conflicts=conflicts,
                    errors=errors,
                    completed_at=completed_at,
                    now=now,
                )
                device = session.get(InventoryDevice, device_id)
                if device is None:
                    device = InventoryDevice(
                        device_id=device_id,
                        device_key=values["device_name"],
                        province=values["province"],
                        current_device_name=values["device_name"],
                        current_site_key=values["site_key"],
                        current_operator=values["operator"],
                        first_seen_at=completed_at,
                        last_seen_at=completed_at,
                        latest_task_id=task_id,
                        latest_status="archived",
                        observation_count=0,
                        site_change_count=0,
                        has_site_conflict=False,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(device)
                    session.flush()
                existing_observation = session.get(InventoryObservation, obs_id)
                if existing_observation is None:
                    observation = InventoryObservation(
                        observation_id=obs_id,
                        task_id=task_id,
                        device_id=device_id,
                        created_at=now,
                        **values,
                    )
                    session.add(observation)
                    session.flush()
                    actions.append("create")
                    after = _observation_snapshot(observation)
                    audit_id = _audit_id(task_id, obs_id, "create", None, after)
                    session.merge(
                        InventoryChangeAudit(
                            audit_id=audit_id,
                            task_id=task_id,
                            device_id=device_id,
                            observation_id=obs_id,
                            action="create",
                            before_snapshot=None,
                            after_snapshot=after,
                            changed_at=now,
                        )
                    )
                else:
                    before = _observation_snapshot(existing_observation)
                    for key, value in values.items():
                        setattr(existing_observation, key, value)
                    after = _observation_snapshot(existing_observation)
                    if _strip_dynamic(before) != _strip_dynamic(after):
                        audit_id = _audit_id(task_id, obs_id, "update", _strip_dynamic(before), _strip_dynamic(after))
                        if not session.get(InventoryChangeAudit, audit_id):
                            session.add(
                                InventoryChangeAudit(
                                    audit_id=audit_id,
                                    task_id=task_id,
                                    device_id=device_id,
                                    observation_id=obs_id,
                                    action="update",
                                    before_snapshot=_strip_dynamic(before),
                                    after_snapshot=_strip_dynamic(after),
                                    changed_at=now,
                                )
                            )
                            actions.append("update")
                _recalculate_device(session, device, now)
        else:
            touched_device_ids = {item.device_id for item in existing_observations}
            for device_id_value in touched_device_ids:
                device = session.get(InventoryDevice, device_id_value)
                if device is not None:
                    _recalculate_device(session, device, now)
        session.commit()

    return {
        "status": str(evidence["status"]),
        "archived": bool(can_archive),
        "audits": actions,
    }


def _strip_dynamic(data: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in data.items() if key not in {"created_at", "updated_at"}}
