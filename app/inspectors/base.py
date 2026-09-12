"""Inspector 基类与规则契约。"""

import re
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
    source_patterns: list[str] | None = None
    outputs_metrics: list[OutputMetric] = field(default_factory=list)
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
        if self.hidden:
            if self.source_patterns is None:
                return self
            if not self.source_patterns:
                raise ValueError(f"隐藏规则 {self.code} source_patterns 不能为空")
        elif self.source_patterns is None or not self.source_patterns:
            raise ValueError(f"普通规则 {self.code} 必须声明非空 source_patterns")
        if self.source_patterns is not None:
            self._validate_source_patterns()
        metric_keys = []
        for metric in self.outputs_metrics:
            key = metric.get("key") if isinstance(metric, dict) else metric.key
            if not key:
                raise ValueError(f"规则 {self.code} metrics key 不能为空")
            metric_keys.append(key)
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError(f"规则 {self.code} metrics key 重复")
        return self

    def _validate_source_patterns(self) -> None:
        if self.source_patterns is None:
            return
        for pattern in self.source_patterns:
            if not pattern or pattern.strip() != pattern:
                raise ValueError(f"规则 {self.code} source_patterns 存在非法正则: {pattern}")
            if pattern.startswith("/") or pattern.startswith("\\"):
                raise ValueError(f"规则 {self.code} source_patterns 禁止绝对路径: {pattern}")
            if ".." in pattern or pattern.startswith("~"):
                raise ValueError(f"规则 {self.code} source_patterns 禁止路径穿越: {pattern}")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"规则 {self.code} source_patterns 存在非法正则: {pattern}") from exc
