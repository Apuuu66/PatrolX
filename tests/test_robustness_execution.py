"""执行器隔离的健壮性测试。"""

from pathlib import Path

from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry
from app.models.schemas import Priority, RuleCategory, RuleResult, RuleStatus, Severity
from app.services.executor import Executor, RuleContext, make_result


def _inspector(code: str, run, *, source_patterns: list[str] | None = None, hidden: bool = False) -> Inspector:
    return Inspector(
        code=code,
        name=code,
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P1,
        rule_version="1.0.0",
        description="测试规则",
        recommendation="测试规则",
        hidden=hidden,
        source_patterns=source_patterns,
        run=run,
    )


def _context(tmp_path: Path) -> RuleContext:
    for name in ("logs/a.log",):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("log", encoding="utf-8")

    def log(_level: str, _message: str, _detail: dict | None = None) -> None:
        return None

    return RuleContext(
        task_id="task-robustness",
        data_dir=tmp_path,
        log=log,
        package_path=tmp_path / "package.zip",
        result_dir=tmp_path / "rules",
        prepared_dir=tmp_path / "prepared",
    )


def test_invalid_rule_result_is_isolated_as_error(tmp_path: Path) -> None:
    registry = RuleRegistry()
    registry.register(
        _inspector(
            "pkg.extract.main",
            lambda _ctx: make_result(registry.get("pkg.extract.main"), status=RuleStatus.PASS, summary="ok"),
            hidden=True,
        )
    )

    def invalid_result(_ctx: RuleContext) -> object:
        return None

    def good_result(ctx: RuleContext) -> RuleResult:
        return make_result(registry.get("rule.good"), status=RuleStatus.PASS, summary="ok", metrics=[])

    registry.register(_inspector("rule.invalid", invalid_result, source_patterns=["^logs/.*$"]))
    registry.register(_inspector("rule.good", good_result, source_patterns=["^logs/.*$"]))

    results = Executor(registry).run_all(_context(tmp_path))
    assert results["rule.invalid"].status == RuleStatus.ERROR
    assert "未返回 RuleResult" in (results["rule.invalid"].metadata.get("error") or "")
    assert results["rule.good"].status == RuleStatus.PASS


def test_missing_source_files_return_skip_with_actionable_reason(tmp_path: Path) -> None:
    registry = RuleRegistry()
    registry.register(
        _inspector(
            "pkg.extract.main",
            lambda _ctx: make_result(registry.get("pkg.extract.main"), status=RuleStatus.PASS, summary="ok"),
            hidden=True,
        )
    )
    registry.register(
        _inspector(
            "rule.missing",
            lambda _ctx: (_ for _ in ()).throw(AssertionError("无匹配文件时不应执行规则")),
            source_patterns=["^missing/.*$"],
        )
    )
    result = Executor(registry).run_all(_context(tmp_path))["rule.missing"]
    assert result.status == RuleStatus.SKIP
    assert "source_patterns 未匹配到文件" in (result.skip_reason or "")
