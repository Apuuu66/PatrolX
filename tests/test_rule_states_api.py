"""规则启停状态 API 契约测试。"""

from fastapi.testclient import TestClient

from app.main import app
from app.models.db import AuthSession, RuleState, session_factory
from app.services.auth import get_current_user
from app.services.rule_states import ensure_rule_states


def test_inspector_states_default_page_size_is_ten() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v2/inspector-states")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert len(body["items"]) == 10
    assert body["total"] >= 10


def test_inspector_states_support_filters() -> None:
    ensure_rule_states()
    with TestClient(app) as client:
        disabled = client.get("/api/v2/inspector-states", params={"enabled": "false", "page_size": 100})
        by_category = client.get("/api/v2/inspector-states", params={"category": "log", "page_size": 100})
        by_search = client.get("/api/v2/inspector-states", params={"search": "error_density", "page_size": 100})

    assert disabled.status_code == 200
    assert all(item["enabled"] is False for item in disabled.json()["items"])
    assert {item["code"] for item in disabled.json()["items"]} == {"log.ccc_service", "log.ddd_service"}
    assert by_category.status_code == 200
    assert all(item["category"] == "log" for item in by_category.json()["items"])
    assert by_search.status_code == 200
    assert [item["code"] for item in by_search.json()["items"]] == ["log.error_density"]


def test_admin_updates_rule_state() -> None:
    ensure_rule_states()
    with TestClient(app) as client:
        response = client.put(
            "/api/v2/inspector-states/log.error_density/enabled",
            json={"enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    with session_factory() as session:
        assert session.get(RuleState, "log.error_density").enabled is False


def test_viewer_cannot_update_rule_state() -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthSession(
        token="viewer-token", username="viewer", role="viewer"
    )
    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/v2/inspector-states/log.error_density/enabled",
                json={"enabled": False},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_unknown_and_hidden_rules_return_explicit_errors() -> None:
    ensure_rule_states()
    with TestClient(app) as client:
        unknown = client.put(
            "/api/v2/inspector-states/rule.not_registered/enabled",
            json={"enabled": False},
        )
        hidden = client.put(
            "/api/v2/inspector-states/pkg.extract.main/enabled",
            json={"enabled": False},
        )

    assert unknown.status_code == 404
    assert unknown.json()["code"] == "not_found"
    assert hidden.status_code == 409
    assert hidden.json()["code"] == "rule_not_manageable"


def test_non_boolean_state_is_validation_error() -> None:
    ensure_rule_states()
    with TestClient(app) as client:
        response = client.put(
            "/api/v2/inspector-states/log.error_density/enabled",
            json={"enabled": "false"},
        )
    assert response.status_code == 422
