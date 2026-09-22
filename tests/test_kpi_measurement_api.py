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
        _create_unregistered_binding(metric_resource_id="ME_CALL")
        listed = client.get("/api/v5/kpi/measurement-bindings")
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1

        for query in ("MU_", "呼叫", "Call"):
            searched = client.get("/api/v5/kpi/measurement-bindings", params={"unit_search": query})
            assert searched.status_code == 200, searched.text
            assert searched.json()["total"] == 1
            assert searched.json()["items"][0]["measurement_unit_id"] == "MU_CALL"

        missing = client.get("/api/v5/kpi/measurement-bindings", params={"unit_search": "MU_OTHER"})
        assert missing.status_code == 200, missing.text
        assert missing.json() == {"total": 0, "items": []}

        metric_search = client.get("/api/v5/kpi/measurement-bindings", params={"search": "ME_CALL"})
        assert metric_search.status_code == 200, metric_search.text
        assert metric_search.json()["total"] == 1
        assert metric_search.json()["items"][0]["metric_resource_id"] == "ME_CALL"


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


def _create_unregistered_binding(
    base_source_name: str = "呼叫请求次数",
    metric_resource_id: str | None = None,
) -> int:
    from datetime import UTC, datetime

    from app.models.db import KpiMeasurementBinding, session_factory

    with session_factory() as session:
        row = KpiMeasurementBinding(
            metric_resource_id=metric_resource_id,
            measurement_unit_id="MU_CALL",
            raw_source_name=f"{base_source_name}(次)",
            base_source_name=base_source_name,
            display_unit="次",
            status="candidate",
            enabled=True,
            task_id="task-1",
            source_file="ne333_Call_Statistics_15_0_202609020000.csv",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        return row.id


def test_register_and_edit_manual_metric_api() -> None:
    with _client() as client:
        binding_id = _create_unregistered_binding()
        response = client.post(
            f"/api/v5/kpi/measurement-bindings/{binding_id}/register-metric",
            json={"name_zh": "呼叫请求次数", "name_en": "Call Requests"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["binding"]["metric_resource_id"].startswith("ME__MANUAL_")
        assert payload["binding"]["status"] == "candidate"
        assert payload["metric"]["is_manual"] is True

        edited = client.patch(
            f"/api/v5/kpi/measurement-resources/{payload['metric']['resource_id']}",
            json={"name_zh": "呼叫请求总数", "name_en": "Call Request Total", "enabled": False},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["name_zh"] == "呼叫请求总数"
        assert edited.json()["is_manual"] is True


def test_register_existing_metric_and_resource_list_api() -> None:
    with _client() as client:
        _import_csv(client)
        binding_id = _create_unregistered_binding(base_source_name="新列")
        response = client.post(
            f"/api/v5/kpi/measurement-bindings/{binding_id}/register-metric",
            json={"name_zh": None, "name_en": None, "bind_existing_resource_id": "ME_CALL"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["binding"]["metric_resource_id"] == "ME_CALL"

        listed = client.get("/api/v5/kpi/measurement-resources", params={"kind": "me", "search": "call"})
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["resource_id"] == "ME_CALL"

        other_binding = _create_unregistered_binding(base_source_name="改绑列")
        not_me = client.post(
            f"/api/v5/kpi/measurement-bindings/{other_binding}/register-metric",
            json={"bind_existing_resource_id": "MU_CALL"},
        )
        assert not_me.status_code == 409, not_me.text
        assert not_me.json()["code"] == "kpi_metric_kind_invalid"

        missing = client.post(
            "/api/v5/kpi/measurement-bindings/999999/register-metric",
            json={"name_zh": "不存在绑定"},
        )
        assert missing.status_code == 404, missing.text
        assert missing.json()["code"] == "kpi_binding_not_found"


def test_register_metric_api_rejects_conflict_and_non_admin() -> None:
    with _client() as client:
        _import_csv(client)
        binding_id = _create_unregistered_binding(base_source_name="新列")
        conflict = client.post(
            f"/api/v5/kpi/measurement-bindings/{binding_id}/register-metric",
            json={"name_zh": "呼叫请求次数"},
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["code"] == "kpi_metric_name_conflict"
        assert conflict.json()["detail"] == {"existing_resource_id": "ME_CALL"}

        from app.main import app
        from app.models.db import AuthSession
        from app.services.auth import get_current_user

        missing_metric = client.patch("/api/v5/kpi/measurement-resources/ME_MISSING", json={"name_zh": "不存在"})
        assert missing_metric.status_code == 404, missing_metric.text
        assert missing_metric.json()["code"] == "kpi_metric_not_found"

        non_manual = client.patch("/api/v5/kpi/measurement-resources/ME_CALL", json={"name_zh": "不允许"})
        assert non_manual.status_code == 409, non_manual.text
        assert non_manual.json()["code"] == "kpi_metric_not_manual"

        app.dependency_overrides[get_current_user] = lambda: AuthSession(
            token="viewer-token", username="viewer", role="viewer"
        )
        try:
            non_admin = client.patch("/api/v5/kpi/measurement-resources/ME_CALL", json={"enabled": False})
            assert non_admin.status_code == 403, non_admin.text
            assert non_admin.json()["code"] == "forbidden"
        finally:
            app.dependency_overrides[get_current_user] = lambda: AuthSession(
                token="integration-test-token",
                username="integration-admin",
                role="admin",
            )


def test_edit_manual_metric_supports_partial_and_conflict() -> None:
    with _client() as client:
        _import_csv(client)
        binding_id = _create_unregistered_binding(base_source_name="部分更新列")
        registered = client.post(
            f"/api/v5/kpi/measurement-bindings/{binding_id}/register-metric",
            json={"name_zh": "部分更新中文", "name_en": "Partial Metric"},
        )
        assert registered.status_code == 200, registered.text
        resource_id = registered.json()["metric"]["resource_id"]

        partial = client.patch(
            f"/api/v5/kpi/measurement-resources/{resource_id}",
            json={"name_en": "Partial Metric Updated"},
        )
        assert partial.status_code == 200, partial.text
        assert partial.json()["name_zh"] == "部分更新中文"
        assert partial.json()["name_en"] == "Partial Metric Updated"

        conflict = client.patch(
            f"/api/v5/kpi/measurement-resources/{resource_id}",
            json={"name_zh": "呼叫请求次数"},
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["code"] == "kpi_metric_name_conflict"


def test_batch_confirm_bindings_api_supports_partial_success() -> None:
    with _client() as client:
        from tests.test_kpi_measurement_binding import _create_binding, _get_binding

        valid = _create_binding(metric_resource_id="ME_CALL")
        second = _create_binding(metric_resource_id="ME_CALL")
        missing_metric = _create_binding(metric_resource_id=None)
        ignored = _create_binding(metric_resource_id="ME_CALL", status="ignored")

        response = client.post(
            "/api/v5/kpi/measurement-bindings/batch-confirm",
            json={"binding_ids": [valid, second, missing_metric, ignored, 999999]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 5
        assert payload["succeeded"] == 2
        assert payload["failed"] == 3
        assert [item["binding_id"] for item in payload["items"]] == [
            valid,
            second,
            missing_metric,
            ignored,
            999999,
        ]
        assert payload["items"][0]["outcome"] == "confirmed"
        assert payload["items"][0]["binding"]["status"] == "confirmed"
        assert payload["items"][2]["error_code"] == "kpi_binding_metric_missing"
        assert _get_binding(missing_metric)["status"] == "candidate"
        assert _get_binding(ignored)["status"] == "ignored"


def test_batch_confirm_bindings_api_rejects_empty_and_non_admin() -> None:
    with _client() as client:
        empty = client.post("/api/v5/kpi/measurement-bindings/batch-confirm", json={"binding_ids": []})
        assert empty.status_code == 422, empty.text

        from app.main import app
        from app.models.db import AuthSession
        from app.services.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: AuthSession(
            token="viewer-token", username="viewer", role="viewer"
        )
        try:
            non_admin = client.post(
                "/api/v5/kpi/measurement-bindings/batch-confirm",
                json={"binding_ids": [1]},
            )
            assert non_admin.status_code == 403, non_admin.text
            assert non_admin.json()["code"] == "forbidden"
        finally:
            app.dependency_overrides[get_current_user] = lambda: AuthSession(
                token="integration-test-token",
                username="integration-admin",
                role="admin",
            )
