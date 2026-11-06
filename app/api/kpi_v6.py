"""KPI 结果工作台 v6 API 骨架。

本模块只承载 HTTP 参数、鉴权和状态码接线。业务查询、事务和判定必须由
``app.services`` 中的 v6 服务提供，路由层不得直接访问持久化层。
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, Query, Response
from fastapi import Path as PathParam

from app.api.errors import AppError
from app.models import kpi_v6 as schemas
from app.services import (
    kpi_measurement_scope,
    kpi_team_focus,
    kpi_workbench,
    rule_network_assignments,
)
from app.services.auth import AuthSession, get_current_user, require_role

router = APIRouter(prefix="/kpi", tags=["KpiV6"])

_NETWORK_ELEMENT_TYPE_PATTERN = r"^[A-Z][A-Z0-9_]*$"
_RULE_CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


def _network_element_type_path() -> str:
    """仅用于保持路径参数约束集中声明。"""
    return PathParam(..., min_length=1, max_length=32, pattern=_NETWORK_ELEMENT_TYPE_PATTERN)


def _raise_team_focus_error(exc: kpi_team_focus.KpiTeamFocusError) -> NoReturn:
    """将团队关注业务错误映射为统一 API 错误。"""
    raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


def _raise_measurement_scope_error(
    exc: kpi_measurement_scope.KpiMeasurementScopeError,
) -> NoReturn:
    """将测量单元范围维护错误映射为统一 API 错误。"""
    raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


def _raise_rule_assignment_error(
    exc: rule_network_assignments.RuleAssignmentError,
) -> NoReturn:
    """将规则网元归属业务错误映射为统一 API 错误。"""
    raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


# --- 团队关注 ---


@router.get(
    "/team-focus/{network_element_type}",
    response_model=schemas.KpiTeamFocusPageV6,
    operation_id="listKpiTeamFocusV6",
)
def list_kpi_team_focus_v6(
    network_element_type: str = _network_element_type_path(),
    task_id: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(default=None, max_length=256),
    measurement_unit_id: str | None = Query(default=None),
    availability: schemas.FocusAvailability | None = Query(default=None),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiTeamFocusPageV6:
    try:
        return kpi_team_focus.list_team_focus(
            network_element_type,
            task_id=task_id,
            actor=_auth,
            page=page,
            page_size=page_size,
            search=search,
            measurement_unit_id=measurement_unit_id,
            availability=availability,
        )
    except kpi_team_focus.KpiTeamFocusError as exc:
        _raise_team_focus_error(exc)


@router.patch(
    "/team-focus/{network_element_type}",
    response_model=schemas.KpiTeamFocusPatchResponseV6,
    operation_id="patchKpiTeamFocusV6",
)
def patch_kpi_team_focus_v6(
    body: schemas.KpiTeamFocusPatchRequestV6,
    network_element_type: str = _network_element_type_path(),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiTeamFocusPatchResponseV6:
    try:
        return kpi_team_focus.patch_team_focus(
            network_element_type,
            body,
            actor=_auth,
        )
    except kpi_team_focus.KpiTeamFocusError as exc:
        _raise_team_focus_error(exc)


# --- 测量单元与绑定 ---


@router.get(
    "/measurement-units",
    response_model=schemas.KpiMeasurementUnitPageV6,
    operation_id="listKpiMeasurementUnitsV6",
)
def list_kpi_measurement_units_v6(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    network_element_type: str = Query(
        ...,
        min_length=1,
        max_length=32,
        pattern=_NETWORK_ELEMENT_TYPE_PATTERN,
    ),
    search: str | None = Query(default=None, max_length=256),
    inspection_enabled: bool | None = Query(default=None),
    configuration_state: schemas.KpiConfigurationState | None = Query(default=None),
    recovery_state: schemas.KpiRecoveryState | None = Query(default=None),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiMeasurementUnitPageV6:
    try:
        return kpi_measurement_scope.list_measurement_units(
            network_element_type,
            page=page,
            page_size=page_size,
            search=search,
            inspection_enabled=inspection_enabled,
            configuration_state=configuration_state,
            recovery_state=recovery_state,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


@router.get(
    "/measurement-units/{network_element_type}/{measurement_unit_id}",
    response_model=schemas.KpiMeasurementUnitV6,
    operation_id="getKpiMeasurementUnitV6",
)
def get_kpi_measurement_unit_v6(
    network_element_type: str = _network_element_type_path(),
    measurement_unit_id: str = PathParam(..., min_length=1),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiMeasurementUnitV6:
    try:
        return kpi_measurement_scope.get_measurement_unit(
            network_element_type,
            measurement_unit_id,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


@router.patch(
    "/measurement-units/{network_element_type}/{measurement_unit_id}",
    response_model=schemas.KpiMeasurementUnitV6,
    operation_id="setKpiMeasurementInspectionEnabledV6",
)
def set_kpi_measurement_inspection_enabled_v6(
    body: schemas.KpiMeasurementInspectionPatchV6,
    network_element_type: str = _network_element_type_path(),
    measurement_unit_id: str = PathParam(..., min_length=1),
    _auth: AuthSession = Depends(require_role("admin")),
) -> schemas.KpiMeasurementUnitV6:
    try:
        return kpi_measurement_scope.set_measurement_inspection_enabled(
            network_element_type,
            measurement_unit_id,
            body,
            actor=_auth,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


@router.get(
    "/measurement-bindings",
    response_model=schemas.KpiMeasurementBindingPageV6,
    operation_id="listKpiMeasurementBindingsV6",
)
def list_kpi_measurement_bindings_v6(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    network_element_type: str = Query(
        ...,
        min_length=1,
        max_length=32,
        pattern=_NETWORK_ELEMENT_TYPE_PATTERN,
    ),
    measurement_unit_id: str | None = Query(default=None),
    status: schemas.KpiBindingState | None = Query(default=None),
    search: str | None = Query(default=None, max_length=256),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiMeasurementBindingPageV6:
    try:
        return kpi_measurement_scope.list_measurement_bindings(
            network_element_type,
            page=page,
            page_size=page_size,
            measurement_unit_id=measurement_unit_id,
            status=status,
            search=search,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


@router.patch(
    "/measurement-bindings/{network_element_type}/{binding_id}",
    response_model=schemas.KpiMeasurementBindingV6,
    operation_id="correctKpiMeasurementBindingV6",
)
def correct_kpi_measurement_binding_v6(
    body: schemas.KpiMeasurementBindingPatchV6,
    network_element_type: str = _network_element_type_path(),
    binding_id: int = PathParam(..., ge=1),
    _auth: AuthSession = Depends(require_role("admin")),
) -> schemas.KpiMeasurementBindingV6:
    try:
        return kpi_measurement_scope.correct_measurement_binding(
            network_element_type,
            binding_id,
            body,
            actor=_auth,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


# --- 历史恢复与待归属 ---


@router.get(
    "/legacy-recovery-audits",
    response_model=schemas.KpiLegacyRecoveryAuditPageV6,
    operation_id="listKpiLegacyRecoveryAuditsV6",
)
def list_kpi_legacy_recovery_audits_v6(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    network_element_type: str | None = Query(
        default=None,
        min_length=1,
        max_length=32,
        pattern=_NETWORK_ELEMENT_TYPE_PATTERN,
    ),
    result: schemas.KpiRecoveryResult | None = Query(default=None),
    object_kind: schemas.KpiRecoveryObjectKind | None = Query(default=None),
    measurement_unit_id: str | None = Query(default=None),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiLegacyRecoveryAuditPageV6:
    try:
        return kpi_measurement_scope.list_legacy_recovery_audits(
            page=page,
            page_size=page_size,
            network_element_type=network_element_type,
            result=result,
            object_kind=object_kind,
            measurement_unit_id=measurement_unit_id,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


@router.post(
    "/legacy-recovery-audits/retry",
    response_model=schemas.KpiMaintenanceOperationAcceptedV6,
    status_code=202,
    operation_id="retryKpiLegacyRecoveryV6",
)
def retry_kpi_legacy_recovery_v6(
    body: schemas.KpiLegacyRecoveryRetryRequestV6,
    response: Response,
    _auth: AuthSession = Depends(require_role("admin")),
) -> schemas.KpiMaintenanceOperationAcceptedV6:
    try:
        accepted = kpi_measurement_scope.retry_legacy_recovery(body, actor=_auth)
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)
    response.headers["Location"] = f"/api/v6/kpi/maintenance-operations/{accepted.operation_id}"
    return accepted


@router.get(
    "/pending-attributions",
    response_model=schemas.KpiPendingAttributionPageV6,
    operation_id="listKpiPendingAttributionsV6",
)
def list_kpi_pending_attributions_v6(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    resolution_state: schemas.KpiPendingResolutionState | None = Query(default=None),
    reason: schemas.KpiPendingReason | None = Query(default=None),
    source_table: str | None = Query(default=None),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiPendingAttributionPageV6:
    try:
        return kpi_measurement_scope.list_pending_attributions(
            page=page,
            page_size=page_size,
            resolution_state=resolution_state,
            reason=reason,
            source_table=source_table,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


@router.post(
    "/pending-attributions/{pending_id}/resolve",
    response_model=schemas.KpiMaintenanceOperationAcceptedV6,
    status_code=202,
    operation_id="resolveKpiPendingAttributionV6",
)
def resolve_kpi_pending_attribution_v6(
    body: schemas.KpiPendingAttributionResolveRequestV6,
    response: Response,
    pending_id: int = PathParam(..., ge=1),
    _auth: AuthSession = Depends(require_role("admin")),
) -> schemas.KpiMaintenanceOperationAcceptedV6:
    try:
        accepted = kpi_measurement_scope.resolve_pending_attribution(
            pending_id,
            body,
            actor=_auth,
        )
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)
    response.headers["Location"] = f"/api/v6/kpi/maintenance-operations/{accepted.operation_id}"
    return accepted


@router.get(
    "/maintenance-operations/{operation_id}",
    response_model=schemas.KpiMaintenanceOperationV6,
    operation_id="getKpiMaintenanceOperationV6",
)
def get_kpi_maintenance_operation_v6(
    operation_id: str = PathParam(..., min_length=1),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiMaintenanceOperationV6:
    try:
        return kpi_measurement_scope.get_maintenance_operation(operation_id)
    except kpi_measurement_scope.KpiMeasurementScopeError as exc:
        _raise_measurement_scope_error(exc)


# --- 规则网元归属 ---


@router.get(
    "/rule-network-assignments",
    response_model=schemas.KpiRuleNetworkAssignmentPageV6,
    operation_id="listKpiRuleNetworkAssignmentsV6",
)
def list_kpi_rule_network_assignments_v6(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    network_element_type: str | None = Query(
        default=None,
        min_length=1,
        max_length=32,
        pattern=_NETWORK_ELEMENT_TYPE_PATTERN,
    ),
    assignment_state: schemas.KpiRuleAssignmentState | None = Query(default=None),
    search: str | None = Query(default=None, max_length=256),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiRuleNetworkAssignmentPageV6:
    try:
        return rule_network_assignments.list_rule_assignments(
            page=page,
            page_size=page_size,
            network_element_type=network_element_type,
            assignment_state=assignment_state,
            search=search,
            actor=_auth,
        )
    except rule_network_assignments.RuleAssignmentError as exc:
        _raise_rule_assignment_error(exc)


@router.post(
    "/rule-network-assignments/batch",
    response_model=schemas.KpiRuleAssignmentBatchResponseV6,
    operation_id="batchUpdateKpiRuleNetworkAssignmentsV6",
)
def batch_update_kpi_rule_network_assignments_v6(
    body: schemas.KpiRuleAssignmentBatchRequestV6,
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiRuleAssignmentBatchResponseV6:
    try:
        return rule_network_assignments.batch_update_rule_assignments(
            body,
            actor=_auth,
        )
    except rule_network_assignments.RuleAssignmentError as exc:
        _raise_rule_assignment_error(exc)


@router.get(
    "/rule-network-assignments/audits",
    response_model=schemas.KpiRuleAssignmentAuditPageV6,
    operation_id="listKpiRuleNetworkAssignmentAuditsV6",
)
def list_kpi_rule_network_assignment_audits_v6(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    rule_code: str | None = Query(default=None, min_length=1, max_length=128),
    network_element_type: str | None = Query(
        default=None,
        min_length=1,
        max_length=32,
        pattern=_NETWORK_ELEMENT_TYPE_PATTERN,
    ),
    result: schemas.KpiRuleAssignmentAuditResult | None = Query(default=None),
    source: schemas.KpiRuleAssignmentAuditSource | None = Query(default=None),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiRuleAssignmentAuditPageV6:
    try:
        return rule_network_assignments.list_rule_assignment_audits(
            page=page,
            page_size=page_size,
            rule_code=rule_code,
            network_element_type=network_element_type,
            result=result,
            source=source,
        )
    except rule_network_assignments.RuleAssignmentError as exc:
        _raise_rule_assignment_error(exc)


@router.patch(
    "/rule-network-assignments/{rule_code}",
    response_model=schemas.KpiRuleAssignmentWriteResultV6,
    operation_id="updateKpiRuleNetworkAssignmentV6",
)
def update_kpi_rule_network_assignment_v6(
    body: schemas.KpiRuleAssignmentPatchRequestV6,
    rule_code: str = PathParam(..., min_length=1, max_length=128, pattern=_RULE_CODE_PATTERN),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiRuleAssignmentWriteResultV6:
    try:
        return rule_network_assignments.update_rule_assignment(
            rule_code,
            body,
            actor=_auth,
        )
    except rule_network_assignments.RuleAssignmentError as exc:
        _raise_rule_assignment_error(exc)


# --- 任务结果工作台 ---


@router.get(
    "/tasks/{task_id}/summary",
    response_model=schemas.KpiTaskSummaryV6,
    operation_id="getKpiTaskSummaryV6",
)
def get_kpi_task_summary_v6(
    task_id: str = PathParam(..., min_length=1),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiTaskSummaryV6:
    try:
        return kpi_workbench.get_kpi_task_summary(task_id)
    except kpi_workbench.KpiWorkbenchError as exc:
        raise AppError(
            exc.code,
            exc.message,
            exc.status_code,
            exc.detail,
        ) from exc


@router.get(
    "/tasks/{task_id}/metrics",
    response_model=schemas.KpiMetricResultPageV6,
    operation_id="listKpiTaskMetricsV6",
)
def list_kpi_task_metrics_v6(
    task_id: str = PathParam(..., min_length=1),
    view: schemas.KpiResultView = Query(default=schemas.KpiResultView.NEEDS_ATTENTION),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(default=None, max_length=256),
    measurement_unit_id: str | None = Query(default=None),
    current_status: schemas.CurrentHealthStatus | None = Query(default=None),
    yesterday_trend: schemas.TrendHealthStatus | None = Query(default=None),
    needs_attention_group: schemas.NeedsAttentionGroup | None = Query(default=None),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiMetricResultPageV6:
    try:
        return kpi_workbench.list_kpi_task_metrics(
            task_id,
            view=view,
            page=page,
            page_size=page_size,
            search=search,
            measurement_unit_id=measurement_unit_id,
            current_status=current_status,
            yesterday_trend=yesterday_trend,
            needs_attention_group=needs_attention_group,
        )
    except kpi_workbench.KpiWorkbenchError as exc:
        raise AppError(
            exc.code,
            exc.message,
            exc.status_code,
            exc.detail,
        ) from exc


@router.get(
    "/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/evidence",
    response_model=schemas.KpiMetricEvidenceV6,
    operation_id="getKpiMetricEvidenceV6",
)
def get_kpi_metric_evidence_v6(
    task_id: str = PathParam(..., min_length=1),
    measurement_unit_id: str = PathParam(..., min_length=1),
    metric_resource_id: str = PathParam(..., min_length=1),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiMetricEvidenceV6:
    try:
        return kpi_workbench.get_kpi_metric_evidence(
            task_id,
            measurement_unit_id,
            metric_resource_id,
        )
    except kpi_workbench.KpiWorkbenchError as exc:
        raise AppError(
            exc.code,
            exc.message,
            exc.status_code,
            exc.detail,
        ) from exc


@router.get(
    "/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/technical-analysis",
    response_model=schemas.KpiTechnicalAnalysisV6,
    operation_id="getKpiMetricTechnicalAnalysisV6",
)
def get_kpi_metric_technical_analysis_v6(
    task_id: str = PathParam(..., min_length=1),
    measurement_unit_id: str = PathParam(..., min_length=1),
    metric_resource_id: str = PathParam(..., min_length=1),
    history_days: int = Query(90, ge=1, le=365),
    version_limit: int = Query(10, ge=1, le=50),
    _auth: AuthSession = Depends(get_current_user),
) -> schemas.KpiTechnicalAnalysisV6:
    try:
        return kpi_workbench.get_kpi_metric_technical_analysis(
            task_id,
            measurement_unit_id,
            metric_resource_id,
            history_days=history_days,
            version_limit=version_limit,
        )
    except kpi_workbench.KpiWorkbenchError as exc:
        raise AppError(
            exc.code,
            exc.message,
            exc.status_code,
            exc.detail,
        ) from exc
