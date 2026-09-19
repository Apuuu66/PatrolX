"""KPI 动态口径配置服务：SQLite 是分类之外业务口径的唯一权威来源。"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.inspectors.kpi.catalog import REGISTERED_DOMAINS, load_kpi_catalog
from app.models.db import (
    KpiCapacityRule,
    KpiClassification,
    KpiCommonConfig,
    KpiDisplayRule,
    KpiMetricFormula,
    KpiMetricRule,
    KpiRuleConfigAudit,
    KpiRuleConfigRevision,
    KpiThresholdRule,
    session_factory,
)
from app.models.schemas import (
    KpiCapacityRulePageV4,
    KpiCapacityRuleRequestV4,
    KpiCapacityRuleV4,
    KpiCommonConfigRequestV4,
    KpiCommonConfigV4,
    KpiConfigDeleteResultV4,
    KpiDisplayRulePageV4,
    KpiDisplayRuleRequestV4,
    KpiDisplayRuleV4,
    KpiFormulaV4,
    KpiMetricRulePageV4,
    KpiMetricRuleRequestV4,
    KpiMetricRuleV4,
    KpiThresholdPageV4,
    KpiThresholdRequestV4,
    KpiThresholdV4,
)

RAW_AGGREGATIONS = {"sum", "min", "max", "mean", "count", "median", "stddev"}
PERIOD_KEYS = {"5", "15", "30", "60"}


class KpiConfigError(Exception):
    """带错误码的 KPI 配置业务错误。"""

    def __init__(self, code: str, message: str, status_code: int = 400, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}


def _now() -> datetime:
    return datetime.now(UTC)


def _database_unavailable(exc: Exception) -> KpiConfigError:
    return KpiConfigError(
        "kpi_config_database_unavailable",
        "KPI 配置数据库不可用",
        500,
        {"reason": str(exc)},
    )


def _model_dump(model: BaseModel) -> dict:
    return model.model_dump(mode="json", exclude={"operator"})


def _base_metric_keys() -> set[str]:
    """读取离线基础资源全集；在线配置不得新增或删除指标。"""
    return set(load_kpi_catalog().metrics)


def _classification_domains() -> dict[str, str]:
    try:
        with session_factory() as session:
            rows = session.query(KpiClassification).all()
            return {row.metric_key: row.domain for row in rows if row.domain in REGISTERED_DOMAINS}
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def _assert_base_metric(metric_key: str) -> None:
    if metric_key not in _base_metric_keys():
        raise KpiConfigError("kpi_metric_not_registered", f"基础指标不存在: {metric_key}", 404)


def _require_domain(metric_key: str) -> str:
    domain = _classification_domains().get(metric_key)
    if domain not in REGISTERED_DOMAINS:
        raise KpiConfigError("kpi_metric_not_classified", f"基础指标尚未分类: {metric_key}", 409)
    return domain


def _revision(session) -> int:
    revision = session.get(KpiRuleConfigRevision, 1)
    if revision is None:
        revision = KpiRuleConfigRevision(id=1, revision=0, updated_at=_now())
        session.add(revision)
        session.flush()
    return int(revision.revision)


def _increment_revision(session) -> int:
    revision = session.get(KpiRuleConfigRevision, 1)
    if revision is None:
        revision = KpiRuleConfigRevision(id=1, revision=0, updated_at=_now())
        session.add(revision)
        session.flush()
    revision.revision += 1
    revision.updated_at = _now()
    return int(revision.revision)


def _audit(
    session,
    *,
    entity_type: str,
    entity_key: str,
    operation: str,
    operator: str,
    before: dict | None,
    after: dict | None,
    version: int,
    detail: dict | None = None,
) -> None:
    session.add(
        KpiRuleConfigAudit(
            entity_type=entity_type,
            entity_key=entity_key,
            operation=operation,
            operator=operator,
            before=before,
            after=after,
            result="success",
            rule_config_version=version,
            detail=detail,
            operated_at=_now(),
        )
    )


def _validate_formula_references(formula: KpiFormulaV4, metric_key: str) -> None:
    references = [formula.numerator, formula.denominator, *formula.denominator_fallback_inputs]
    if metric_key in references:
        raise KpiConfigError("kpi_formula_cycle", "派生公式不能引用自身", 409)
    base_keys = _base_metric_keys()
    missing = sorted({key for key in references if key not in base_keys})
    if missing:
        raise KpiConfigError("kpi_formula_unknown_input", f"公式引用未知基础指标: {missing}", 400, {"keys": missing})


def _validate_no_formula_cycles(session, metric_key: str) -> None:
    rules = {row.metric_key: row for row in session.query(KpiMetricRule).all()}
    formulas = {row.metric_key: row for row in session.query(KpiMetricFormula).all()}
    formulas[metric_key] = formulas.get(metric_key) or KpiMetricFormula(
        metric_key=metric_key,
        numerator="",
        denominator="",
        denominator_fallback_inputs=[],
        scale=1.0,
        created_at=_now(),
        updated_at=_now(),
    )
    references: dict[str, set[str]] = {}
    for key, formula in formulas.items():
        references[key] = {formula.numerator, formula.denominator, *formula.denominator_fallback_inputs}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise KpiConfigError("kpi_formula_cycle", f"派生公式存在循环引用: {key}", 409)
        if key in visited:
            return
        visiting.add(key)
        for ref in references.get(key, set()):
            if ref in references:
                visit(ref)
        visiting.remove(key)
        visited.add(key)

    visit(metric_key)
    del rules


def _validate_formula_inputs_are_raw(session, formula: KpiFormulaV4) -> None:
    keys = {formula.numerator, formula.denominator, *formula.denominator_fallback_inputs}
    rows = session.query(KpiMetricRule).filter(KpiMetricRule.metric_key.in_(keys)).all()
    derived = sorted(row.metric_key for row in rows if row.source_type == "derived")
    if derived:
        raise KpiConfigError("kpi_formula_input_derived", f"公式输入必须是 raw 指标: {derived}", 409)


def _metric_rule_dict(row: KpiMetricRule, formula: KpiMetricFormula | None) -> dict:
    return {
        "metric_key": row.metric_key,
        "metric_type": row.metric_type,
        "semantic_group": row.semantic_group,
        "display_role": row.display_role,
        "unit": row.unit,
        "source_type": row.source_type,
        "aggregation_kind": row.aggregation_kind,
        "description": row.description,
        "formula": None
        if formula is None
        else {
            "kind": "ratio",
            "numerator": formula.numerator,
            "denominator": formula.denominator,
            "denominator_fallback_inputs": list(formula.denominator_fallback_inputs or []),
            "scale": float(formula.scale),
        },
    }


def _metric_rule_model(
    row: KpiMetricRule, formula: KpiMetricFormula | None, domain: str, version: int
) -> KpiMetricRuleV4:
    return KpiMetricRuleV4(
        **_metric_rule_dict(row, formula),
        domain=domain,  # type: ignore[arg-type]
        updated_at=row.updated_at,
        rule_config_version=version,
    )


def list_metric_rules(
    *,
    search: str | None = None,
    source_type: str | None = None,
    domain: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> KpiMetricRulePageV4:
    try:
        with session_factory() as session:
            rows = session.query(KpiMetricRule).order_by(KpiMetricRule.metric_key).all()
            formulas = {row.metric_key: row for row in session.query(KpiMetricFormula).all()}
            domains = _classification_domains()
            version = _revision(session)
            items = []
            for row in rows:
                item_domain = domains.get(row.metric_key)
                if domain is not None and item_domain != domain:
                    continue
                metric = KpiMetricRuleV4(
                    **_metric_rule_dict(row, formulas.get(row.metric_key)),
                    domain=item_domain,  # type: ignore[arg-type]
                    updated_at=row.updated_at,
                    rule_config_version=version,
                )
                if search and search.casefold() not in metric.metric_key.casefold():
                    continue
                if source_type and row.source_type != source_type:
                    continue
                items.append(metric)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc
    total = len(items)
    start = (page - 1) * page_size
    return KpiMetricRulePageV4(
        items=items[start : start + page_size], total=total, page=page, page_size=page_size, rule_config_version=version
    )


def get_metric_rule(metric_key: str) -> KpiMetricRuleV4:
    try:
        with session_factory() as session:
            row = session.get(KpiMetricRule, metric_key)
            if row is None:
                raise KpiConfigError("kpi_metric_rule_not_found", f"指标规则不存在: {metric_key}", 404)
            formula = session.get(KpiMetricFormula, metric_key)
            version = _revision(session)
            return _metric_rule_model(row, formula, _require_domain(metric_key), version)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def upsert_metric_rule(metric_key: str, body: KpiMetricRuleRequestV4) -> KpiMetricRuleV4:
    _assert_base_metric(metric_key)
    domain = _require_domain(metric_key)
    if body.source_type == "raw":
        if body.formula is not None:
            raise KpiConfigError("kpi_metric_rule_invalid", "raw 指标不能配置公式", 400)
        if body.aggregation_kind not in RAW_AGGREGATIONS:
            raise KpiConfigError("kpi_metric_rule_invalid", "raw 指标只支持受控聚合", 400)
    else:
        if body.formula is None:
            raise KpiConfigError("kpi_metric_rule_invalid", "derived 指标必须配置 ratio 公式", 400)
        if body.aggregation_kind != "success_rate":
            raise KpiConfigError("kpi_metric_rule_invalid", "derived 指标必须使用 success_rate", 400)
        _validate_formula_references(body.formula, metric_key)
    try:
        with session_factory() as session, session.begin():
            existing = session.get(KpiMetricRule, metric_key)
            old = _metric_rule_dict(existing, session.get(KpiMetricFormula, metric_key)) if existing else None
            now = _now()
            row = existing or KpiMetricRule(metric_key=metric_key, created_at=now, updated_at=now)
            row.metric_type = body.metric_type.value
            row.semantic_group = body.semantic_group.value
            row.display_role = body.display_role.value
            row.unit = body.unit
            row.source_type = body.source_type.value
            row.aggregation_kind = body.aggregation_kind.value
            row.description = body.description
            row.updated_at = now
            session.add(row)

            formula_row = session.get(KpiMetricFormula, metric_key)
            if body.formula is None:
                if formula_row is not None:
                    session.delete(formula_row)
            else:
                _validate_formula_inputs_are_raw(session, body.formula)
                formula_row = formula_row or KpiMetricFormula(metric_key=metric_key, created_at=now, updated_at=now)
                formula_row.numerator = body.formula.numerator
                formula_row.denominator = body.formula.denominator
                formula_row.denominator_fallback_inputs = list(dict.fromkeys(body.formula.denominator_fallback_inputs))
                formula_row.scale = body.formula.scale
                formula_row.updated_at = now
                session.add(formula_row)
                session.flush()
                _validate_no_formula_cycles(session, metric_key)

            version = _increment_revision(session)
            new = _metric_rule_dict(row, session.get(KpiMetricFormula, metric_key))
            _audit(
                session,
                entity_type="metric_rule",
                entity_key=metric_key,
                operation="upsert",
                operator=body.operator,
                before=old,
                after=new,
                version=version,
            )
            return _metric_rule_model(row, session.get(KpiMetricFormula, metric_key), domain, version)
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def delete_metric_rule(metric_key: str, operator: str) -> KpiConfigDeleteResultV4:
    try:
        with session_factory() as session, session.begin():
            row = session.get(KpiMetricRule, metric_key)
            if row is None:
                raise KpiConfigError("kpi_metric_rule_not_found", f"指标规则不存在: {metric_key}", 404)
            old = _metric_rule_dict(row, session.get(KpiMetricFormula, metric_key))
            formula = session.get(KpiMetricFormula, metric_key)
            if formula is not None:
                session.delete(formula)
            session.delete(row)
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="metric_rule",
                entity_key=metric_key,
                operation="delete",
                operator=operator,
                before=old,
                after=None,
                version=version,
            )
            return KpiConfigDeleteResultV4(
                deleted=True,
                entity_type="metric_rule",
                entity_key=metric_key,
                rule_config_version=version,
            )
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def _threshold_dict(row: KpiThresholdRule) -> dict:
    return {
        "id": row.id,
        "domain": row.domain,
        "metric_key": row.metric_key,
        "label": row.label,
        "direction": row.direction,
        "unit": row.unit,
        "default": float(row.default_value),
        "periods": dict(row.periods or {}),
    }


def _threshold_model(row: KpiThresholdRule, version: int) -> KpiThresholdV4:
    return KpiThresholdV4(**_threshold_dict(row), updated_at=row.updated_at, rule_config_version=version)


def list_thresholds(
    *, domain: str | None = None, search: str | None = None, page: int = 1, page_size: int = 20
) -> KpiThresholdPageV4:
    try:
        with session_factory() as session:
            rows = session.query(KpiThresholdRule).order_by(KpiThresholdRule.id).all()
            version = _revision(session)
            items = [
                _threshold_model(row, version)
                for row in rows
                if (domain is None or row.domain == domain)
                and (search is None or search.casefold() in f"{row.metric_key} {row.label}".casefold())
            ]
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc
    total = len(items)
    start = (page - 1) * page_size
    return KpiThresholdPageV4(
        items=items[start : start + page_size], total=total, page=page, page_size=page_size, rule_config_version=version
    )


def get_threshold(threshold_id: int) -> KpiThresholdV4:
    try:
        with session_factory() as session:
            row = session.get(KpiThresholdRule, threshold_id)
            if row is None:
                raise KpiConfigError("kpi_threshold_not_found", f"阈值不存在: {threshold_id}", 404)
            return _threshold_model(row, _revision(session))
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def _validate_threshold_periods(periods: dict[str, float]) -> None:
    invalid = sorted(set(periods) - PERIOD_KEYS)
    if invalid:
        raise KpiConfigError("kpi_threshold_period_invalid", f"阈值周期只能是 5/15/30/60 分钟: {invalid}", 400)


def create_threshold(body: KpiThresholdRequestV4) -> KpiThresholdV4:
    _assert_base_metric(body.metric_key)
    _require_domain(body.metric_key)
    _validate_threshold_periods(body.periods)
    try:
        with session_factory() as session, session.begin():
            duplicate = (
                session.query(KpiThresholdRule)
                .filter(KpiThresholdRule.domain == body.domain.value, KpiThresholdRule.metric_key == body.metric_key)
                .one_or_none()
            )
            if duplicate is not None:
                raise KpiConfigError("kpi_threshold_duplicate", "同一业务域和指标已有阈值", 409)
            now = _now()
            row = KpiThresholdRule(
                domain=body.domain.value,
                metric_key=body.metric_key,
                label=body.label,
                direction=body.direction.value,
                unit=body.unit,
                default_value=body.default,
                periods=dict(body.periods),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="threshold",
                entity_key=str(row.id),
                operation="upsert",
                operator=body.operator,
                before=None,
                after=_threshold_dict(row),
                version=version,
            )
            return _threshold_model(row, version)
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def update_threshold(threshold_id: int, body: KpiThresholdRequestV4) -> KpiThresholdV4:
    _assert_base_metric(body.metric_key)
    _require_domain(body.metric_key)
    _validate_threshold_periods(body.periods)
    try:
        with session_factory() as session, session.begin():
            row = session.get(KpiThresholdRule, threshold_id)
            if row is None:
                raise KpiConfigError("kpi_threshold_not_found", f"阈值不存在: {threshold_id}", 404)
            duplicate = (
                session.query(KpiThresholdRule)
                .filter(
                    KpiThresholdRule.domain == body.domain.value,
                    KpiThresholdRule.metric_key == body.metric_key,
                    KpiThresholdRule.id != threshold_id,
                )
                .one_or_none()
            )
            if duplicate is not None:
                raise KpiConfigError("kpi_threshold_duplicate", "同一业务域和指标已有阈值", 409)
            before = _threshold_dict(row)
            row.domain = body.domain.value
            row.metric_key = body.metric_key
            row.label = body.label
            row.direction = body.direction.value
            row.unit = body.unit
            row.default_value = body.default
            row.periods = dict(body.periods)
            row.updated_at = _now()
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="threshold",
                entity_key=str(row.id),
                operation="upsert",
                operator=body.operator,
                before=before,
                after=_threshold_dict(row),
                version=version,
            )
            return _threshold_model(row, version)
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def delete_threshold(threshold_id: int, operator: str) -> KpiConfigDeleteResultV4:
    try:
        with session_factory() as session, session.begin():
            row = session.get(KpiThresholdRule, threshold_id)
            if row is None:
                raise KpiConfigError("kpi_threshold_not_found", f"阈值不存在: {threshold_id}", 404)
            before = _threshold_dict(row)
            session.delete(row)
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="threshold",
                entity_key=str(threshold_id),
                operation="delete",
                operator=operator,
                before=before,
                after=None,
                version=version,
            )
            return KpiConfigDeleteResultV4(
                deleted=True, entity_type="threshold", entity_key=str(threshold_id), rule_config_version=version
            )
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def _capacity_dict(row: KpiCapacityRule) -> dict:
    return {
        "id": row.id,
        "source_name": row.source_name,
        "metric_key": row.metric_key,
        "domain": row.domain,
        "status": row.status,
        "semantics": row.semantics,
    }


def _capacity_model(row: KpiCapacityRule, version: int) -> KpiCapacityRuleV4:
    return KpiCapacityRuleV4(**_capacity_dict(row), updated_at=row.updated_at, rule_config_version=version)


def list_capacity_rules(*, page: int = 1, page_size: int = 20) -> KpiCapacityRulePageV4:
    try:
        with session_factory() as session:
            rows = session.query(KpiCapacityRule).order_by(KpiCapacityRule.id).all()
            version = _revision(session)
            items = [_capacity_model(row, version) for row in rows]
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc
    total = len(items)
    start = (page - 1) * page_size
    return KpiCapacityRulePageV4(
        items=items[start : start + page_size], total=total, page=page, page_size=page_size, rule_config_version=version
    )


def upsert_capacity_rule(body: KpiCapacityRuleRequestV4, rule_id: int | None = None) -> KpiCapacityRuleV4:
    _assert_base_metric(body.metric_key)
    if body.status == "confirmed" and body.semantics is None:
        raise KpiConfigError("kpi_capacity_invalid", "确认容量规则必须设置语义", 400)
    if body.status == "unknown" and body.semantics is not None:
        raise KpiConfigError("kpi_capacity_invalid", "未知容量规则不能设置语义", 400)
    try:
        with session_factory() as session, session.begin():
            duplicate = session.query(KpiCapacityRule).filter(KpiCapacityRule.source_name == body.source_name)
            if rule_id is not None:
                duplicate = duplicate.filter(KpiCapacityRule.id != rule_id)
            if duplicate.one_or_none() is not None:
                raise KpiConfigError("kpi_capacity_duplicate", "容量源列名称已存在", 409)
            now = _now()
            row = session.get(KpiCapacityRule, rule_id) if rule_id is not None else None
            if row is None and rule_id is not None:
                raise KpiConfigError("kpi_capacity_not_found", f"容量规则不存在: {rule_id}", 404)
            old = _capacity_dict(row) if row is not None else None
            row = row or KpiCapacityRule(source_name=body.source_name, created_at=now, updated_at=now)
            row.source_name = body.source_name
            row.metric_key = body.metric_key
            row.domain = body.domain.value if body.domain is not None else None
            row.status = body.status.value
            row.semantics = body.semantics.value if body.semantics is not None else None
            row.updated_at = now
            session.add(row)
            session.flush()
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="capacity_rule",
                entity_key=str(row.id),
                operation="upsert",
                operator=body.operator,
                before=old,
                after=_capacity_dict(row),
                version=version,
            )
            return _capacity_model(row, version)
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def delete_capacity_rule(rule_id: int, operator: str) -> KpiConfigDeleteResultV4:
    try:
        with session_factory() as session, session.begin():
            row = session.get(KpiCapacityRule, rule_id)
            if row is None:
                raise KpiConfigError("kpi_capacity_not_found", f"容量规则不存在: {rule_id}", 404)
            before = _capacity_dict(row)
            session.delete(row)
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="capacity_rule",
                entity_key=str(rule_id),
                operation="delete",
                operator=operator,
                before=before,
                after=None,
                version=version,
            )
            return KpiConfigDeleteResultV4(
                deleted=True, entity_type="capacity_rule", entity_key=str(rule_id), rule_config_version=version
            )
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def _display_dict(row: KpiDisplayRule) -> dict:
    return {"id": row.id, "domain": row.domain, "metric_key": row.metric_key, "role": row.role}


def _display_model(row: KpiDisplayRule, version: int) -> KpiDisplayRuleV4:
    return KpiDisplayRuleV4(**_display_dict(row), updated_at=row.updated_at, rule_config_version=version)


def list_display_rules(*, domain: str | None = None, page: int = 1, page_size: int = 20) -> KpiDisplayRulePageV4:
    try:
        with session_factory() as session:
            rows = session.query(KpiDisplayRule).order_by(KpiDisplayRule.id).all()
            version = _revision(session)
            items = [_display_model(row, version) for row in rows if domain is None or row.domain == domain]
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc
    total = len(items)
    start = (page - 1) * page_size
    return KpiDisplayRulePageV4(
        items=items[start : start + page_size], total=total, page=page, page_size=page_size, rule_config_version=version
    )


def upsert_display_rule(body: KpiDisplayRuleRequestV4, rule_id: int | None = None) -> KpiDisplayRuleV4:
    _assert_base_metric(body.metric_key)
    _require_domain(body.metric_key)
    try:
        with session_factory() as session, session.begin():
            duplicate = session.query(KpiDisplayRule).filter(
                KpiDisplayRule.domain == body.domain.value, KpiDisplayRule.metric_key == body.metric_key
            )
            if rule_id is not None:
                duplicate = duplicate.filter(KpiDisplayRule.id != rule_id)
            if duplicate.one_or_none() is not None:
                raise KpiConfigError("kpi_display_duplicate", "同一业务域和指标已有展示规则", 409)
            now = _now()
            row = session.get(KpiDisplayRule, rule_id) if rule_id is not None else None
            if row is None and rule_id is not None:
                raise KpiConfigError("kpi_display_not_found", f"展示规则不存在: {rule_id}", 404)
            old = _display_dict(row) if row is not None else None
            row = row or KpiDisplayRule(created_at=now, updated_at=now)
            row.domain = body.domain.value
            row.metric_key = body.metric_key
            row.role = body.role.value
            row.updated_at = now
            session.add(row)
            session.flush()
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="display_rule",
                entity_key=str(row.id),
                operation="upsert",
                operator=body.operator,
                before=old,
                after=_display_dict(row),
                version=version,
            )
            return _display_model(row, version)
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def delete_display_rule(rule_id: int, operator: str) -> KpiConfigDeleteResultV4:
    try:
        with session_factory() as session, session.begin():
            row = session.get(KpiDisplayRule, rule_id)
            if row is None:
                raise KpiConfigError("kpi_display_not_found", f"展示规则不存在: {rule_id}", 404)
            before = _display_dict(row)
            session.delete(row)
            version = _increment_revision(session)
            _audit(
                session,
                entity_type="display_rule",
                entity_key=str(rule_id),
                operation="delete",
                operator=operator,
                before=before,
                after=None,
                version=version,
            )
            return KpiConfigDeleteResultV4(
                deleted=True, entity_type="display_rule", entity_key=str(rule_id), rule_config_version=version
            )
    except KpiConfigError:
        raise
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def get_common_config() -> KpiCommonConfigV4:
    try:
        with session_factory() as session, session.begin():
            row = session.get(KpiCommonConfig, 1)
            if row is None:
                row = KpiCommonConfig(
                    id=1, input_timezone="Asia/Shanghai", max_files=1000, max_records=200000, updated_at=_now()
                )
                session.add(row)
                session.flush()
            version = _revision(session)
            return KpiCommonConfigV4(
                input_timezone=row.input_timezone,
                max_files=row.max_files,
                max_records=row.max_records,
                updated_at=row.updated_at,
                rule_config_version=version,
            )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def update_common_config(body: KpiCommonConfigRequestV4) -> KpiCommonConfigV4:
    try:
        ZoneInfo(body.input_timezone)
    except ZoneInfoNotFoundError as exc:
        raise KpiConfigError("kpi_common_timezone_invalid", "输入时区无效", 400) from exc
    try:
        with session_factory() as session, session.begin():
            row = session.get(KpiCommonConfig, 1)
            if row is None:
                row = KpiCommonConfig(
                    id=1, input_timezone="Asia/Shanghai", max_files=1000, max_records=200000, updated_at=_now()
                )
                session.add(row)
                session.flush()
            before = {"input_timezone": row.input_timezone, "max_files": row.max_files, "max_records": row.max_records}
            row.input_timezone = body.input_timezone
            row.max_files = body.max_files
            row.max_records = body.max_records
            row.updated_at = _now()
            version = _increment_revision(session)
            after = {"input_timezone": row.input_timezone, "max_files": row.max_files, "max_records": row.max_records}
            _audit(
                session,
                entity_type="common_config",
                entity_key="1",
                operation="upsert",
                operator=body.operator,
                before=before,
                after=after,
                version=version,
            )
            return KpiCommonConfigV4(
                input_timezone=row.input_timezone,
                max_files=row.max_files,
                max_records=row.max_records,
                updated_at=row.updated_at,
                rule_config_version=version,
            )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def list_config_audits(
    *, entity_type: str | None = None, operator: str | None = None, page: int = 1, page_size: int = 20
) -> tuple[list, int, int]:
    try:
        with session_factory() as session:
            query = session.query(KpiRuleConfigAudit)
            if entity_type:
                query = query.filter(KpiRuleConfigAudit.entity_type == entity_type)
            if operator:
                query = query.filter(KpiRuleConfigAudit.operator == operator)
            total = int(query.count())
            rows = (
                query.order_by(KpiRuleConfigAudit.operated_at.desc(), KpiRuleConfigAudit.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return rows, total, _revision(session)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def assert_metric_classifiable(metric_key: str) -> None:
    """分类变更前检查动态配置引用；确认变更仍由分类服务写入。"""
    _assert_base_metric(metric_key)
    try:
        with session_factory() as session:
            if session.get(KpiMetricRule, metric_key) is not None:
                raise KpiConfigError("kpi_metric_referenced", f"指标已配置动态口径: {metric_key}", 409)
            if session.get(KpiMetricFormula, metric_key) is not None:
                raise KpiConfigError("kpi_metric_referenced", f"指标被派生公式引用: {metric_key}", 409)
            formula_reference = (
                session.query(KpiMetricFormula).filter(KpiMetricFormula.numerator == metric_key).one_or_none()
            )
            if formula_reference is None:
                formula_reference = (
                    session.query(KpiMetricFormula).filter(KpiMetricFormula.denominator == metric_key).one_or_none()
                )
            if formula_reference is not None:
                raise KpiConfigError("kpi_metric_referenced", f"指标被派生公式引用: {metric_key}", 409)
            if session.query(KpiThresholdRule).filter(KpiThresholdRule.metric_key == metric_key).count():
                raise KpiConfigError("kpi_metric_referenced", f"指标被阈值引用: {metric_key}", 409)
            if session.query(KpiCapacityRule).filter(KpiCapacityRule.metric_key == metric_key).count():
                raise KpiConfigError("kpi_metric_referenced", f"指标被容量规则引用: {metric_key}", 409)
            if session.query(KpiDisplayRule).filter(KpiDisplayRule.metric_key == metric_key).count():
                raise KpiConfigError("kpi_metric_referenced", f"指标被展示规则引用: {metric_key}", 409)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def referenced_metric_keys() -> set[str]:
    """返回数据库动态配置仍引用的所有基础指标 key。"""
    try:
        with session_factory() as session:
            keys: set[str] = set()
            keys.update(row.metric_key for row in session.query(KpiMetricRule).all())
            for formula in session.query(KpiMetricFormula).all():
                keys.update(
                    {formula.metric_key, formula.numerator, formula.denominator, *formula.denominator_fallback_inputs}
                )
            keys.update(row.metric_key for row in session.query(KpiThresholdRule).all())
            keys.update(row.metric_key for row in session.query(KpiCapacityRule).all())
            keys.update(row.metric_key for row in session.query(KpiDisplayRule).all())
            return keys
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def rule_config_version() -> int:
    try:
        with session_factory() as session:
            return _revision(session)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


def config_count() -> int:
    try:
        with session_factory() as session:
            return int(session.query(func.count(KpiMetricRule.metric_key)).scalar() or 0)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc
