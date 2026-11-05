"""Pydantic v2 契约模型，字段与 docs/api/openapi.yaml 严格对齐。"""

from datetime import date, datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RuleStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Priority(IntEnum):
    P0 = 0
    P1 = 1
    P2 = 2


class RuleCategory(StrEnum):
    LOG = "log"
    KPI = "kpi"
    TRAFFIC = "traffic"
    ALARM = "alarm"
    CONFIG = "config"
    RESOURCE = "resource"
    OTHER = "other"


class TaskMode(StrEnum):
    ONLINE = "online"
    LOCAL = "local"


class SystemStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class TaskTrigger(StrEnum):
    API = "api"
    CLI = "cli"
    RERUN = "rerun"


class RebuildMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class RebuildTriggerSource(StrEnum):
    UI = "ui"
    API = "api"


class MeasurementHistoryMatchStatus(StrEnum):
    MATCHED = "matched"
    DEGRADED = "degraded"
    NO_HISTORY = "no_history"


class MeasurementBaselineSignificance(StrEnum):
    INSUFFICIENT = "insufficient"
    NORMAL = "normal"
    HIGHER = "higher"
    LOWER = "lower"


class PreparationStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


class PreparationIssueType(StrEnum):
    CONFLICT = "conflict"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
    FAILED = "failed"
    REJECTED = "rejected"


class Summary(BaseModel):
    total: int = Field(ge=0)
    pass_: int = Field(ge=0, alias="pass")
    warn: int = Field(ge=0)
    fail: int = Field(ge=0)
    error: int = Field(ge=0)
    skip: int = Field(ge=0)

    model_config = {"populate_by_name": True}


class TaskStats(Summary):
    systems: int = Field(ge=0, default=1)


class Metric(BaseModel):
    key: str
    label: str
    value: int | float | str
    unit: str | None = None
    threshold: dict[str, int | float] | None = None
    baseline: int | float | str | None = None
    series: list[dict[str, Any]] | None = None


class Finding(BaseModel):
    finding_id: str
    title: str
    severity: Severity
    source_file: str | None = None
    evidence: str | None = None

    @model_validator(mode="after")
    def require_traceability(self) -> "Finding":
        if not self.source_file or not self.source_file.strip():
            raise ValueError("finding.source_file 不能为空")
        if not self.evidence or not self.evidence.strip():
            raise ValueError("finding.evidence 不能为空")
        return self

    details: str | None = None
    recommendation: str | None = None
    metrics: list[Metric] | None = None


class RuleResult(BaseModel):
    code: str
    name: str
    category: RuleCategory
    priority: Priority
    execution_order: int
    status: RuleStatus
    severity: Severity
    summary: str | None = None
    skip_reason: str | None = None
    executed_at: datetime | None = None
    duration_ms: int | None = None
    metrics: list[Metric] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_skip_reason(self) -> "RuleResult":
        if self.status == RuleStatus.SKIP and (not self.skip_reason or not self.skip_reason.strip()):
            raise ValueError("status=skip 时 skip_reason 不能为空")
        return self


class MeasurementMetricDetail(BaseModel):
    """KPI 单指标完整明细。"""

    task_id: str
    rule_code: str
    measurement_unit_id: str
    metric: dict[str, Any]


class SystemInspection(BaseModel):
    package_file: str
    package_checksum: str | None = None
    version: str | None = None
    status: SystemStatus
    summary: Summary
    rules: list[RuleResult] = Field(default_factory=list)
    customer: dict[str, str] = Field(default_factory=dict)


class PreparationIssue(BaseModel):
    type: PreparationIssueType
    source: str | None = None
    target: str | None = None
    reason: str
    path_length: int | None = Field(default=None, ge=0)
    path_limit: int | None = Field(default=None, ge=0)


class PreparationItem(BaseModel):
    code: str
    name: str
    category: str
    status: PreparationStatus
    summary: str
    duration_ms: int | None = Field(default=None, ge=0)
    extracted_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    issues: list[PreparationIssue] = Field(default_factory=list)


class DataPreparation(BaseModel):
    status: PreparationStatus
    items: list[PreparationItem] = Field(min_length=1)
    total: int = Field(ge=0)
    success_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    skip_count: int = Field(ge=0)


class InspectionTask(BaseModel):
    task_id: str
    name: str
    mode: TaskMode
    status: TaskStatus
    trigger: TaskTrigger
    created_at: datetime
    completed_at: datetime | None = None
    last_run_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    stats: TaskStats
    preparation: DataPreparation | None = None
    system: SystemInspection | None = None
    package_kind: "PackageKind | None" = None
    inventory: "TaskInventory | None" = None

    @model_validator(mode="after")
    def validate_summary(self) -> "InspectionTask":
        if self.system is None:
            return self
        rules = self.system.rules
        if self.stats.total != len(rules) or self.system.summary.total != len(rules):
            raise ValueError("任务 summary 与规则数量不一致")
        counted = self.stats.pass_ + self.stats.warn + self.stats.fail + self.stats.error + self.stats.skip
        if counted != self.stats.total:
            raise ValueError("任务 summary 各状态计数之和必须等于总数")
        actual = {
            RuleStatus.PASS: self.stats.pass_,
            RuleStatus.WARN: self.stats.warn,
            RuleStatus.FAIL: self.stats.fail,
            RuleStatus.ERROR: self.stats.error,
            RuleStatus.SKIP: self.stats.skip,
        }
        for status in RuleStatus:
            if sum(rule.status == status for rule in rules) != actual[status]:
                raise ValueError("任务 summary 与规则状态分布不一致")
        return self


class TaskSummary(InspectionTask):
    device_id: str | None = None
    customer_province: str | None = None
    customer_operator: str | None = None
    customer_product: str | None = None
    customer_version: str | None = None


class TaskDeviceIdUpdateRequest(BaseModel):
    """任务设备 ID 修改请求。"""

    device_id: str = Field(min_length=1, max_length=128)


class MeasurementHistoryWindow(BaseModel):
    end_date: str
    start_date: str
    days: int = Field(ge=1)
    anchor_measured_at: datetime


class MeasurementHistoryMatch(BaseModel):
    status: MeasurementHistoryMatchStatus
    reason_code: str | None = None
    message: str


class MeasurementHistoryCoverage(BaseModel):
    history_task_count: int = Field(ge=0)
    history_date_count: int = Field(ge=0)
    history_point_count: int = Field(ge=0)
    current_point_count: int = Field(ge=0)
    latest_history_date: str | None = None


class MeasurementHistoryPoint(BaseModel):
    measured_at: datetime
    date: str
    time_label: str
    value: float
    task_id: str
    source_file: str
    line_number: int | None = None


class MeasurementHistoryDateSeries(BaseModel):
    date: str
    source_task_ids: list[str]
    points: list[MeasurementHistoryPoint]


class MeasurementHistoryBaselinePoint(BaseModel):
    time_label: str
    baseline_value: float | None = None
    current_value: float | None = None
    deviation: float | None = None
    deviation_ratio: float | None = None
    sample_count: int = Field(ge=0)
    date_count: int = Field(ge=0)
    significance: MeasurementBaselineSignificance


class MeasurementVersionDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"
    UNKNOWN = "unknown"


class MeasurementVersionComparisonTask(BaseModel):
    """参与版本对比的单个任务来源。"""

    task_id: str
    completed_at: datetime | None = None
    version: str | None = None
    version_known: bool


class MeasurementVersionCandidateTask(MeasurementVersionComparisonTask):
    """同设备候选版本中的任务。"""


class MeasurementVersionCandidate(BaseModel):
    """同设备历史任务的版本分组。"""

    version: str | None = None
    version_known: bool
    latest_task_id: str
    latest_completed_at: datetime
    task_count: int = Field(ge=1)
    tasks: list[MeasurementVersionCandidateTask] = Field(min_length=1)


class MeasurementVersionCandidateList(BaseModel):
    """同设备版本候选响应。"""

    task_id: str
    rule_code: str
    measurement_unit_id: str
    metric_resource_id: str
    device_id: str | None = None
    current_version: str | None = None
    items: list[MeasurementVersionCandidate] = Field(default_factory=list)


class MeasurementVersionComparisonSummary(BaseModel):
    current_value: float | None = None
    baseline_value: float | None = None
    absolute_change: float | None = None
    change_ratio: float | None = None
    direction: MeasurementVersionDirection = MeasurementVersionDirection.UNKNOWN
    sample_count: int = Field(ge=0)
    message: str


class MeasurementVersionComparison(BaseModel):
    """同设备不同系统版本的单指标对比响应。"""

    task_id: str
    baseline_task_id: str
    rule_code: str
    measurement_unit_id: str
    metric_resource_id: str
    device_id: str | None = None
    object_key: str
    period_minutes: int | None = None
    current_version: str | None = None
    baseline_version: str | None = None
    current_task: MeasurementVersionComparisonTask
    baseline_task: MeasurementVersionComparisonTask | None = None
    current_points: list[MeasurementHistoryPoint] = Field(default_factory=list)
    baseline_points: list[MeasurementHistoryPoint] = Field(default_factory=list)
    summary: MeasurementVersionComparisonSummary
    match: MeasurementHistoryMatch


class MeasurementHistoryTrend(BaseModel):
    """KPI 单指标跨任务历史趋势响应。"""

    task_id: str
    rule_code: str
    measurement_unit_id: str
    metric_resource_id: str
    device_id: str | None = None
    object_key: str
    period_minutes: int | None = None
    window: MeasurementHistoryWindow
    match: MeasurementHistoryMatch
    coverage: MeasurementHistoryCoverage
    current_points: list[MeasurementHistoryPoint] = Field(default_factory=list)
    history_series: list[MeasurementHistoryDateSeries] = Field(default_factory=list)
    baseline_points: list[MeasurementHistoryBaselinePoint] = Field(default_factory=list)
    source_tasks: list[str] = Field(default_factory=list)


class TaskCreated(BaseModel):
    task_id: str


class TaskListResponse(BaseModel):
    items: list[TaskSummary]
    total: int
    page: int
    page_size: int


class InspectorState(BaseModel):
    """分页规则状态列表中的一条普通规则。"""

    code: str
    name: str
    category: RuleCategory
    priority: Priority
    enabled: bool
    updated_at: datetime


class InspectorStateListResponse(BaseModel):
    """规则启停状态分页契约；默认每页 10 条。"""

    items: list[InspectorState] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class RuleStateUpdateRequest(BaseModel):
    """规则启停状态更新请求。"""

    enabled: StrictBool


class OverviewSummary(BaseModel):
    task_count: int = Field(ge=0)
    registered_rule_count: int = Field(ge=0)
    rule_result_count: int = Field(ge=0)
    finding_count: int = Field(ge=0)
    status_counts: Summary


class RerunRequest(BaseModel):
    rule_codes: list[str] | None = None


class RebuildRequest(BaseModel):
    mode: RebuildMode
    confirmed: bool
    rule_codes: list[str] | None = None
    trigger_source: RebuildTriggerSource = RebuildTriggerSource.UI

    @model_validator(mode="after")
    def validate_rebuild_scope(self) -> "RebuildRequest":
        if self.confirmed is not True:
            raise ValueError("重建重跑必须显式确认")
        if self.mode == RebuildMode.INCREMENTAL:
            if not self.rule_codes:
                raise ValueError("增量重建必须指定至少一条普通规则")
            if len(self.rule_codes) != len(set(self.rule_codes)):
                raise ValueError("增量重建规则列表必须去重")
        elif self.rule_codes:
            raise ValueError("全量重建不能指定规则列表")
        return self


class LogEntry(BaseModel):
    ts: datetime
    level: str
    message: str
    rule_code: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class TaskLogs(BaseModel):
    task_id: str
    entries: list[LogEntry]


class OutputMetricDef(BaseModel):
    key: str
    label: str
    unit: str | None = None
    type: str = "number"


class InspectorInfo(BaseModel):
    code: str
    name: str
    category: RuleCategory
    severity: Severity
    priority: Priority
    rule_version: str
    hidden: bool = False
    description: str | None = None
    recommendation: str | None = None
    source_patterns: list[str] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    params: list[dict[str, str]] = Field(default_factory=list)


class DictItem(BaseModel):
    code: str
    name: str


class DictsResponse(BaseModel):
    province: list[DictItem]
    operator: list[DictItem]
    product: list[DictItem]
    version: list[DictItem]


class DictUpdateRequest(BaseModel):
    code: str
    name: str


class Error(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] | None = None


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


class DailyAggregation(StrEnum):
    LATEST = "latest"
    MEAN = "mean"
    SUM = "sum"
    MAX = "max"
    MIN = "min"


class ZeroSemantics(StrEnum):
    UNKNOWN = "unknown"
    EXPECTED_ZERO = "expected_zero"
    BUSINESS_NOT_TRIGGERED = "business_not_triggered"


class ObjectMatchMode(StrEnum):
    EXACT = "exact"


class ConfigSource(StrEnum):
    CUSTOM = "custom"
    DEFAULT = "default"
    LEGACY_RESOURCE = "legacy_resource"
    MISSING = "missing"


class KpiThresholdEvidence(BaseModel):
    direction: Literal["higher_better", "lower_better", "neutral"] | None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    source: ConfigSource


class KpiChangeThresholdEvidence(BaseModel):
    value: float | None = Field(default=None, ge=0)
    unit: Literal["pp", "relative", "unavailable"]
    source: ConfigSource


class KpiConsistencyEvidence(BaseModel):
    status: Literal["not_checked", "within_tolerance", "exceeded", "unavailable"]
    tolerance_pp: float = Field(ge=0)
    difference_pp: float | None = None


class KpiDailyBucket(BaseModel):
    date: date
    value: float | None = None
    numerator: float | None = None
    denominator: float | None = None
    valid_count: int = Field(default=0, ge=0)
    first_measured_at: datetime | None = None
    last_measured_at: datetime | None = None
    status: Literal["ok", "no_data", "zero_denominator", "unreadable", "no_baseline"]


class KpiDailyHealthGroup(BaseModel):
    object_key: str
    period_minutes: int | None = Field(ge=1)
    today: KpiDailyBucket | None = None
    yesterday: KpiDailyBucket | None = None
    current_status: CurrentHealthStatus
    trend_status: TrendHealthStatus
    reason: str = ""
    source_files: list[str] = Field(default_factory=list)


class KpiDailyHealthMetricEvidence(BaseModel):
    name_zh: str = ""
    role: MetricRole
    data_date: date | None = None
    previous_date: date | None = None
    daily_aggregation: str
    formula: str | None = None
    current_status: CurrentHealthStatus
    trend_status: TrendHealthStatus
    current_threshold: KpiThresholdEvidence
    change_threshold: KpiChangeThresholdEvidence
    consistency: KpiConsistencyEvidence


class KpiLegacyFallback(BaseModel):
    code: str
    message: str


class KpiDailyHealthMetricDetail(BaseModel):
    task_id: str
    rule_code: str
    measurement_unit_id: str
    metric_resource_id: str
    metric: KpiDailyHealthMetricEvidence
    groups: list[KpiDailyHealthGroup]
    seven_day_trend: list[KpiDailyBucket] = Field(max_length=7)
    legacy_fallback: KpiLegacyFallback | None = None


class KpiMeasurementImportResult(BaseModel):
    added: dict[str, int] = Field(default_factory=dict)
    updated: dict[str, int] = Field(default_factory=dict)
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class KpiMeasurementUnit(BaseModel):
    resource_id: str
    name_zh: str
    name_en: str
    filename_fragment: str | None
    enabled: bool
    metric_count: int = Field(ge=0)
    unit_count: int = Field(ge=0)
    confirmed_binding_count: int = Field(ge=0)
    candidate_binding_count: int = Field(ge=0)
    derived_count: int = Field(ge=0)


class KpiMeasurementUnitList(BaseModel):
    total: int = Field(ge=0)
    items: list[KpiMeasurementUnit]


class KpiMeasurementEnabledRequest(BaseModel):
    enabled: bool


class KpiMeasurementBinding(BaseModel):
    id: int
    metric_resource_id: str | None
    metric_resource_name_zh: str | None = None
    measurement_unit_id: str
    measurement_unit_name_zh: str | None = None
    raw_source_name: str
    base_source_name: str
    display_unit: str | None
    status: Literal["candidate", "confirmed", "conflict", "ignored"]
    enabled: bool
    task_id: str
    source_file: str
    metric_is_manual: bool = False


class KpiMeasurementBindingList(BaseModel):
    total: int = Field(ge=0)
    items: list[KpiMeasurementBinding]


class KpiMeasurementBindingBatchConfirmRequest(BaseModel):
    binding_ids: list[int] = Field(min_length=1, max_length=200)


class KpiMeasurementBindingConfirmResult(BaseModel):
    binding_id: int
    outcome: Literal["confirmed", "already_confirmed", "failed"]
    binding: KpiMeasurementBinding | None = None
    error_code: str | None = None
    message: str | None = None


class KpiMeasurementBindingBatchConfirmResponse(BaseModel):
    total: int = Field(ge=1)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    items: list[KpiMeasurementBindingConfirmResult] = Field(min_length=1)


class KpiMeasurementBindingStatusRequest(BaseModel):
    status: Literal["candidate", "confirmed", "ignored"]
    enabled: bool | None = None


class KpiMeasurementResource(BaseModel):
    resource_id: str
    kind: Literal["mu", "me", "unit"]
    name_zh: str
    name_en: str
    enabled: bool
    is_manual: bool
    display_order: int | None = None
    metric_group: str | None = None
    direction: Literal["higher_better", "lower_better", "neutral"] | None = None
    importance: Literal["P0", "P1", "P2", "normal"] | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    source: Literal["preset", "discovered", "manual"] = "preset"
    origin_task_id: str | None = None
    origin_file: str | None = None
    created_at: datetime
    updated_at: datetime


class KpiMeasurementMetricRegisterRequest(BaseModel):
    name_zh: str | None = Field(default=None, max_length=256)
    name_en: str | None = Field(default=None, max_length=256)
    bind_existing_resource_id: str | None = Field(default=None, max_length=128)


class KpiMeasurementMetricRegisterResponse(BaseModel):
    binding: KpiMeasurementBinding
    metric: KpiMeasurementResource


class KpiMeasurementResourceList(BaseModel):
    total: int = Field(ge=0)
    items: list[KpiMeasurementResource]


class KpiMeasurementResourceUpdateRequest(BaseModel):
    name_zh: str | None = Field(default=None, min_length=1, max_length=256)
    name_en: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    metric_group: str | None = Field(default=None, max_length=64)
    direction: Literal["higher_better", "lower_better", "neutral"] | None = None
    importance: Literal["P0", "P1", "P2", "normal"] | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None


class KpiMeasurementDerivedCreateRequest(BaseModel):
    measurement_unit_id: str
    metric_resource_id: str
    numerator_metric_id: str
    denominator_metric_id: str
    template: Literal["success_rate", "reverse_success_rate"] = "success_rate"


class KpiMeasurementDerived(BaseModel):
    id: int
    measurement_unit_id: str
    metric_resource_id: str
    numerator_metric_id: str
    denominator_metric_id: str
    template: Literal["success_rate", "reverse_success_rate"] = "success_rate"
    enabled: bool
    metric_resource_name_zh: str
    numerator_metric_name_zh: str
    denominator_metric_name_zh: str
    created_at: datetime
    updated_at: datetime


class KpiMeasurementDerivedList(BaseModel):
    total: int = Field(ge=0)
    items: list[KpiMeasurementDerived]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class KpiMeasurementDerivedUpdateRequest(BaseModel):
    numerator_metric_id: str | None = None
    denominator_metric_id: str | None = None
    template: Literal["success_rate", "reverse_success_rate"] | None = None
    enabled: bool | None = None


class KpiMetricMaintenanceConfig(BaseModel):
    measurement_unit_id: str
    metric_resource_id: str
    name_zh: str
    role: MetricRole
    direction: Literal["higher_better", "lower_better", "neutral"] | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    daily_aggregation: DailyAggregation
    daily_change_threshold: float | None = Field(default=None, ge=0)
    daily_change_threshold_unit: Literal["pp", "relative", "auto"]
    is_percentage: bool
    zero_semantics: ZeroSemantics
    consistency_tolerance: float = Field(ge=0)
    object_match_mode: ObjectMatchMode
    enabled: bool
    config_source: ConfigSource
    updated_at: datetime


class KpiMetricMaintenanceConfigList(BaseModel):
    total: int = Field(ge=0)
    items: list[KpiMetricMaintenanceConfig]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class KpiMetricMaintenanceConfigUpdateRequest(BaseModel):
    role: MetricRole | None = None
    direction: Literal["higher_better", "lower_better", "neutral"] | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    daily_aggregation: DailyAggregation | None = None
    daily_change_threshold: float | None = Field(default=None, ge=0)
    daily_change_threshold_unit: Literal["pp", "relative", "auto"] | None = None
    is_percentage: bool | None = None
    zero_semantics: ZeroSemantics | None = None
    consistency_tolerance: float | None = Field(default=None, ge=0)
    object_match_mode: ObjectMatchMode | None = None
    enabled: bool | None = None


class KpiMetricMaintenanceAudit(BaseModel):
    id: int
    measurement_unit_id: str
    metric_resource_id: str
    actor: str
    changed_fields: list[str]
    before_values: dict[str, Any]
    after_values: dict[str, Any]
    created_at: datetime


class KpiMetricMaintenanceAuditList(BaseModel):
    total: int = Field(ge=0)
    items: list[KpiMetricMaintenanceAudit]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class LoginRequestV1(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LoginResponseV1(BaseModel):
    token: str
    username: str
    role: str


class UserInfoV1(BaseModel):
    username: str
    role: str


class UserV1(BaseModel):
    username: str
    role: str
    created_at: datetime
    updated_at: datetime


class UserListResponseV1(BaseModel):
    items: list[UserV1] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class UserCreateRequestV1(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["admin", "viewer"]


class UserPasswordRequestV1(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class UserRoleRequestV1(BaseModel):
    role: Literal["admin", "viewer"]


class PackageKind(StrEnum):
    """上传任务包类型；日志补充包显式声明且不参与设备台账。"""

    INSPECTION = "inspection"
    LOG_SUPPLEMENT = "log_supplement"


class Product(StrEnum):
    """巡检包网元类型；输入在匹配前执行 trim + upper 规范化。"""

    UMF = "UMF"
    CSP = "CSP"

    @classmethod
    def _missing_(cls, value: object) -> "Product | None":
        normalized = value.strip().upper() if isinstance(value, str) else None
        return cls._value2member_map_.get(normalized) if normalized else None


class TaskCreateErrorCode(StrEnum):
    """创建任务的稳定元数据校验错误码。"""

    MISSING_PROVINCE = "missing_province"
    MISSING_OPERATOR = "missing_operator"
    MISSING_PRODUCT = "missing_product"
    INVALID_PRODUCT = "invalid_product"
    METADATA_NOT_APPLICABLE = "metadata_not_applicable"


class TaskConflictCode(StrEnum):
    """同名任务恢复矩阵的稳定冲突错误码。"""

    PACKAGE_CHECKSUM_CONFLICT = "package_checksum_conflict"
    PACKAGE_KIND_CONFLICT = "package_kind_conflict"
    PACKAGE_PRODUCT_CONFLICT = "package_product_conflict"


class TaskUploadMetadata(BaseModel):
    """创建任务时的条件元数据；日志补充包禁止携带巡检元数据。"""

    package_kind: PackageKind
    province: str | None = None
    operator: str | None = None
    product: Product | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_log_supplement_metadata(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        package_kind = data.get("package_kind")
        if package_kind not in (PackageKind.LOG_SUPPLEMENT, PackageKind.LOG_SUPPLEMENT.value):
            return data
        for field in ("province", "operator", "product"):
            value = data.get(field)
            if isinstance(value, str) and not value.strip():
                continue
            if value is not None:
                raise ValueError("metadata_not_applicable: 日志补充包禁止携带省份、运营商或网元类型")
        return data

    @field_validator("province", "operator", "product", mode="before")
    @classmethod
    def normalize_blank_metadata(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_package_kind_metadata(self) -> "TaskUploadMetadata":
        if self.package_kind == PackageKind.INSPECTION:
            if self.province is None:
                raise ValueError("missing_province: 巡检包必须提供省份")
            if self.operator is None:
                raise ValueError("missing_operator: 巡检包必须提供运营商")
            if self.product is None:
                raise ValueError("missing_product: 巡检包必须提供网元类型")
            return self
        if self.province is not None or self.operator is not None or self.product is not None:
            raise ValueError("metadata_not_applicable: 日志补充包禁止携带省份、运营商或网元类型")
        return self


class InventoryParseStatus(StrEnum):
    ARCHIVED = "archived"
    NOT_ARCHIVED = "not_archived"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class InventoryFieldStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    CONFLICT = "conflict"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"
    MATCHED_MULTIPLE = "matched_multiple"


class InventoryObservationStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class InventoryTimeSource(StrEnum):
    """观测时间来源：设备执行时间或任务完成时间兜底。"""

    LST_ME = "lst_me"
    TASK = "task"


class InventoryTimeSourceReason(StrEnum):
    """回退任务完成时间的原因。"""

    HEADER_TIME_MISSING = "header_time_missing"
    HEADER_TIME_INVALID = "header_time_invalid"
    TIME_IN_FUTURE = "time_in_future"


class VersionDirection(StrEnum):
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    UNCHANGED = "unchanged"


class InventoryQualityIssueType(StrEnum):
    MISSING_SITE = "missing_site"
    MISSING_DEVICE_IDENTITY = "missing_device_identity"
    MISSING_VERSION = "missing_version"
    VERSION_CONFLICT = "version_conflict"
    DEVICE_IDENTITY_CONFLICT = "device_identity_conflict"
    SITE_OWNERSHIP_CHANGE = "site_ownership_change"


class TaskInventorySite(BaseModel):
    status: InventoryFieldStatus
    source: Literal["upload_metadata", "none"]
    province: str | None = None
    operator: str | None = None
    site_key: str | None = None


class TaskInventoryNetworkElementTypeFilter(BaseModel):
    requested: str | None = None
    normalized: str | None = None
    status: Literal["ok", "missing", "no_match"]
    matched_count: int = Field(ge=0, description="与所选网元类型匹配的记录数量。")
    unmatched_count: int = Field(ge=0, description="未匹配所选网元类型的记录数量；不保留记录明细。")


class TaskInventoryRecord(BaseModel):
    raw_name: str | None = None
    normalized_name: str | None = None
    raw_network_element_type: str | None = None
    normalized_network_element_type: str | None = None
    network_element_type_status: InventoryFieldStatus = InventoryFieldStatus.MISSING
    raw_version: str | None = None
    version_status: InventoryFieldStatus = InventoryFieldStatus.MISSING
    version_candidates: list[str] = Field(default_factory=list)
    matched: bool
    source_file: str | None = None
    name_source_lines: list[int] = Field(default_factory=list)
    type_source_lines: list[int] = Field(default_factory=list)
    version_source_lines: list[int] = Field(default_factory=list)


class TaskInventoryVersion(BaseModel):
    status: InventoryFieldStatus
    raw_version: str | None = None
    candidates: list[str] = Field(default_factory=list)
    source_lines: list[int] = Field(default_factory=list)


class TaskInventoryMatchedDevice(BaseModel):
    status: InventoryFieldStatus = InventoryFieldStatus.OK
    raw_name: str | None = None
    normalized_name: str
    network_element_type: str | None = None
    version: TaskInventoryVersion
    source_file: str | None = None
    source_files: list[str] = Field(default_factory=list)


class TaskInventoryArchivedDevice(BaseModel):
    device_id: str
    observation_id: str
    normalized_name: str
    network_element_type: str | None = None


class TaskInventoryDevice(BaseModel):
    status: InventoryFieldStatus
    raw_names: list[str] = Field(default_factory=list)
    normalized_name: str | None = None
    reason_code: str | None = None
    source_lines: list[int] = Field(default_factory=list)


class TaskInventoryExecutionTimeEntry(BaseModel):
    source_file: str = Field(description="来源文件相对路径。")
    raw_text: str | None = Field(default=None, description="命中的头部原文；未命中为 null。")
    line: int | None = Field(description="命中行号；未命中为 null。")
    parsed_at: datetime | None = Field(default=None, description="解析出的 UTC 时间；未解析成功为 null。")
    status: Literal["ok", "missing", "invalid", "time_in_future"] = Field(description="文件级执行时间解析状态。")
    reason: InventoryTimeSourceReason | None = Field(default=None, description="未采用该时间时的原因。")


class TaskInventoryExecutionTime(BaseModel):
    status: Literal["ok", "partial", "missing"] = Field(description="全部来源文件的整体解析状态。")
    source: InventoryTimeSource = Field(description="本次归档实际使用的时间来源。")
    per_file: list[TaskInventoryExecutionTimeEntry] = Field(description="按来源文件记录的解析结果。")


class TaskInventoryArchive(BaseModel):
    archived: bool
    device_id: str | None = None
    observation_id: str | None = None
    reason: str | None = None
    devices: list[TaskInventoryArchivedDevice] = Field(default_factory=list)


class TaskInventory(BaseModel):
    package_kind: PackageKind
    status: InventoryParseStatus
    parser_id: str
    parser_version: str
    schema_version: int = 1
    not_applicable_reason: str | None = None
    not_archived_reason: str | None = None
    network_element_type_filter: TaskInventoryNetworkElementTypeFilter | None = None
    site: TaskInventorySite | None = None
    device: TaskInventoryDevice | None = None
    version: TaskInventoryVersion | None = None
    records: list[TaskInventoryRecord] = Field(
        default_factory=list,
        description="只包含与所选网元类型匹配的记录明细；其它类型的记录仅计入 unmatched_count。",
    )
    devices: list[TaskInventoryMatchedDevice] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    execution_time: TaskInventoryExecutionTime | None = Field(
        default=None,
        description="本次归档使用的执行时间证据；历史证据（schema_version < 3）为 null。",
    )
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    archived: TaskInventoryArchive


class InventoryDevice(BaseModel):
    device_id: str
    province: str
    device_name: str
    site_key: str
    operator: str
    current_version: str | None = None
    current_version_observed_at: datetime | None = Field(
        default=None,
        description="当前版本所在观测的执行时间（UTC）；不可解析时为任务完成时间兜底。",
    )
    current_version_task_id: str | None = None
    first_seen_at: datetime = Field(description="该设备最早观测的执行时间（UTC）；不可解析时为任务完成时间兜底。")
    last_seen_at: datetime = Field(description="该设备最近观测的执行时间（UTC）；不可解析时为任务完成时间兜底。")
    observation_count: int = Field(ge=0)
    site_change_count: int = Field(ge=0)
    has_site_conflict: bool
    quality_issue_types: list[InventoryQualityIssueType] = Field(default_factory=list)
    created_by: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class PagedMeta(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class InventoryDeviceList(PagedMeta):
    items: list[InventoryDevice]


class InventoryObservation(BaseModel):
    observation_id: str
    task_id: str
    task_status: Literal["completed"]
    observed_at: datetime = Field(
        description="观测时间（UTC）：优先取包内 LST ME.txt 头部记录的执行时间，不可用时回退任务完成时间。",
    )
    time_source: InventoryTimeSource = Field(
        description="观测时间来源：lst_me 为设备执行时间，task 为任务完成时间兜底。"
    )
    time_source_reason: InventoryTimeSourceReason | None = Field(default=None, description="回退任务完成时间时的原因。")
    province: str
    operator: str
    site_key: str
    device_name: str
    identity_status: Literal["ok"]
    version_status: InventoryFieldStatus
    raw_version: str | None = None
    version_source_files: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    snapshot: dict[str, Any] = Field(default_factory=dict)


class InventoryObservationList(PagedMeta):
    items: list[InventoryObservation]


class InventoryVersionPoint(BaseModel):
    observed_at: datetime = Field(description="该版本观测的执行时间（UTC）。")
    time_source: InventoryTimeSource = Field(
        description="观测时间来源：lst_me 为设备执行时间，task 为任务完成时间兜底。"
    )
    task_id: str
    version_status: InventoryFieldStatus
    raw_version: str | None = None
    direction: VersionDirection | None = None
    has_gap: bool = False


class InventoryVersionHistory(PagedMeta):
    items: list[InventoryVersionPoint]


class InventoryQualityIssue(BaseModel):
    issue_id: str
    issue_type: InventoryQualityIssueType
    message: str
    task_id: str | None = None
    device_id: str | None = None
    province: str | None = None
    operator: str | None = None
    detected_at: datetime = Field(
        description="问题检测时间；观测类问题取该观测的执行时间（UTC），不可解析时为任务完成时间兜底。",
    )
    detail: dict[str, Any] = Field(default_factory=dict)


class InventoryQualityIssueList(PagedMeta):
    items: list[InventoryQualityIssue]


InspectionTask.model_rebuild()
