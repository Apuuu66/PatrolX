"""执行器测试：依赖校验、产物复用、单规则重跑。"""

from pathlib import Path

import pytest

from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.artifacts import ArtifactStore
from app.services.executor import Executor, RuleContext, make_result


def _make_inspector(
    code: str,
    priority: Priority,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    hidden: bool = False,
    run=None,
) -> Inspector:
    inspector = Inspector(
        code=code,
        name=code,
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=priority,
        rule_version="1.0.0",
        description="测试规则描述",
        recommendation="测试处理建议",
        hidden=hidden,
        inputs=inputs or [],
        outputs_artifacts=outputs or [],
    )
    inspector.run = run or (lambda ctx: make_result(inspector, status=RuleStatus.PASS, summary="ok"))
    return inspector


def _ctx(tmp_path: Path) -> tuple[RuleContext, ArtifactStore]:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    ctx = RuleContext(
        task_id="t1",
        system_id="s1",
        data_dir=tmp_path / "data",
        artifacts=artifacts,
        log=lambda level, message, detail=None: None,
        result_dir=tmp_path / "rules",
    )
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return ctx, artifacts


def test_same_priority_non_extract_dependency_rejected(tmp_path: Path) -> None:
    registry = RuleRegistry()
    producer = _make_inspector("p1", Priority.P1, outputs=["p1.ready"])
    consumer = _make_inspector("c1", Priority.P1, inputs=["p1.ready"])
    registry.register(producer)
    registry.register(consumer)
    with pytest.raises(ValueError, match="同优先级"):
        Executor(registry).validate_dependencies()


def test_extract_hidden_dependency_allowed(tmp_path: Path) -> None:
    registry = RuleRegistry()
    extract = _make_inspector("pkg.extract.log", Priority.P0, outputs=["pkg.extract.log.ready"], hidden=True)
    consumer = _make_inspector("log.filter", Priority.P0, inputs=["pkg.extract.log.ready"])
    registry.register(extract)
    registry.register(consumer)
    Executor(registry).validate_dependencies()


def test_undeclared_artifact_rejected(tmp_path: Path) -> None:
    registry = RuleRegistry()
    consumer = _make_inspector("c1", Priority.P1, inputs=["ghost.ready"])
    registry.register(consumer)
    with pytest.raises(ValueError, match="未声明的产物"):
        Executor(registry).validate_dependencies()


def test_artifact_reuse_skips_producer(tmp_path: Path) -> None:
    registry = RuleRegistry()
    calls = {"producer": 0}

    def producer_run(ctx: RuleContext):
        calls["producer"] += 1
        path = ctx.rule_artifact_path("producer", "producer.artifacts.data")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")
        return make_result(producer, status=RuleStatus.PASS, summary="ok")

    producer = _make_inspector("producer", Priority.P0, outputs=["producer.artifacts.data"], run=producer_run)
    consumer = _make_inspector("consumer", Priority.P1, inputs=["producer.artifacts.data"])
    registry.register(producer)
    registry.register(consumer)

    ctx, artifacts = _ctx(tmp_path)
    executor = Executor(registry)
    executor.run_all(ctx)
    first = calls["producer"]
    assert first == 1
    (tmp_path / "rules").mkdir(parents=True, exist_ok=True)
    for code, result in executor.collected.items():
        (tmp_path / "rules" / f"{code}.json").write_text(
            result.model_dump_json(by_alias=True),
            encoding="utf-8",
        )

    executor2 = Executor(registry)
    executor2.run_all(ctx)
    assert calls["producer"] == first  # 产物复用，不重跑生产者
