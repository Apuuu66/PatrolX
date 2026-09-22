"""SQLAlchemy 任务元数据模型（在线模式；结果数据仍在 output/ 文件）。"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, DateTime, Engine, String, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core.config import settings


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    trigger: Mapped[str] = mapped_column(String(16))
    package_file: Mapped[str] = mapped_column(String(512))
    customer: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _sqlite_path() -> Path:
    """返回按项目根解析后的 SQLite 路径。"""
    return settings.resolved(settings.sqlite_path)


def session_factory() -> Session:
    """按当前 settings 创建会话，保证测试环境切换 SQLite 生效。"""
    engine = create_engine(f"sqlite:///{_sqlite_path()}", connect_args={"check_same_thread": False})
    return Session(bind=engine, autoflush=False, expire_on_commit=False)


def _rebuild_legacy_tasks(engine: Engine) -> None:
    """重建包含 system_id 的旧版任务表，并保留仍有效的元数据列。"""
    legacy_columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE tasks RENAME TO tasks_legacy"))

    Base.metadata.create_all(engine)

    columns = sorted(set(TaskRecord.__table__.columns.keys()) & legacy_columns)
    with engine.begin() as connection:
        if columns:
            names = ", ".join(columns)
            connection.execute(text(f"INSERT INTO tasks ({names}) SELECT {names} FROM tasks_legacy"))
        connection.execute(text("DROP TABLE tasks_legacy"))


def init_db() -> None:
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    if inspect(engine).has_table("tasks") and "system_id" in {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }:
        _rebuild_legacy_tasks(engine)
    else:
        Base.metadata.create_all(engine)


class KpiMeasurementResource(Base):
    """新版测量单元/指标/单位资源目录。"""

    __tablename__ = "kpi_measurement_resources"

    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), index=True)
    name_zh: Mapped[str] = mapped_column(String(256))
    name_en: Mapped[str] = mapped_column(String(256))
    filename_fragment: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiMeasurementBinding(Base):
    """任务发现的指标列与测量单元绑定。"""

    __tablename__ = "kpi_measurement_bindings"
    __table_args__ = (UniqueConstraint("measurement_unit_id", "raw_source_name", name="uq_kpi_binding_mu_raw_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    metric_resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    raw_source_name: Mapped[str] = mapped_column(String(256))
    base_source_name: Mapped[str] = mapped_column(String(256))
    display_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    source_file: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiMeasurementDerived(Base):
    """新版 KPI 成功率派生定义。"""

    __tablename__ = "kpi_measurement_derived"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    numerator_metric_id: Mapped[str] = mapped_column(String(128))
    denominator_metric_id: Mapped[str] = mapped_column(String(128))
    template: Mapped[str] = mapped_column(String(32), default="success_rate")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthUser(Base):
    """认证用户；由 CLI 创建，不支持在线注册。"""

    __tablename__ = "auth_users"

    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    """登录会话；服务重启即全部失效（内存外 SQLite，重启后 token 不匹配）。"""

    __tablename__ = "auth_sessions"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RuleState(Base):
    """界面管理的普通规则启停状态。"""

    __tablename__ = "rule_states"

    rule_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
