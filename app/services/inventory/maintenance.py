"""设备台账删除维护服务：物理删除危险资产并保留删除审计。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app.models.db import InventoryChangeAudit, InventoryDevice, InventoryObservation, session_factory
from app.services.inventory.parser import utc_now


@dataclass(frozen=True)
class InventoryMaintenanceError(Exception):
    """台账维护业务错误。"""

    code: str
    message: str
    status_code: int = 400
    detail: dict[str, object] | None = None


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
