"""两个隐藏解压单元的规则生命周期与分类状态契约。"""

import json
from pathlib import Path

import pytest

from app.models.schemas import RuleStatus
from app.services.executor import RuleContext


def _manifest(status: str = "extracted") -> dict:
    item: dict = {
        "source": ".main/KPI/kpi.csv",
        "category": "kpi",
        "target": "kpi/kpi.csv",
        "depth": 1,
        "status": status,
    }
    if status in {"conflict", "duplicate", "failed", "rejected"}:
        item["error"] = f"{status} failure"
        item["error_code"] = "target_conflict" if status == "conflict" else "archive_corrupt"
    return {
        "version": 4,
        "main": {"checksum": "a", "count": 1, "evidence_path": ".main", "reused": False},
        "files": [item],
        "subpackages": [],
        "log_gz": [],
        "rejected": [],
    }


def _write_manifest(data_dir: Path, value: dict | str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = value if isinstance(value, str) else json.dumps(value)
    (data_dir / ".patrolx-extracted.json").write_text(payload, encoding="utf-8")


def _context(data_dir: Path) -> RuleContext:
    return RuleContext(
        task_id="task-classification",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        prepared_dir=data_dir / "prepared",
    )


@pytest.mark.parametrize("payload", [None, "{bad", "[]", {"version": 3}])
def test_classification_invalid_manifest_is_error(tmp_path: Path, payload: dict | str | None) -> None:
    """manifest 缺失、损坏、根类型错误或 v4 校验失败都返回 ERROR。"""
    from app.inspectors.pkg import classification_inspector

    if payload is not None:
        _write_manifest(tmp_path, payload)

    result = classification_inspector.run(_context(tmp_path))

    assert result.status == RuleStatus.ERROR


def test_classification_invalid_utf8_manifest_is_structured_error(tmp_path: Path) -> None:
    """非法 UTF-8 与损坏 JSON 一样返回可展示的结构化 ERROR。"""
    from app.inspectors.pkg import classification_inspector

    (tmp_path / ".patrolx-extracted.json").write_bytes(b"\xff")

    result = classification_inspector.run(_context(tmp_path))

    assert result.status == RuleStatus.ERROR
    assert "分类清单无法读取或解析" in str(result.summary)
    assert "utf-8" in str(result.metadata["error"]).lower()
    assert result.metadata["manifest"].endswith(".patrolx-extracted.json")


@pytest.mark.parametrize("status", ["conflict", "duplicate", "failed", "rejected"])
def test_classification_local_failure_is_warn(tmp_path: Path, status: str) -> None:
    """v4 局部冲突或失败表示 catalog 可用，但 classification 必须返回 WARN。"""
    from app.inspectors.pkg import classification_inspector

    _write_manifest(tmp_path, _manifest(status))
    ctx = _context(tmp_path)
    catalog_calls: list[bool] = []
    ctx.ensure_catalog = lambda: catalog_calls.append(True) or ctx.catalog  # type: ignore[method-assign]

    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.WARN
    assert result.metadata["failed"] == 1
    assert catalog_calls == [True]


def test_classification_skipped_item_is_not_failure_and_publishes_catalog(tmp_path: Path) -> None:
    """skipped 是策略成功保留而非局部失败，PASS 时仍必须校验 catalog。"""
    from app.inspectors.pkg import classification_inspector

    _write_manifest(tmp_path, _manifest("skipped"))
    ctx = _context(tmp_path)
    catalog_calls: list[bool] = []
    ctx.ensure_catalog = lambda: catalog_calls.append(True) or ctx.catalog  # type: ignore[method-assign]

    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["failed"] == 0
    assert catalog_calls == [True]


def test_classification_catalog_failure_is_error(tmp_path: Path) -> None:
    """PASS/WARN 后 catalog 构建失败必须升级为 ERROR。"""
    from app.inspectors.pkg import classification_inspector

    _write_manifest(tmp_path, _manifest())
    ctx = _context(tmp_path)

    def broken_catalog() -> object:
        raise ValueError("catalog 损坏")

    ctx.ensure_catalog = broken_catalog  # type: ignore[method-assign]

    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.ERROR
    assert "catalog 损坏" in result.summary
