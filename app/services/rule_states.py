"""普通规则启停状态的初始化、查询与更新。"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.scan_config import load_scan_config
from app.inspectors.registry import RuleRegistry, registry
from app.models.db import RuleState, init_db, session_factory
from app.models.schemas import InspectorState, InspectorStateListResponse


@dataclass(slots=True)
class RuleStateError(Exception):
    """规则状态业务错误，保留给 API 层转换的契约上下文。"""

    code: str
    message: str
    status_code: int


def _normal_codes(target: RuleRegistry) -> list[str]:
    return [rule.code for rule in target.all() if not rule.hidden]


def ensure_rule_states(target: RuleRegistry | None = None) -> None:
    """惰性初始化普通规则状态；已有状态不因后续配置修改被覆盖。"""
    rule_registry = target or registry
    rule_registry.load_all()
    disabled_rules = load_scan_config(settings.scan_rules).disabled_rules if settings.scan_rules.exists() else ()
    init_db()

    normal_codes = _normal_codes(rule_registry)
    with session_factory() as session:
        existing = set(session.scalars(select(RuleState.rule_code)).all())
        now = datetime.now(UTC)
        for code in normal_codes:
            if code in existing:
                continue
            session.add(RuleState(rule_code=code, enabled=code not in disabled_rules, updated_at=now))
        session.commit()


def _state_map() -> dict[str, RuleState]:
    with session_factory() as session:
        return {item.rule_code: item for item in session.query(RuleState).all()}


def list_rule_states(
    page: int = 1,
    page_size: int = 10,
    *,
    category: str | None = None,
    enabled: bool | None = None,
    search: str | None = None,
    registry_override: RuleRegistry | None = None,
) -> InspectorStateListResponse:
    """返回普通规则启停状态分页列表。"""
    ensure_rule_states(registry_override)
    rule_registry = registry_override or registry
    rules = {rule.code: rule for rule in rule_registry.all() if not rule.hidden}
    states = _state_map()

    normalized_search = search.strip().lower() if search else None
    filtered: list[tuple[object, RuleState]] = []
    for code in _normal_codes(rule_registry):
        rule = rules[code]
        state = states.get(code)
        if state is None:
            continue
        if category and rule.category.value != category:
            continue
        if enabled is not None and state.enabled != enabled:
            continue
        if normalized_search and normalized_search not in f"{rule.code} {rule.name}".lower():
            continue
        filtered.append((rule, state))

    total = len(filtered)
    start = (page - 1) * page_size
    items = [
        InspectorState(
            code=rule.code,
            name=rule.name,
            category=rule.category,
            priority=rule.priority,
            enabled=state.enabled,
            updated_at=state.updated_at,
        )
        for rule, state in filtered[start : start + page_size]
    ]
    return InspectorStateListResponse(items=items, total=total, page=page, page_size=page_size)


def get_enabled_rule_codes(registry_override: RuleRegistry | None = None) -> set[str]:
    """返回当前启用的普通规则代码集合。"""
    ensure_rule_states(registry_override)
    states = _state_map()
    target = registry_override or registry
    return {code for code in _normal_codes(target) if states.get(code) is not None and states[code].enabled}


def update_rule_state(rule_code: str, enabled: bool) -> InspectorState:
    """更新普通规则启停状态；重复同值更新不刷新 updated_at。"""
    ensure_rule_states()
    try:
        rule = registry.get(rule_code)
    except KeyError as exc:
        raise RuleStateError("not_found", f"规则不存在: {rule_code}", 404) from exc
    if rule.hidden:
        raise RuleStateError("rule_not_manageable", f"规则不可启停: {rule_code}", 409)

    now = datetime.now(UTC)
    changed_at = now
    with session_factory() as session:
        state = session.get(RuleState, rule_code)
        if state is None:
            state = RuleState(rule_code=rule_code, enabled=enabled, updated_at=now)
            session.add(state)
        elif state.enabled != enabled:
            state.enabled = enabled
            state.updated_at = now
        else:
            changed_at = state.updated_at
        session.commit()
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=UTC)
        return InspectorState(
            code=rule.code,
            name=rule.name,
            category=rule.category,
            priority=rule.priority,
            enabled=state.enabled,
            updated_at=changed_at,
        )


def assert_rule_enabled(rule_code: str) -> None:
    """单规则操作前校验普通规则已启用。"""
    ensure_rule_states()
    try:
        rule = registry.get(rule_code)
    except KeyError as exc:
        raise RuleStateError("not_found", f"规则不存在: {rule_code}", 404) from exc
    if rule.hidden:
        return
    states = _state_map()
    state = states.get(rule_code)
    if state is None or not state.enabled:
        raise RuleStateError("rule_disabled", f"规则已停用: {rule_code}", 409)
