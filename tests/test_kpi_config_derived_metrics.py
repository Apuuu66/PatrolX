"""KPI 在线派生指标 CRUD 契约测试。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.db import KpiDisplayRule, KpiRuleConfigAudit, init_db, session_factory
from app.services.kpi_resources import classify_resource_metrics
from tests.kpi_helpers import write_kpi_split_config

client = TestClient(app)


@pytest.fixture()
def derived_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "source_csv_sha256": "a" * 64,
        "metrics": [
            {"resource_id": "ME_1", "key": "me_1", "name_zh": "成功数", "name_en": "Success", "unit_key": None},
            {"resource_id": "ME_2", "key": "me_2", "name_zh": "总数", "name_en": "Total", "unit_key": None},
        ],
        "units": [],
        "rules": {
            "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 10, "max_records": 20}},
            "metric_rules": [],
            "thresholds": [],
            "capacity_rules": [],
            "display_rules": [],
        },
    }
    data_dir = tmp_path / "kpi"
    write_kpi_split_config(data_dir, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "db.sqlite")
    init_db()
    classify_resource_metrics(["me_1", "me_2"], domain="call", operator="test")
    return data_dir


def _create_payload(metric_key: str = "call_success_rate", kind: str = "ratio") -> dict:
    return {
        "metric_key": metric_key,
        "name_zh": "呼叫成功率",
        "name_en": "Call Success Rate",
        "domain": "call",
        "metric_type": "rate",
        "semantic_group": "quality",
        "display_role": "highlight",
        "unit": "%",
        "enabled": True,
        "formula": {"kind": kind, "numerator": "me_1", "denominator": "me_2", "scale": 100},
    }


def test_derived_metric_crud_and_audit(derived_env: Path) -> None:
    created = client.post("/api/v4/kpi/config/derived-metrics", json=_create_payload())
    assert created.status_code == 202, created.text
    assert created.headers["Location"].endswith("/api/v4/kpi/config/derived-metrics/call_success_rate")
    body = created.json()
    assert body["formula"]["kind"] == "ratio"
    assert body["rule_config_version"] == 1

    inverse = client.post(
        "/api/v4/kpi/config/derived-metrics",
        json=_create_payload("call_failure_rate", "inverse_ratio"),
    )
    assert inverse.status_code == 202
    assert inverse.json()["formula"]["kind"] == "inverse_ratio"

    page = client.get("/api/v4/kpi/config/derived-metrics").json()
    assert page["total"] == 2
    detail = client.get("/api/v4/kpi/config/derived-metrics/call_success_rate")
    assert detail.status_code == 200

    updated = client.put(
        "/api/v4/kpi/config/derived-metrics/call_success_rate",
        json={**_create_payload(), "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = client.delete("/api/v4/kpi/config/derived-metrics/call_success_rate")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    with session_factory() as session:
        audits = session.query(KpiRuleConfigAudit).filter_by(entity_type="derived_metric").all()
        assert [item.operation for item in audits] == ["upsert", "upsert", "upsert", "delete"]
        assert audits[-1].before is not None


def test_derived_metric_auto_generates_unique_key(derived_env: Path) -> None:
    first_payload = _create_payload()
    first_payload.pop("metric_key")
    first = client.post("/api/v4/kpi/config/derived-metrics", json=first_payload)
    assert first.status_code == 202, first.text
    first_key = first.json()["metric_key"]
    assert re.fullmatch(r"^[a-z][a-z0-9_]{2,127}$", first_key)
    assert first.headers["Location"].endswith(f"/api/v4/kpi/config/derived-metrics/{first_key}")

    second_payload = _create_payload()
    second_payload.pop("metric_key")
    second = client.post("/api/v4/kpi/config/derived-metrics", json=second_payload)
    assert second.status_code == 202, second.text
    second_key = second.json()["metric_key"]
    assert second_key != first_key


def test_derived_metric_validations(derived_env: Path) -> None:
    assert client.post("/api/v4/kpi/config/derived-metrics", json=_create_payload()).status_code == 202
    assert client.post("/api/v4/kpi/config/derived-metrics", json=_create_payload()).status_code == 409
    invalid_key = _create_payload("Bad-Key")
    assert client.post("/api/v4/kpi/config/derived-metrics", json=invalid_key).status_code == 400
    unknown = _create_payload("missing_rate")
    unknown["formula"]["denominator"] = "me_missing"
    assert client.post("/api/v4/kpi/config/derived-metrics", json=unknown).status_code == 400
    zero_scale = _create_payload("zero_scale")
    zero_scale["formula"]["scale"] = 0
    assert client.post("/api/v4/kpi/config/derived-metrics", json=zero_scale).status_code == 422
    cross_domain = _create_payload("cross_rate")
    cross_domain["domain"] = "api"
    assert client.post("/api/v4/kpi/config/derived-metrics", json=cross_domain).status_code == 400


def test_derived_metric_delete_reference_protection(derived_env: Path) -> None:
    assert client.post("/api/v4/kpi/config/derived-metrics", json=_create_payload()).status_code == 202
    now = datetime.now(UTC)
    with session_factory() as session, session.begin():
        session.add(
            KpiDisplayRule(
                domain="call",
                metric_key="call_success_rate",
                role="highlight",
                created_at=now,
                updated_at=now,
            )
        )
    assert client.delete("/api/v4/kpi/config/derived-metrics/call_success_rate").status_code == 409


def test_derived_metric_write_requires_admin(derived_env: Path) -> None:
    from app.main import app
    from app.models.db import AuthSession
    from app.services.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: AuthSession(
        token="viewer-token",
        username="viewer",
        role="viewer",
    )
    try:
        assert client.post("/api/v4/kpi/config/derived-metrics", json=_create_payload()).status_code == 403
        assert (
            client.put("/api/v4/kpi/config/derived-metrics/call_success_rate", json=_create_payload()).status_code
            == 403
        )
        assert client.delete("/api/v4/kpi/config/derived-metrics/call_success_rate").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_derived_metric_invalid_configs_do_not_audit(derived_env: Path) -> None:
    assert client.post("/api/v4/kpi/config/derived-metrics", json=_create_payload()).status_code == 202

    derived_input = _create_payload("nested_rate")
    derived_input["formula"]["numerator"] = "call_success_rate"
    assert client.post("/api/v4/kpi/config/derived-metrics", json=derived_input).status_code == 400

    duplicate_fallback = _create_payload("duplicate_fallback")
    duplicate_fallback["formula"]["denominator_fallback_inputs"] = ["me_1", "me_1"]
    assert client.post("/api/v4/kpi/config/derived-metrics", json=duplicate_fallback).status_code == 400

    with session_factory() as session:
        audits = session.query(KpiRuleConfigAudit).filter_by(entity_type="derived_metric").count()
    assert audits == 1
