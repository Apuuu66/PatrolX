"""数据列表默认分页契约测试。"""

from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app


def test_data_list_apis_default_to_page_size_ten() -> None:
    client = TestClient(app)

    tasks = client.get("/api/v2/tasks")
    assert tasks.status_code == 200
    assert tasks.json()["page_size"] == 10

    users = client.get("/api/v1/users")
    assert users.status_code == 200
    assert users.json()["page_size"] == 10


def test_measurement_units_default_to_page_size_ten() -> None:
    rows = "".join(f"MU_{index:02d},测量单元 {index:02d},Measurement {index:02d}\n" for index in range(1, 12))
    csv_bytes = f"资源id,中文描述,英文描述\n{rows}".encode()
    with TestClient(app) as client:
        imported = client.post(
            "/api/v5/kpi/measurement-units/import",
            files={"file": ("resources.csv", BytesIO(csv_bytes), "text/csv")},
        )
        assert imported.status_code == 200, imported.text

        listed = client.get("/api/v5/kpi/measurement-units")
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] == 11
        assert len(body["items"]) == 10
