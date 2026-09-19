"""KPI 基础资源配置与动态配置测试助手。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.db import (
    KpiCapacityRule,
    KpiCommonConfig,
    KpiDisplayRule,
    KpiMetricFormula,
    KpiMetricRule,
    KpiRuleConfigRevision,
    KpiThresholdRule,
    init_db,
    session_factory,
)
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
        "aggregation": aggregation or {"kind": "success_rate" if source_type == "derived" else "sum"},
        "formula": formula,
    }


def kpi_catalog_payload() -> dict:
    """返回测试基础资源及其可注入 SQLite 的默认动态配置。"""
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


KPI_BASE_FILES = (
    "base/metrics.json",
    "base/units.json",
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_kpi_split_config(root: Path, payload: dict | None = None) -> Path:
    """只写入 Git 管控的基础资源文件；动态规则由 SQLite 承载。"""
    payload = payload or kpi_catalog_payload()
    _write_json(
        root / "base/metrics.json",
        {
            "schema_version": 1,
            "source_csv_sha256": payload["source_csv_sha256"],
            "metrics": payload["metrics"],
        },
    )
    _write_json(root / "base/units.json", {"schema_version": 1, "units": payload["units"]})
    return root


def seed_kpi_dynamic_config(payload: dict | None = None, *, operator: str = "test") -> None:
    """把测试动态配置写入当前 SQLite；仅供测试准备使用。"""
    payload = payload or kpi_catalog_payload()
    rules = payload["rules"]
    now = datetime.now(UTC)
    with session_factory() as session, session.begin():
        session.query(KpiMetricFormula).delete()
        session.query(KpiMetricRule).delete()
        session.query(KpiThresholdRule).delete()
        session.query(KpiCapacityRule).delete()
        session.query(KpiDisplayRule).delete()
        for item in rules["metric_rules"]:
            session.merge(
                KpiMetricRule(
                    metric_key=item["key"],
                    metric_type=item["metric_type"],
                    semantic_group=item["semantic_group"],
                    display_role=item["display_role"],
                    unit=item["unit"],
                    source_type=item["source_type"],
                    aggregation_kind=item["aggregation"]["kind"],
                    description=item.get("description"),
                    created_at=now,
                    updated_at=now,
                )
            )
            formula = item.get("formula")
            if formula is not None:
                session.merge(
                    KpiMetricFormula(
                        metric_key=item["key"],
                        numerator=formula["numerator"],
                        denominator=formula["denominator"],
                        denominator_fallback_inputs=list(formula.get("denominator_fallback", {}).get("inputs", [])),
                        scale=float(formula["scale"]),
                        created_at=now,
                        updated_at=now,
                    )
                )
        for item in rules["thresholds"]:
            session.add(
                KpiThresholdRule(
                    domain=item["domain"],
                    metric_key=item["metric_key"],
                    label=item["label"],
                    direction=item["direction"],
                    unit=item["unit"],
                    default_value=float(item["default"]),
                    periods={str(key): float(value) for key, value in item["periods"].items()},
                    created_at=now,
                    updated_at=now,
                )
            )
        for item in rules["capacity_rules"]:
            session.add(
                KpiCapacityRule(
                    source_name=item["source_name"],
                    metric_key=item["metric_key"],
                    domain=item.get("domain"),
                    semantics=item.get("semantics"),
                    status=item["status"],
                    created_at=now,
                    updated_at=now,
                )
            )
        for item in rules["display_rules"]:
            session.add(
                KpiDisplayRule(
                    domain=item["domain"],
                    metric_key=item["metric_key"],
                    role=item["role"],
                    created_at=now,
                    updated_at=now,
                )
            )
        common = rules["common"]
        session.merge(
            KpiCommonConfig(
                id=1,
                input_timezone=common["input_timezone"],
                max_files=common["budgets"]["max_files"],
                max_records=common["budgets"]["max_records"],
                updated_at=now,
            )
        )
        revision = session.get(KpiRuleConfigRevision, 1)
        if revision is None:
            revision = KpiRuleConfigRevision(id=1, revision=0, updated_at=now)
            session.add(revision)


def configure_kpi_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_dir: Path | None = None,
    sqlite_path: Path | None = None,
    payload: dict | None = None,
) -> Path:
    """初始化测试数据库、写入基础资源、分类标准指标并注入动态配置。"""
    monkeypatch.setattr(settings, "output_dir", output_dir or tmp_path / "output")
    monkeypatch.setattr(settings, "sqlite_path", sqlite_path or tmp_path / "kpi.db")
    init_db()
    data_dir = tmp_path / "kpi"
    write_kpi_split_config(data_dir, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    classify_resource_metrics(
        [metric["key"] for metric in (payload or kpi_catalog_payload())["metrics"]],
        domain="call",
        operator="test",
    )
    seed_kpi_dynamic_config(payload)
    return data_dir


def write_kpi_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict) -> Path:
    """兼容旧测试名；写入基础资源并按当前 SQLite 重建动态配置。"""
    data_dir = write_kpi_split_config(tmp_path, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    seed_kpi_dynamic_config(payload)
    return data_dir
