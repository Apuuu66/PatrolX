"""设备台账维护服务：手动建档、维护信息更新和物理删除。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.db import InventoryChangeAudit, InventoryDevice, InventoryObservation, session_factory
from app.models.schemas import InventoryDevice as InventoryDeviceModel
from app.services.inventory.parser import device_identity, normalize_device_name, utc_now


@dataclass(frozen=True)
class InventoryMaintenanceError(Exception):
    """台账维护业务错误。"""

    code: str
    message: str
    status_code: int = 400
    detail: dict[str, object] | None = None


def _normalize_required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InventoryMaintenanceError("invalid_request", f"{field}不能为空", 400)
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _device_model(device: InventoryDevice) -> InventoryDeviceModel:
    return InventoryDeviceModel(
        device_id=device.device_id,
        province=device.province,
        device_name=device.current_device_name,
        site_key=device.current_site_key,
        operator=device.current_operator,
        current_version=device.current_version_raw,
        current_version_observed_at=device.current_version_observed_at,
        current_version_task_id=device.current_version_task_id,
        first_seen_at=device.first_seen_at,
        last_seen_at=device.last_seen_at,
        observation_count=device.observation_count,
        site_change_count=device.site_change_count,
        has_site_conflict=device.has_site_conflict,
        quality_issue_types=[],
        remark=device.remark,
        created_by=device.created_by,
        updated_by=device.updated_by,
        updated_at=device.updated_at,
    )


def _device_summary(device: InventoryDevice) -> dict[str, object]:
    return {
        "device_id": device.device_id,
        "province": device.province,
        "operator": device.current_operator,
        "device_name": device.current_device_name,
        "observation_count": device.observation_count,
        "remark": device.remark,
    }


def _maintenance_audit(
    *,
    device_id: str,
    action: str,
    before: dict[str, object] | None,
    after: dict[str, object],
    operator: str,
    now: datetime,
) -> InventoryChangeAudit:
    audit_id = f"manual-{device_id}-{action}-{int(now.timestamp() * 1_000_000)}"
    return InventoryChangeAudit(
        audit_id=audit_id,
        task_id=None,
        device_id=device_id,
        observation_id=None,
        action=action,
        before_snapshot=before,
        after_snapshot=after,
        changed_at=now,
    )


def create_device(
    *, province: str, operator: str, device_name: str, remark: str | None, operator_name: str
) -> InventoryDeviceModel:
    """创建手动设备档案；版本只能由巡检任务观测得到。"""
    province_value = _normalize_required(province, "省份")
    operator_value = _normalize_required(operator, "运营商")
    device_name_value = normalize_device_name(_normalize_required(device_name, "设备名"))
    remark_value = _normalize_optional(remark)
    device_key, device_id = device_identity(province_value, device_name_value)
    now = utc_now()
    site_key = f"{province_value}:{operator_value}"
    try:
        with session_factory() as session:
            if session.get(InventoryDevice, device_id) is not None:
                raise InventoryMaintenanceError("device_already_exists", "同省份设备名已存在", 409)
            device = InventoryDevice(
                device_id=device_id,
                device_key=device_key,
                province=province_value,
                current_device_name=device_name_value,
                current_site_key=site_key,
                current_operator=operator_value,
                current_version_raw=None,
                current_version_observed_at=None,
                current_version_task_id=None,
                current_observation_id=None,
                first_seen_at=now,
                last_seen_at=now,
                latest_task_id="manual",
                latest_status="manual",
                observation_count=0,
                site_change_count=0,
                has_site_conflict=False,
                remark=remark_value,
                created_by=operator_name,
                updated_by=operator_name,
                created_at=now,
                updated_at=now,
            )
            session.add(device)
            session.flush()
            session.add(
                _maintenance_audit(
                    device_id=device_id,
                    action="create",
                    before=None,
                    after=_device_summary(device),
                    operator=operator_name,
                    now=now,
                )
            )
            session.commit()
            return _device_model(device)
    except IntegrityError as exc:
        raise InventoryMaintenanceError("device_already_exists", "同省份设备名已存在", 409) from exc
    except SQLAlchemyError as exc:
        raise InventoryMaintenanceError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def update_device(device_id: str, *, remark: str | None, operator_name: str) -> InventoryDeviceModel:
    """更新设备维护信息；第一版仅允许维护备注。"""
    now = utc_now()
    remark_value = _normalize_optional(remark)
    try:
        with session_factory() as session:
            device = session.get(InventoryDevice, device_id)
            if device is None:
                raise InventoryMaintenanceError("not_found", "设备不存在", 404)
            before = _device_summary(device)
            device.remark = remark_value
            device.updated_by = operator_name
            device.updated_at = now
            session.add(
                _maintenance_audit(
                    device_id=device_id,
                    action="update",
                    before=before,
                    after=_device_summary(device),
                    operator=operator_name,
                    now=now,
                )
            )
            session.commit()
            return _device_model(device)
    except SQLAlchemyError as exc:
        raise InventoryMaintenanceError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def delete_device(device_id: str, operator_name: str) -> None:
    """物理删除设备及其全部观测和历史审计，仅保留一条删除审计。"""
    now = utc_now()
    try:
        with session_factory() as session:
            device = session.get(InventoryDevice, device_id)
            if device is None:
                raise InventoryMaintenanceError("not_found", "设备不存在", 404)
            summary = _device_summary(device)
            session.query(InventoryChangeAudit).filter(InventoryChangeAudit.device_id == device_id).delete(
                synchronize_session=False
            )
            session.query(InventoryObservation).filter(InventoryObservation.device_id == device_id).delete(
                synchronize_session=False
            )
            session.delete(device)
            session.flush()
            session.add(
                _maintenance_audit(
                    device_id=device_id,
                    action="delete",
                    before=summary,
                    after={},
                    operator=operator_name,
                    now=now,
                )
            )
            session.commit()
    except SQLAlchemyError as exc:
        raise InventoryMaintenanceError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc
