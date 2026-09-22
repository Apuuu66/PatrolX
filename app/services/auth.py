"""认证服务：SQLite 存储用户和会话，不支持在线注册。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, Header
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.db import AuthSession, AuthUser, session_factory

TOKEN_TTL_HOURS = 24
PBKDF2_ITERATIONS = 260_000

VALID_ROLES = {"admin", "viewer"}


class AuthError(Exception):
    """认证业务错误。"""

    def __init__(self, code: str, message: str, status_code: int = 401, detail: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 生成密码哈希（格式：salt$hash）。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码与存储的哈希是否匹配。"""
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return secrets.compare_digest(digest.hex(), expected)


def create_user(username: str, password: str, role: str = "viewer") -> dict[str, object]:
    """创建用户。用户名已存在时抛出异常。"""
    if role not in VALID_ROLES:
        raise AuthError("invalid_role", f"非法角色: {role}", 400)
    now = datetime.now(UTC)
    try:
        with session_factory() as session:
            if session.get(AuthUser, username) is not None:
                raise AuthError("user_exists", f"用户已存在: {username}", 409)
            session.add(
                AuthUser(
                    username=username, password_hash=hash_password(password), role=role, created_at=now, updated_at=now
                )
            )
            session.commit()
            return {
                "username": username,
                "role": role,
                "created_at": now,
                "updated_at": now,
            }
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def change_password(username: str, old_password: str, new_password: str) -> None:
    """CLI 使用：修改密码。"""
    try:
        with session_factory() as session:
            user = session.get(AuthUser, username)
            if user is None:
                raise AuthError("user_not_found", f"用户不存在: {username}", 404)
            if not verify_password(old_password, user.password_hash):
                raise AuthError("wrong_password", "原密码错误", 403)
            user.password_hash = hash_password(new_password)
            user.updated_at = datetime.now(UTC)
            session.commit()
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def list_users(page: int = 1, page_size: int = 10) -> dict[str, object]:
    """返回认证用户台账；仅认证管理服务使用。"""
    offset = (page - 1) * page_size
    try:
        with session_factory() as session:
            total = session.scalar(select(func.count()).select_from(AuthUser)) or 0
            query = select(AuthUser).order_by(AuthUser.username).offset(offset).limit(page_size)
            records = session.scalars(query).all()
            items = [
                {
                    "username": record.username,
                    "role": record.role,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                }
                for record in records
            ]
            return {"items": items, "total": total, "page": page, "page_size": page_size}
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def update_user_role(username: str, role: str, current_username: str) -> dict[str, object]:
    """更新用户角色，并使其旧会话立即失效。"""
    if role not in VALID_ROLES:
        raise AuthError("invalid_role", f"非法角色: {role}", 400)
    if username == current_username:
        raise AuthError("self_role_change_forbidden", "不能修改自己的角色", 403)
    now = datetime.now(UTC)
    try:
        with session_factory() as session:
            user = session.get(AuthUser, username)
            if user is None:
                raise AuthError("user_not_found", f"用户不存在: {username}", 404)
            admin_count = (
                session.scalar(select(func.count()).select_from(AuthUser).where(AuthUser.role == "admin")) or 0
            )
            if user.role == "admin" and role != "admin" and admin_count <= 1:
                raise AuthError("last_admin_protected", "至少保留一个管理员", 409)
            user.role = role
            user.updated_at = now
            session.execute(delete(AuthSession).where(AuthSession.username == username))
            session.commit()
            return {
                "username": user.username,
                "role": user.role,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
            }
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def reset_user_password(username: str, new_password: str) -> dict[str, object]:
    """管理员重置密码，并使目标用户全部旧会话失效。"""
    now = datetime.now(UTC)
    try:
        with session_factory() as session:
            user = session.get(AuthUser, username)
            if user is None:
                raise AuthError("user_not_found", f"用户不存在: {username}", 404)
            user.password_hash = hash_password(new_password)
            user.updated_at = now
            session.execute(delete(AuthSession).where(AuthSession.username == username))
            session.commit()
            return {
                "username": user.username,
                "role": user.role,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
            }
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def delete_user(username: str, current_username: str) -> None:
    """删除用户；保护当前登录账号和最后一个管理员。"""
    if username == current_username:
        raise AuthError("self_delete_forbidden", "不能删除当前登录账号", 403)
    try:
        with session_factory() as session:
            user = session.get(AuthUser, username)
            if user is None:
                raise AuthError("user_not_found", f"用户不存在: {username}", 404)
            if user.role == "admin":
                admin_count = (
                    session.scalar(select(func.count()).select_from(AuthUser).where(AuthUser.role == "admin")) or 0
                )
                if admin_count <= 1:
                    raise AuthError("last_admin_protected", "至少保留一个管理员", 409)
            session.execute(delete(AuthSession).where(AuthSession.username == username))
            session.delete(user)
            session.commit()
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def ensure_default_admin(username: str, password: str) -> Literal["created", "password_updated"]:
    """初始化默认管理员；目标管理员已存在时直接重置密码。"""
    if len(password) < 8:
        raise AuthError("weak_password", "管理员密码至少 8 位", 400)
    now = datetime.now(UTC)
    try:
        with session_factory() as session:
            user = session.get(AuthUser, username)
            if user is not None:
                if user.role != "admin":
                    raise AuthError("target_not_admin", f"目标用户不是管理员: {username}", 409)
                user.password_hash = hash_password(password)
                user.updated_at = now
                session.execute(delete(AuthSession).where(AuthSession.username == username))
                session.commit()
                return "password_updated"

            admin_count = (
                session.scalar(select(func.count()).select_from(AuthUser).where(AuthUser.role == "admin")) or 0
            )
            if admin_count > 0:
                raise AuthError("admin_not_found", f"管理员不存在: {username}", 409)
            session.add(
                AuthUser(
                    username=username,
                    password_hash=hash_password(password),
                    role="admin",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
            return "created"
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def login(username: str, password: str) -> dict[str, str]:
    """验证用户名密码并创建会话，返回 token 和用户信息。"""
    try:
        with session_factory() as session:
            user = session.get(AuthUser, username)
            if user is None or not verify_password(password, user.password_hash):
                raise AuthError("invalid_credentials", "用户名或密码错误", 401)
            token = secrets.token_urlsafe(48)
            now = datetime.now(UTC)
            expires = now + timedelta(hours=TOKEN_TTL_HOURS)
            session.add(
                AuthSession(token=token, username=user.username, role=user.role, created_at=now, expires_at=expires)
            )
            session.commit()
            return {"token": token, "username": user.username, "role": user.role}
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def logout(token: str) -> None:
    """删除会话。"""
    try:
        with session_factory() as session:
            record = session.get(AuthSession, token)
            if record is not None:
                session.delete(record)
                session.commit()
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def _resolve_session(token: str) -> AuthSession:
    """校验 token 有效性并返回会话记录。"""
    if not token:
        raise AuthError("unauthorized", "未登录", 401)
    try:
        with session_factory() as session:
            record = session.get(AuthSession, token)
            if record is None:
                raise AuthError("unauthorized", "会话已失效，请重新登录", 401)
            if record.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
                session.delete(record)
                session.commit()
                raise AuthError("unauthorized", "会话已过期，请重新登录", 401)
            return record
    except SQLAlchemyError as exc:
        raise AuthError("database_unavailable", "数据库不可用", 500, {"reason": str(exc)}) from exc


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> AuthSession:
    """FastAPI 依赖：从 Authorization header 提取 Bearer token 并校验。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("unauthorized", "未登录", 401)
    token = authorization.removeprefix("Bearer ").strip()
    return _resolve_session(token)


def require_role(required: str):
    """FastAPI 依赖工厂：要求当前用户具有指定角色。"""

    def dependency(user: Annotated[AuthSession, Depends(get_current_user)]) -> AuthSession:
        if required == "admin" and user.role != "admin":
            raise AuthError("forbidden", "需要管理员权限", 403)
        return user

    return dependency
