"""测量单元管理 API 契约测试。"""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.main import app

CSV = "资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n"


def _client() -> TestClient:
    return TestClient(app)


def _import_csv(client: TestClient) -> dict:
    response = client.post(
        "/api/v5/kpi/measurement-units/import",
        files={"file": ("resources.csv", BytesIO(CSV.encode("utf-8")), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_import_list_and_toggle_measurement_units() -> None:
    with _client() as client:
        result = _import_csv(client)
        assert result["added"] == {"mu": 1, "me": 1, "unit": 0}

        listed = client.get("/api/v5/kpi/measurement-units", params={"search": "呼叫"})
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        unit = listed.json()["items"][0]
        assert unit["resource_id"] == "MU_CALL"
        assert unit["filename_fragment"] == "Call_Statistics"

        updated = client.patch("/api/v5/kpi/measurement-units/MU_CALL", json={"enabled": False})
        assert updated.status_code == 200, updated.text
        assert updated.json()["enabled"] is False
        filtered = client.get("/api/v5/kpi/measurement-units", params={"enabled": True})
        assert filtered.json()["total"] == 0


def test_binding_list_and_status_api() -> None:
    with _client() as client:
        _import_csv(client)
        listed = client.get("/api/v5/kpi/measurement-bindings")
        assert listed.status_code == 200, listed.text
        assert listed.json() == {"total": 0, "items": []}


def test_create_derived_api_validates_bindings() -> None:
    with _client() as client:
        _import_csv(client)
        response = client.post(
            "/api/v5/kpi/measurement-derived",
            json={
                "measurement_unit_id": "MU_CALL",
                "metric_resource_id": "ME_CALL",
                "numerator_metric_id": "ME_CALL",
                "denominator_metric_id": "ME_CALL",
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "kpi_binding_not_confirmed"


def test_import_resource_csv_does_not_use_default_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    """资源导入必须在内存解析，避免 Windows 默认 TEMP 无权限导致失败。"""

    def fail(*args: object, **kwargs: object) -> object:
        raise PermissionError("default temp is unavailable")

    monkeypatch.setattr("app.api.router.tempfile.NamedTemporaryFile", fail)
    with _client() as client:
        result = _import_csv(client)
    assert result["added"] == {"mu": 1, "me": 1, "unit": 0}
