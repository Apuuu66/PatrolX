"""KPI 动态配置删除契约回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db import KpiRuleConfigAudit, session_factory
from tests.kpi_helpers import configure_kpi_catalog

client = TestClient(app)


@pytest.mark.parametrize(
    ("endpoint", "entity_type", "entity_key"),
    [
        ("/api/v4/kpi/config/metric-rules/me_call_attempts", "metric_rule", "me_call_attempts"),
        ("/api/v4/kpi/config/thresholds/1", "threshold", "1"),
        ("/api/v4/kpi/config/capacity-rules/1", "capacity_rule", "1"),
    ],
)
def test_delete_uses_authenticated_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str, entity_type: str, entity_key: str
) -> None:
    configure_kpi_catalog(tmp_path, monkeypatch)

    response = client.delete(endpoint)
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True

    with session_factory() as session:
        audit = (
            session.query(KpiRuleConfigAudit)
            .filter_by(entity_type=entity_type, entity_key=entity_key, operation="delete")
            .one()
        )
        assert audit.operator == "integration-admin"


def test_delete_display_rule_uses_authenticated_operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_kpi_catalog(tmp_path, monkeypatch)
    created = client.post(
        "/api/v4/kpi/config/display-rules",
        json={"domain": "call", "metric_key": "me_call_attempts", "role": "context", "operator": "setup"},
    )
    assert created.status_code == 202, created.text
    display_rule_id = created.json()["id"]

    response = client.delete(f"/api/v4/kpi/config/display-rules/{display_rule_id}")
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True

    with session_factory() as session:
        audit = (
            session.query(KpiRuleConfigAudit)
            .filter_by(entity_type="display_rule", entity_key=str(display_rule_id), operation="delete")
            .one()
        )
        assert audit.operator == "integration-admin"
