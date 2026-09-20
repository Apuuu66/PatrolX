"""按需分类线索服务测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.kpi_classification_clues import list_classification_clues


@pytest.fixture()
def task_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    task_dir = tmp_path / "task-clue"
    (task_dir / "kpi").mkdir(parents=True)
    (task_dir / "rules").mkdir(parents=True)
    snapshot = {
        "schema_version": 2,
        "base_data_version": "sha256:" + "0" * 64,
        "classification_version": 3,
        "rule_config_version": 7,
        "captured_at": "2026-09-19T00:00:00Z",
        "base_metrics": [
            {"resource_id": "ME_A", "key": "me_a", "name_zh": "呼叫次数", "name_en": "Call Attempts"},
            {"resource_id": "ME_B", "key": "me_b", "name_zh": "呼叫次数", "name_en": "Call"},
            {"resource_id": "ME_C", "key": "me_c", "name_zh": "成功率", "name_en": "Success Rate"},
        ],
        "metrics": [
            {
                "key": "me_c",
                "resource_id": "ME_C",
                "name_zh": "成功率",
                "name_en": "Success Rate",
                "domain": "call",
                "rule": {},
            }
        ],
        "rules": {"common": {}, "metric_rules": [], "thresholds": [], "capacity_rules": [], "display_rules": []},
    }
    (task_dir / "kpi" / "kpi_catalog_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    rule_result = {
        "metadata": {
            "domain": "call",
            "kpi_files": [
                {
                    "path": "kpi/call-5.csv",
                    "objects": ["呼叫次数", "成功率", "未登记指标", "Call Attempts"],
                    "record_count": 4,
                    "records": [
                        {"values": {"呼叫次数": 1, "成功率": 99, "未登记指标": "x", "Call Attempts": 2}},
                        {"values": {"呼叫次数": 2, "成功率": 98, "Call Attempts": 3}},
                    ],
                }
            ],
        }
    }
    (task_dir / "rules" / "kpi.call.json").write_text(json.dumps(rule_result), encoding="utf-8")
    return task_dir


def test_classification_clues_use_task_snapshot_and_paginate(task_site: Path) -> None:
    page = list_classification_clues("task-clue")
    assert page.total == 4
    by_name = {item.source_name: item for item in page.items}
    assert by_name["成功率"].clue_status == "classified"
    assert by_name["成功率"].metric_key == "me_c"
    assert by_name["呼叫次数"].clue_status == "ambiguous"
    assert [candidate["metric_key"] for candidate in by_name["呼叫次数"].candidates] == ["me_a", "me_b"]
    assert by_name["Call Attempts"].clue_status == "unclassified"
    assert by_name["Call Attempts"].metric_key == "me_a"
    assert by_name["未登记指标"].clue_status == "unregistered"
    assert by_name["未登记指标"].source_files == ["kpi/call-5.csv"]
    assert by_name["呼叫次数"].record_count == 2
    assert by_name["未登记指标"].sample_values == ["x"]


def test_classification_clues_filter_and_page(task_site: Path) -> None:
    page = list_classification_clues("task-clue", clue_status="unclassified", page=1, page_size=1)
    assert page.total == 1
    assert [item.source_name for item in page.items] == ["Call Attempts"]

    page = list_classification_clues("task-clue", search="成功率")
    assert [item.source_name for item in page.items] == ["成功率"]


def test_classification_clues_prefix_match_with_unit_suffix(task_site: Path) -> None:
    """CSV 列名带单位后缀时应通过前缀匹配正确识别，而非误报未注册。"""
    task_dir = task_site
    rule_result = json.loads((task_dir / "rules" / "kpi.call.json").read_text(encoding="utf-8"))
    rule_result["metadata"]["kpi_files"][0]["objects"].extend(["呼叫次数(次)", "成功率(%)", "Call Attempts(total)"])
    rule_result["metadata"]["kpi_files"][0]["records"].append(
        {"values": {"呼叫次数(次)": 100, "成功率(%)": 99.5, "Call Attempts(total)": 200}}
    )
    (task_dir / "rules" / "kpi.call.json").write_text(json.dumps(rule_result), encoding="utf-8")

    page = list_classification_clues("task-clue", page=1, page_size=50)
    by_name = {item.source_name: item for item in page.items}
    assert by_name["呼叫次数(次)"].clue_status == "ambiguous"
    assert by_name["成功率(%)"].clue_status == "classified"
    assert by_name["成功率(%)"].metric_key == "me_c"
    assert by_name["Call Attempts(total)"].clue_status == "unclassified"
    assert by_name["Call Attempts(total)"].metric_key == "me_a"


def test_classification_clues_summary_counts(task_site: Path) -> None:
    """响应应包含不受筛选条件影响的各状态计数。"""
    page = list_classification_clues("task-clue")
    assert page.summary == {
        "ambiguous": 1,
        "classified": 1,
        "unclassified": 1,
        "unregistered": 1,
    }

    # 筛选后 summary 不变
    filtered = list_classification_clues("task-clue", clue_status="classified")
    assert filtered.total == 1
    assert filtered.summary == page.summary
