"""Pydantic v2 契约模型，字段与 docs/api/openapi.yaml 严格对齐。"""

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

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
