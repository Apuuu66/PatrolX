"""KPI 任务快照组合与追溯测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.models.db import init_db
from app.services.kpi_catalog import KpiSnapshotError, load_task_kpi_config
from app.services.kpi_resources import classify_resource_metrics


def _write_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, metric_count: int = 2) -> Path:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "source_csv_sha256": "a" * 64,
        "metrics": [
            {
                "resource_id": f"ME_{index}",
                "key": f"me_{index}",
                "name_zh": f"指标{index}",
                "name_en": f"Metric {index}",
                "unit_key": None,
            }
            for index in range(1, metric_count + 1)
        ],
        "units": [],
        "rules": {
            "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 10, "max_records": 20}},
            "metric_rules": [
                {
                    "key": "me_2",
                    "metric_type": "count",
                    "semantic_group": "traffic",
                    "display_role": "context",
                    "unit": "次",
                    "source_type": "raw",
                    "aggregation": {"kind": "sum"},
                    "formula": None,
                }
            ],
            "thresholds": [],
            "capacity_rules": [],
            "display_rules": [],
        },
    }
    path = tmp_path / "kpi_catalog.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "kpi_catalog_path", path)
    return path


@pytest.fixture()
def db_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "db.sqlite")
    init_db()
    return _write_catalog(tmp_path, monkeypatch)


def test_snapshot_written_and_reused(db_catalog: Path, tmp_path: Path) -> None:
    classify_resource_metrics(["me_1", "me_2"], domain="call", operator="alice")
    task_id = "task-snapshot"
    config = load_task_kpi_config(task_id)
    snapshot_path = settings.output / task_id / "kpi" / "kpi_catalog_snapshot.json"
    assert snapshot_path.is_file()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["classification_version"] == 1
    assert {item["key"] for item in snapshot["metrics"]} == {"me_1", "me_2"}
    assert snapshot["metrics"][0]["domain"] == "call"
    assert snapshot["rules"]["metric_rules"][0]["key"] == "me_2"
    assert config.classification_version == 1

    classify_resource_metrics(["me_1"], domain="api", operator="bob")
    load_task_kpi_config(task_id)
    unchanged = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert unchanged["classification_version"] == 1
    assert unchanged["metrics"][0]["domain"] == "call"


def test_snapshot_missing_reads_current_catalog(db_catalog: Path, tmp_path: Path) -> None:
    task_id = "task-missing"
    load_task_kpi_config(task_id)
    assert (settings.output / task_id / "kpi" / "kpi_catalog_snapshot.json").is_file()


def test_snapshot_corruption_fails(db_catalog: Path) -> None:
    task_id = "task-corrupt"
    load_task_kpi_config(task_id)
    path = settings.output / task_id / "kpi" / "kpi_catalog_snapshot.json"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(KpiSnapshotError, match="损坏"):
        load_task_kpi_config(task_id)


def test_database_unavailable_fails_without_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "missing" / "nested" / "db.sqlite")
    _write_catalog(tmp_path, monkeypatch)
    with pytest.raises(KpiSnapshotError, match="数据库不可用"):
        load_task_kpi_config("task-db-failure")
    assert not (settings.output / "task-db-failure" / "kpi" / "kpi_catalog_snapshot.json").exists()
