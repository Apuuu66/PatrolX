"""认证服务测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models.db import init_db
from app.services.auth import AuthError, create_user, hash_password, login, logout, verify_password


@pytest.fixture(autouse=True)
def _init_db() -> None:
    init_db()


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def test_hash_and_verify_password() -> None:
    stored = hash_password("secret123")
    assert stored != "secret123"
    assert verify_password("secret123", stored)
    assert not verify_password("wrong", stored)


def test_create_user_and_login() -> None:
    create_user("testadmin", "pass123", role="admin")
    result = login("testadmin", "pass123")
    assert result["username"] == "testadmin"
    assert result["role"] == "admin"
    assert len(result["token"]) > 20


def test_login_wrong_password() -> None:
    create_user("testuser", "correct", role="viewer")
    with pytest.raises(AuthError, match="用户名或密码错误"):
        login("testuser", "wrong")


def test_login_nonexistent_user() -> None:
    with pytest.raises(AuthError, match="用户名或密码错误"):
        login("ghost", "whatever")


def test_create_duplicate_user() -> None:
    create_user("dup", "pass", role="viewer")
    with pytest.raises(AuthError, match="用户已存在"):
        create_user("dup", "pass", role="viewer")


def test_logout_invalidates_token() -> None:
    create_user("logout_user", "pass", role="viewer")
    result = login("logout_user", "pass")
    token = result["token"]
    logout(token)
    with pytest.raises(AuthError, match="会话已失效"):
        from app.services.auth import _resolve_session

        _resolve_session(token)


def test_invalid_role_rejected() -> None:
    with pytest.raises(AuthError, match="非法角色"):
        create_user("badrole", "pass", role="superuser")


class TestAuthAPI:
    """通过 FastAPI TestClient 测试认证端点。"""

    def test_login_endpoint(self, client: TestClient) -> None:
        create_user("api_user", "secret", role="admin")
        resp = client.post("/api/v1/auth/login", json={"username": "api_user", "password": "secret"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"
        assert "token" in data

    def test_login_endpoint_wrong_password(self, client: TestClient) -> None:
        create_user("api_user2", "secret", role="viewer")
        resp = client.post("/api/v1/auth/login", json={"username": "api_user2", "password": "bad"})
        assert resp.status_code == 401
        assert resp.json()["code"] == "invalid_credentials"

    def test_me_endpoint(self, client: TestClient) -> None:
        create_user("me_user", "pass", role="viewer")
        login_result = login("me_user", "pass")
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login_result['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "me_user"

    def test_me_endpoint_no_token(self, client: TestClient) -> None:
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_logout_endpoint(self, client: TestClient) -> None:
        create_user("out_user", "pass", role="viewer")
        result = login("out_user", "pass")
        token = result["token"]
        resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        # Token should now be invalid
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_write_endpoint_requires_auth(self, client: TestClient) -> None:
        # Try to classify without token → 401
        resp = client.put(
            "/api/v3/kpi/resource-metrics/classification",
            json={"metric_keys": ["me_call_attempts"], "domain": "call", "operator": "x"},
        )
        assert resp.status_code == 401

    def test_write_endpoint_admin_required(self, client: TestClient) -> None:
        # Viewer cannot write
        create_user("viewonly", "pass", role="viewer")
        result = login("viewonly", "pass")
        resp = client.put(
            "/api/v3/kpi/resource-metrics/classification",
            json={"metric_keys": ["me_call_attempts"], "domain": "call", "operator": "x"},
            headers={"Authorization": f"Bearer {result['token']}"},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "forbidden"

    def test_write_endpoint_admin_can_write(self, client: TestClient) -> None:
        # Admin can write (may fail for other reasons like metric not found, but not 401/403)
        create_user("theadmin", "pass", role="admin")
        result = login("theadmin", "pass")
        resp = client.put(
            "/api/v3/kpi/resource-metrics/classification",
            json={"metric_keys": ["nonexistent_metric"], "domain": "call", "operator": "x"},
            headers={"Authorization": f"Bearer {result['token']}"},
        )
        assert resp.status_code != 401
        assert resp.status_code != 403
