"""任务执行范围冻结：生产执行只消费启动时快照。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.models.db import KpiRuleNetworkAssignment, session_factory
from app.models.schemas import Priority, RuleCategory, Severity
from app.services.executor import Executor
from tests.baseline_helpers import SAMPLE, setup_env


def _rule(
    code: str,
    *,
    hidden: bool = False,
    owner_prepare: bool = False,
) -> Inspector:
    return Inspector(
        code=code,
        name=code,
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P0 if hidden else Priority.P1,
        rule_version="1.0.0",
        description=f"{code} 测试规则",
        recommendation=f"{code} 测试建议",
        hidden=hidden,
        source_patterns=None if hidden else [r"kpi/.+\.csv"],
        run=lambda _ctx: None,
        prepare=(
            PrepareSpec(code=f"{code}.prepare", owner_code=code, run=lambda _ctx: None) if owner_prepare else None
        ),
    )


def test_executor_filters_business_plans_by_frozen_rules_and_keeps_hidden_units() -> None:
    target = RuleRegistry()
    for rule in (
        _rule("pkg.extract.main", hidden=True),
        _rule("pkg.extract.classification", hidden=True),
        _rule("rule.frozen", owner_prepare=True),
        _rule("rule.outside", owner_prepare=True),
    ):
        target.register(rule)

    executor = Executor(target, frozen_rule_codes={"rule.frozen"})

    assert executor.extract_plan() == ["pkg.extract.main", "pkg.extract.classification"]
    assert executor.prepare_plan() == ["rule.frozen.prepare"]
    assert executor.inspect_plan() == ["rule.frozen"]


def test_run_task_freezes_scope_before_execution_and_skips_unassigned_rules(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.cli import run_task
    from app.services import task_db

    env = setup_env(tmp_path, monkeypatch)
    now = datetime(2026, 11, 6, tzinfo=UTC)
    with session_factory() as session:
        session.add(
            KpiRuleNetworkAssignment(
                rule_code="kpi.measurement_units",
                network_element_type="UMF",
                rule_revision=0,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    original_run_all = Executor.run_all

    def reassign_before_execution(self, ctx, after_extract=None):
        with session_factory() as session:
            session.query(KpiRuleNetworkAssignment).delete()
            for rule_code in ("alarm.active_state", "alarm.recurrence"):
                session.add(
                    KpiRuleNetworkAssignment(
                        rule_code=rule_code,
                        network_element_type="UMF",
                        rule_revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.commit()
        return original_run_all(self, ctx, after_extract=after_extract)

    monkeypatch.setattr(Executor, "run_all", reassign_before_execution)
    published_snapshots: list[tuple[object, object]] = []

    def publish(_task) -> None:
        published_snapshots.append(
            (
                task_db.get_rule_scope_snapshot("task-execution-scope", network_element_type="UMF"),
                task_db.get_kpi_scope_snapshot("task-execution-scope", network_element_type="UMF"),
            )
        )

    task = run_task(
        SAMPLE,
        task_id="task-execution-scope",
        customer={"province": "北京", "operator": "移动", "product": "UMF"},
        publish=publish,
    )

    assert [rule.code for rule in task.system.rules] == ["kpi.measurement_units"]
    assert (env.task_dir(task.task_id) / "rules" / "pkg.extract.main.json").is_file()
    assert (env.task_dir(task.task_id) / "rules" / "pkg.extract.classification.json").is_file()
    assert not (env.task_dir(task.task_id) / "rules" / "alarm.active_state.json").exists()

    persisted_rule_snapshot, persisted_kpi_snapshot = published_snapshots[0]
    assert persisted_rule_snapshot is not None
    assert [item.rule_code for item in persisted_rule_snapshot.items] == ["kpi.measurement_units"]
    assert persisted_kpi_snapshot is not None
    assert persisted_kpi_snapshot.network_element_type == "UMF"
