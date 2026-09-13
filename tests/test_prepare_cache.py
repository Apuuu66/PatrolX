"""规则私有 prepare 轻量缓存测试：只校验当前规则 Python 文件 SHA-256。"""

from pathlib import Path

import pytest

from app.core.checksum import sha256_file
from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import Executor, RuleContext


def make_rule(registry: RuleRegistry, calls: list[str]) -> Inspector:
    def prepare(ctx: RuleContext) -> object:
        calls.append("prepare")
        target = ctx.prepared_dir / "rule.owner"
        target.mkdir(parents=True, exist_ok=True)
        (target / "rows.jsonl").write_text('{"value":1}\n', encoding="utf-8")
        return None

    def inspect(ctx: RuleContext) -> object:
        calls.append("inspect")
        assert (ctx.prepared_dir / "rule.owner" / "rows.jsonl").is_file()
        return RuleStatus.PASS

    owner_file = Path(prepare.__globals__["__file__"])  # 实际由 monkeypatch 指向临时规则文件
    del owner_file
    rule = Inspector(
        code="rule.owner",
        name="owner",
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P1,
        rule_version="1.0.0",
        description="测试规则",
        recommendation="测试规则",
        source_patterns=[r"^logs/.*$"],
        run=inspect,
        prepare=PrepareSpec(code="prepare.owner", owner_code="rule.owner", run=prepare),
    )
    registry.register(rule)
    return rule


def test_prepare_cache_hit_rebuild_on_rule_file_change_and_ignore_output_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = RuleRegistry()
    calls: list[str] = []
    rule = make_rule(registry, calls)
    owner_file = tmp_path / "owner_rule.py"
    owner_file.write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setitem(prepare_globals(rule), "__file__", str(owner_file))

    for name in ("logs/a.log",):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("log", encoding="utf-8")

    def log(_level: str, message: str, _detail: dict | None = None) -> None:
        return None

    ctx = RuleContext(
        task_id="task-cache",
        data_dir=tmp_path,
        log=log,
        result_dir=tmp_path / "rules",
        prepared_dir=tmp_path / "prepared",
    )
    executor = Executor(registry)
    executor.run_all(ctx)
    assert calls == ["prepare", "inspect"]
    marker = ctx.prepared_dir / "rule.owner" / ".prepare.sha256"
    first_marker = marker.read_text(encoding="utf-8")
    assert first_marker == sha256_file(owner_file)

    executor.run_all(ctx)
    assert calls == ["prepare", "inspect", "inspect"]
    assert marker.read_text(encoding="utf-8") == first_marker

    owner_file.write_text("version = 2\n", encoding="utf-8")
    executor.run_all(ctx)
    assert calls == ["prepare", "inspect", "inspect", "prepare", "inspect"]
    assert marker.read_text(encoding="utf-8") != first_marker

    (ctx.prepared_dir / "rule.owner" / "rows.jsonl").unlink()
    executor.run_all(ctx)
    assert calls == ["prepare", "inspect", "inspect", "prepare", "inspect", "inspect"]

    import shutil

    shutil.rmtree(ctx.prepared_dir / "rule.owner")
    executor.run_all(ctx)
    assert calls[-2:] == ["prepare", "inspect"]
    assert (ctx.prepared_dir / "rule.owner" / "rows.jsonl").is_file()


def prepare_globals(rule: Inspector) -> dict:
    assert rule.prepare is not None
    return rule.prepare.run.__globals__
