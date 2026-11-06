"""KPI 结果工作台 v6 请求与响应契约。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _network_element_type(value: str) -> str:
    """拒绝契约明令禁止的伪公共作用域。"""
    if value in {"*", "COMMON", "PUBLIC"}:
        raise ValueError("network_element_type 不得使用公共作用域")
    return value


NetworkElementType: TypeAlias = Annotated[
    str,
    Field(min_length=1, max_length=32, pattern=r"^[A-Z][A-Z0-9_]*$"),
    AfterValidator(_network_element_type),
]
NumberOrNull: TypeAlias = int | float | None


def _unique_network_element_types(values: list[NetworkElementType]) -> list[NetworkElementType]:
    if len(values) != len(set(values)):
        raise ValueError("network_element_types 不得重复")
    return values


KpiRuleNetworkElementTypes: TypeAlias = Annotated[
    list[NetworkElementType],
    Field(max_length=16),
    AfterValidator(_unique_network_element_types),
]


class StrictRequest(BaseModel):
    """请求模型与 OpenAPI additionalProperties=false 对齐。"""

    model_config = ConfigDict(extra="forbid")


class FocusAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class FocusAvailabilityReason(StrEnum):
    NOT_IN_TASK_SCOPE = "not_in_task_scope"
    MEASUREMENT_UNIT_DISABLED = "measurement_unit_disabled"


class KpiConfigurationState(StrEnum):
    READY = "ready"
    INCOMPLETE = "incomplete"


class KpiRecoveryState(StrEnum):
    NONE = "none"
    PENDING = "pending"
    PARTIAL_FAILURE = "partial_failure"
    COMPLETED = "completed"


class KpiBindingState(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    IGNORED = "ignored"


class KpiRecoveryResult(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RECOVERED = "recovered"
    FAILED = "failed"
    SKIPPED = "skipped"


class KpiRecoveryObjectKind(StrEnum):
    METRIC = "metric"
    BINDING = "binding"
    DERIVED = "derived"


class KpiRecoverySource(StrEnum):
    MIGRATION = "migration"
    UI = "ui"
    API = "api"


class KpiPendingResolutionState(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    MATERIALIZED = "materialized"
    FAILED = "failed"


class KpiPendingReason(StrEnum):
    MISSING_PRODUCT = "missing_product"
    AMBIGUOUS_PRODUCT = "ambiguous_product"
    ORPHAN_REFERENCE = "orphan_reference"


class KpiRuleAssignmentState(StrEnum):
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


class KpiRuleAssignmentAuditResult(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class KpiRuleAssignmentAuditSource(StrEnum):
    UI = "ui"
    API = "api"
    MIGRATION = "migration"


class KpiResultView(StrEnum):
    NEEDS_ATTENTION = "needs_attention"
    TEAM_FOCUS = "team_focus"
    ALL = "all"


class NeedsAttentionGroup(StrEnum):
    FAILURE = "failure"
    WARNING = "warning"
    TREND_DEGRADED = "trend_degraded"
    UNJUDGEABLE = "unjudgeable"
    NEEDS_CONFIG = "needs_config"


class CurrentHealthStatus(StrEnum):
    NORMAL = "normal"
    WARN = "warn"
    FAIL = "fail"
    PENDING_CONFIG = "pending_config"
    UNABLE_TO_JUDGE = "unable_to_judge"
    NOT_APPLICABLE = "not_applicable"


class TrendHealthStatus(StrEnum):
    IMPROVED = "improved"
    STABLE = "stable"
    WORSENED = "worsened"
    OBSERVE = "observe"
    NO_BASELINE = "no_baseline"


class MetricRole(StrEnum):
    BASE = "base"
    DERIVED = "derived"


class MetricAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class MetricSpecialState(StrEnum):
    NO_ACTION = "no_action"
    NOT_APPLICABLE = "not_applicable"
    NO_BASELINE = "no_baseline"
    ALL_ZERO = "all_zero"
    ZERO_DENOMINATOR = "zero_denominator"
    NO_DATA = "no_data"
    UNAVAILABLE = "unavailable"


class Importance(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    NORMAL = "normal"


class KpiFocusIdentity(BaseModel):
    measurement_unit_id: str = Field(min_length=1)
    metric_resource_id: str = Field(min_length=1)


class KpiTeamFocusItemV6(BaseModel):
    network_element_type: str
    measurement_unit_id: str
    measurement_unit_name: str
    metric_resource_id: str
    metric_name: str
    availability: FocusAvailability
    availability_reason: FocusAvailabilityReason | None = None
    added_by: str
    added_at: str


class KpiTeamFocusPageV6(BaseModel):
    network_element_type: str
    revision: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total: int = Field(ge=0)
    available_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    items: list[KpiTeamFocusItemV6]
    can_write: bool


class KpiTeamFocusPatchRequestV6(StrictRequest):
    task_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    add: list[KpiFocusIdentity] = Field(max_length=500)
    remove: list[KpiFocusIdentity] = Field(max_length=500)

    @model_validator(mode="after")
    def validate_atomic_difference(self) -> KpiTeamFocusPatchRequestV6:
        add_keys = [(item.measurement_unit_id, item.metric_resource_id) for item in self.add]
        remove_keys = [(item.measurement_unit_id, item.metric_resource_id) for item in self.remove]
        if not add_keys and not remove_keys:
            raise ValueError("add/remove 至少一个非空")
        if len(add_keys) != len(set(add_keys)) or len(remove_keys) != len(set(remove_keys)):
            raise ValueError("add/remove 数组内身份必须唯一")
        if set(add_keys) & set(remove_keys):
            raise ValueError("同一身份不能同时加入和移出")
        return self


class KpiTeamFocusPatchResponseV6(BaseModel):
    network_element_type: str
    revision: int = Field(ge=1)
    added_count: int = Field(ge=0)
    removed_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)


class KpiMeasurementUnitV6(BaseModel):
    network_element_type: str
    measurement_unit_id: str
    name_zh: str
    name_en: str
    inspection_enabled: bool
    revision: int = Field(ge=0)
    base_metric_count: int = Field(ge=0)
    derived_metric_count: int = Field(ge=0)
    confirmed_binding_count: int = Field(ge=0)
    candidate_binding_count: int = Field(ge=0)
    configuration_state: KpiConfigurationState
    recovery_state: KpiRecoveryState
    source: Literal["preset", "discovered", "manual"] | None = None
    updated_at: str
    notice: str | None = None


class KpiMeasurementUnitPageV6(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    items: list[KpiMeasurementUnitV6]


class KpiMeasurementInspectionPatchV6(StrictRequest):
    expected_revision: int = Field(ge=0)
    inspection_enabled: bool


class KpiMeasurementBindingV6(BaseModel):
    id: int = Field(ge=1)
    network_element_type: str
    measurement_unit_id: str
    measurement_unit_name: str | None = None
    raw_source_name: str
    base_source_name: str
    metric_resource_id: str | None = None
    metric_resource_name: str | None = None
    display_unit: str | None = None
    status: KpiBindingState
    source_file: str
    origin_task_id: str
    revision: int = Field(ge=0)
    updated_at: str
    diagnostic: str | None = None


class KpiMeasurementBindingPageV6(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    items: list[KpiMeasurementBindingV6]


class KpiMeasurementBindingPatchV6(StrictRequest):
    expected_revision: int = Field(ge=0)
    status: Literal["confirmed", "ignored"]
    reason: str = Field(min_length=1, max_length=512)


class KpiLegacyRecoveryAuditV6(BaseModel):
    audit_id: int = Field(ge=1)
    source_table: str
    source_record_id: str
    source_key: str
    network_element_type: str | None = None
    measurement_unit_id: str | None = None
    metric_resource_id: str | None = None
    object_kind: KpiRecoveryObjectKind
    before_snapshot: dict[str, Any]
    result: KpiRecoveryResult
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = Field(ge=0)
    actor: str | None = None
    source: KpiRecoverySource
    created_at: str
    updated_at: str


class KpiLegacyRecoveryAuditPageV6(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    items: list[KpiLegacyRecoveryAuditV6]


class KpiLegacyRecoveryRetryRequestV6(StrictRequest):
    audit_ids: list[int] = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_unique_audits(self) -> KpiLegacyRecoveryRetryRequestV6:
        if any(audit_id < 1 for audit_id in self.audit_ids):
            raise ValueError("audit_ids 必须为正整数")
        if len(self.audit_ids) != len(set(self.audit_ids)):
            raise ValueError("audit_ids 不得重复")
        return self


class KpiPendingAttributionV6(BaseModel):
    pending_id: int = Field(ge=1)
    source_table: str
    source_record_id: str
    source_key: str
    source_payload: dict[str, Any]
    candidate_network_element_types: list[str]
    reason: KpiPendingReason
    resolution_state: KpiPendingResolutionState
    assigned_network_element_type: str | None = None
    attempt_count: int = Field(ge=0)
    last_error: str | None = None
    idempotency_key: str
    created_at: str
    updated_at: str


class KpiPendingAttributionPageV6(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    items: list[KpiPendingAttributionV6]


class KpiPendingAttributionResolveRequestV6(StrictRequest):
    network_element_type: NetworkElementType
    idempotency_key: str = Field(min_length=8, max_length=128)


class KpiMaintenanceOperationAcceptedV6(BaseModel):
    operation_id: str
    status: Literal["queued", "running"]


class KpiMaintenanceOperationItemV6(BaseModel):
    target_id: str
    result: Literal["pending", "running", "succeeded", "failed", "skipped"]
    error_code: str | None = None
    error_message: str | None = None


class KpiMaintenanceOperationV6(BaseModel):
    operation_id: str
    operation_type: Literal["legacy_recovery_retry", "pending_attribution_resolve"]
    status: Literal["queued", "running", "succeeded", "partial_success", "failed"]
    idempotency_key: str
    total_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    items: list[KpiMaintenanceOperationItemV6]
    created_at: str
    completed_at: str | None = None


class KpiRuleNetworkAssignmentV6(BaseModel):
    rule_code: str
    name: str
    category: str
    priority: int = Field(ge=1)
    rule_version: str
    description: str
    recommendation: str
    assignment_state: KpiRuleAssignmentState
    network_element_types: KpiRuleNetworkElementTypes
    revision: int = Field(ge=0)
    updated_at: str | None = None
    updated_by: str | None = None


class KpiRuleNetworkAssignmentPageV6(BaseModel):
    global_revision: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total: int = Field(ge=0)
    can_write: bool
    items: list[KpiRuleNetworkAssignmentV6]


class KpiRuleAssignmentPatchRequestV6(StrictRequest):
    expected_revision: int = Field(ge=0)
    network_element_types: KpiRuleNetworkElementTypes
    confirm_unassign: bool = False

    @model_validator(mode="after")
    def validate_empty_assignment(self) -> KpiRuleAssignmentPatchRequestV6:
        if not self.network_element_types and not self.confirm_unassign:
            raise ValueError("清空最后归属必须显式确认")
        return self


class KpiRuleAssignmentWriteResultV6(BaseModel):
    rule_code: str
    assignment_state: KpiRuleAssignmentState
    network_element_types: KpiRuleNetworkElementTypes
    revision: int = Field(ge=1)
    global_revision: int = Field(ge=1)
    audit_id: str
    updated_at: str
    snapshot_notice: str | None = None


class KpiRuleAssignmentBatchItemV6(StrictRequest):
    rule_code: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    expected_revision: int = Field(ge=0)
    network_element_types: KpiRuleNetworkElementTypes
    confirm_unassign: bool = False

    @model_validator(mode="after")
    def validate_empty_assignment(self) -> KpiRuleAssignmentBatchItemV6:
        if not self.network_element_types and not self.confirm_unassign:
            raise ValueError("清空最后归属必须显式确认")
        return self


class KpiRuleAssignmentBatchRequestV6(StrictRequest):
    items: list[KpiRuleAssignmentBatchItemV6] = Field(min_length=1, max_length=200)


class KpiRuleAssignmentBatchResponseV6(BaseModel):
    global_revision: int = Field(ge=1)
    items: list[KpiRuleAssignmentWriteResultV6]
    audit_ids: list[str]


class KpiRuleAssignmentAuditV6(BaseModel):
    audit_id: str
    rule_code: str
    before_network_element_types: list[str]
    after_network_element_types: list[str]
    rule_revision: int = Field(ge=0)
    global_revision: int = Field(ge=0)
    actor: str
    source: KpiRuleAssignmentAuditSource
    result: KpiRuleAssignmentAuditResult
    error_code: str | None = None
    idempotency_key: str | None = None
    created_at: str


class KpiRuleAssignmentAuditPageV6(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    items: list[KpiRuleAssignmentAuditV6]


class KpiRuleScopeStatusV6(BaseModel):
    business_rule_count: int = Field(ge=0)
    has_executable_rules: bool
    notice: str | None = None


class KpiSummaryCountsV6(BaseModel):
    enabled_measurement_unit_count: int = Field(ge=0)
    all_metric_count: int = Field(ge=0)
    team_focus_count: int = Field(ge=0)
    needs_attention_count: int = Field(ge=0)
    no_action_count: int = Field(ge=0)
    unavailable_focus_count: int = Field(ge=0)


class KpiNeedsAttentionGroupSummary(BaseModel):
    group: NeedsAttentionGroup
    order: int
    count: int = Field(ge=0)


class KpiTaskSummaryV6(BaseModel):
    task_id: str
    network_element_type: str | None
    result_contract_version: Literal["v6"]
    data_date: str | None
    previous_date: str | None
    latest_measured_at: str | None
    counts: KpiSummaryCountsV6
    needs_attention_groups: list[KpiNeedsAttentionGroupSummary]
    rule_scope: KpiRuleScopeStatusV6
    notices: list[str] = Field(default_factory=list)


class KpiMetricResultV6(BaseModel):
    task_id: str
    network_element_type: str
    measurement_unit_id: str
    measurement_unit_name: str
    metric_resource_id: str
    metric_name: str
    role: MetricRole
    importance: Importance
    importance_rank: int = Field(ge=0)
    availability: MetricAvailability
    availability_reason: Literal["not_in_task_scope", "measurement_unit_disabled"] | None = None
    is_team_focus: bool
    current_status: CurrentHealthStatus | None = None
    yesterday_trend: TrendHealthStatus | None = None
    needs_attention_group: NeedsAttentionGroup | None = None
    special_state: MetricSpecialState | None = None
    today_value: NumberOrNull = None
    yesterday_value: NumberOrNull = None
    change_value: NumberOrNull = None
    change_unit: Literal["pp", "relative", "absolute", "unavailable"] | None = None
    reason: str | None = None
    evidence_available: bool | None = None


class KpiAppliedFiltersV6(BaseModel):
    search: str | None = None
    measurement_unit_id: str | None = None
    current_status: CurrentHealthStatus | None = None
    yesterday_trend: TrendHealthStatus | None = None
    needs_attention_group: NeedsAttentionGroup | None = None


class KpiMetricResultPageV6(BaseModel):
    items: list[KpiMetricResultV6]
    total: int = Field(ge=0)
    view_total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    empty_state: Literal[
        "none",
        "no_task_metrics",
        "team_focus_empty",
        "no_matching_metrics",
    ]
    applied_filters: KpiAppliedFiltersV6


class KpiThresholdEvidenceV6(BaseModel):
    direction: Literal["higher_better", "lower_better", "neutral"]
    warning_threshold: NumberOrNull
    critical_threshold: NumberOrNull
    source: Literal["custom", "default", "legacy_resource", "missing"]


class KpiDailyBucketV6(BaseModel):
    date: date
    value: NumberOrNull = None
    numerator: NumberOrNull = None
    denominator: NumberOrNull = None
    valid_count: int = Field(ge=0)
    first_measured_at: str | None = None
    last_measured_at: str | None = None
    status: Literal["ok", "no_data", "zero_denominator", "unreadable", "no_baseline"]


class KpiEvidenceComponentV6(BaseModel):
    metric_resource_id: str
    name: str
    role: Literal["numerator", "denominator"]
    value: NumberOrNull = None


class KpiEvidenceGroupV6(BaseModel):
    object_key: str
    period_minutes: int | None = Field(ge=1)
    today: KpiDailyBucketV6 | None = None
    yesterday: KpiDailyBucketV6 | None = None
    current_status: CurrentHealthStatus
    trend_status: TrendHealthStatus
    reason: str | None = None
    source_files: list[str]


class KpiMetricEvidenceMetricV6(BaseModel):
    name: str
    role: MetricRole
    is_percentage: bool
    formula: str | None = None
    daily_aggregation: Literal["latest", "mean", "sum", "max", "min"]
    current_status: CurrentHealthStatus
    trend_status: TrendHealthStatus


class KpiMetricChangeThresholdV6(BaseModel):
    value: NumberOrNull = None
    unit: Literal["pp", "relative", "unavailable"] | None = None
    source: Literal["custom", "default", "legacy_resource", "missing"] | None = None


class KpiMetricSourceV6(BaseModel):
    file: str
    record_group: str | None = None
    raw_source_names: list[str]


class KpiMetricConfigSnapshotV6(BaseModel):
    config_revision: int | None = Field(default=None, ge=0)
    config_fingerprint: str | None = None


class KpiMetricEvidenceV6(BaseModel):
    task_id: str
    network_element_type: str
    measurement_unit_id: str
    metric_resource_id: str
    metric: KpiMetricEvidenceMetricV6
    current: KpiDailyBucketV6
    previous: KpiDailyBucketV6 | None
    change_value: NumberOrNull = None
    change_unit: Literal["pp", "relative", "absolute", "unavailable"] | None = None
    reason: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    valid_count: int | None = Field(default=None, ge=0)
    current_threshold: KpiThresholdEvidenceV6
    change_threshold: KpiMetricChangeThresholdV6 | None = None
    components: list[KpiEvidenceComponentV6] = Field(default_factory=list)
    groups: list[KpiEvidenceGroupV6]
    seven_day_trend: list[KpiDailyBucketV6] = Field(max_length=7)
    sources: list[KpiMetricSourceV6]
    config_snapshot: KpiMetricConfigSnapshotV6 | None = None

    @model_validator(mode="after")
    def keep_base_metrics_uncomputed(self) -> KpiMetricEvidenceV6:
        # 来源成功率属于 base 指标；PatrolX 不得为其生成公式或分子分母。
        if self.metric.role == MetricRole.BASE:
            self.metric.formula = None
            self.current.numerator = None
            self.current.denominator = None
            if self.previous is not None:
                self.previous.numerator = None
                self.previous.denominator = None
            for group in self.groups:
                for bucket in (group.today, group.yesterday):
                    if bucket is not None:
                        bucket.numerator = None
                        bucket.denominator = None
            for bucket in self.seven_day_trend:
                bucket.numerator = None
                bucket.denominator = None
            self.components = []
        return self


class KpiHistoryPointV6(BaseModel):
    task_id: str
    data_date: date
    value: NumberOrNull
    status: Literal[
        "ok",
        "no_data",
        "zero_denominator",
        "unreadable",
        "no_baseline",
        "pending_config",
    ]


class KpiVersionComparisonV6(BaseModel):
    task_id: str
    device_id: str
    version: str
    data_date: date
    current_value: NumberOrNull
    comparison_value: NumberOrNull
    change_value: NumberOrNull = None


class KpiTechnicalAnalysisV6(BaseModel):
    task_id: str
    measurement_unit_id: str
    metric_resource_id: str
    generated_at: str
    cross_task_history: list[KpiHistoryPointV6]
    version_comparisons: list[KpiVersionComparisonV6]
