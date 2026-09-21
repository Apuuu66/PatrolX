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


def test_ensure_default_admin_resets_existing_admin_password(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings
    from app.services.auth import _resolve_session, ensure_default_admin

    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "default-admin.db")
    init_db()
    assert ensure_default_admin("boot_admin", "boot-pass-123") == "created"
    old_session = login("boot_admin", "boot-pass-123")
    assert ensure_default_admin("boot_admin", "new-pass-123") == "password_updated"

    with pytest.raises(AuthError, match="会话已失效"):
        _resolve_session(old_session["token"])
    assert login("boot_admin", "new-pass-123")["role"] == "admin"


def test_ensure_default_admin_requires_existing_admin(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings
    from app.services.auth import ensure_default_admin

    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "existing-admin.db")
    init_db()
    create_user("root_admin", "root-pass-123", role="admin")

    with pytest.raises(AuthError) as exc_info:
        ensure_default_admin("another_admin", "another-pass-123")
    assert exc_info.value.code == "admin_not_found"


def test_ensure_default_admin_rejects_non_admin_target(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings
    from app.services.auth import ensure_default_admin

    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "viewer-target.db")
    init_db()
    create_user("normal_user", "normal-pass-123", role="viewer")

    with pytest.raises(AuthError) as exc_info:
        ensure_default_admin("normal_user", "another-pass-123")
    assert exc_info.value.code == "target_not_admin"


def test_cli_create_default_admin(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.cli import main
    from app.core.config import settings

    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "cli-admin.db")
    init_db()
    assert main(["create-default-admin", "--username", "cli_admin", "--password", "cli-pass-123"]) == 0
    assert login("cli_admin", "cli-pass-123")["role"] == "admin"
    assert main(["create-default-admin", "--username", "cli_admin", "--password", "cli-pass-456"]) == 0
    assert login("cli_admin", "cli-pass-456")["role"] == "admin"


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

    def test_task_endpoints_allow_anonymous(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """任务创建/重跑/重建/删除属于执行操作，访客模式不需要登录。"""
        from app.api import router as api_router
        from app.models.schemas import TaskCreated
        from app.services.tasks import DeleteResult

        monkeypatch.setattr(api_router.task_service, "exists", lambda task_id: False)
        monkeypatch.setattr(
            api_router.task_service,
            "reserve",
            lambda *args, **kwargs: TaskCreated(task_id="guest-task"),
        )
        monkeypatch.setattr(api_router.task_service, "submit", lambda task_id: None)
        monkeypatch.setattr(api_router.task_service, "rerun", lambda task_id, codes: True)
        monkeypatch.setattr(api_router.task_service, "rebuild", lambda task_id, body: True)
        monkeypatch.setattr(api_router.task_service, "delete", lambda task_id: DeleteResult.DELETED)

        upload = client.post(
            "/api/v2/tasks",
            files={"package_file": ("guest.zip", b"guest-package", "application/zip")},
        )
        assert upload.status_code == 202

        rerun = client.post("/api/v2/tasks/guest-task/rerun", json={})
        assert rerun.status_code == 202

        rebuild = client.post(
            "/api/v2/tasks/guest-task/rebuild",
            json={"mode": "full", "confirmed": True, "trigger_source": "ui"},
        )
        assert rebuild.status_code == 202

        deleted = client.delete("/api/v2/tasks/guest-task")
        assert deleted.status_code == 204

    def test_write_endpoint_requires_auth(self, client: TestClient) -> None:
        # Try to classify without token → 401
        resp = client.post(
            "/api/v5/kpi/measurement-units/import",
            files={"file": ("resources.csv", "资源id,中文描述,英文描述\n", "text/csv")},
        )
        assert resp.status_code == 401

    def test_write_endpoint_admin_required(self, client: TestClient) -> None:
        # Viewer cannot write
        create_user("viewonly", "pass", role="viewer")
        result = login("viewonly", "pass")
        resp = client.post(
            "/api/v5/kpi/measurement-units/import",
            files={"file": ("resources.csv", "资源id,中文描述,英文描述\n", "text/csv")},
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

    def _login_as(self, username: str, password: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {login(username, password)['token']}"}

    def test_user_management_requires_admin(self, client: TestClient) -> None:
        create_user("user_admin", "admin-pass-123", role="admin")
        create_user("user_viewer", "viewer-pass-123", role="viewer")
        admin = self._login_as("user_admin", "admin-pass-123")
        viewer = self._login_as("user_viewer", "viewer-pass-123")

        assert client.get("/api/v1/users").status_code == 401
        assert client.get("/api/v1/users", headers=viewer).status_code == 403
        assert client.post("/api/v1/users", json={}, headers=viewer).status_code == 403

        listed = client.get("/api/v1/users?page=1&page_size=200", headers=admin)
        assert listed.status_code == 200
        usernames = {item["username"] for item in listed.json()["items"]}
        assert {"user_admin", "user_viewer"}.issubset(usernames)

    def test_user_lifecycle(self, client: TestClient) -> None:
        create_user("lifecycle_admin", "admin-pass-123", role="admin")
        admin = self._login_as("lifecycle_admin", "admin-pass-123")

        created = client.post(
            "/api/v1/users",
            json={"username": "lifecycle_user", "password": "user-pass-123", "role": "viewer"},
            headers=admin,
        )
        assert created.status_code == 201
        assert created.json()["username"] == "lifecycle_user"

        user_login = login("lifecycle_user", "user-pass-123")
        old_token = user_login["token"]
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 200

        reset = client.put(
            "/api/v1/users/lifecycle_user/password",
            json={"new_password": "new-user-pass-123"},
            headers=admin,
        )
        assert reset.status_code == 200
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
        assert login("lifecycle_user", "new-user-pass-123")["role"] == "viewer"

        role = client.patch(
            "/api/v1/users/lifecycle_user",
            json={"role": "admin"},
            headers=admin,
        )
        assert role.status_code == 200
        assert login("lifecycle_user", "new-user-pass-123")["role"] == "admin"

        deleted = client.delete("/api/v1/users/lifecycle_user", headers=admin)
        assert deleted.status_code == 204
        with pytest.raises(AuthError, match="用户名或密码错误"):
            login("lifecycle_user", "new-user-pass-123")

    def test_user_management_guards(self, client: TestClient) -> None:
        create_user("guard_admin", "admin-pass-123", role="admin")
        create_user("guard_viewer", "viewer-pass-123", role="viewer")
        admin = self._login_as("guard_admin", "admin-pass-123")

        duplicate = client.post(
            "/api/v1/users",
            json={"username": "guard_viewer", "password": "viewer-pass-123", "role": "viewer"},
            headers=admin,
        )
        assert duplicate.status_code == 409

        self_role = client.patch("/api/v1/users/guard_admin", json={"role": "viewer"}, headers=admin)
        assert self_role.status_code == 403

        self_delete = client.delete("/api/v1/users/guard_admin", headers=admin)
        assert self_delete.status_code == 403

        demote_last = client.patch("/api/v1/users/guard_admin", json={"role": "viewer"}, headers=admin)
        assert demote_last.status_code == 403
