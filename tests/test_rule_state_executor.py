"""执行器按启用集合过滤普通规则和私有 prepare。"""

from pathlib import Path
from typing import Any

import pytest

from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.models.schemas import Priority, RuleCategory, Severity
from app.services.executor import Executor, RuleContext


def _rule(
    target: RuleRegistry,
    code: str,
    run: Any,
    *,
    prepare: PrepareSpec | None = None,
) -> None:
    target.register(
        Inspector(
            code=code,
            name=code,
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"logs/.*"],
            run=run,
            prepare=prepare,
        )
    )


def test_enabled_set_filters_prepare_and_inspect_plans() -> None:
    target = RuleRegistry()
    prepares: list[str] = []
    for code in ("rule.enabled", "rule.disabled"):
        _rule(
            target,
            code,
            lambda _ctx: None,
            prepare=PrepareSpec(
                code=f"prepare.{code}",
                owner_code=code,
                run=lambda ctx, _code=code: prepares.append(_code),
            ),
        )
    executor = Executor(target, enabled_rules={"rule.enabled"})

    assert executor.prepare_plan() == ["prepare.rule.enabled"]
    assert executor.inspect_plan() == ["rule.enabled"]


def test_none_enabled_set_keeps_all_rules_for_compatible_construction() -> None:
    target = RuleRegistry()
    _rule(target, "rule.first", lambda _ctx: None)
    _rule(target, "rule.second", lambda _ctx: None)

    executor = Executor(target)
    assert set(executor.inspect_plan()) == {"rule.first", "rule.second"}


def test_run_rule_rejects_disabled_rule() -> None:
    target = RuleRegistry()
    _rule(target, "rule.disabled", lambda _ctx: None)
    executor = Executor(target, enabled_rules=set())
    ctx = RuleContext(task_id="task-x", data_dir=Path("output/task-x"), log=lambda *_: None)

    with pytest.raises(ValueError, match="规则已停用"):
        executor.run_rule("rule.disabled", ctx)
