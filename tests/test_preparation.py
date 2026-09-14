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


def test_valid_manifest_builds_main_and_categories(tmp_path: Path) -> None:
    """清单明细组装为主包与七类准备项，冲突影响分类状态。"""
    (tmp_path / ".patrolx-extracted.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    preparation = load_preparation(tmp_path)

    assert preparation is not None
    assert preparation.status == PreparationStatus.WARN
    assert [item.category for item in preparation.items] == [
        "main",
        "logs",
        "kpi",
        "traffic",
        "alarm",
        "config",
        "resource",
        "other",
    ]
    kpi = preparation.items[2]
    assert kpi.status == PreparationStatus.WARN
    assert kpi.total_count == 1
    assert kpi.extracted_count == 0
    assert kpi.issues[0].type == "conflict"
    assert kpi.issues[0].target == "kpi/kpi.csv"
    assert preparation.success_count == 1
    assert preparation.warning_count == 1
    assert preparation.skip_count == 6


def test_invalid_manifest_is_error_not_crash(tmp_path: Path) -> None:
    """清单损坏时返回结构化 error，任务读取不被中断。"""
    (tmp_path / ".patrolx-extracted.json").write_text("{bad", encoding="utf-8")
    preparation = load_preparation(tmp_path)

    assert preparation is not None
    assert preparation.status == PreparationStatus.ERROR
    assert preparation.items[0].issues[0].reason == "manifest 损坏或版本不匹配"
