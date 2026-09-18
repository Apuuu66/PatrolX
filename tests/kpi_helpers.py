"""KPI 新目录测试助手。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.db import init_db
from app.services.kpi_resources import classify_resource_metrics

_CALL_METRICS = [
    ("ME_CALL_ATTEMPTS", "呼叫请求次数", "Call Attempts"),
    ("ME_CALL_SUCCESS_COUNT", "呼叫请求成功次数", "Call Success Count"),
    ("ME_CALL_FAILURE_COUNT", "呼叫请求失败次数", "Call Failure Count"),
    ("ME_CALL_SUCCESS_RATE", "呼叫成功率", "Call Success Rate"),
    ("ME_CALL_FAILURE_RATE", "呼叫失败率", "Call Failure Rate"),
    ("ME_STAT_PEAK", "统计峰值", "Stat Peak"),
    ("ME_MAX_CONCURRENCY", "最大并发", "Max Concurrency"),
]


def _metric_rule(
    key: str, *, metric_type: str = "count", source_type: str = "raw", formula=None, aggregation=None
) -> dict:
    return {
        "key": key,
        "metric_type": metric_type,
        "semantic_group": "traffic" if metric_type == "count" else "quality" if metric_type == "rate" else "capacity",
        "display_role": "context",
        "unit": "次" if metric_type == "count" else "%" if metric_type == "rate" else "个",
        "source_type": source_type,
        "aggregation": aggregation or {"kind": "sum"},
        "formula": formula,
    }


def kpi_catalog_payload() -> dict:
    """返回覆盖呼叫域执行行为的合法 Git JSON。"""
    metrics = [
        {
            "resource_id": resource_id,
            "key": resource_id.lower(),
            "name_zh": name_zh,
            "name_en": name_en,
            "unit_key": None,
        }
        for resource_id, name_zh, name_en in _CALL_METRICS
    ]

    def ratio(numerator: str, denominator: str) -> dict[str, object]:
        return {
            "kind": "ratio",
            "numerator": numerator,
            "denominator": denominator,
            "scale": 100,
        }

    rules = {
        "common": {
            "input_timezone": "Asia/Shanghai",
            "budgets": {"max_files": 1000, "max_records": 200000},
        },
        "metric_rules": [
            _metric_rule("me_call_attempts"),
            _metric_rule("me_call_success_count"),
            _metric_rule("me_call_failure_count"),
            _metric_rule(
                "me_call_success_rate",
                metric_type="rate",
                source_type="derived",
                formula=ratio("me_call_success_count", "me_call_attempts"),
            ),
            _metric_rule(
                "me_call_failure_rate",
                metric_type="rate",
                source_type="derived",
                formula=ratio("me_call_failure_count", "me_call_attempts"),
            ),
            _metric_rule("me_stat_peak", metric_type="capacity", aggregation={"kind": "max"}),
            _metric_rule("me_max_concurrency", metric_type="capacity", aggregation={"kind": "max"}),
        ],
        "thresholds": [
            {
                "domain": "call",
                "metric_key": "me_call_success_rate",
                "label": "呼叫成功率",
                "direction": "min",
                "unit": "%",
                "default": 99.0,
                "periods": {"5": 99.0, "15": 99.0, "30": 99.0, "60": 99.0},
            },
            {
                "domain": "call",
                "metric_key": "me_call_failure_rate",
                "label": "呼叫失败率",
                "direction": "max",
                "unit": "%",
                "default": 1.0,
                "periods": {},
            },
        ],
        "capacity_rules": [
            {"source_name": "统计峰值", "metric_key": "me_stat_peak", "semantics": "peak", "status": "confirmed"},
            {
                "source_name": "最大并发",
                "metric_key": "me_max_concurrency",
                "semantics": "concurrency",
                "status": "confirmed",
            },
        ],
        "display_rules": [],
    }
    return {
        "schema_version": 1,
        "source_csv_sha256": "a" * 64,
        "metrics": metrics,
        "units": [],
        "rules": rules,
    }


def configure_kpi_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_dir: Path | None = None,
    sqlite_path: Path | None = None,
) -> Path:
    """初始化测试数据库、写入并分类标准 KPI 目录。"""
    monkeypatch.setattr(settings, "output_dir", output_dir or tmp_path / "output")
    monkeypatch.setattr(settings, "sqlite_path", sqlite_path or tmp_path / "kpi.db")
    init_db()
    path = tmp_path / "kpi_catalog.json"
    path.write_text(json.dumps(kpi_catalog_payload(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "kpi_catalog_path", path)
    classify_resource_metrics(
        [resource_id.lower() for resource_id, _, _ in _CALL_METRICS],
        domain="call",
        operator="test",
    )
    return path


def write_kpi_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict) -> Path:
    """覆盖 Git JSON 路径，用于测试特定目录规则。"""
    path = tmp_path / "kpi_catalog_override.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "kpi_catalog_path", path)
    return path
