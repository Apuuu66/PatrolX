"""规则私有 prepare 的三阶段编排与失败隔离测试。"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry, registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import Executor, RuleContext, make_result
from app.services.scanning import match_paths


def make_registry() -> tuple[RuleRegistry, list[str]]:
    """创建测试专用注册表与执行事件收集器。"""
    registry = RuleRegistry()
    events: list[str] = []

    def register(
        code: str,
        *,
        priority: Priority = Priority.P1,
        source_patterns: list[str] | None = None,
        prepare: PrepareSpec | None = None,
        hidden: bool = False,
        run: Callable[[RuleContext], object] | None = None,
    ) -> Inspector:
        inspector = Inspector(
            code=code,
            name=code,
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=priority,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            hidden=hidden,
            source_patterns=source_patterns,
            run=run,
            prepare=prepare,
        )
        registry.register(inspector)
        return inspector

    return registry, events


def make_context(tmp_path: Path, registry: RuleRegistry, events: list[str], files: dict[str, str]) -> RuleContext:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def log(_level: str, _message: str, _detail: dict | None = None) -> None:
        return None

    return RuleContext(
        task_id="task-test",
        data_dir=tmp_path,
        log=log,
        package_path=tmp_path / "package.zip",
        result_dir=tmp_path / "rules",
        prepared_dir=tmp_path / "prepared",
    )


def test_extract_prepare_and_inspect_use_fixed_phase_barriers(tmp_path: Path) -> None:
    registry, events = make_registry()

    def extract(_ctx: RuleContext) -> object:
        events.append("extract:pkg.extract.main")
        from app.services.executor import make_result

        return make_result(registry.get("pkg.extract.main"), status=RuleStatus.PASS, summary="ok")

    def category_extract(ctx: RuleContext) -> object:
        events.append("extract:pkg.extract.logs")
        (ctx.data_dir / "logs").mkdir(exist_ok=True)
        (ctx.data_dir / "logs/app.log").write_text("ok", encoding="utf-8")
        return None

    def first_prepare(ctx: RuleContext) -> object:
        events.append("prepare:rule.a")
        (ctx.prepared_dir / "rule.a").mkdir(parents=True, exist_ok=True)
        (ctx.prepared_dir / "rule.a" / "data.txt").write_text("a", encoding="utf-8")
        return None

    def second_prepare(ctx: RuleContext) -> object:
        events.append("prepare:rule.b")
        (ctx.prepared_dir / "rule.b").mkdir(parents=True, exist_ok=True)
        (ctx.prepared_dir / "rule.b" / "data.txt").write_text("b", encoding="utf-8")
        return None

    def inspect_a(ctx: RuleContext) -> object:
        events.append("inspect:rule.a")
        assert (ctx.prepared_dir / "rule.a" / "data.txt").read_text(encoding="utf-8") == "a"
        return None

    def inspect_b(ctx: RuleContext) -> object:
        events.append("inspect:rule.b")
        assert (ctx.prepared_dir / "rule.b" / "data.txt").read_text(encoding="utf-8") == "b"
        return None

    registry.register(
        Inspector(
            code="pkg.extract.main",
            name="main extract",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P0,
            rule_version="1.0.0",
            description="测试主包解压",
            recommendation="测试主包解压",
            hidden=True,
            run=extract,
        )
    )
    registry.register(
        Inspector(
            code="pkg.extract.logs",
            name="logs extract",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P0,
            rule_version="1.0.0",
            description="测试解压",
            recommendation="测试解压",
            hidden=True,
            run=category_extract,
        )
    )
    registry.register(
        Inspector(
            code="rule.b",
            name="rule b",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P2,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^logs/.*\.log$"],
            run=inspect_b,
            prepare=PrepareSpec(code="prepare.rule.b", owner_code="rule.b", run=second_prepare),
        )
    )
    registry.register(
        Inspector(
            code="rule.a",
            name="rule a",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^logs/.*\.log$"],
            run=inspect_a,
            prepare=PrepareSpec(code="prepare.rule.a", owner_code="rule.a", run=first_prepare),
        )
    )

    ctx = make_context(tmp_path, registry, events, {})
    executor = Executor(registry)
    results = executor.run_all(ctx)

    extract_events = [event for event in events if event.startswith("extract:")]
    prepare_events = [event for event in events if event.startswith("prepare:")]
    inspect_events = [event for event in events if event.startswith("inspect:")]
    assert events[:2] == ["extract:pkg.extract.main", "extract:pkg.extract.logs"]
    assert events[2:4] == ["prepare:rule.a", "prepare:rule.b"]
    assert events[4:] == ["inspect:rule.a", "inspect:rule.b"]
    assert extract_events == ["extract:pkg.extract.main", "extract:pkg.extract.logs"]
    assert prepare_events == ["prepare:rule.a", "prepare:rule.b"]
    assert inspect_events == ["inspect:rule.a", "inspect:rule.b"]
    assert set(results) == {"pkg.extract.main", "pkg.extract.logs", "rule.a", "rule.b"}
    assert (ctx.prepared_dir / "rule.a" / "data.txt").is_file()
    assert (ctx.prepared_dir / "rule.b" / "data.txt").is_file()


def test_main_extract_failure_blocks_prepare_and_inspect(tmp_path: Path) -> None:
    registry, events = make_registry()

    def failed_main(_ctx: RuleContext) -> object:
        events.append("extract:failed")
        from app.services.executor import make_result

        main = registry.get("pkg.extract.main")
        return make_result(main, status=RuleStatus.ERROR, summary="failed")

    def blocked(_ctx: RuleContext) -> object:
        events.append("blocked")
        return None

    main = Inspector(
        code="pkg.extract.main",
        name="failed main",
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P0,
        rule_version="1.0.0",
        description="测试解压",
        recommendation="测试解压",
        hidden=True,
        run=failed_main,
    )
    registry.register(main)
    registry.register(
        Inspector(
            code="rule.owner",
            name="owner",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^logs/.*$"],
            run=blocked,
            prepare=PrepareSpec(code="prepare.owner", owner_code="rule.owner", run=blocked),
        )
    )

    ctx = make_context(tmp_path, registry, events, {})
    results = Executor(registry).run_all(ctx)
    assert events == ["extract:failed"]
    assert results["pkg.extract.main"].status == RuleStatus.ERROR
    assert "rule.owner" not in results


def test_prepare_failure_and_missing_input_skip_owner_without_spread(tmp_path: Path) -> None:
    registry, events = make_registry()

    def failed_prepare(_ctx: RuleContext) -> object:
        events.append("prepare:rule.failed")
        raise RuntimeError("prepare failed")

    def failed_inspect(_ctx: RuleContext) -> object:
        events.append("inspect:rule.failed")
        return None

    def missing_prepare(_ctx: RuleContext) -> object:
        events.append("prepare:rule.missing")
        return None

    def missing_inspect(_ctx: RuleContext) -> object:
        events.append("inspect:rule.missing")
        return None

    def pass_run(_ctx: RuleContext) -> object:
        events.append("inspect:rule.ok")
        return make_result(registry.get("rule.ok"), status=RuleStatus.PASS, summary="ok")

    registry.register(
        Inspector(
            code="rule.failed",
            name="failed",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^logs/.*$"],
            run=failed_inspect,
            prepare=PrepareSpec(code="prepare.failed", owner_code="rule.failed", run=failed_prepare),
        )
    )
    registry.register(
        Inspector(
            code="rule.missing",
            name="missing",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^kpi/.*$"],
            run=missing_inspect,
            prepare=PrepareSpec(code="prepare.missing", owner_code="rule.missing", run=missing_prepare),
        )
    )
    registry.register(
        Inspector(
            code="rule.ok",
            name="ok",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^other/.*$"],
            run=pass_run,
        )
    )

    ctx = make_context(tmp_path, registry, events, {"logs/app.log": "log", "other/file.txt": "ok"})
    results = Executor(registry).run_all(ctx)
    assert events == ["prepare:rule.failed", "inspect:rule.ok"]
    assert results["rule.failed"].status == RuleStatus.SKIP
    assert results["rule.failed"].skip_reason == "预处理未就绪"
    assert results["rule.missing"].status == RuleStatus.SKIP
    assert "未发现匹配源文件" in (results["rule.missing"].skip_reason or "")
    assert results["rule.ok"].status == RuleStatus.PASS
    assert not (ctx.prepared_dir / "rule.failed" / ".prepare.sha256").exists()
    assert executor_prepare_states(ctx) == {
        "rule.failed": "FAILED",
        "rule.missing": "SKIP",
    }


def executor_prepare_states(ctx: RuleContext) -> dict[str, str]:
    """测试辅助：读取 executor 暴露的 prepare 状态映射。"""
    return ctx.prepare_states


def test_partial_available_source_files_allow_owner_to_run(tmp_path: Path) -> None:
    registry, events = make_registry()

    def prepare(ctx: RuleContext) -> object:
        events.append(f"prepare:{len(ctx.files)}")
        return None

    def inspect(ctx: RuleContext) -> object:
        events.append(f"inspect:{len(ctx.files)}")
        return make_result(registry.get("rule.partial"), status=RuleStatus.PASS, summary="ok")

    registry.register(
        Inspector(
            code="rule.partial",
            name="partial",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^logs/.*\.log$"],
            run=inspect,
            prepare=PrepareSpec(code="prepare.partial", owner_code="rule.partial", run=prepare),
        )
    )
    ctx = make_context(tmp_path, registry, events, {"logs/available.log": "ok"})
    results = Executor(registry).run_all(ctx)
    assert events == ["prepare:1", "inspect:1"]
    assert results["rule.partial"].status == RuleStatus.PASS


def test_registry_keeps_prepare_contracts_unique_and_queryable() -> None:
    registry, _events = make_registry()

    def run(_ctx: RuleContext) -> object:
        return None

    prepare = PrepareSpec(code="prepare.owner", owner_code="rule.owner", run=run)
    registry.register(
        Inspector(
            code="rule.owner",
            name="owner",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"^logs/.*$"],
            run=run,
            prepare=prepare,
        )
    )
    assert registry.prepare_for_owner("rule.owner") is prepare
    assert registry.prepare_for_owner("other") is None
    with pytest.raises(ValueError, match="prepare code 重复"):
        registry.register(
            Inspector(
                code="rule.other",
                name="other",
                category=RuleCategory.OTHER,
                severity=Severity.LOW,
                priority=Priority.P1,
                rule_version="1.0.0",
                description="测试规则",
                recommendation="测试规则",
                source_patterns=[r"^logs/.*$"],
                run=run,
                prepare=PrepareSpec(code="prepare.owner", owner_code="rule.other", run=run),
            )
        )


def test_matcher_matches_relative_files_safely() -> None:
    paths = [Path("logs/a.log"), Path("logs/b.txt")]

    assert [p.as_posix() for p in match_paths(paths, [r"^logs/.*\.log$"])] == ["logs/a.log"]
    with pytest.raises(ValueError, match="禁止路径穿越"):
        match_paths(paths, [r"^\.\./.*$"])


def test_sample_rules_create_isolated_prepared_data(tmp_path: Path, monkeypatch) -> None:
    from tests.baseline_helpers import SAMPLE, load_task, setup_env

    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-sample")
    task_dir = env.task_dir(task.task_id)
    log_prepared = task_dir / "prepared" / "log.app_service" / "app_service_records.jsonl"
    assert log_prepared.is_file()
    assert (task_dir / "prepared" / "log.app_service" / ".prepare.sha256").is_file()
    assert not (task_dir / "prepared" / "log.app_service" / "kpi_values.json").exists()
    assert {result["code"] for result in load_task(env, task.task_id)["system"]["rules"]} >= {
        "kpi.api",
        "log.app_service",
    }


def test_cli_main_extract_failure_creates_failed_task_without_report(tmp_path: Path, monkeypatch) -> None:
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "bad.zip"
    package.write_text("not archive", encoding="utf-8")
    from app.cli import run_task

    task = run_task(package, task_id="task-bad")
    task_dir = env.task_dir(task.task_id)
    assert task.status.value == "failed"
    assert (task_dir / "rules" / "pkg.extract.main.json").is_file()
    assert not (task_dir / "report.html").exists()


def test_main_extract_failure_marks_task_failed_without_report(tmp_path: Path, monkeypatch) -> None:
    from tests.baseline_helpers import SAMPLE, setup_env

    env = setup_env(tmp_path, monkeypatch)
    registry.load_all()
    from app.inspectors.pkg import main_inspector

    def failed_extract(_ctx: RuleContext) -> object:
        return make_result(main_inspector, status=RuleStatus.ERROR, summary="主包解压失败")

    monkeypatch.setattr(main_inspector, "run", failed_extract)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-main-failed")
    task_dir = env.task_dir(task.task_id)

    assert task.status == "failed"
    assert task.system is not None and task.system.status == "failed"
    assert task.completed_at is not None
    assert task.stats.model_dump(by_alias=True) == {
        "total": 0,
        "pass": 0,
        "warn": 0,
        "fail": 0,
        "error": 0,
        "skip": 0,
        "systems": 1,
    }
    assert not (task_dir / "report.html").exists()
    assert json.loads((task_dir / "system.json").read_text(encoding="utf-8"))["status"] == "failed"
    saved = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert saved["status"] == "failed"
