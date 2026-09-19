"""基础指标配置查询、数据库分类和审计服务。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.inspectors.kpi.catalog import KpiCatalogError, KpiGitCatalog, load_kpi_catalog
from app.models.db import KpiClassification, KpiClassificationAudit, KpiClassificationRevision, session_factory
from app.models.schemas import (
    KpiClassificationAuditPageV3,
    KpiClassificationAuditV3,
    KpiResourceDomain,
    KpiResourceMetricPageV3,
    KpiResourceMetricV3,
)

VALID_DOMAINS = ("unclassified", "call", "api", "media")


class KpiResourceError(Exception):
    """基础指标配置服务错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


def _load_catalog() -> KpiGitCatalog:
    try:
        return load_kpi_catalog(settings.kpi_catalog)
    except KpiCatalogError as exc:
        raise KpiResourceError("kpi_catalog_invalid", str(exc), 500) from exc


def _classification_version(session: Session) -> int:
    revision = session.get(KpiClassificationRevision, 1)
    return int(revision.revision) if revision is not None else 0


def _ensure_revision(session: Session) -> KpiClassificationRevision:
    revision = session.get(KpiClassificationRevision, 1)
    if revision is None:
        revision = KpiClassificationRevision(id=1, revision=0, updated_at=datetime.now(UTC))
        session.add(revision)
        session.flush()
    return revision


def _domain_for(domain: str) -> str | None:
    return None if domain == "unclassified" else domain


def _display_domain(domain: str | None) -> str:
    return domain if domain in {"call", "api", "media"} else "unclassified"


def list_resource_metrics(
    *,
    search: str | None = None,
    domain: str | None = None,
    include_missing: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> KpiResourceMetricPageV3:
    """分页返回基础指标和当前分类状态，可选包含失效分类记录。"""
    if domain is not None and domain not in VALID_DOMAINS:
        raise KpiResourceError("invalid_domain", f"非法业务域: {domain}", 400)
    catalog = _load_catalog()
    try:
        with session_factory() as session:
            rows = session.query(KpiClassification).all()
            revision = _classification_version(session)
    except (OSError, SQLAlchemyError) as exc:
        raise KpiResourceError("database_unavailable", "KPI 分类数据库不可用", 400, {"reason": str(exc)}) from exc

    class Row:
        def __init__(
            self,
            *,
            key: str,
            resource_id: str,
            name_zh: str,
            name_en: str,
            record: KpiClassification | None,
            missing: bool,
        ) -> None:
            self.key = key
            self.resource_id = resource_id
            self.name_zh = name_zh
            self.name_en = name_en
            self.record = record
            self.missing = missing

        @property
        def current_domain(self) -> str:
            return _display_domain(self.record.domain if self.record else None)

        @property
        def searchable(self) -> str:
            return "\n".join((self.key, self.resource_id, self.name_zh, self.name_en)).casefold()

    all_rows = [
        Row(
            key=metric.key,
            resource_id=metric.resource_id,
            name_zh=metric.name_zh,
            name_en=metric.name_en,
            record=next((row for row in rows if row.metric_key == metric.key), None),
            missing=False,
        )
        for metric in catalog.metrics.values()
    ]
    base_keys = set(catalog.metrics)
    for record in rows:
        if record.metric_key in base_keys or not include_missing:
            continue
        all_rows.append(
            Row(
                key=record.metric_key,
                resource_id=record.metric_key.upper(),
                name_zh="(基础数据已移除)",
                name_en="(Missing from base)",
                record=record,
                missing=True,
            )
        )
    if search:
        normalized = search.casefold()
        all_rows = [row for row in all_rows if normalized in row.searchable]
    if domain:
        all_rows = [row for row in all_rows if row.current_domain == domain]
    all_rows.sort(key=lambda row: row.key)
    total = len(all_rows)
    start = (page - 1) * page_size
    page_rows = all_rows[start : start + page_size]
    now = datetime.now(UTC)
    summary = {name: 0 for name in VALID_DOMAINS}
    for metric_key in catalog.metrics:
        record = next((row for row in rows if row.metric_key == metric_key), None)
        summary[_display_domain(record.domain if record else None)] += 1
    return KpiResourceMetricPageV3(
        items=[
            KpiResourceMetricV3(
                key=row.key,
                resource_id=row.resource_id,
                name_zh=row.name_zh,
                name_en=row.name_en,
                domain=KpiResourceDomain(row.current_domain),
                missing_from_base=row.missing,
                created_at=row.record.created_at if row.record else now,
                updated_at=row.record.updated_at if row.record else now,
            )
            for row in page_rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        base_data_version=catalog.base_data_version,
        classification_version=revision,
        summary=summary,
    )


def _protected_metric_keys(catalog: KpiGitCatalog) -> set[str]:
    protected: set[str] = set()
    for rule in catalog.rules.metric_rules.values():
        formula = rule.get("formula")
        if not formula:
            continue
        fallback = formula.get("denominator_fallback") or {}
        protected.update(
            (
                formula["numerator"],
                formula["denominator"],
                *(fallback.get("inputs") or []),
            )
        )
    protected.update(rule["metric_key"] for rule in catalog.rules.thresholds)
    protected.update(rule["metric_key"] for rule in catalog.rules.capacity_rules)
    return protected


def classify_resource_metrics(
    metric_keys: list[str],
    *,
    domain: str,
    operator: str,
) -> dict[str, Any]:
    """整批原子保存分类状态、审计，并在成功后递增全局修订。"""
    if domain not in VALID_DOMAINS:
        raise KpiResourceError("invalid_domain", f"非法业务域: {domain}", 400)
    if not metric_keys or len(metric_keys) != len(set(metric_keys)):
        raise KpiResourceError("invalid_metric_keys", "metric_keys 必须非空且唯一", 400)
    if not operator or not operator.strip():
        raise KpiResourceError("invalid_operator", "operator 必须是非空字符串", 400)
    catalog = _load_catalog()
    protected = _protected_metric_keys(catalog)
    next_domain = _domain_for(domain)
    try:
        with session_factory() as session:
            missing = sorted(key for key in metric_keys if key not in catalog.metrics)
            if missing:
                raise KpiResourceError("metric_not_found", "指标不在当前基础数据中", 404, {"metric_keys": missing})
            records: dict[str, KpiClassification] = {}
            now = datetime.now(UTC)
            for key in metric_keys:
                record = session.get(KpiClassification, key)
                if record is None:
                    record = KpiClassification(metric_key=key, domain=None, created_at=now, updated_at=now)
                    session.add(record)
                    session.flush()
                records[key] = record
                previous = record.domain
                if previous is not None and previous != next_domain and key in protected:
                    raise KpiResourceError(
                        "metric_reference_protected",
                        f"指标 {key} 已被规则引用，不能变更分类",
                        409,
                        {"metric_key": key, "domain": previous},
                    )
            for key in metric_keys:
                record = records[key]
                previous = record.domain
                record.domain = next_domain
                record.updated_at = now
                session.add(
                    KpiClassificationAudit(
                        metric_key=key,
                        operation="unclassify" if next_domain is None else "classify",
                        operator=operator.strip(),
                        previous_domain=previous,
                        next_domain=next_domain,
                        result="success",
                        detail=None,
                        operated_at=now,
                    )
                )
            revision = _ensure_revision(session)
            revision.revision += 1
            revision.updated_at = now
            session.add(revision)
            session.commit()
            return {
                "classification_version": revision.revision,
                "domain": domain,
                "metric_keys": list(metric_keys),
                "audited_count": len(metric_keys),
            }
    except KpiResourceError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise KpiResourceError("database_unavailable", "KPI 分类数据库不可用", 400, {"reason": str(exc)}) from exc


def list_classification_audits(
    *,
    metric_key: str | None = None,
    operator: str | None = None,
    domain: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> KpiClassificationAuditPageV3:
    """按操作时间倒序分页查询分类审计。"""
    if domain is not None and domain not in VALID_DOMAINS:
        raise KpiResourceError("invalid_domain", f"非法业务域: {domain}", 400)
    try:
        with session_factory() as session:
            query = session.query(KpiClassificationAudit)
            if metric_key:
                query = query.filter(KpiClassificationAudit.metric_key == metric_key)
            if operator:
                query = query.filter(KpiClassificationAudit.operator == operator)
            if domain:
                query = query.filter(
                    KpiClassificationAudit.next_domain.is_(None)
                    if domain == "unclassified"
                    else KpiClassificationAudit.next_domain == domain
                )
            total = int(query.with_session(session).count() if False else query.count())
            rows = (
                query.order_by(KpiClassificationAudit.operated_at.desc(), KpiClassificationAudit.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
    except (OSError, SQLAlchemyError) as exc:
        raise KpiResourceError("database_unavailable", "KPI 分类数据库不可用", 400, {"reason": str(exc)}) from exc
    return KpiClassificationAuditPageV3(
        items=[
            KpiClassificationAuditV3(
                id=row.id,
                metric_key=row.metric_key,
                operation=row.operation,
                operator=row.operator,
                from_domain=_display_domain(row.previous_domain),
                to_domain=_display_domain(row.next_domain),
                result=row.result,
                operated_at=row.operated_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
