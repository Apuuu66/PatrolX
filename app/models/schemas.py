"""Pydantic v2 契约模型，字段与 docs/api/openapi.yaml 严格对齐。"""

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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


class SystemInspection(BaseModel):
    package_file: str
    package_checksum: str | None = None
    version: str | None = None
    status: SystemStatus
    summary: Summary
    rules: list[RuleResult] = Field(default_factory=list)
    customer: dict[str, str] = Field(default_factory=dict)


class KpiPeriodMinutes(IntEnum):
    FIVE = 5
    FIFTEEN = 15
    THIRTY = 30
    SIXTY = 60


class KpiDisplayStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NEUTRAL = "neutral"
    UNAVAILABLE = "unavailable"


KpiValue = int | float | str | None


class KpiMetricDefinition(BaseModel):
    """KPI 目录中的指标定义。"""

    key: str
    name_zh: str
    name_en: str
    aliases: list[dict[str, Any]] = Field(default_factory=list)
    metric_type: str
    semantic_group: str
    display_role: str
    unit: str | None = None
    source_type: str
    aggregation: dict[str, Any]
    formula: dict[str, Any] | None = None
    description: str | None = None


class KpiMetricResult(BaseModel):
    """KPI 指标聚合结果。"""

    key: str
    main_value: KpiValue = None
    value_available: bool = True
    unavailable_reason: str | None = None
    display_status: KpiDisplayStatus
    unit: str | None = None
    aggregation: str
    threshold: dict[str, Any] | None = None
    breach_count: int = Field(default=0, ge=0)
    series: list[dict[str, Any]] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class KpiUnclassifiedMetric(BaseModel):
    """未登记 KPI 指标，仅作为目录补齐线索展示。"""

    source_name: str
    source_files: list[str] = Field(default_factory=list)
    record_count: int = Field(default=0, ge=0)
    sample_values: list[Any] = Field(default_factory=list)
    reason: str = "metric_not_registered"


class KpiRecordError(BaseModel):
    """KPI 原始记录错误投影。"""

    code: str
    line_number: int | None = None
    column: str | None = None
    message: str = ""
    value: KpiValue = None


class KpiRecordItem(BaseModel):
    """按指标展开的 KPI 原始记录。"""

    metric_key: str
    metric_name_zh: str
    source_file: str
    line_number: int = Field(ge=1)
    period_minutes: int = Field(ge=1)
    start_at: datetime
    end_at: datetime
    value: KpiValue = None
    status: KpiDisplayStatus = KpiDisplayStatus.NEUTRAL
    errors: list[dict[str, Any]] = Field(default_factory=list)


class KpiRecordPage(BaseModel):
    """KPI 原始记录分页响应。"""

    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    items: list[KpiRecordItem] = Field(default_factory=list)


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
    stats: TaskStats
    preparation: DataPreparation | None = None
    system: SystemInspection | None = None

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
    customer_province: str | None = None
    customer_operator: str | None = None
    customer_product: str | None = None
    customer_version: str | None = None


class TaskCreated(BaseModel):
    task_id: str


class TaskListResponse(BaseModel):
    items: list[TaskSummary]
    total: int
    page: int
    page_size: int


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


class KpiResourceDomain(StrEnum):
    """KPI 资源指标的业务域筛选值。"""

    UNCLASSIFIED = "unclassified"
    CALL = "call"
    API = "api"
    MEDIA = "media"
    RESERVED = "reserved"


class KpiResourceMetricV3(BaseModel):
    """基础指标配置中的基础资源与分类状态。"""

    key: str
    resource_id: str
    name_zh: str
    name_en: str
    domain: KpiResourceDomain
    missing_from_base: bool
    created_at: datetime
    updated_at: datetime


class KpiResourceMetricPageV3(BaseModel):
    """基础指标配置分页查询响应。"""

    items: list[KpiResourceMetricV3] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    base_data_version: str
    classification_version: int = Field(ge=0)
    summary: dict[KpiResourceDomain, int]


class KpiResourceClassificationRequestV3(BaseModel):
    """KPI 指标批量分类请求。"""

    metric_keys: list[str] = Field(min_length=1, max_length=100)
    domain: Literal["unclassified", "call", "api", "media", "reserved"]
    operator: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_metric_keys(self) -> "KpiResourceClassificationRequestV3":
        if len(self.metric_keys) != len(set(self.metric_keys)):
            raise ValueError("metric_keys 不能重复")
        return self


class KpiResourceClassificationResultV3(BaseModel):
    """KPI 指标批量分类结果。"""

    classification_version: int = Field(ge=0)
    domain: Literal["unclassified", "call", "api", "media", "reserved"]
    metric_keys: list[str]
    audited_count: int = Field(ge=0)


class KpiClassificationAuditV3(BaseModel):
    """KPI 分类审计记录。"""

    id: int
    metric_key: str
    operation: str
    operator: str
    from_domain: str
    to_domain: str
    result: str
    operated_at: datetime


class KpiClassificationAuditPageV3(BaseModel):
    """KPI 分类审计分页响应。"""

    items: list[KpiClassificationAuditV3] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class KpiTaskCatalogSnapshot(BaseModel):
    """任务启动时的 KPI 配置快照。"""

    schema_version: int = 1
    base_data_version: str
    classification_version: int = Field(ge=0)
    rule_config_version: int = Field(default=0, ge=0)
    captured_at: datetime
    base_metrics: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    reserved_metric_keys: list[str] = Field(default_factory=list)
    rules: dict[str, Any]
    derived_metrics: list[dict[str, Any]] = Field(default_factory=list)


class KpiMetricTypeV4(StrEnum):
    COUNT = "count"
    RATE = "rate"
    CAPACITY = "capacity"
    LATENCY = "latency"
    GAUGE = "gauge"


class KpiSemanticGroupV4(StrEnum):
    TRAFFIC = "traffic"
    QUALITY = "quality"
    LATENCY = "latency"
    CAPACITY = "capacity"
    OTHER = "other"


class KpiDisplayRoleV4(StrEnum):
    HIGHLIGHT = "highlight"
    CONTEXT = "context"


class KpiSourceTypeV4(StrEnum):
    RAW = "raw"
    DERIVED = "derived"


class KpiAggregationKindV4(StrEnum):
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    MEAN = "mean"
    COUNT = "count"
    MEDIAN = "median"
    STDDEV = "stddev"
    SUCCESS_RATE = "success_rate"


class KpiRegisteredDomainV4(StrEnum):
    CALL = "call"
    API = "api"
    MEDIA = "media"


class KpiThresholdDirectionV4(StrEnum):
    MIN = "min"
    MAX = "max"


class KpiCapacityStatusV4(StrEnum):
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class KpiCapacitySemanticsV4(StrEnum):
    PEAK = "peak"
    CONCURRENCY = "concurrency"
    GAUGE = "gauge"


class KpiConfigEntityTypeV4(StrEnum):
    METRIC_RULE = "metric_rule"
    THRESHOLD = "threshold"
    CAPACITY_RULE = "capacity_rule"
    DISPLAY_RULE = "display_rule"
    COMMON_CONFIG = "common_config"
    DERIVED_METRIC = "derived_metric"


class KpiClueStatusV4(StrEnum):
    UNCLASSIFIED = "unclassified"
    CLASSIFIED = "classified"
    UNREGISTERED = "unregistered"
    AMBIGUOUS = "ambiguous"
    RESERVED = "reserved"


class KpiFormulaV4(BaseModel):
    kind: Literal["ratio"]
    numerator: str
    denominator: str
    denominator_fallback_inputs: list[str] = Field(default_factory=list)
    scale: float


class KpiMetricRuleRequestV4(BaseModel):
    metric_type: KpiMetricTypeV4
    semantic_group: KpiSemanticGroupV4
    display_role: KpiDisplayRoleV4
    unit: str = Field(min_length=1)
    source_type: KpiSourceTypeV4
    aggregation_kind: KpiAggregationKindV4
    description: str | None = None
    formula: KpiFormulaV4 | None = None
    operator: str = Field(min_length=1)


class KpiMetricRuleV4(BaseModel):
    metric_key: str
    metric_type: KpiMetricTypeV4
    semantic_group: KpiSemanticGroupV4
    display_role: KpiDisplayRoleV4
    unit: str
    source_type: KpiSourceTypeV4
    aggregation_kind: KpiAggregationKindV4
    description: str | None = None
    formula: KpiFormulaV4 | None = None
    domain: KpiRegisteredDomainV4 | None = None
    updated_at: datetime
    rule_config_version: int


class KpiMetricRulePageV4(BaseModel):
    items: list[KpiMetricRuleV4] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rule_config_version: int = Field(ge=0)


class KpiDerivedFormulaV4(BaseModel):
    kind: Literal["ratio", "inverse_ratio"]
    numerator: str
    denominator: str
    denominator_fallback_inputs: list[str] = Field(default_factory=list)
    scale: float = Field(gt=0)


class KpiDerivedMetricRequestV4(BaseModel):
    name_zh: str = Field(min_length=1)
    name_en: str = Field(min_length=1)
    domain: KpiRegisteredDomainV4
    metric_type: KpiMetricTypeV4
    semantic_group: KpiSemanticGroupV4
    display_role: KpiDisplayRoleV4
    unit: str = Field(min_length=1)
    description: str | None = None
    enabled: bool
    formula: KpiDerivedFormulaV4


class KpiDerivedMetricCreateRequestV4(KpiDerivedMetricRequestV4):
    metric_key: str | None = Field(default=None, min_length=3, max_length=128)


KpiDerivedMetricUpdateRequestV4 = KpiDerivedMetricRequestV4


class KpiDerivedMetricV4(BaseModel):
    metric_key: str
    name_zh: str
    name_en: str
    domain: KpiRegisteredDomainV4
    metric_type: KpiMetricTypeV4
    semantic_group: KpiSemanticGroupV4
    display_role: KpiDisplayRoleV4
    unit: str
    description: str | None = None
    enabled: bool
    formula: KpiDerivedFormulaV4
    updated_at: datetime
    rule_config_version: int


class KpiDerivedMetricPageV4(BaseModel):
    items: list[KpiDerivedMetricV4] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rule_config_version: int = Field(ge=0)


class KpiThresholdRequestV4(BaseModel):
    domain: KpiRegisteredDomainV4
    metric_key: str
    label: str = Field(min_length=1)
    direction: KpiThresholdDirectionV4
    unit: str = Field(min_length=1)
    default: float
    periods: dict[str, float]
    operator: str = Field(min_length=1)


class KpiThresholdV4(BaseModel):
    id: int
    domain: KpiRegisteredDomainV4
    metric_key: str
    label: str
    direction: KpiThresholdDirectionV4
    unit: str
    default: float
    periods: dict[str, float]
    updated_at: datetime
    rule_config_version: int


class KpiThresholdPageV4(BaseModel):
    items: list[KpiThresholdV4] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rule_config_version: int = Field(ge=0)


class KpiCapacityRuleRequestV4(BaseModel):
    source_name: str = Field(min_length=1)
    metric_key: str
    domain: KpiRegisteredDomainV4 | None = None
    status: KpiCapacityStatusV4
    semantics: KpiCapacitySemanticsV4 | None = None
    operator: str = Field(min_length=1)


class KpiCapacityRuleV4(BaseModel):
    id: int
    source_name: str
    metric_key: str
    domain: KpiRegisteredDomainV4 | None = None
    status: KpiCapacityStatusV4
    semantics: KpiCapacitySemanticsV4 | None = None
    updated_at: datetime
    rule_config_version: int


class KpiCapacityRulePageV4(BaseModel):
    items: list[KpiCapacityRuleV4] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rule_config_version: int = Field(ge=0)


class KpiDisplayRuleRequestV4(BaseModel):
    domain: KpiRegisteredDomainV4
    metric_key: str
    role: KpiDisplayRoleV4
    operator: str = Field(min_length=1)


class KpiDisplayRuleV4(BaseModel):
    id: int
    domain: KpiRegisteredDomainV4
    metric_key: str
    role: KpiDisplayRoleV4
    updated_at: datetime
    rule_config_version: int


class KpiDisplayRulePageV4(BaseModel):
    items: list[KpiDisplayRuleV4] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rule_config_version: int = Field(ge=0)


class KpiCommonConfigRequestV4(BaseModel):
    input_timezone: str = Field(min_length=1)
    max_files: int = Field(ge=1)
    max_records: int = Field(ge=1)
    operator: str = Field(min_length=1)


class KpiCommonConfigV4(BaseModel):
    input_timezone: str
    max_files: int
    max_records: int
    updated_at: datetime
    rule_config_version: int


class KpiConfigDeleteResultV4(BaseModel):
    deleted: bool
    entity_type: KpiConfigEntityTypeV4
    entity_key: str
    rule_config_version: int


class KpiConfigAuditV4(BaseModel):
    id: int
    entity_type: KpiConfigEntityTypeV4
    entity_key: str
    operation: Literal["upsert", "delete"]
    operator: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    result: str
    rule_config_version: int
    detail: dict[str, Any] | None = None
    operated_at: datetime


class KpiConfigAuditPageV4(BaseModel):
    items: list[KpiConfigAuditV4] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class KpiClassificationClueV4(BaseModel):
    source_name: str
    metric_key: str | None = None
    candidates: list[dict[str, str]] = Field(default_factory=list)
    clue_status: KpiClueStatusV4
    rule_code: str
    domain: str
    source_files: list[str] = Field(default_factory=list)
    record_count: int = Field(ge=0)
    sample_values: list[Any] = Field(default_factory=list)
    resolution_note: str | None = None


class KpiClassificationCluePageV4(BaseModel):
    items: list[KpiClassificationClueV4] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    summary: dict[KpiClueStatusV4, int] = Field(default_factory=dict)


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
