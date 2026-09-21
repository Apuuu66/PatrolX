"""KPI Git/数据库组合、任务快照和任务执行目录服务。"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.inspectors.kpi.catalog import (
    REGISTERED_DOMAINS,
    KpiAggregation,
    KpiBaseMetric,
    KpiCatalogError,
    KpiConfig,
    KpiGitCatalog,
    KpiMetricDefinition,
    KpiRatioFormula,
    KpiRuleSet,
    _validate_rules,
    build_kpi_config_from_catalog,
    load_kpi_catalog,
    normalize_metric_name,
)
from app.models.db import (
    KpiCapacityRule,
    KpiClassification,
    KpiClassificationRevision,
    KpiCommonConfig,
    KpiDerivedMetric,
    KpiDisplayRule,
    KpiMetricFormula,
    KpiMetricRule,
    KpiRuleConfigRevision,
    KpiThresholdRule,
    session_factory,
)
from app.models.schemas import KpiTaskCatalogSnapshot

SNAPSHOT_SCHEMA_VERSION = 3
SNAPSHOT_RELATIVE_PATH = Path("kpi") / "kpi_catalog_snapshot.json"
SNAPSHOT_CLASSIFICATION_DOMAINS = set(REGISTERED_DOMAINS) | {"reserved"}


class KpiSnapshotError(KpiCatalogError):
    """任务 KPI 配置快照服务错误。"""


def _read_catalog_state() -> tuple[
    dict[str, str],
    int,
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    int,
]:
    """读取分类、动态规则、派生指标、公共配置和两个权威版本。"""
    try:
        with session_factory() as session:
            classification_rows = session.query(KpiClassification).all()
            classifications = {
                row.metric_key: row.domain
                for row in classification_rows
                if row.domain in SNAPSHOT_CLASSIFICATION_DOMAINS
            }
            classification_revision = session.get(KpiClassificationRevision, 1)
            classification_version = int(classification_revision.revision) if classification_revision else 0

            metric_rules: dict[str, dict[str, Any]] = {}
            for row in session.query(KpiMetricRule).order_by(KpiMetricRule.metric_key).all():
                formula = session.get(KpiMetricFormula, row.metric_key)
                metric_rules[row.metric_key] = {
                    "key": row.metric_key,
                    "metric_type": row.metric_type,
                    "semantic_group": row.semantic_group,
                    "display_role": row.display_role,
                    "unit": row.unit,
                    "source_type": row.source_type,
                    "description": row.description,
                    "aggregation": {"kind": row.aggregation_kind, "quantile": None},
                    "formula": None,
                }
                if formula is not None:
                    metric_rules[row.metric_key]["formula"] = {
                        "kind": "ratio",
                        "numerator": formula.numerator,
                        "denominator": formula.denominator,
                        "scale": float(formula.scale),
                        **(
                            {
                                "denominator_fallback": {
                                    "kind": "sum",
                                    "inputs": list(formula.denominator_fallback_inputs or []),
                                }
                            }
                            if formula.denominator_fallback_inputs
                            else {}
                        ),
                    }

            derived_metrics = [
                {
                    "metric_key": row.metric_key,
                    "name_zh": row.name_zh,
                    "name_en": row.name_en,
                    "domain": row.domain,
                    "metric_type": row.metric_type,
                    "semantic_group": row.semantic_group,
                    "display_role": row.display_role,
                    "unit": row.unit,
                    "description": row.description,
                    "enabled": bool(row.enabled),
                    "formula": {
                        "kind": row.formula_kind,
                        "numerator": row.numerator,
                        "denominator": row.denominator,
                        "denominator_fallback_inputs": list(row.denominator_fallback_inputs or []),
                        "scale": float(row.scale),
                    },
                }
                for row in session.query(KpiDerivedMetric)
                .filter(KpiDerivedMetric.enabled.is_(True))
                .order_by(KpiDerivedMetric.metric_key)
                .all()
            ]
            thresholds = [
                {
                    "domain": row.domain,
                    "metric_key": row.metric_key,
                    "label": row.label,
                    "direction": row.direction,
                    "unit": row.unit,
                    "default": float(row.default_value),
                    "periods": dict(row.periods or {}),
                }
                for row in session.query(KpiThresholdRule).order_by(KpiThresholdRule.id).all()
            ]
            capacity_rules = [
                {
                    "source_name": row.source_name,
                    "metric_key": row.metric_key,
                    "semantics": row.semantics,
                    "status": row.status,
                }
                for row in session.query(KpiCapacityRule).order_by(KpiCapacityRule.id).all()
            ]
            display_rules = [
                {
                    "domain": row.domain,
                    "metric_key": row.metric_key,
                    "role": row.role,
                }
                for row in session.query(KpiDisplayRule).order_by(KpiDisplayRule.id).all()
            ]

            common_row = session.get(KpiCommonConfig, 1)
            if common_row is None:
                common = {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 1000, "max_records": 200000}}
            else:
                common = {
                    "input_timezone": common_row.input_timezone,
                    "budgets": {"max_files": common_row.max_files, "max_records": common_row.max_records},
                }

            rule_revision = session.get(KpiRuleConfigRevision, 1)
            rule_config_version = int(rule_revision.revision) if rule_revision else 0
            return (
                classifications,
                classification_version,
                metric_rules,
                derived_metrics,
                thresholds,
                capacity_rules,
                display_rules,
                common,
                rule_config_version,
            )
    except (OSError, SQLAlchemyError) as exc:
        raise KpiSnapshotError(f"KPI 分类或规则配置数据库不可用: {exc}") from exc


def _default_rule() -> dict[str, Any]:
    return {
        "metric_type": "count",
        "semantic_group": "other",
        "display_role": "context",
        "unit": "",
        "source_type": "raw",
        "aggregation": {"kind": "sum", "quantile": None},
        "formula": None,
    }


def _effective_metrics(catalog: KpiGitCatalog, classifications: dict[str, str]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for key in sorted(catalog.metrics):
        domain = classifications.get(key)
        if domain not in REGISTERED_DOMAINS:
            continue
        metric = catalog.metrics[key]
        metrics.append(
            {
                "key": key,
                "resource_id": metric.resource_id,
                "name_zh": metric.name_zh,
                "name_en": metric.name_en,
                "domain": domain,
                "rule": dict(catalog.rules.metric_rules.get(key, _default_rule())),
            }
        )
    return metrics


def _snapshot_path(task_id: str) -> Path:
    return settings.output / task_id / SNAPSHOT_RELATIVE_PATH


def _atomic_write_snapshot(task_id: str, snapshot: KpiTaskCatalogSnapshot) -> None:
    path = _snapshot_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(snapshot.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def _inject_derived_metrics(config: KpiConfig, items: list[dict[str, Any]]) -> None:
    for item in items:
        domain = str(item["domain"])
        if domain not in REGISTERED_DOMAINS or not item.get("enabled", True):
            continue
        formula_raw = item["formula"]
        fallback_raw = formula_raw.get("denominator_fallback_inputs", [])
        definition = KpiMetricDefinition(
            key=str(item["metric_key"]),
            name_zh=str(item["name_zh"]),
            name_en=str(item["name_en"]),
            metric_type=str(item["metric_type"]),
            semantic_group=str(item["semantic_group"]),
            display_role=str(item["display_role"]),
            unit=str(item["unit"]),
            source_type="derived",
            aggregation=KpiAggregation("success_rate"),
            aliases=[],
            description=item.get("description"),
            formula=KpiRatioFormula(
                numerator=str(formula_raw["numerator"]),
                denominator=str(formula_raw["denominator"]),
                kind=str(formula_raw.get("kind", "ratio")),
                denominator_fallback_inputs=list(fallback_raw),
                scale=float(formula_raw["scale"]),
            ),
        )
        config.domains[domain].metrics[definition.key] = definition


def _config_from_snapshot(snapshot: KpiTaskCatalogSnapshot) -> KpiConfig:
    metrics: dict[str, Any] = {}
    classifications: dict[str, str] = {}
    for metric in snapshot.metrics:
        key = str(metric["key"])
        domain = str(metric["domain"])
        if domain not in REGISTERED_DOMAINS:
            continue
        resource_id = str(metric["resource_id"])
        metrics[key] = KpiBaseMetric(
            resource_id=resource_id,
            key=key,
            name_zh=str(metric["name_zh"]),
            name_en=str(metric["name_en"]),
            unit_key=None,
        )
        classifications[key] = domain
    rules_raw = snapshot.rules
    metric_rules = {str(rule["key"]): rule for rule in rules_raw.get("metric_rules", []) if "key" in rule}
    rules = KpiRuleSet(
        common=dict(rules_raw.get("common", {})),
        metric_rules=metric_rules,
        thresholds=[dict(rule) for rule in rules_raw.get("thresholds", [])],
        capacity_rules=[dict(rule) for rule in rules_raw.get("capacity_rules", [])],
        display_rules=[dict(rule) for rule in rules_raw.get("display_rules", [])],
    )
    catalog = KpiGitCatalog(
        schema_version=1,
        source_csv_sha256="0" * 64,
        metrics=metrics,
        units={},
        rules=rules,
        base_data_version=snapshot.base_data_version,
    )
    config = build_kpi_config_from_catalog(catalog, classifications, snapshot.classification_version)
    config.reserved_metric_keys = frozenset(snapshot.reserved_metric_keys)
    config.reserved_alias_index = {
        normalize_metric_name(str(metric.get(name_field, ""))): str(metric["key"])
        for metric in snapshot.base_metrics
        if metric.get("key") in snapshot.reserved_metric_keys
        for name_field in ("name_zh", "name_en", "key")
        if metric.get(name_field)
    }
    _inject_derived_metrics(config, snapshot.derived_metrics)
    return config


def _base_metric_items(catalog: KpiGitCatalog) -> list[dict[str, Any]]:
    return [
        {
            "resource_id": metric.resource_id,
            "key": metric.key,
            "name_zh": metric.name_zh,
            "name_en": metric.name_en,
            "unit_key": metric.unit_key,
        }
        for _, metric in sorted(catalog.metrics.items())
    ]


def load_task_kpi_config(task_id: str) -> KpiConfig:
    """读取或补写任务 KPI 快照，并返回任务执行用有效目录。"""
    path = _snapshot_path(task_id)
    if path.is_file():
        try:
            snapshot = KpiTaskCatalogSnapshot.model_validate_json(path.read_bytes())
            return _config_from_snapshot(snapshot)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise KpiSnapshotError(f"任务 KPI 配置快照损坏: {path}: {exc}") from exc

    try:
        catalog = load_kpi_catalog(settings.kpi_data)
        (
            classifications,
            classification_version,
            metric_rules,
            derived_metrics,
            thresholds,
            capacity_rules,
            display_rules,
            common,
            rule_config_version,
        ) = _read_catalog_state()
        catalog.rules = KpiRuleSet(
            common=common,
            metric_rules=metric_rules,
            thresholds=thresholds,
            capacity_rules=capacity_rules,
            display_rules=display_rules,
        )
        _validate_rules(catalog.rules.to_dict(), set(catalog.metrics))
        reserved_metric_keys = sorted(
            key for key, domain in classifications.items() if domain == "reserved" and key in catalog.metrics
        )
        snapshot = KpiTaskCatalogSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            base_data_version=catalog.base_data_version,
            classification_version=classification_version,
            rule_config_version=rule_config_version,
            captured_at=datetime.now(UTC),
            base_metrics=_base_metric_items(catalog),
            metrics=_effective_metrics(catalog, classifications),
            reserved_metric_keys=reserved_metric_keys,
            rules=catalog.rules.to_dict(),
            derived_metrics=derived_metrics,
        )
        _atomic_write_snapshot(task_id, snapshot)
        config = build_kpi_config_from_catalog(catalog, classifications, classification_version)
        _inject_derived_metrics(config, derived_metrics)
        return config
    except KpiCatalogError as exc:
        raise KpiSnapshotError(f"KPI 基础资源或动态配置无效: {exc}") from exc
    except (OSError, SQLAlchemyError) as exc:
        raise KpiSnapshotError(f"任务 KPI 配置快照写入失败: {exc}") from exc
