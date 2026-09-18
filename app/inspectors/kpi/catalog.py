"""KPI 指标字典、目录化配置模型与加载校验。"""

from __future__ import annotations

import re
import unicodedata
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KPI_CONFIG_DIR = Path("deploy/config/kpi")
REGISTERED_DOMAINS = ("call", "api", "media")
COMMON_FILE = "common.yaml"
_METRIC_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VALID_METRIC_TYPES = {"count", "rate", "capacity", "latency", "gauge"}
_VALID_SOURCE_TYPES = {"raw", "derived"}
_VALID_DISPLAY_ROLES = {"highlight", "context"}
_VALID_AGGREGATIONS = {
    "sum",
    "max",
    "percentile",
    "ratio_from_inputs",
    "last",
}
_VALID_LANGUAGES = {"zh", "en"}
_VALID_DIRECTIONS = {"min", "max"}
_VALID_CAPACITY_STATUS = {"confirmed", "unknown"}
_VALID_SEMANTICS = {"peak", "concurrency", "gauge"}
_BUDGET_KEYS = {
    "max_file_bytes",
    "max_rows_per_file",
    "max_columns_per_file",
    "max_files_per_domain",
    "max_records_per_domain",
}
_REQUIRED_CALL_METRICS = {
    "call_attempts",
    "call_success_count",
    "call_failure_count",
    "call_success_rate",
    "call_failure_rate",
}
_REQUIRED_CALL_THRESHOLDS = {"call_success_rate", "call_failure_rate"}


class KpiCatalogError(Exception):
    """KPI 目录配置错误。"""


def normalize_metric_name(value: str) -> str:
    """按配置契约归一化指标名；前缀匹配使用同一规则。"""
    normalized = unicodedata.normalize("NFKC", value).strip()
    return " ".join(normalized.split()).casefold()


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


def _numeric_values(values: list[Any]) -> tuple[list[float], bool]:
    """保留可解析数值；布尔值按配置口径视为非法。"""
    result: list[float] = []
    has_missing = False
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float):
            has_missing = True
            continue
        result.append(float(value))
    return result, has_missing


def _aggregate_values(kind: str, values: list[float], quantile: float | None = None) -> float:
    if kind == "sum":
        return sum(values)
    if kind == "max":
        return max(values)
    if kind == "percentile":
        if quantile is None:
            raise ValueError("percentile aggregation requires quantile")
        ordered = sorted(values)
        position = (len(ordered) - 1) * quantile
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    raise ValueError(f"unsupported aggregation kind: {kind}")


def _actual_aggregation(kind: str, quantile: float | None = None) -> str:
    if kind == "percentile":
        if quantile is None:
            raise ValueError("percentile aggregation requires quantile")
        percent = quantile * 100
        if percent.is_integer():
            return f"p{int(percent)}"
        return f"p{format(percent, '.15g')}"
    return kind


def _sum_input(values: list[Any]) -> float | None:
    numeric, _ = _numeric_values(values)
    return sum(numeric) if numeric else None


def _formula_text(formula: KpiRatioFormula) -> str:
    text = f"{formula.numerator} / {formula.denominator}"
    if formula.scale != 1:
        text += f" * {format(formula.scale, '.15g')}"
    return text


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
    """KPI 目录化配置，同时提供旧解析器所需的兼容视图。"""

    version: int
    input_timezone: str
    budgets: dict[str, int]
    domains: dict[str, KpiDomainConfig]
    config_source: str = "deploy/config/kpi"

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


def _read_yaml(path: Path, context: str) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KpiCatalogError(f"{context}: 配置读取或解析失败: {exc}") from exc


def _validate_common(raw: Any) -> tuple[int, str, dict[str, int]]:
    if not isinstance(raw, dict):
        raise KpiCatalogError("common.yaml: 顶层必须是字典")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise KpiCatalogError("common.version: 必须是整数")
    if version != 2:
        raise KpiCatalogError(f"common.version: 不支持的配置版本 {version}")
    timezone = raw.get("input_timezone")
    if not isinstance(timezone, str) or not timezone.strip():
        raise KpiCatalogError("common.input_timezone: 缺失或非法")
    try:
        zoneinfo.ZoneInfo(timezone)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise KpiCatalogError(f"common.input_timezone: 非法时区 {timezone}") from exc

    budgets_raw = raw.get("budgets")
    if not isinstance(budgets_raw, dict):
        raise KpiCatalogError("common.budgets: 缺失或非法")
    budgets: dict[str, int] = {}
    for key in _BUDGET_KEYS:
        value = budgets_raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise KpiCatalogError(f"common.budgets.{key}: 必须为正整数")
        budgets[key] = value
    if set(budgets_raw) - _BUDGET_KEYS:
        unknown = sorted(set(budgets_raw) - _BUDGET_KEYS)
        raise KpiCatalogError(f"common.budgets: 存在未知字段 {unknown}")
    return version, timezone, budgets


def _validate_metric(raw: Any, domain: str, index: int) -> KpiMetricDefinition:
    context = f"{domain}.metrics[{index}]"
    if not isinstance(raw, dict):
        raise KpiCatalogError(f"{context}: 必须是字典")
    key = raw.get("key")
    if not isinstance(key, str) or not _METRIC_KEY_RE.fullmatch(key):
        raise KpiCatalogError(f"{context}.key: 非法 {key}")
    context = f"{domain}.metrics[key={key}]"
    for field_name in ("name_zh", "name_en", "unit", "semantic_group"):
        if not isinstance(raw.get(field_name), str) or not raw[field_name].strip():
            raise KpiCatalogError(f"{context}.{field_name}: 缺失或非法")
    if raw.get("metric_type") not in _VALID_METRIC_TYPES:
        raise KpiCatalogError(f"{context}.metric_type: 非法 {raw.get('metric_type')}")
    if raw.get("display_role") not in _VALID_DISPLAY_ROLES:
        raise KpiCatalogError(f"{context}.display_role: 非法 {raw.get('display_role')}")
    if raw.get("source_type") not in _VALID_SOURCE_TYPES:
        raise KpiCatalogError(f"{context}.source_type: 非法 {raw.get('source_type')}")

    aggregation_raw = raw.get("aggregation")
    if not isinstance(aggregation_raw, dict) or aggregation_raw.get("kind") not in _VALID_AGGREGATIONS:
        raise KpiCatalogError(f"{context}.aggregation.kind: 非法")
    quantile = aggregation_raw.get("quantile")
    if quantile is not None and (
        isinstance(quantile, bool) or not isinstance(quantile, int | float) or not 0 <= quantile <= 1
    ):
        raise KpiCatalogError(f"{context}.aggregation.quantile: 必须在 [0,1]")

    # aliases 仅作为历史结果兼容字段保留；新配置不再登记别名，匹配只依赖 key 和中英文名。
    aliases: list[dict[str, str]] = []

    formula: KpiRatioFormula | None = None
    if raw.get("formula") is not None:
        formula_raw = raw["formula"]
        if not isinstance(formula_raw, dict) or formula_raw.get("kind") != "ratio":
            raise KpiCatalogError(f"{context}.formula.kind: 当前仅支持 ratio")
        for input_name in ("numerator", "denominator"):
            if not isinstance(formula_raw.get(input_name), str):
                raise KpiCatalogError(f"{context}.formula.{input_name}: 缺失")
        scale = formula_raw.get("scale", 1.0)
        if isinstance(scale, bool) or not isinstance(scale, int | float) or scale <= 0:
            raise KpiCatalogError(f"{context}.formula.scale: 必须为正数")
        fallback = formula_raw.get("denominator_fallback")
        fallback_inputs: list[str] = []
        if fallback is not None:
            if (
                not isinstance(fallback, dict)
                or fallback.get("kind") != "sum"
                or not isinstance(fallback.get("inputs"), list)
            ):
                raise KpiCatalogError(f"{context}.formula.denominator_fallback: 非法")
            fallback_inputs = fallback["inputs"]
        formula = KpiRatioFormula(
            numerator=formula_raw["numerator"],
            denominator=formula_raw["denominator"],
            denominator_fallback_inputs=fallback_inputs,
            scale=float(scale),
        )
    return KpiMetricDefinition(
        key=key,
        name_zh=raw["name_zh"],
        name_en=raw["name_en"],
        metric_type=raw["metric_type"],
        semantic_group=raw["semantic_group"],
        display_role=raw["display_role"],
        unit=raw["unit"],
        source_type=raw["source_type"],
        aggregation=KpiAggregation(kind=aggregation_raw["kind"], quantile=quantile),
        aliases=aliases,
        formula=formula,
    )


def _validate_domain_file(
    path: Path,
    domain: str,
) -> tuple[dict[str, KpiMetricDefinition], dict[str, KpiThreshold], dict[str, dict[str, Any]], dict[str, str]]:
    raw = _read_yaml(path, path.name)
    if not isinstance(raw, dict):
        raise KpiCatalogError(f"{domain}.yaml: 顶层必须是字典")
    if raw.get("domain") != domain:
        raise KpiCatalogError(f"{domain}.yaml: domain_mismatch 期望 {domain}，实际 {raw.get('domain')}")
    metrics_raw = raw.get("metrics", [])
    if not isinstance(metrics_raw, list):
        raise KpiCatalogError(f"{domain}.metrics: 必须是列表")
    metrics: dict[str, KpiMetricDefinition] = {}
    for index, item in enumerate(metrics_raw):
        metric = _validate_metric(item, domain, index)
        if metric.key in metrics:
            raise KpiCatalogError(f"{domain}.metrics[key={metric.key}]: 重复")
        metrics[metric.key] = metric

    # 候选索引沿用 alias_index 名称，避免内部配置模型和展示契约破坏兼容。
    alias_index: dict[str, str] = {}
    for metric in metrics.values():
        names = [metric.key, metric.name_zh, metric.name_en]
        for name in names:
            normalized = normalize_metric_name(name)
            if normalized in alias_index and alias_index[normalized] != metric.key:
                raise KpiCatalogError(f"{domain}.aliases[normalized={normalized}]: 已映射到 {alias_index[normalized]}")
            alias_index[normalized] = metric.key

    thresholds_raw = raw.get("thresholds", {})
    if not isinstance(thresholds_raw, dict):
        raise KpiCatalogError(f"{domain}.thresholds: 必须是字典")
    thresholds: dict[str, KpiThreshold] = {}
    for key, value in thresholds_raw.items():
        if key not in metrics:
            raise KpiCatalogError(f"{domain}.thresholds[{key}]: 引用未知指标")
        if not isinstance(value, dict):
            raise KpiCatalogError(f"{domain}.thresholds[{key}]: 必须是字典")
        direction = value.get("direction")
        if direction not in _VALID_DIRECTIONS:
            raise KpiCatalogError(f"{domain}.thresholds[{key}].direction: 非法")
        default = value.get("default")
        if isinstance(default, bool) or not isinstance(default, int | float):
            raise KpiCatalogError(f"{domain}.thresholds[{key}].default: 必须为数字")
        periods_raw = value.get("periods", {})
        if not isinstance(periods_raw, dict):
            raise KpiCatalogError(f"{domain}.thresholds[{key}].periods: 必须是字典")
        periods: dict[str, float] = {}
        for period_key, period_value in periods_raw.items():
            if (
                period_key not in {"5", "15", "30", "60"}
                or isinstance(period_value, bool)
                or not isinstance(period_value, int | float)
            ):
                raise KpiCatalogError(f"{domain}.thresholds[{key}].periods[{period_key}]: 非法")
            periods[period_key] = float(period_value)
        thresholds[key] = KpiThreshold(
            metric=key,
            label=str(value.get("label", metrics[key].name_zh)),
            direction=direction,
            unit=str(value.get("unit", metrics[key].unit)),
            default=float(default),
            periods=periods,
        )

    capacity_raw = raw.get("capacity_metrics", {})
    if not isinstance(capacity_raw, dict):
        raise KpiCatalogError(f"{domain}.capacity_metrics: 必须是字典")
    for source_name, value in capacity_raw.items():
        if not isinstance(value, dict) or value.get("metric") not in metrics:
            raise KpiCatalogError(f"{domain}.capacity_metrics[{source_name}].metric: 引用未知指标")
        status = value.get("status")
        semantics = value.get("semantics")
        semantics_valid = semantics in _VALID_SEMANTICS or (status == "unknown" and semantics is None)
        if not semantics_valid or status not in _VALID_CAPACITY_STATUS:
            raise KpiCatalogError(f"{domain}.capacity_metrics[{source_name}]: 非法容量语义或状态")

    formula_refs: dict[str, set[str]] = {}
    for metric in metrics.values():
        if metric.formula is not None:
            formula_refs[metric.key] = {
                metric.formula.numerator,
                metric.formula.denominator,
                *metric.formula.denominator_fallback_inputs,
            }
    for key, refs in formula_refs.items():
        missing = sorted(ref for ref in refs if ref not in metrics)
        if missing:
            raise KpiCatalogError(f"{domain}.metrics[key={key}].formula: 引用未知输入 {missing}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise KpiCatalogError(f"{domain}.metrics[key={key}].formula: 存在循环依赖")
        if key in visited:
            return
        visiting.add(key)
        for ref in formula_refs.get(key, set()):
            visit(ref)
        visiting.remove(key)
        visited.add(key)

    for key in formula_refs:
        visit(key)

    if domain == "call":
        missing_metrics = _REQUIRED_CALL_METRICS - set(metrics)
        if missing_metrics:
            raise KpiCatalogError(f"{domain}.metrics: 缺少必需兼容指标 {sorted(missing_metrics)}")
        missing_thresholds = _REQUIRED_CALL_THRESHOLDS - set(thresholds)
        if missing_thresholds:
            raise KpiCatalogError(f"{domain}.thresholds: 缺少必需阈值 {sorted(missing_thresholds)}")

    return metrics, thresholds, capacity_raw, alias_index


def load_kpi_catalog(config_dir: Path | None = None) -> KpiConfig:
    """读取并校验目录化 KPI 配置。"""
    directory = config_dir or KPI_CONFIG_DIR
    if not directory.is_dir():
        raise KpiCatalogError(f"KPI 配置目录不存在: {directory}")
    yaml_files = {path.name for path in directory.iterdir() if path.is_file() and path.suffix == ".yaml"}
    expected = {COMMON_FILE, *(f"{domain}.yaml" for domain in REGISTERED_DOMAINS)}
    unknown = sorted(yaml_files - expected)
    if unknown:
        raise KpiCatalogError(f"KPI 配置目录包含 unknown file: {unknown}")
    missing = sorted(expected - yaml_files)
    if missing:
        raise KpiCatalogError(f"KPI 配置目录缺少文件: {missing}")

    version, timezone, budgets = _validate_common(_read_yaml(directory / COMMON_FILE, COMMON_FILE))
    domains: dict[str, KpiDomainConfig] = {}
    for domain in REGISTERED_DOMAINS:
        metrics, thresholds, capacities, aliases = _validate_domain_file(directory / f"{domain}.yaml", domain)
        domains[domain] = KpiDomainConfig(
            domain=domain,
            metrics=metrics,
            thresholds=thresholds,
            capacity_metrics=capacities,
            alias_index=aliases,
            config_source=f"{directory.as_posix()}/{domain}.yaml",
        )
    return KpiConfig(version=version, input_timezone=timezone, budgets=budgets, domains=domains)
