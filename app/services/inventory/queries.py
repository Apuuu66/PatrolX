"""台账只读查询投影。"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy.orm import Session

from app.models.db import InventoryDevice, InventoryObservation, InventoryParseResult
from app.models.schemas import (
    InventoryDevice as InventoryDeviceModel,
)
from app.models.schemas import (
    InventoryFieldStatus,
    InventoryQualityIssue,
    InventoryQualityIssueType,
    InventoryVersionPoint,
    VersionDirection,
)
from app.models.schemas import (
    InventoryObservation as InventoryObservationModel,
)


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _device_model(device: InventoryDevice, issue_types: list[InventoryQualityIssueType]) -> InventoryDeviceModel:
    return InventoryDeviceModel(
        device_id=device.device_id,
        province=device.province,
        device_name=device.current_device_name,
        site_key=device.current_site_key,
        operator=device.current_operator,
        current_version=device.current_version_raw,
        current_version_observed_at=(
            _ensure_utc(device.current_version_observed_at) if device.current_version_observed_at else None
        ),
        current_version_task_id=device.current_version_task_id,
        first_seen_at=_ensure_utc(device.first_seen_at),
        last_seen_at=_ensure_utc(device.last_seen_at),
        observation_count=device.observation_count,
        site_change_count=device.site_change_count,
        has_site_conflict=device.has_site_conflict,
        quality_issue_types=issue_types,
        remark=device.remark,
        created_by=device.created_by,
        updated_by=device.updated_by,
        updated_at=_ensure_utc(device.updated_at) if device.updated_at else None,
    )


def _device_issue_types(device: InventoryDevice) -> list[InventoryQualityIssueType]:
    issues: list[InventoryQualityIssueType] = []
    if device.current_version_raw is None:
        issues.append(InventoryQualityIssueType.MISSING_VERSION)
    if device.has_site_conflict:
        issues.append(InventoryQualityIssueType.SITE_OWNERSHIP_CHANGE)
    return issues


def list_devices(
    session: Session,
    *,
    page: int,
    page_size: int,
    province: str | None = None,
    operator: str | None = None,
    quality_status: str = "all",
) -> tuple[list[InventoryDeviceModel], int]:
    query = session.query(InventoryDevice)
    if province:
        query = query.filter(InventoryDevice.province == province)
    if operator:
        query = query.filter(InventoryDevice.current_operator == operator)
    if quality_status == "issue":
        query = query.filter(
            InventoryDevice.current_version_raw.is_(None) | InventoryDevice.has_site_conflict.is_(True)
        )
    total = query.count()
    rows = (
        query.order_by(InventoryDevice.current_site_key.asc(), InventoryDevice.current_device_name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_device_model(row, _device_issue_types(row)) for row in rows], total


def get_device(session: Session, device_id: str) -> InventoryDeviceModel | None:
    device = session.get(InventoryDevice, device_id)
    return _device_model(device, _device_issue_types(device)) if device else None


def _observation_model(observation: InventoryObservation) -> InventoryObservationModel:
    return InventoryObservationModel(
        observation_id=observation.observation_id,
        task_id=observation.task_id,
        task_status="completed",
        observed_at=_ensure_utc(observation.observed_at),
        province=observation.province,
        operator=observation.operator,
        site_key=observation.site_key,
        device_name=observation.device_name,
        identity_status="ok",
        version_status=InventoryFieldStatus(observation.version_status),
        raw_version=observation.raw_version,
        version_source_files=list(observation.version_source_files or []),
        conflicts=list(observation.device_snapshot.get("conflicts", [])) if observation.device_snapshot else [],
        snapshot=observation.device_snapshot or {},
    )


def list_observations(
    session: Session,
    device_id: str,
    *,
    page: int,
    page_size: int,
    order: str = "desc",
    site_key: str | None = None,
) -> tuple[list[InventoryObservationModel], int]:
    if session.get(InventoryDevice, device_id) is None:
        return [], 0
    query = session.query(InventoryObservation).filter(
        InventoryObservation.device_id == device_id,
        InventoryObservation.status == "active",
    )
    if site_key:
        query = query.filter(InventoryObservation.site_key == site_key)
    total = query.count()
    query = query.order_by(
        InventoryObservation.observed_at.asc() if order == "asc" else InventoryObservation.observed_at.desc(),
        InventoryObservation.task_id.asc() if order == "asc" else InventoryObservation.task_id.desc(),
    )
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return [_observation_model(row) for row in rows], total


def _version_history_points(observations: list[InventoryObservation]) -> list[InventoryVersionPoint]:
    points: list[InventoryVersionPoint] = []
    previous_valid_version: str | None = None
    saw_gap = False
    for observation in observations:
        status = InventoryFieldStatus(observation.version_status)
        direction: VersionDirection | None = None
        has_gap = False
        if status == InventoryFieldStatus.OK and observation.raw_version:
            if previous_valid_version is not None:
                has_gap = saw_gap
                if observation.raw_version > previous_valid_version:
                    direction = VersionDirection.UPGRADE
                elif observation.raw_version < previous_valid_version:
                    direction = VersionDirection.DOWNGRADE
                else:
                    direction = VersionDirection.UNCHANGED
            previous_valid_version = observation.raw_version
            saw_gap = False
        else:
            has_gap = previous_valid_version is not None
            saw_gap = True
        points.append(
            InventoryVersionPoint(
                observed_at=_ensure_utc(observation.observed_at),
                task_id=observation.task_id,
                version_status=status,
                raw_version=observation.raw_version,
                direction=direction,
                has_gap=has_gap,
            )
        )
    return points


def get_version_history(
    session: Session,
    device_id: str,
    *,
    page: int,
    page_size: int,
) -> tuple[list[InventoryVersionPoint], int]:
    if session.get(InventoryDevice, device_id) is None:
        return [], 0
    rows = (
        session.query(InventoryObservation)
        .filter(InventoryObservation.device_id == device_id, InventoryObservation.status == "active")
        .order_by(InventoryObservation.observed_at.asc(), InventoryObservation.task_id.asc())
        .all()
    )
    points = _version_history_points(rows)
    start = (page - 1) * page_size
    return points[start : start + page_size], len(points)


def _issue_id(*parts: object) -> str:
    payload = "\n".join(str(part) for part in parts)
    return sha256(payload.encode("utf-8")).hexdigest()


def list_quality_issues(
    session: Session,
    *,
    page: int,
    page_size: int,
    issue_type: InventoryQualityIssueType | None = None,
    province: str | None = None,
    operator: str | None = None,
    task_id: str | None = None,
    device_id: str | None = None,
) -> tuple[list[InventoryQualityIssue], int]:
    results = (
        session.query(InventoryParseResult)
        .filter(InventoryParseResult.package_kind == "inspection")
        .order_by(InventoryParseResult.updated_at.desc(), InventoryParseResult.task_id.desc())
        .all()
    )
    observations = (
        session.query(InventoryObservation)
        .filter(InventoryObservation.status == "active")
        .order_by(InventoryObservation.observed_at.asc(), InventoryObservation.task_id.asc())
        .all()
    )
    issues: list[InventoryQualityIssue] = []
    for result in results:
        result_province = result.province
        result_operator = result.operator
        if result.status == "not_archived" and result.site_status == "missing":
            issues.append(
                InventoryQualityIssue(
                    issue_id=_issue_id("missing_site", result.task_id),
                    issue_type=InventoryQualityIssueType.MISSING_SITE,
                    message="任务缺少省份或运营商，设备观测未归档",
                    task_id=result.task_id,
                    device_id=None,
                    province=None,
                    operator=None,
                    detected_at=_ensure_utc(result.updated_at),
                    detail={"reason": result.snapshot.get("not_archived_reason")},
                )
            )
        if result.device_status == "missing":
            issues.append(
                InventoryQualityIssue(
                    issue_id=_issue_id("missing_device_identity", result.task_id),
                    issue_type=InventoryQualityIssueType.MISSING_DEVICE_IDENTITY,
                    message="任务缺少设备身份，设备观测未归档",
                    task_id=result.task_id,
                    province=result_province,
                    operator=result_operator,
                    detected_at=_ensure_utc(result.updated_at),
                    detail={"reason": "missing_device_identity"},
                )
            )
        if result.device_status == "conflict":
            issues.append(
                InventoryQualityIssue(
                    issue_id=_issue_id("device_identity_conflict", result.task_id),
                    issue_type=InventoryQualityIssueType.DEVICE_IDENTITY_CONFLICT,
                    message="任务内设备名称冲突",
                    task_id=result.task_id,
                    province=result_province,
                    operator=result_operator,
                    detected_at=_ensure_utc(result.updated_at),
                    detail={"conflicts": result.conflicts},
                )
            )
        if result.version_status == "missing":
            issues.append(
                InventoryQualityIssue(
                    issue_id=_issue_id("missing_version", result.task_id),
                    issue_type=InventoryQualityIssueType.MISSING_VERSION,
                    message="设备观测缺少版本信息",
                    task_id=result.task_id,
                    province=result_province,
                    operator=result_operator,
                    detected_at=_ensure_utc(result.updated_at),
                    detail={"reason": "missing_version"},
                )
            )
        if result.version_status == "conflict":
            issues.append(
                InventoryQualityIssue(
                    issue_id=_issue_id("version_conflict", result.task_id),
                    issue_type=InventoryQualityIssueType.VERSION_CONFLICT,
                    message="任务内版本信息冲突",
                    task_id=result.task_id,
                    province=result_province,
                    operator=result_operator,
                    detected_at=_ensure_utc(result.updated_at),
                    detail={"conflicts": result.conflicts},
                )
            )
    for index, (previous, current) in enumerate(zip(observations, observations[1:], strict=False), start=1):
        if previous.device_id != current.device_id:
            continue
        if previous.operator == current.operator:
            continue
        issues.append(
            InventoryQualityIssue(
                issue_id=_issue_id("site_ownership_change", current.device_id, current.task_id, index),
                issue_type=InventoryQualityIssueType.SITE_OWNERSHIP_CHANGE,
                message="设备观测局点归属发生变化",
                task_id=current.task_id,
                device_id=current.device_id,
                province=current.province,
                operator=current.operator,
                detected_at=_ensure_utc(current.observed_at),
                detail={"from_operator": previous.operator, "to_operator": current.operator},
            )
        )

    if province:
        issues = [issue for issue in issues if issue.province == province]
    if operator:
        issues = [issue for issue in issues if issue.operator == operator]
    if task_id:
        issues = [issue for issue in issues if issue.task_id == task_id]
    if device_id:
        issues = [issue for issue in issues if issue.device_id == device_id]
    if issue_type:
        issues = [issue for issue in issues if issue.issue_type == issue_type]
    issues.sort(key=lambda item: (item.detected_at, item.issue_id), reverse=True)
    return issues[(page - 1) * page_size : (page - 1) * page_size + page_size], len(issues)
