"""数据准备状态组装契约测试。"""

import json
from pathlib import Path

from app.models.schemas import PreparationStatus
from app.services.preparation import load_preparation


def _manifest() -> dict:
    return {
        "version": 4,
        "main": {"checksum": "a", "count": 1, "evidence_path": ".main", "reused": False},
        "files": [
            {
                "source": ".main/KPI/kpi.csv",
                "category": "kpi",
                "target": "kpi/kpi.csv",
                "depth": 1,
                "status": "conflict",
                "error": "目标文件已存在",
                "error_code": "target_conflict",
            }
        ],
        "subpackages": [],
        "log_gz": [],
        "rejected": [],
    }


def test_missing_manifest_returns_none(tmp_path: Path) -> None:
    """历史任务或进行中任务无清单时不展示准备状态。"""
    assert load_preparation(tmp_path) is None


def test_registry_exposes_only_main_and_classification_extract_units() -> None:
    """数据准备展示所依赖的隐藏解压规则只能有主包与分类两个单元。"""
    from app.inspectors.registry import registry

    registry.load_all()
    hidden = {rule.code for rule in registry.all(include_hidden=True) if rule.hidden}

    assert hidden == {"pkg.extract.main", "pkg.extract.classification"}


def test_valid_manifest_builds_main_and_classification(tmp_path: Path) -> None:
    """清单明细只组装主包与分类两项，冲突使分类状态为 WARN。"""
    (tmp_path / ".patrolx-extracted.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    preparation = load_preparation(tmp_path)

    assert preparation is not None
    assert preparation.status == PreparationStatus.WARN
    assert [item.category for item in preparation.items] == ["main", "classification"]
    classification = preparation.items[1]
    assert classification.code == "pkg.extract.classification"
    assert classification.status == PreparationStatus.WARN
    assert classification.total_count == 1
    assert classification.extracted_count == 0
    assert classification.issues[0].type == "conflict"
    assert classification.issues[0].target == "kpi/kpi.csv"
    assert preparation.success_count == 1
    assert preparation.warning_count == 1
    assert preparation.skip_count == 0


def test_valid_manifest_without_failures_builds_two_passed_items(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["files"][0]["status"] = "extracted"
    manifest["files"][0].pop("error")
    manifest["files"][0].pop("error_code")
    (tmp_path / ".patrolx-extracted.json").write_text(json.dumps(manifest), encoding="utf-8")

    preparation = load_preparation(tmp_path)

    assert preparation is not None
    assert preparation.status == PreparationStatus.PASS
    assert [item.code for item in preparation.items] == [
        "pkg.extract.main",
        "pkg.extract.classification",
    ]
    assert all(item.status == PreparationStatus.PASS for item in preparation.items)


def test_persisted_classification_error_is_not_recomputed_from_manifest(tmp_path: Path) -> None:
    """持久化 ERROR 必须原样展示，不能被看似有效的 manifest 重算成 PASS/WARN。"""
    (tmp_path / ".patrolx-extracted.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "pkg.extract.classification.json").write_text(
        json.dumps(
            {
                "code": "pkg.extract.classification",
                "name": "分类",
                "category": "other",
                "priority": "P0",
                "execution_order": 1,
                "status": "error",
                "severity": "low",
                "summary": "分类配置无效",
                "metadata": {"error": "invalid_classification_config"},
            }
        ),
        encoding="utf-8",
    )

    preparation = load_preparation(tmp_path)

    assert preparation is not None
    classification = preparation.items[1]
    assert classification.status == PreparationStatus.ERROR
    assert classification.summary == "分类配置无效"
    assert classification.issues[0].reason == "invalid_classification_config"


def test_invalid_manifest_is_error_not_crash(tmp_path: Path) -> None:
    """清单损坏时返回结构化 error，任务读取不被中断。"""
    (tmp_path / ".patrolx-extracted.json").write_text("{bad", encoding="utf-8")
    preparation = load_preparation(tmp_path)

    assert preparation is not None
    assert preparation.status == PreparationStatus.ERROR
    assert [item.code for item in preparation.items] == [
        "pkg.extract.main",
        "pkg.extract.classification",
    ]
    assert all(item.status == PreparationStatus.ERROR for item in preparation.items)
    assert preparation.items[0].issues[0].reason == "manifest 损坏或版本不匹配"


def test_corrupt_manifest_preserves_persisted_classification_error(tmp_path: Path) -> None:
    """manifest 本身损坏时仍应优先展示已保存的 classification 错误详情。"""
    (tmp_path / ".patrolx-extracted.json").write_bytes(b"\xff")
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "pkg.extract.classification.json").write_text(
        json.dumps(
            {
                "code": "pkg.extract.classification",
                "name": "分类",
                "category": "other",
                "priority": "P0",
                "execution_order": 1,
                "status": "error",
                "severity": "low",
                "summary": "分类清单无法读取或解析",
                "duration_ms": 12,
                "metadata": {"error": "invalid utf-8"},
            }
        ),
        encoding="utf-8",
    )

    preparation = load_preparation(tmp_path)

    assert preparation is not None
    classification = preparation.items[1]
    assert classification.status == PreparationStatus.ERROR
    assert classification.summary == "分类清单无法读取或解析"
    assert classification.duration_ms == 12
    assert classification.issues[0].reason == "invalid utf-8"
    assert classification.total_count == 0
