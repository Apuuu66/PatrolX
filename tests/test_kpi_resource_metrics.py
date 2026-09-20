"""KPI 基础指标配置页面行为与未登记指标线索回归。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.inspectors.registry import registry
from app.main import app
from app.models.db import init_db
from app.services.executor import RuleContext
from app.services.kpi_resources import classify_resource_metrics
from tests.kpi_helpers import kpi_catalog_payload, write_kpi_split_config

client = TestClient(app)


def _setup(tmp_path: Path, monkeypatch, metrics: list[dict] | None = None) -> Path:
    payload = kpi_catalog_payload()
    payload["metrics"] = metrics if metrics is not None else payload["metrics"]
    data_dir = write_kpi_split_config(tmp_path, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "db.sqlite")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    init_db()
    return data_dir


def test_missing_base_metric_is_only_a_retired_clue(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    classify_resource_metrics(["me_call_attempts"], domain="call", operator="alice")
    payload = kpi_catalog_payload()
    payload["metrics"] = []
    payload["rules"]["metric_rules"] = []
    payload["rules"]["thresholds"] = []
    payload["rules"]["capacity_rules"] = []
    data_dir = write_kpi_split_config(tmp_path / "changed", payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    page = client.get("/api/v3/kpi/resource-metrics", params={"include_missing": True}).json()
    removed = next(item for item in page["items"] if item["key"] == "me_call_attempts")
    assert removed["missing_from_base"] is True
    assert removed["domain"] == "call"
    assert not any(item["key"] == "me_call_attempts" for item in page["items"] if not item["missing_from_base"])


def test_unregistered_metric_is_a_clue_not_rule_failure(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    classify_resource_metrics(
        [item["key"] for item in kpi_catalog_payload()["metrics"]], domain="call", operator="alice"
    )
    from app.inspectors.kpi.common import parse_csv_file

    content = (
        "设备类型：XXX\n测量单元名称：呼叫会话统计\n"
        "服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数,自定义指标\n"
        "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15,10,7\n"
    )
    path = tmp_path / "kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    from app.services.kpi_catalog import load_task_kpi_config

    config = load_task_kpi_config("clue-task")
    relative_path = path.relative_to(tmp_path).as_posix()
    parsed = parse_csv_file(path, relative_path, "call", 15, config)
    assert not parsed.records[0].errors
    registry.load_all()
    ctx = RuleContext(task_id="clue-task", data_dir=tmp_path, log=lambda *args, **kwargs: None)
    ctx.files = [path]
    result = registry.get("kpi.call").run(ctx)
    assert result.status.value in {"pass", "warn", "fail", "error", "skip"}
    assert any(item["reason"] == "metric_not_registered" for item in result.metadata["unclassified_metrics"])


def test_reserved_metric_is_hidden_from_task_unclassified(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    metric_keys = [item["key"] for item in kpi_catalog_payload()["metrics"]]
    classify_resource_metrics(metric_keys, domain="call", operator="alice")
    classify_resource_metrics(["me_call_attempts"], domain="reserved", operator="alice")

    from app.services.kpi_catalog import load_task_kpi_config

    content = (
        "设备类型：XXX\n测量单元名称：呼叫会话统计\n"
        "服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数,自定义指标\n"
        "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15,10,7\n"
    )
    path = tmp_path / "kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    config = load_task_kpi_config("reserved-task")
    assert config.reserved_metric_keys == {"me_call_attempts"}
    snapshot_path = settings.output / "reserved-task" / "kpi" / "kpi_catalog_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["reserved_metric_keys"] == ["me_call_attempts"]

    registry.load_all()
    ctx = RuleContext(task_id="reserved-task", data_dir=tmp_path, log=lambda *args, **kwargs: None)
    ctx.files = [path]
    result = registry.get("kpi.call").run(ctx)
    names = {item["source_name"] for item in result.metadata["unclassified_metrics"]}
    assert "呼叫请求次数" not in names
    assert "自定义指标" in names
