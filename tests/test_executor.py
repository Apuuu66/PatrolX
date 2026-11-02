"""执行器与 TaskFileCatalog 的集成契约测试。"""

from pathlib import Path
from typing import Any

import pytest

from app.core.checksum import sha256_file
from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.models.schemas import PackageKind, Priority, Product, RuleCategory, RuleStatus, Severity
from app.services.executor import Executor, RuleContext, make_result
from app.services.scanning import TaskFileCatalog
from tests.manifest_helpers import write_catalog_manifest


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
    source_patterns: list[str] | None,
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
    write_catalog_manifest(tmp_path, ["logs/a.log"])
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


def test_extract_errors_run_all_extract_units_and_block_followup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任一 EXTRACT ERROR 都必须等全部解压单元执行后统一阻断后续阶段。"""
    logs: list[tuple[str, str, dict]] = []
    events: list[str] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append((level, message, detail or {}))

    def main_extract(_ctx: RuleContext) -> object:
        events.append("extract:main")
        return make_result(registry.get("pkg.extract.main"), status=RuleStatus.ERROR, summary="主包失败")

    def classification(_ctx: RuleContext) -> object:
        events.append("extract:classification")
        return make_result(
            registry.get("pkg.extract.classification"),
            status=RuleStatus.ERROR,
            summary="分类失败",
        )

    def prepare(_ctx: RuleContext) -> None:
        events.append("prepare")

    def inspect(_ctx: RuleContext) -> object:
        events.append("inspect")
        return make_result(registry.get("rule.owner"), status=RuleStatus.PASS, summary="ok")

    registry = RuleRegistry()
    _rule(registry, "pkg.extract.main", main_extract, source_patterns=None)
    _rule(registry, "pkg.extract.classification", classification, source_patterns=None)
    _rule(
        registry,
        "rule.owner",
        inspect,
        source_patterns=[r"logs/.*"],
        prepare=PrepareSpec(code="prepare.owner", owner_code="rule.owner", run=prepare),
    )
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
    ctx = RuleContext(
        task_id="task-extract-gate",
        data_dir=tmp_path,
        log=log,
        package_path=tmp_path / "package.zip",
        prepared_dir=tmp_path / "prepared",
    )
    build_calls: list[Path] = []

    def forbidden_build(cls: type[TaskFileCatalog], data_dir: Path) -> TaskFileCatalog:
        build_calls.append(data_dir)
        raise AssertionError("解压失败后不得构建 catalog")

    monkeypatch.setattr(TaskFileCatalog, "build", classmethod(forbidden_build))

    results = Executor(registry).run_all(ctx, after_extract=lambda: events.append("after_extract"))

    assert set(results) == {"pkg.extract.main", "pkg.extract.classification"}
    assert events == ["extract:main", "extract:classification"]
    assert build_calls == []
    gate = next(detail for _level, message, detail in logs if message == "解压失败，阻断 prepare 和 inspect")
    assert gate["failed_units"] == ["pkg.extract.main", "pkg.extract.classification"]


def test_classification_error_blocks_followup_when_main_passes(tmp_path: Path) -> None:
    """主包成功但分类 ERROR 时，仍必须阻断 prepare 与 inspect。"""
    events: list[str] = []
    logs: list[tuple[str, str, dict]] = []
    registry = RuleRegistry()

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append((level, message, detail or {}))

    def main_extract(_ctx: RuleContext) -> object:
        events.append("extract:main")
        return make_result(registry.get("pkg.extract.main"), status=RuleStatus.PASS, summary="ok")

    def classification(_ctx: RuleContext) -> object:
        events.append("extract:classification")
        return make_result(
            registry.get("pkg.extract.classification"),
            status=RuleStatus.ERROR,
            summary="分类失败",
        )

    def prepare(_ctx: RuleContext) -> None:
        events.append("prepare")

    def inspect(_ctx: RuleContext) -> object:
        events.append("inspect")
        return make_result(registry.get("rule.owner"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "pkg.extract.main", main_extract, source_patterns=None)
    _rule(registry, "pkg.extract.classification", classification, source_patterns=None)
    _rule(
        registry,
        "rule.owner",
        inspect,
        source_patterns=[r"logs/.*"],
        prepare=PrepareSpec(code="prepare.owner", owner_code="rule.owner", run=prepare),
    )
    _file(tmp_path, "logs/a.log")
    ctx = RuleContext(
        task_id="task-classification-error",
        data_dir=tmp_path,
        log=log,
        package_path=tmp_path / "package.zip",
        prepared_dir=tmp_path / "prepared",
    )

    results = Executor(registry).run_all(ctx, after_extract=lambda: events.append("after_extract"))

    assert set(results) == {"pkg.extract.main", "pkg.extract.classification"}
    assert events == ["extract:main", "extract:classification"]
    gate = next(detail for _level, message, detail in logs if message == "解压失败，阻断 prepare 和 inspect")
    assert gate["failed_units"] == ["pkg.extract.classification"]


def test_classification_warn_allows_prepare_and_inspect(tmp_path: Path) -> None:
    """classification WARN 表示局部失败但 catalog 可用，后续阶段必须继续。"""
    events: list[str] = []
    registry = RuleRegistry()

    def main_extract(_ctx: RuleContext) -> object:
        events.append("extract:main")
        return make_result(registry.get("pkg.extract.main"), status=RuleStatus.PASS, summary="ok")

    def classification(_ctx: RuleContext) -> object:
        events.append("extract:classification")
        return make_result(
            registry.get("pkg.extract.classification"),
            status=RuleStatus.WARN,
            summary="局部解压失败",
        )

    def prepare(_ctx: RuleContext) -> None:
        events.append("prepare")

    def inspect(_ctx: RuleContext) -> object:
        events.append("inspect")
        return make_result(registry.get("rule.owner"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "pkg.extract.main", main_extract, source_patterns=None)
    _rule(registry, "pkg.extract.classification", classification, source_patterns=None)
    _rule(
        registry,
        "rule.owner",
        inspect,
        source_patterns=[r"logs/.*"],
        prepare=PrepareSpec(code="prepare.owner", owner_code="rule.owner", run=prepare),
    )
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])

    results = Executor(registry).run_all(
        _context(tmp_path),
        after_extract=lambda: events.append("after_extract"),
    )

    assert results["rule.owner"].status == RuleStatus.PASS
    assert events == ["extract:main", "extract:classification", "after_extract", "prepare", "inspect"]


def test_prepare_and_inspect_match_same_catalog_and_exclude_infrastructure(
    tmp_path: Path,
) -> None:
    _file(tmp_path, "logs/a.log")
    _file(tmp_path, "prepared/rule.owner/old.csv")
    _file(tmp_path, ".main/evidence.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
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
    _file(tmp_path, "basic/a.txt")
    write_catalog_manifest(tmp_path, ["basic/a.txt"])
    registry = RuleRegistry()

    def inspect(_ctx: RuleContext) -> object:
        raise AssertionError("无匹配不应执行规则")

    _rule(registry, "rule.none", inspect, source_patterns=[r"logs/.*\.log"])
    ctx = _context(tmp_path)
    result = Executor(registry).run_all(ctx)["rule.none"]

    assert result.status == RuleStatus.SKIP
    assert "patterns=logs/.*\\.log" in (result.skip_reason or "")
    assert "profile=UMF" in (result.skip_reason or "")


def test_single_rule_rerun_ensures_extraction_then_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
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


def test_single_rule_rerun_is_blocked_by_classification_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    registry = RuleRegistry()

    def classification(_ctx: RuleContext) -> object:
        events.append("classification")
        return make_result(
            registry.get("pkg.extract.classification"),
            status=RuleStatus.ERROR,
            summary="分类失败",
        )

    def inspect(_ctx: RuleContext) -> object:
        events.append("inspect")
        return make_result(registry.get("rule.target"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "pkg.extract.classification", classification, source_patterns=None)
    _rule(registry, "rule.target", inspect, source_patterns=[r"logs/.*"])
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
    monkeypatch.setattr(Executor, "_ensure_extraction_site", lambda self, ctx: None)

    with pytest.raises(ValueError, match="pkg.extract.classification"):
        Executor(registry).run_rule_with_deps("rule.target", _context(tmp_path))

    assert events == ["classification"]


def test_single_rule_rerun_allows_classification_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """classification WARN 时单规则重跑仍继续执行目标 prepare 与 inspect。"""
    events: list[str] = []
    registry = RuleRegistry()

    def classification(_ctx: RuleContext) -> object:
        events.append("classification")
        return make_result(
            registry.get("pkg.extract.classification"),
            status=RuleStatus.WARN,
            summary="局部失败",
        )

    def prepare(_ctx: RuleContext) -> None:
        events.append("prepare")

    def inspect(_ctx: RuleContext) -> object:
        events.append("inspect")
        return make_result(registry.get("rule.target"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "pkg.extract.classification", classification, source_patterns=None)
    _rule(
        registry,
        "rule.target",
        inspect,
        source_patterns=[r"logs/.*"],
        prepare=PrepareSpec(code="prepare.target", owner_code="rule.target", run=prepare),
    )
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
    monkeypatch.setattr(Executor, "_ensure_extraction_site", lambda self, ctx: None)

    result = Executor(registry).run_rule_with_deps("rule.target", _context(tmp_path))

    assert result.status == RuleStatus.PASS
    assert events == ["classification", "prepare", "inspect"]


def test_single_rule_rerun_does_not_collect_classification_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分类门禁可执行，但不得混入单规则重跑的目标结果集合。"""
    registry = RuleRegistry()

    def classification(_ctx: RuleContext) -> object:
        return make_result(
            registry.get("pkg.extract.classification"),
            status=RuleStatus.WARN,
            summary="局部失败",
        )

    def inspect(_ctx: RuleContext) -> object:
        return make_result(registry.get("rule.target"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "pkg.extract.classification", classification, source_patterns=None)
    _rule(registry, "rule.target", inspect, source_patterns=[r"logs/.*"])
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
    monkeypatch.setattr(Executor, "_ensure_extraction_site", lambda self, ctx: None)
    executor = Executor(registry)

    executor.run_rule_with_deps("rule.target", _context(tmp_path))

    assert set(executor.collected) == {"rule.target"}


def test_single_rule_classification_target_does_not_recurse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    registry = RuleRegistry()

    def classification(_ctx: RuleContext) -> object:
        events.append("classification")
        return make_result(
            registry.get("pkg.extract.classification"),
            status=RuleStatus.ERROR,
            summary="分类失败",
        )

    _rule(registry, "pkg.extract.classification", classification, source_patterns=None)
    monkeypatch.setattr(
        Executor,
        "_ensure_extraction_site",
        lambda self, ctx: (_ for _ in ()).throw(AssertionError("直接重跑分类不得递归解压")),
    )

    result = Executor(registry).run_rule_with_deps("pkg.extract.classification", _context(tmp_path))

    assert result.status == RuleStatus.ERROR
    assert events == ["classification"]


def test_single_rule_rerun_does_not_require_classification_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试注册表未注册 classification 时，普通规则重跑仍可继续。"""
    registry = RuleRegistry()

    def inspect(_ctx: RuleContext) -> object:
        return make_result(registry.get("rule.target"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "rule.target", inspect, source_patterns=[r"logs/.*"])
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
    monkeypatch.setattr(Executor, "_ensure_extraction_site", lambda self, ctx: None)

    result = Executor(registry).run_rule_with_deps("rule.target", _context(tmp_path))

    assert result.status == RuleStatus.PASS


def test_inspect_request_propagates_task_product_and_package_kind(tmp_path: Path) -> None:
    registry = RuleRegistry()
    _rule(registry, "rule.meta", lambda _ctx: None, source_patterns=[r"logs/.*"])
    _file(tmp_path, "logs/a.log")
    write_catalog_manifest(tmp_path, ["logs/a.log"])
    ctx = RuleContext(
        task_id="task-meta",
        data_dir=tmp_path,
        log=lambda *_args, **_kwargs: None,
        product=Product.CSP,
        package_kind=PackageKind.INSPECTION,
        prepared_dir=tmp_path / "prepared",
    )

    plan = Executor(registry)._plan_inspect("rule.meta", ctx)

    assert plan.request is not None
    assert plan.request.product == "CSP"
    assert plan.request.package_kind == "inspection"


def test_ensure_catalog_reuses_existing_context_catalog(tmp_path: Path) -> None:
    _file(tmp_path, "basic/a.txt")
    write_catalog_manifest(tmp_path, ["basic/a.txt"])
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
    write_catalog_manifest(tmp_path, ["logs/a.log"])
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
    write_catalog_manifest(tmp_path, ["logs/a.log"])
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
    """单规则重跑只经 pkg.extract.main，且每个上下文 checksum 只算一次。"""
    import app.core.checksum as checksum_module

    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    checksum_calls: list[Path] = []
    main_calls: list[str] = []
    original_sha256_file = checksum_module.sha256_file

    def counting_sha256_file(path: Path) -> str:
        checksum_calls.append(path)
        return original_sha256_file(path)

    monkeypatch.setattr(checksum_module, "sha256_file", counting_sha256_file)

    registry = RuleRegistry()

    def main_extract(ctx: RuleContext) -> object:
        main_calls.append(ctx.ensure_package_checksum())
        return make_result(registry.get("pkg.extract.main"), status=RuleStatus.PASS, summary="ok")

    def run(_ctx: RuleContext) -> object:
        return make_result(registry.get("rule.first"), status=RuleStatus.PASS, summary="ok")

    _rule(registry, "pkg.extract.main", main_extract, source_patterns=None)
    _rule(registry, "rule.first", run, source_patterns=[r"logs/.*"])
    _rule(registry, "rule.second", run, source_patterns=[r"kpi/.*"])
    _file(tmp_path, "basic/a.txt")
    write_catalog_manifest(tmp_path, ["basic/a.txt"])
    ctx = _context(tmp_path)
    ctx.package_path = package
    executor = Executor(registry)

    executor.run_rule_with_deps("rule.first", ctx)
    executor.run_rule_with_deps("rule.second", ctx)

    assert checksum_calls == [package]
    assert main_calls == [sha256_file(package), sha256_file(package)]


def test_no_match_skip_reason_reports_v5_context(tmp_path: Path) -> None:
    """无匹配 skip_reason 必须来自 manifest v5 的 profile、配置指纹和审计摘要。"""
    _file(tmp_path, "basic/a.txt")
    write_catalog_manifest(
        tmp_path,
        ["basic/a.txt"],
        ignored=[
            {
                "source_relative": "source/ignored.log",
                "member_relative": None,
                "route_id": "route.ignore",
                "product": "UMF",
                "category": "log",
                "original_target": None,
                "target": None,
                "action": "ignore",
                "status": "ignored",
                "reason": "member_not_selected",
                "error_code": None,
            }
        ],
        failures=[
            {
                "source_relative": "source/broken.zip",
                "member_relative": "nested/alarm.log",
                "route_id": "route.alarm",
                "category": "alarm",
                "action": "expand_recursive",
                "error_code": "archive_corrupt",
                "reason": "损坏归档",
            }
        ],
    )
    registry = RuleRegistry()

    def inspect(_ctx: RuleContext) -> object:
        raise AssertionError("无匹配不应执行规则")

    _rule(registry, "rule.none", inspect, source_patterns=[r"other/.*\.log"])
    result = Executor(registry).run_all(_context(tmp_path))["rule.none"]

    assert result.status == RuleStatus.SKIP
    skip_reason = result.skip_reason or ""
    assert "patterns=other/.*\\.log" in skip_reason
    assert "profile=UMF" in skip_reason
    assert f"config={'a' * 64}" in skip_reason
    assert "ignored=1" in skip_reason
    assert "member_not_selected" in skip_reason
    assert "failures=1" in skip_reason
    assert "archive_corrupt" in skip_reason
