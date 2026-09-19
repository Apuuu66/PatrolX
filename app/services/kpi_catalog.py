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
    KpiBaseMetric,
    KpiCatalogError,
    KpiConfig,
    KpiGitCatalog,
    KpiRuleSet,
    build_kpi_config_from_catalog,
    load_kpi_catalog,
)
from app.models.db import KpiClassification, KpiClassificationRevision, session_factory
from app.models.schemas import KpiTaskCatalogSnapshot

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_RELATIVE_PATH = Path("kpi") / "kpi_catalog_snapshot.json"


class KpiSnapshotError(KpiCatalogError):
    """任务 KPI 配置快照服务错误。"""


def _read_classifications() -> tuple[dict[str, str], int]:
    try:
        with session_factory() as session:
            rows = session.query(KpiClassification).all()
            revision = session.get(KpiClassificationRevision, 1)
            classifications = {row.metric_key: row.domain for row in rows if row.domain in REGISTERED_DOMAINS}
            return classifications, int(revision.revision) if revision is not None else 0
    except (OSError, SQLAlchemyError) as exc:
        raise KpiSnapshotError(f"KPI 分类数据库不可用: {exc}") from exc


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
    return build_kpi_config_from_catalog(catalog, classifications, snapshot.classification_version)


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
        classifications, revision = _read_classifications()
        snapshot = KpiTaskCatalogSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            base_data_version=catalog.base_data_version,
            classification_version=revision,
            captured_at=datetime.now(UTC),
            metrics=_effective_metrics(catalog, classifications),
            rules=catalog.rules.to_dict(),
        )
        _atomic_write_snapshot(task_id, snapshot)
        return build_kpi_config_from_catalog(catalog, classifications, revision)
    except KpiCatalogError as exc:
        raise KpiSnapshotError(f"KPI 拆分配置无效: {exc}") from exc
    except (OSError, SQLAlchemyError) as exc:
        raise KpiSnapshotError(f"任务 KPI 配置快照写入失败: {exc}") from exc
