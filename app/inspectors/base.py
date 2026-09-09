"""Inspector 基类与规则契约。"""

from dataclasses import dataclass, field
from typing import Any

from app.models.schemas import Priority, RuleCategory, Severity


@dataclass(slots=True)
class OutputMetric:
    key: str
    label: str
    unit: str | None = None
    type: str = "number"


@dataclass(slots=True)
class Inspector:
    """规则契约（RuleContract）。"""

    code: str
    name: str
    category: RuleCategory
    severity: Severity
    priority: Priority
    rule_version: str
    description: str
    recommendation: str
    hidden: bool = False
    inputs: list[str] = field(default_factory=list)
    outputs_metrics: list[OutputMetric] = field(default_factory=list)
    outputs_artifacts: list[str] = field(default_factory=list)
    params: list[dict[str, Any]] = field(default_factory=list)
    run: Any = None

    def validate(self) -> None:
        if not self.code or not self.name:
            raise ValueError(f"规则 {self.code} 缺少 code/name")
        if not self.description or not self.recommendation:
            raise ValueError(f"规则 {self.code} 必须声明 description 与 recommendation")
        if not self.rule_version:
            raise ValueError(f"规则 {self.code} 必须声明 rule_version")
        if self.priority not in (Priority.P0, Priority.P1, Priority.P2):
            raise ValueError(f"规则 {self.code} priority 非法")
        if self.run is None:
            raise ValueError(f"规则 {self.code} 缺少执行函数 run")
        if len(set(self.outputs_artifacts)) != len(self.outputs_artifacts):
            raise ValueError(f"规则 {self.code} outputs_artifacts 重复")
