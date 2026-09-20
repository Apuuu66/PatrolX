"""KPI Git JSON 目录模型、加载校验和聚合评估函数。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from app.core.config import settings

REGISTERED_DOMAINS = ("call", "api", "media")
KPI_BASE_FILES = (
    "base/metrics.json",
    "base/units.json",
)
_METRIC_RESOURCE_RE = re.compile(r"^ME_[A-Za-z0-9_]+$")
_UNIT_RESOURCE_RE = re.compile(r"^UNIT_[A-Za-z0-9_]+$")
_STABLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VALID_METRIC_TYPES = {"count", "rate", "capacity", "latency", "gauge"}
_VALID_SOURCE_TYPES = {"raw", "derived"}
_VALID_DISPLAY_ROLES = {"highlight", "context"}
_VALID_RAW_AGGREGATIONS = {"sum", "min", "max", "mean", "count", "median", "stddev"}
_VALID_AGGREGATIONS = _VALID_RAW_AGGREGATIONS | {"success_rate"}
_VALID_DIRECTIONS = {"min", "max"}
_VALID_CAPACITY_STATUS = {"confirmed", "unknown"}
_VALID_SEMANTICS = {"peak", "concurrency", "gauge"}


class KpiCatalogError(Exception):
    """KPI Git 目录加载或校验错误。"""


def normalize_metric_name(value: str) -> str:
    """按配置契约归一化指标名；前缀匹配使用同一规则。"""
    normalized = unicodedata.normalize("NFKC", value).strip()
    return " ".join(normalized.split()).casefold()


_MatchValueT = TypeVar("_MatchValueT")


def match_longest_prefix(normalized: str, index: dict[str, _MatchValueT]) -> _MatchValueT | None:
    """对已归一化的输入做最长前缀匹配，返回对应的值或 None。

    规则执行和分类线索服务共用同一算法，保证匹配逻辑一致。
    """
    best: _MatchValueT | None = None
    best_length = 0
    for name, value in index.items():
        if not name or not normalized.startswith(name):
            continue
        if len(name) > best_length:
            best = value
            best_length = len(name)
    return best


@dataclass(slots=True)
class KpiAggregation:
    kind: str
    quantile: float | None = None


@dataclass(slots=True)
class KpiRatioFormula:
    numerator: str
    denominator: str
    denominator_fallback_inputs: list[str] = field(default_factory=list)
    scale: float = 1.0


@dataclass(slots=True)
class KpiMetricDefinition:
    key: str
    name_zh: str
    name_en: str
    metric_type: str
    semantic_group: str
    display_role: str
    unit: str
    source_type: str
    aggregation: KpiAggregation
    aliases: list[dict[str, str]]
    description: str | None = None
    formula: KpiRatioFormula | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "metric_type": self.metric_type,
            "semantic_group": self.semantic_group,
            "display_role": self.display_role,
            "unit": self.unit,
            "source_type": self.source_type,
            "aggregation": {
                "kind": self.aggregation.kind,
                **({"quantile": self.aggregation.quantile} if self.aggregation.quantile is not None else {}),
            },
            "aliases": [dict(alias) for alias in self.aliases],
            **({"description": self.description} if self.description is not None else {}),
            **({"formula": _formula_dict(self.formula)} if self.formula is not None else {}),
        }


@dataclass(slots=True)
class KpiThreshold:
    metric: str
    label: str
    direction: str
    unit: str
    default: float
    periods: dict[str, float]


@dataclass(slots=True)
class KpiAggregationResult:
    """单个 KPI 指标的聚合结果与溯源。"""

    key: str
    main_value: float | None = None
    value_available: bool = False
    unavailable_reason: str | None = None
    actual_aggregation: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KpiBaseMetric:
    """Git JSON 中的基础资源指标。"""

    resource_id: str
    key: str
    name_zh: str
    name_en: str
    unit_key: str | None = None


@dataclass(slots=True)
class KpiReservedUnit:
    """Git JSON 中预留的单位资源。"""

    resource_id: str
    key: str
    name_zh: str
    name_en: str


@dataclass(slots=True)
class KpiRuleSet:
    common: dict[str, Any]
    metric_rules: dict[str, dict[str, Any]]
    thresholds: list[dict[str, Any]]
    capacity_rules: list[dict[str, Any]]
    display_rules: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "common": dict(self.common),
            "metric_rules": [dict(item) for item in self.metric_rules.values()],
            "thresholds": [dict(item) for item in self.thresholds],
            "capacity_rules": [dict(item) for item in self.capacity_rules],
            "display_rules": [dict(item) for item in self.display_rules],
        }


@dataclass(slots=True)
class KpiGitCatalog:
    """Git JSON 解析结果。"""

    schema_version: int = 1
    source_csv_sha256: str = "0" * 64
    metrics: dict[str, KpiBaseMetric] = field(default_factory=dict)
    units: dict[str, KpiReservedUnit] = field(default_factory=dict)
    rules: KpiRuleSet = field(
        default_factory=lambda: KpiRuleSet(
            common={"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 1000, "max_records": 200000}},
            metric_rules={},
            thresholds=[],
            capacity_rules=[],
            display_rules=[],
        )
    )
    base_data_version: str = "sha256:" + "0" * 64


def _numeric_values(values: list[Any]) -> tuple[list[float], bool]:
    numbers: list[float] = []
    has_missing = False
    for value in values:
        if value is None:
            has_missing = True
        elif isinstance(value, bool):
            numbers.append(float(int(value)))
        elif isinstance(value, int | float):
            numbers.append(float(value))
    return numbers, has_missing


def _actual_aggregation(kind: str, quantile: float | None = None) -> str:
    return kind


def _aggregate_values(kind: str, values: list[float], quantile: float | None = None) -> float:
    if not values:
        raise ValueError("values 不能为空")
    if kind == "sum":
        return sum(values)
    if kind == "mean":
        return sum(values) / len(values)
    if kind == "count":
        return float(len(values))
    if kind in {"max", "min"}:
        return max(values) if kind == "max" else min(values)
    if kind == "median":
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2
    if kind == "stddev":
        mean = sum(values) / len(values)
        return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5
    raise KpiCatalogError(f"不支持的 raw 聚合类型: {kind}")


def _sum_input(values: list[Any]) -> float | None:
    numbers, has_missing = _numeric_values(values)
    if has_missing or not numbers:
        return None
    return sum(numbers)


def _formula_text(formula: KpiRatioFormula) -> str:
    return f"{formula.numerator} / {formula.denominator}"


def aggregate_kpi_metric(
    definition: KpiMetricDefinition,
    input_values: dict[str, list[Any]],
) -> KpiAggregationResult:
    """按指标声明聚合主值；派生比率先汇总输入再计算。"""
    if definition.source_type == "derived":
        if definition.formula is None:
            return KpiAggregationResult(
                key=definition.key,
                unavailable_reason="formula_not_configured",
                actual_aggregation=definition.aggregation.kind,
            )
        formula = definition.formula
        aggregated_inputs: dict[str, float | None] = {
            key: _sum_input(input_values.get(key, []))
            for key in (formula.numerator, formula.denominator, *formula.denominator_fallback_inputs)
        }
        input_provenance: list[dict[str, Any]] = []
        missing_inputs: list[str] = []
        numerator = aggregated_inputs.get(formula.numerator)
        if numerator is None:
            missing_inputs.append(formula.numerator)
        denominator = aggregated_inputs.get(formula.denominator)
        denominator_present = denominator is not None
        fallback_used = False

        if not denominator_present and not formula.denominator_fallback_inputs:
            missing_inputs.append(formula.denominator)
        if not denominator_present:
            fallback_values: list[float] = []
            for key in formula.denominator_fallback_inputs:
                value = aggregated_inputs.get(key)
                if value is None:
                    missing_inputs.append(key)
                else:
                    fallback_values.append(value)
            if not missing_inputs and fallback_values:
                denominator = sum(fallback_values)
                fallback_used = True

        inputs = [formula.numerator, formula.denominator, *formula.denominator_fallback_inputs]
        for key in dict.fromkeys(inputs):
            value = aggregated_inputs.get(key)
            input_provenance.append(
                {
                    "key": key,
                    "aggregation": "sum",
                    "value": value,
                }
            )

        if numerator is None:
            return KpiAggregationResult(
                key=definition.key,
                unavailable_reason=f"missing_input: {formula.numerator}",
                actual_aggregation=definition.aggregation.kind,
                provenance={
                    "formula": _formula_text(formula),
                    "inputs": input_provenance,
                    "missing_inputs": list(dict.fromkeys(missing_inputs)),
                    "denominator_zero": False,
                    "fallback_used": fallback_used,
                },
            )
        if denominator is None:
            reason_key = missing_inputs[0] if missing_inputs else formula.denominator
            return KpiAggregationResult(
                key=definition.key,
                unavailable_reason=f"missing_input: {reason_key}",
                actual_aggregation=definition.aggregation.kind,
                provenance={
                    "formula": _formula_text(formula),
                    "inputs": input_provenance,
                    "missing_inputs": list(dict.fromkeys(missing_inputs)),
                    "denominator_zero": False,
                    "fallback_used": fallback_used,
                },
            )
        if denominator == 0:
            return KpiAggregationResult(
                key=definition.key,
                unavailable_reason="denominator_zero",
                actual_aggregation=definition.aggregation.kind,
                provenance={
                    "formula": _formula_text(formula),
                    "inputs": input_provenance,
                    "missing_inputs": [],
                    "denominator_zero": True,
                    "fallback_used": fallback_used,
                },
            )
        return KpiAggregationResult(
            key=definition.key,
            main_value=numerator / denominator * formula.scale,
            value_available=True,
            actual_aggregation=definition.aggregation.kind,
            provenance={
                "formula": _formula_text(formula),
                "inputs": input_provenance,
                "missing_inputs": [],
                "denominator_zero": False,
                "fallback_used": fallback_used,
            },
        )

    values, has_missing = _numeric_values(input_values.get(definition.key, []))
    kind = definition.aggregation.kind
    actual = _actual_aggregation(kind, definition.aggregation.quantile)
    if not values:
        return KpiAggregationResult(
            key=definition.key,
            unavailable_reason="no_records",
            actual_aggregation=actual,
            provenance={"inputs": [], "missing_inputs": [definition.key] if has_missing else []},
        )
    value = _aggregate_values(kind, values, definition.aggregation.quantile)
    return KpiAggregationResult(
        key=definition.key,
        main_value=value,
        value_available=True,
        actual_aggregation=actual,
        provenance={
            "inputs": [
                {
                    "key": definition.key,
                    "aggregation": actual,
                    "value": value,
                }
            ],
            "missing_inputs": [],
        },
    )


def evaluate_kpi_threshold(
    value: float | None,
    threshold: KpiThreshold | None,
    period_minutes: int,
) -> str:
    """评估阈值状态；无阈值始终为 neutral。"""
    if threshold is None:
        return "neutral"
    if value is None:
        return "unavailable"
    limit = threshold.periods.get(str(period_minutes), threshold.default)
    if threshold.direction == "min" and value < limit:
        return "fail"
    if threshold.direction == "max" and value > limit:
        return "fail"
    return "pass"


def _formula_dict(formula: KpiRatioFormula) -> dict[str, Any]:
    value: dict[str, Any] = {
        "kind": "ratio",
        "numerator": formula.numerator,
        "denominator": formula.denominator,
        "scale": formula.scale,
    }
    if formula.denominator_fallback_inputs:
        value["denominator_fallback"] = {
            "kind": "sum",
            "inputs": list(formula.denominator_fallback_inputs),
        }
    return value


@dataclass(slots=True)
class KpiDomainConfig:
    domain: str
    metrics: dict[str, KpiMetricDefinition]
    thresholds: dict[str, KpiThreshold]
    capacity_metrics: dict[str, dict[str, Any]]
    alias_index: dict[str, str]
    config_source: str


@dataclass(slots=True)
class KpiConfig:
    """任务执行使用的领域化有效目录。"""

    version: int
    input_timezone: str
    budgets: dict[str, int]
    domains: dict[str, KpiDomainConfig]
    config_source: str = "git-json+db"
    base_data_version: str = ""
    classification_version: int = 0
    reserved_metric_keys: frozenset[str] = frozenset()
    reserved_alias_index: dict[str, str] = field(default_factory=dict)

    @property
    def tzinfo(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.input_timezone)

    @property
    def aliases(self) -> dict[str, dict[str, str]]:
        return {domain: dict(item.alias_index) for domain, item in self.domains.items()}

    @property
    def capacity_metrics(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {domain: dict(item.capacity_metrics) for domain, item in self.domains.items()}

    @property
    def limits(self) -> dict[str, dict[str, KpiThreshold]]:
        return {domain: dict(item.thresholds) for domain, item in self.domains.items()}


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON 解析时拒绝重复对象字段。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise KpiCatalogError(f"JSON 对象字段重复: {key}")
        result[key] = value
    return result


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KpiCatalogError(f"{context}: 必须是对象")
    return value


def _require_array(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise KpiCatalogError(f"{context}: 必须是数组")
    return value


def _require_keys(raw: dict[str, Any], expected: set[str], context: str) -> None:
    unknown = sorted(set(raw) - expected)
    missing = sorted(expected - set(raw))
    if unknown:
        raise KpiCatalogError(f"{context}: 未知字段 {unknown}")
    if missing:
        raise KpiCatalogError(f"{context}: 缺少字段 {missing}")


def _require_non_empty_str(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KpiCatalogError(f"{context}: 必须是非空字符串")
    return value


def _require_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise KpiCatalogError(f"{context}: 必须为数字")
    return float(value)


def _require_sha256(value: Any, context: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise KpiCatalogError(f"{context}: 必须是 64 位小写 SHA-256")
    return value


def _validate_resource(
    value: Any, context: str, prefix: str, pattern: re.Pattern[str]
) -> tuple[str, str, str, str, str | None]:
    item = _require_object(value, context)
    _require_keys(
        item, {"resource_id", "key", "name_zh", "name_en", *({"unit_key"} if prefix == "ME_" else set())}, context
    )
    resource_id = _require_non_empty_str(item["resource_id"], f"{context}.resource_id")
    if pattern.fullmatch(resource_id) is None:
        raise KpiCatalogError(f"{context}.resource_id: 必须匹配 {prefix}[A-Za-z0-9_]+")
    key = _require_non_empty_str(item["key"], f"{context}.key")
    if _STABLE_KEY_RE.fullmatch(key) is None or key != resource_id.lower():
        raise KpiCatalogError(f"{context}.key: 必须为资源 ID 的小写稳定 key")
    name_zh = _require_non_empty_str(item["name_zh"], f"{context}.name_zh")
    name_en = _require_non_empty_str(item["name_en"], f"{context}.name_en")
    unit_key: str | None = None
    if prefix == "ME_":
        unit_key = item["unit_key"]
        if unit_key is not None:
            raise KpiCatalogError(f"{context}.unit_key: 当前必须为 null")
    return resource_id, key, name_zh, name_en, unit_key


def _validate_formula(value: Any, context: str, metric_keys: set[str]) -> KpiRatioFormula:
    formula = _require_object(value, context)
    _require_keys(formula, {"kind", "numerator", "denominator", "scale"}, context)
    if "denominator_fallback" not in formula:
        formula["denominator_fallback"] = None
    if formula["kind"] != "ratio":
        raise KpiCatalogError(f"{context}.kind: 当前只支持 ratio")
    numerator = _require_non_empty_str(formula["numerator"], f"{context}.numerator")
    denominator = _require_non_empty_str(formula["denominator"], f"{context}.denominator")
    scale = _require_number(formula["scale"], f"{context}.scale")
    fallback_raw = formula["denominator_fallback"]
    fallback_inputs: list[str] = []
    if fallback_raw is not None:
        fallback = _require_object(fallback_raw, f"{context}.denominator_fallback")
        _require_keys(fallback, {"kind", "inputs"}, f"{context}.denominator_fallback")
        if fallback["kind"] != "sum":
            raise KpiCatalogError(f"{context}.denominator_fallback.kind: 当前只支持 sum")
        inputs = _require_array(fallback["inputs"], f"{context}.denominator_fallback.inputs")
        if not inputs:
            raise KpiCatalogError(f"{context}.denominator_fallback.inputs: 不能为空")
        for index, item in enumerate(inputs):
            key = _require_non_empty_str(item, f"{context}.denominator_fallback.inputs[{index}]")
            if key in fallback_inputs:
                raise KpiCatalogError(f"{context}.denominator_fallback.inputs[{index}]: 输入重复")
            fallback_inputs.append(key)
    references = {numerator, denominator, *fallback_inputs}
    missing = sorted(ref for ref in references if ref not in metric_keys)
    if missing:
        raise KpiCatalogError(f"{context}: 引用未知输入 {missing}")
    return KpiRatioFormula(numerator, denominator, fallback_inputs, scale)


def _validate_metric_rule(value: Any, context: str, metric_keys: set[str]) -> tuple[str, dict[str, Any]]:
    raw = _require_object(value, context)
    _require_keys(
        raw,
        {
            "key",
            "metric_type",
            "semantic_group",
            "display_role",
            "unit",
            "source_type",
            "aggregation",
            "formula",
            "description",
        },
        context,
    )
    if "description" not in raw:
        raw["description"] = None
    key = _require_non_empty_str(raw["key"], f"{context}.key")
    if key not in metric_keys:
        raise KpiCatalogError(f"{context}.key: 引用未知基础指标 {key}")
    for field_name, valid in (
        ("metric_type", _VALID_METRIC_TYPES),
        ("semantic_group", {"traffic", "quality", "latency", "capacity", "other"}),
        ("display_role", _VALID_DISPLAY_ROLES),
        ("source_type", _VALID_SOURCE_TYPES),
    ):
        value_for_field = raw[field_name]
        if value_for_field not in valid:
            raise KpiCatalogError(f"{context}.{field_name}: 非法值")
    _require_non_empty_str(raw["unit"], f"{context}.unit")
    aggregation = _require_object(raw["aggregation"], f"{context}.aggregation")
    _require_keys(aggregation, {"kind", "quantile"}, f"{context}.aggregation")
    aggregation.setdefault("quantile", None)
    if aggregation["kind"] not in _VALID_AGGREGATIONS:
        raise KpiCatalogError(f"{context}.aggregation.kind: 非法聚合")
    quantile = aggregation["quantile"]
    if quantile is not None:
        number = _require_number(quantile, f"{context}.aggregation.quantile")
        if not 0 <= number <= 1:
            raise KpiCatalogError(f"{context}.aggregation.quantile: 必须在 [0,1]")
    if raw["source_type"] == "derived":
        if raw["aggregation"]["kind"] != "success_rate":
            raise KpiCatalogError(f"{context}.aggregation.kind: derived 指标必须使用 success_rate")
        if raw["formula"] is None:
            raise KpiCatalogError(f"{context}.formula: derived 指标必须配置公式")
        _validate_formula(raw["formula"], f"{context}.formula", metric_keys)
    elif raw["formula"] is not None or raw["aggregation"]["kind"] not in _VALID_RAW_AGGREGATIONS:
        raise KpiCatalogError(f"{context}.aggregation.kind: raw 指标只支持受控聚合")
    if raw["description"] is not None:
        _require_non_empty_str(raw["description"], f"{context}.description")
    return key, raw


def _validate_formula_cycles(metric_rules: dict[str, dict[str, Any]]) -> None:
    references: dict[str, set[str]] = {}
    for key, raw in metric_rules.items():
        if raw["formula"] is not None:
            formula = raw["formula"]
            fallback = formula["denominator_fallback"]
            references[key] = {formula["numerator"], formula["denominator"]}
            if fallback is not None:
                references[key].update(fallback["inputs"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise KpiCatalogError(f"rules.metric_rules[key={key}].formula: 存在循环依赖")
        if key in visited:
            return
        visiting.add(key)
        for ref in references.get(key, set()):
            visit(ref)
        visiting.remove(key)
        visited.add(key)

    for key in metric_rules:
        visit(key)


def _validate_rules(raw: Any, metric_keys: set[str]) -> KpiRuleSet:
    rules = _require_object(raw, "rules")
    _require_keys(rules, {"common", "metric_rules", "thresholds", "capacity_rules", "display_rules"}, "rules")
    common = _require_object(rules["common"], "rules.common")
    _require_keys(common, {"input_timezone", "budgets"}, "rules.common")
    timezone = _require_non_empty_str(common["input_timezone"], "rules.common.input_timezone")
    try:
        zoneinfo.ZoneInfo(timezone)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise KpiCatalogError("rules.common.input_timezone: 非法 IANA 时区") from exc
    budgets = _require_object(common["budgets"], "rules.common.budgets")
    _require_keys(budgets, {"max_files", "max_records"}, "rules.common.budgets")
    for key in ("max_files", "max_records"):
        value = budgets[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise KpiCatalogError(f"rules.common.budgets.{key}: 必须为正整数")

    metric_rule_list = _require_array(rules["metric_rules"], "rules.metric_rules")
    metric_rules: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(metric_rule_list):
        key, validated = _validate_metric_rule(item, f"rules.metric_rules[{index}]", metric_keys)
        if key in metric_rules:
            raise KpiCatalogError(f"rules.metric_rules[key={key}]: 重复指标规则")
        metric_rules[key] = validated
    _validate_formula_cycles(metric_rules)

    thresholds: list[dict[str, Any]] = []
    threshold_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(_require_array(rules["thresholds"], "rules.thresholds")):
        context = f"rules.thresholds[{index}]"
        raw = _require_object(item, context)
        _require_keys(raw, {"domain", "metric_key", "label", "direction", "default", "periods", "unit"}, context)
        domain = raw["domain"]
        if domain not in REGISTERED_DOMAINS:
            raise KpiCatalogError(f"{context}.domain: 非法业务域")
        _require_non_empty_str(raw["unit"], f"{context}.unit")
        metric_key = _require_non_empty_str(raw["metric_key"], f"{context}.metric_key")
        if metric_key not in metric_keys:
            raise KpiCatalogError(f"{context}.metric_key: 引用未知基础指标 {raw['metric_key']}")
        if (domain, metric_key) in threshold_keys:
            raise KpiCatalogError(f"{context}: domain+metric_key 重复")
        threshold_keys.add((domain, metric_key))
        _require_non_empty_str(raw["label"], f"{context}.label")
        if raw["direction"] not in _VALID_DIRECTIONS:
            raise KpiCatalogError(f"{context}.direction: 非法方向")
        _require_number(raw["default"], f"{context}.default")
        periods_raw = _require_object(raw["periods"], f"{context}.periods")
        for period_key, period_value in periods_raw.items():
            if period_key not in {"5", "15", "30", "60"}:
                raise KpiCatalogError(f"{context}.periods[{period_key}]: 非法周期")
            _require_number(period_value, f"{context}.periods[{period_key}]")
        thresholds.append(dict(raw))

    capacity_rules: list[dict[str, Any]] = []
    source_names: set[str] = set()
    for index, item in enumerate(_require_array(rules["capacity_rules"], "rules.capacity_rules")):
        context = f"rules.capacity_rules[{index}]"
        raw = _require_object(item, context)
        _require_keys(raw, {"source_name", "metric_key", "semantics", "status"}, context)
        raw.setdefault("domain", None)
        if raw["domain"] is not None and raw["domain"] not in REGISTERED_DOMAINS:
            raise KpiCatalogError(f"{context}.domain: 非法业务域")
        source_name = _require_non_empty_str(raw["source_name"], f"{context}.source_name")
        if source_name in source_names:
            raise KpiCatalogError(f"{context}.source_name: 重复源列名")
        source_names.add(source_name)
        if raw["metric_key"] not in metric_keys:
            raise KpiCatalogError(f"{context}.metric_key: 引用未知基础指标 {raw['metric_key']}")
        if raw["status"] not in _VALID_CAPACITY_STATUS:
            raise KpiCatalogError(f"{context}.status: 非法状态")
        if raw["status"] == "confirmed" and raw["semantics"] not in _VALID_SEMANTICS:
            raise KpiCatalogError(f"{context}.semantics: 非法容量语义")
        if raw["status"] == "unknown" and raw["semantics"] is not None:
            raise KpiCatalogError(f"{context}.semantics: unknown 状态应为 null")
        capacity_rules.append(dict(raw))

    display_rules: list[dict[str, Any]] = []
    display_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(_require_array(rules["display_rules"], "rules.display_rules")):
        context = f"rules.display_rules[{index}]"
        raw = _require_object(item, context)
        _require_keys(raw, {"domain", "metric_key", "role"}, context)
        if raw["domain"] not in REGISTERED_DOMAINS:
            raise KpiCatalogError(f"{context}.domain: 非法业务域")
        if raw["metric_key"] not in metric_keys:
            raise KpiCatalogError(f"{context}.metric_key: 引用未知基础指标 {raw['metric_key']}")
        if (raw["domain"], raw["metric_key"]) in display_keys:
            raise KpiCatalogError(f"{context}: domain+metric_key 重复")
        display_keys.add((raw["domain"], raw["metric_key"]))
        if raw["role"] not in _VALID_DISPLAY_ROLES:
            raise KpiCatalogError(f"{context}.role: 非法展示角色")
        display_rules.append(dict(raw))

    return KpiRuleSet(
        common={"input_timezone": timezone, "budgets": dict(budgets)},
        metric_rules=metric_rules,
        thresholds=thresholds,
        capacity_rules=capacity_rules,
        display_rules=display_rules,
    )


def _read_split_json(data_dir: Path, relative: str) -> tuple[dict[str, Any], bytes]:
    """读取一个固定拆分 JSON，拒绝重复字段并附带文件上下文。"""
    path = data_dir / relative
    try:
        file_bytes = path.read_bytes()
        raw = json.loads(file_bytes.decode("utf-8"), object_pairs_hook=_strict_object)
    except KpiCatalogError as exc:
        raise KpiCatalogError(f"{relative}: {exc}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KpiCatalogError(f"{relative}: 读取或解析失败: {exc}") from exc
    return _require_object(raw, relative), file_bytes


def _validate_split_file(raw: dict[str, Any], relative: str, container: str, *, with_hash: bool = False) -> list[Any]:
    """校验拆分文件公共顶层字段并返回配置数组。"""
    expected = {"schema_version", container, *({"source_csv_sha256"} if with_hash else set())}
    _require_keys(raw, expected, relative)
    if raw["schema_version"] != 1 or isinstance(raw["schema_version"], bool):
        raise KpiCatalogError(f"{relative}.schema_version: 当前只支持 1")
    if with_hash:
        _require_sha256(raw["source_csv_sha256"], f"{relative}.source_csv_sha256")
    return _require_array(raw[container], f"{relative}.{container}")


def load_kpi_catalog(path: Path | None = None) -> KpiGitCatalog:
    """读取并严格校验离线 KPI 基础资源；业务规则一律来自数据库。"""
    data_dir = path or settings.kpi_data
    raw_files: dict[str, dict[str, Any]] = {}
    file_bytes: dict[str, bytes] = {}
    for relative in KPI_BASE_FILES:
        raw_files[relative], file_bytes[relative] = _read_split_json(data_dir, relative)

    metric_items = _validate_split_file(raw_files["base/metrics.json"], "base/metrics.json", "metrics", with_hash=True)
    unit_items = _validate_split_file(raw_files["base/units.json"], "base/units.json", "units")

    metrics: dict[str, KpiBaseMetric] = {}
    used_ids: set[str] = set()
    for index, item in enumerate(metric_items):
        context = f"base/metrics.json: metrics[{index}]"
        resource_id, key, name_zh, name_en, unit_key = _validate_resource(item, context, "ME_", _METRIC_RESOURCE_RE)
        if resource_id in used_ids or key in metrics:
            raise KpiCatalogError(f"{context}: 资源 ID 或稳定 key 重复")
        used_ids.add(resource_id)
        metrics[key] = KpiBaseMetric(resource_id, key, name_zh, name_en, unit_key)

    units: dict[str, KpiReservedUnit] = {}
    for index, item in enumerate(unit_items):
        context = f"base/units.json: units[{index}]"
        resource_id, key, name_zh, name_en, _ = _validate_resource(item, context, "UNIT_", _UNIT_RESOURCE_RE)
        if resource_id in used_ids or key in metrics or key in units:
            raise KpiCatalogError(f"{context}: 资源 ID 或稳定 key 重复")
        used_ids.add(resource_id)
        units[key] = KpiReservedUnit(resource_id, key, name_zh, name_en)

    digest = hashlib.sha256()
    for relative in KPI_BASE_FILES:
        digest.update(relative.encode("utf-8") + b"\x00" + file_bytes[relative] + b"\x00")
    return KpiGitCatalog(
        schema_version=1,
        source_csv_sha256=raw_files["base/metrics.json"]["source_csv_sha256"],
        metrics=metrics,
        units=units,
        base_data_version=f"sha256:{digest.hexdigest()}",
    )


def build_kpi_config_from_catalog(
    catalog: KpiGitCatalog,
    classifications: dict[str, str],
    classification_version: int = 0,
) -> KpiConfig:
    """把 Git 基础/规则与数据库分类组合为任务执行目录。"""
    budgets_raw = catalog.rules.common["budgets"]
    budgets = {
        "max_file_bytes": 64 * 1024 * 1024,
        "max_rows_per_file": 100000,
        "max_columns_per_file": 256,
        "max_files_per_domain": int(budgets_raw["max_files"]),
        "max_records_per_domain": int(budgets_raw["max_records"]),
    }
    domains: dict[str, KpiDomainConfig] = {
        domain: KpiDomainConfig(domain, {}, {}, {}, {}, f"git-json+db:{domain}") for domain in REGISTERED_DOMAINS
    }
    for key, metric in catalog.metrics.items():
        domain = classifications.get(key)
        if domain not in REGISTERED_DOMAINS:
            continue
        rule = catalog.rules.metric_rules.get(key)
        if rule is None:
            definition = KpiMetricDefinition(
                key=key,
                name_zh=metric.name_zh,
                name_en=metric.name_en,
                metric_type="count",
                semantic_group="other",
                display_role="context",
                unit="",
                source_type="raw",
                aggregation=KpiAggregation("mean"),
                aliases=[],
            )
        else:
            aggregation_raw = rule["aggregation"]
            formula_raw = rule["formula"]
            formula = None
            if formula_raw is not None:
                fallback_raw = formula_raw["denominator_fallback"]
                formula = KpiRatioFormula(
                    numerator=formula_raw["numerator"],
                    denominator=formula_raw["denominator"],
                    denominator_fallback_inputs=list(fallback_raw["inputs"]) if fallback_raw else [],
                    scale=float(formula_raw["scale"]),
                )
            definition = KpiMetricDefinition(
                key=key,
                name_zh=metric.name_zh,
                name_en=metric.name_en,
                metric_type=str(rule["metric_type"]),
                semantic_group=str(rule["semantic_group"]),
                display_role=str(rule["display_role"]),
                unit=str(rule["unit"]),
                source_type=str(rule["source_type"]),
                aggregation=KpiAggregation(str(aggregation_raw["kind"]), aggregation_raw["quantile"]),
                aliases=[],
                description=rule["description"],
                formula=formula,
            )
        domains[domain].metrics[key] = definition
        domains[domain].alias_index[normalize_metric_name(metric.name_zh)] = key
        domains[domain].alias_index[normalize_metric_name(metric.name_en)] = key

    for rule in catalog.rules.thresholds:
        metric = domains[rule["domain"]].metrics.get(rule["metric_key"])
        if metric is None:
            continue
        unit = str(rule.get("unit", metric.unit))
        domains[rule["domain"]].thresholds[metric.key] = KpiThreshold(
            metric=metric.key,
            label=str(rule["label"]),
            direction=str(rule["direction"]),
            unit=unit,
            default=float(rule["default"]),
            periods={str(k): float(v) for k, v in rule["periods"].items()},
        )

    for rule in catalog.rules.capacity_rules:
        domain = classifications.get(rule["metric_key"])
        if domain not in REGISTERED_DOMAINS:
            continue
        domains[domain].capacity_metrics[rule["source_name"]] = {
            "metric": rule["metric_key"],
            "semantics": rule["semantics"],
            "status": rule["status"],
        }

    reserved_alias_index: dict[str, str] = {}
    for key, domain in classifications.items():
        if domain != "reserved" or key not in catalog.metrics:
            continue
        metric = catalog.metrics[key]
        for value in (metric.name_zh, metric.name_en, metric.key):
            reserved_alias_index[normalize_metric_name(value)] = key

    return KpiConfig(
        version=1,
        input_timezone=str(catalog.rules.common["input_timezone"]),
        budgets=budgets,
        domains=domains,
        config_source="git-json+db",
        base_data_version=catalog.base_data_version,
        classification_version=classification_version,
        reserved_metric_keys=frozenset(reserved_alias_index.values()),
        reserved_alias_index=reserved_alias_index,
    )
