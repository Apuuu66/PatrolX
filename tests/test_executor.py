"""执行器与 TaskFileCatalog 的集成契约测试。"""

from pathlib import Path
from typing import Any

import pytest

from app.core.checksum import sha256_file
from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import Executor, RuleContext, make_result
from app.services.scanning import TaskFileCatalog


def _context(tmp_path: Path) -> RuleContext:
    def log(_level: str, _message: str, _detail: dict | None = None) -> None:
        return None

    return RuleContext(
        task_id="task-catalog",
        data_dir=tmp_path,
        log=log,
        package_path=tmp_path / "package.zip",
        prepared_dir=tmp_path / "prepared",
    )


def _file(root: Path, relative: str, content: str = "ok") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _rule(
    registry: RuleRegistry,
    code: str,
    run: Any,
    *,
    source_patterns: list[str],
    prepare: PrepareSpec | None = None,
) -> None:
    registry.register(
        Inspector(
            code=code,
            name=code,
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            hidden=code.startswith("pkg.extract."),
            source_patterns=source_patterns,
            run=run,
            prepare=prepare,
        )
    )


def test_run_all_builds_catalog_once_after_extract_barrier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _file(tmp_path, "logs/a.log")
    build_calls: list[Path] = []
    original_build = TaskFileCatalog.build.__func__

    def counting_build(cls: type[TaskFileCatalog], data_dir: Path) -> TaskFileCatalog:
        build_calls.append(data_dir)
        return original_build(cls, data_dir)

    monkeypatch.setattr(TaskFileCatalog, "build", classmethod(counting_build))

    registry = RuleRegistry()

    def main_extract(_ctx: RuleContext) -> object:
        return make_result(registry.get("pkg.extract.main"), status=RuleStatus.PASS, summary="ok")

    def inspect(ctx: RuleContext) -> object:
        assert [path.as_posix() for path in ctx.files] == ["logs/a.log"]
        return make_result(registry.get("rule.log"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "pkg.extract.main", main_extract, source_patterns=[r"package\.zip"])
    _rule(registry, "rule.log", inspect, source_patterns=[r"logs/.*\.log"])

    ctx = _context(tmp_path)
    results = Executor(registry).run_all(ctx)

    assert build_calls == [tmp_path]
    assert results["rule.log"].status == RuleStatus.PASS
    assert ctx.catalog is not None


def test_prepare_and_inspect_match_same_catalog_and_exclude_infrastructure(
    tmp_path: Path,
) -> None:
    _file(tmp_path, "logs/a.log")
    _file(tmp_path, "prepared/rule.owner/old.csv")
    _file(tmp_path, ".main/evidence.log")
    _file(tmp_path, ".patrolx-extracted.json")
    seen: list[list[Path]] = []

    def prepare(ctx: RuleContext) -> None:
        seen.append(list(ctx.files))

    def inspect(ctx: RuleContext) -> object:
        seen.append(list(ctx.files))
        return make_result(registry.get("rule.owner"), status=RuleStatus.PASS, summary="ok")

    registry = RuleRegistry()
    _rule(
        registry,
        "rule.owner",
        inspect,
        source_patterns=[r"logs/.*"],
        prepare=PrepareSpec(code="prepare.owner", owner_code="rule.owner", run=prepare),
    )
    ctx = _context(tmp_path)
    results = Executor(registry).run_all(ctx)

    assert results["rule.owner"].status == RuleStatus.PASS
    assert len(seen) == 2
    assert [path.as_posix() for path in seen[0]] == ["logs/a.log"]
    assert seen[0] == seen[1]


def test_no_catalog_match_returns_skip(tmp_path: Path) -> None:
    registry = RuleRegistry()

    def inspect(_ctx: RuleContext) -> object:
        raise AssertionError("无匹配不应执行规则")

    _rule(registry, "rule.none", inspect, source_patterns=[r"logs/.*\.log"])
    ctx = _context(tmp_path)
    result = Executor(registry).run_all(ctx)["rule.none"]

    assert result.status == RuleStatus.SKIP
    assert result.skip_reason == "source_patterns 未匹配到文件: logs/.*\\.log"


def test_single_rule_rerun_ensures_extraction_then_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _file(tmp_path, "logs/a.log")
    calls: list[str] = []
    monkeypatch.setattr(
        Executor,
        "_ensure_extraction_site",
        lambda self, ctx: calls.append("extract"),
    )
    original_build = TaskFileCatalog.build.__func__

    def counting_build(cls: type[TaskFileCatalog], data_dir: Path) -> TaskFileCatalog:
        calls.append("catalog")
        return original_build(cls, data_dir)

    monkeypatch.setattr(TaskFileCatalog, "build", classmethod(counting_build))
    registry = RuleRegistry()

    def inspect(ctx: RuleContext) -> object:
        assert calls == ["extract", "catalog"]
        return make_result(registry.get("rule.target"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "rule.target", inspect, source_patterns=[r"logs/.*"])
    ctx = _context(tmp_path)

    result = Executor(registry).run_rule_with_deps("rule.target", ctx)

    assert result.status == RuleStatus.PASS
    assert calls == ["extract", "catalog"]


def test_ensure_catalog_reuses_existing_context_catalog(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    ctx.catalog = TaskFileCatalog.build(tmp_path)

    assert ctx.ensure_catalog() is ctx.catalog


def test_catalog_error_is_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[tuple[str, str, dict]] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append((level, message, detail or {}))

    def broken_build(cls: type[TaskFileCatalog], data_dir: Path) -> TaskFileCatalog:
        raise ValueError("匹配路径越界: logs/../a.log")

    monkeypatch.setattr(TaskFileCatalog, "build", classmethod(broken_build))
    registry = RuleRegistry()
    _rule(registry, "rule.log", lambda _ctx: None, source_patterns=[r"logs/.*"])
    ctx = RuleContext(
        "task-catalog",
        tmp_path,
        log,
        package_path=tmp_path / "package.zip",
        prepared_dir=tmp_path / "prepared",
    )

    with pytest.raises(ValueError, match="匹配路径越界"):
        Executor(registry).run_all(ctx)

    catalog_logs = [detail for _level, message, detail in logs if message == "catalog_error"]
    assert catalog_logs == [{"task_id": "task-catalog", "error": "匹配路径越界: logs/../a.log"}]


def test_pattern_rejection_is_logged_and_rule_error(tmp_path: Path) -> None:
    logs: list[tuple[str, str, dict]] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append((level, message, detail or {}))

    _file(tmp_path, "logs/a.log")
    registry = RuleRegistry()

    def inspect(_ctx: RuleContext) -> object:
        raise AssertionError("非法 pattern 不应执行规则")

    _rule(registry, "rule.bad", inspect, source_patterns=[r"logs/.*"])
    registry.get("rule.bad").source_patterns = [r"logs/("]
    ctx = RuleContext(
        "task-pattern",
        tmp_path,
        log,
        package_path=tmp_path / "package.zip",
        prepared_dir=tmp_path / "prepared",
    )
    result = Executor(registry).run_all(ctx)["rule.bad"]

    assert result.status == RuleStatus.ERROR
    assert result.metadata["error"] == "source_patterns 存在非法正则: logs/("
    detail = next(detail for _level, message, detail in logs if message == "pattern_rejected")
    assert detail["task_id"] == "task-pattern"
    assert detail["rule_code"] == "rule.bad"
    assert detail["pattern"] == "logs/("
    assert detail["error"] == "source_patterns 存在非法正则: logs/("


def test_prepare_pattern_rejection_is_logged_and_skips_owner(tmp_path: Path) -> None:
    logs: list[tuple[str, str, dict]] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append((level, message, detail or {}))

    _file(tmp_path, "logs/a.log")
    registry = RuleRegistry()

    def prepare(_ctx: RuleContext) -> None:
        raise AssertionError("非法 pattern 不应执行 prepare")

    def inspect(_ctx: RuleContext) -> object:
        raise AssertionError("非法 pattern 不应执行规则")

    _rule(
        registry,
        "rule.bad",
        inspect,
        source_patterns=[r"logs/.*"],
        prepare=PrepareSpec(code="prepare.bad", owner_code="rule.bad", run=prepare),
    )
    registry.get("rule.bad").source_patterns = [r"logs/("]
    ctx = RuleContext(
        "task-prepare-pattern",
        tmp_path,
        log,
        package_path=tmp_path / "package.zip",
        prepared_dir=tmp_path / "prepared",
    )
    result = Executor(registry).run_all(ctx)["rule.bad"]

    assert result.status == RuleStatus.SKIP
    assert result.skip_reason == "预处理未就绪"
    detail = next(detail for _level, message, detail in logs if message == "pattern_rejected")
    assert detail["rule_code"] == "rule.bad"
    assert ctx.prepare_states["rule.bad"] == "FAILED"


def test_single_rule_rerun_hashes_package_once_per_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    checksum_calls: list[Path] = []
    original_sha256_file = sha256_file.__wrapped__ if hasattr(sha256_file, "__wrapped__") else sha256_file

    def counting_sha256_file(path: Path) -> str:
        checksum_calls.append(path)
        return original_sha256_file(path)

    monkeypatch.setattr("app.services.executor.sha256_file", counting_sha256_file)
    monkeypatch.setattr(
        "app.services.executor.extraction.reusable_manifest",
        lambda _data_dir, checksum: {"main": {"checksum": checksum}},
    )

    registry = RuleRegistry()

    def run(_ctx: RuleContext) -> object:
        return make_result(registry.get("rule.first"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "rule.first", run, source_patterns=[r"logs/.*"])
    _rule(registry, "rule.second", run, source_patterns=[r"kpi/.*"])
    ctx = _context(tmp_path)
    ctx.package_path = package
    executor = Executor(registry)

    executor.run_rule_with_deps("rule.first", ctx)
    executor.run_rule_with_deps("rule.second", ctx)

    assert checksum_calls == [package]


def test_no_match_skip_reason_reports_policy_skipped_items(tmp_path: Path) -> None:
    """同分类存在策略保留项时，无匹配规则补充可读原因。"""
    import json

    manifest = {
        "version": 3,
        "main": {"checksum": "a", "count": 1, "evidence_path": ".main", "reused": False},
        "subpackages": [
            {
                "source": ".main/0/a.zip",
                "parent": None,
                "category": "other",
                "classification_reason": "policy:name",
                "depth": 1,
                "checksum": "a",
                "target": "other/0/a.zip",
                "status": "skipped",
                "error": None,
                "policy": {"action": "skip", "reason": "skip_path", "scope": "0/", "keyword": None},
            }
        ],
        "log_gz": [],
        "rejected": [],
    }
    (tmp_path / ".patrolx-extracted.json").write_text(json.dumps(manifest), encoding="utf-8")
    registry = RuleRegistry()

    def inspect(_ctx: RuleContext) -> object:
        raise AssertionError("无匹配不应执行规则")

    _rule(registry, "rule.none", inspect, source_patterns=[r"other/.*\.log"])
    result = Executor(registry).run_all(_context(tmp_path))["rule.none"]

    assert result.status == RuleStatus.SKIP
    assert "项目级解压策略保留了压缩项: a.zip" in (result.skip_reason or "")
