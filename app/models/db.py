"""SQLAlchemy 任务元数据模型（在线模式；结果数据仍在 output/ 文件）。"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
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
    package_kind: Mapped[str] = mapped_column(String(32), default="inspection", index=True)
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
    if "package_kind" not in columns:
        columns.append("package_kind")
    with engine.begin() as connection:
        if columns:
            names = ", ".join(columns)
            select_names = ", ".join(
                "'inspection' AS package_kind" if name == "package_kind" else name for name in columns
            )
            connection.execute(text(f"INSERT INTO tasks ({names}) SELECT {select_names} FROM tasks_legacy"))
        connection.execute(text("DROP TABLE tasks_legacy"))


def init_db() -> None:
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    if inspect(engine).has_table("tasks") and "system_id" in {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }:
        _rebuild_legacy_tasks(engine)
        _rebuild_legacy_inventory_tables(engine)
    else:
        _rebuild_legacy_inventory_tables(engine)
        Base.metadata.create_all(engine)
    _ensure_task_columns(engine)
    _ensure_kpi_measurement_columns(engine)
    _ensure_inventory_device_columns(engine)


def _rebuild_legacy_inventory_tables(engine: Engine) -> None:
    """重建旧台账表，解决观测 task_id 唯一约束和审计可空字段迁移。"""
    inspector = inspect(engine)
    observation_table = InventoryObservation.__tablename__
    audit_table = InventoryChangeAudit.__tablename__
    rebuild_observation = False
    if inspector.has_table(observation_table):
        indexes = inspector.get_indexes(observation_table)
        rebuild_observation = any(index.get("unique") and index.get("column_names") == ["task_id"] for index in indexes)

    rebuild_audit = False
    if inspector.has_table(audit_table):
        columns = {column["name"]: column for column in inspector.get_columns(audit_table)}
        rebuild_audit = any(not columns.get(name, {}).get("nullable", True) for name in ("task_id", "observation_id"))

    if rebuild_observation:
        _rebuild_table(engine, InventoryObservation)
        inspector = inspect(engine)
    if rebuild_audit:
        _rebuild_table(engine, InventoryChangeAudit)


def _rebuild_table(engine: Engine, model: type[Base]) -> None:  # type: ignore[type-arg]
    """按当前模型重建一张 SQLite 表并复制交集字段。"""
    table_name = model.__tablename__
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} RENAME TO {table_name}_legacy"))
        for index in inspect(connection).get_indexes(f"{table_name}_legacy"):
            name = str(index["name"])
            if not name.startswith("sqlite_autoindex_"):
                connection.execute(text(f"DROP INDEX IF EXISTS {name}"))

    model.__table__.create(engine)
    legacy_columns = {column["name"] for column in inspect(engine).get_columns(f"{table_name}_legacy")}
    columns = [name for name in model.__table__.columns.keys() if name in legacy_columns]
    names = ", ".join(columns)
    with engine.begin() as connection:
        connection.execute(text(f"INSERT INTO {table_name} ({names}) SELECT {names} FROM {table_name}_legacy"))
        connection.execute(text(f"DROP TABLE {table_name}_legacy"))


def _ensure_inventory_device_columns(engine: Engine) -> None:
    """为旧设备表补充台账维护字段。"""
    table = InventoryDevice.__tablename__
    if not inspect(engine).has_table(table):
        return
    existing = {column["name"] for column in inspect(engine).get_columns(table)}
    wanted = {
        "remark": "TEXT",
        "created_by": "VARCHAR(64)",
        "updated_by": "VARCHAR(64)",
    }
    with engine.begin() as connection:
        for name, ddl in wanted.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _ensure_task_columns(engine: Engine) -> None:
    """为旧任务表补充台账包类型字段，旧任务统一视为巡检包。"""
    if not inspect(engine).has_table(TaskRecord.__tablename__):
        return
    existing = {column["name"] for column in inspect(engine).get_columns(TaskRecord.__tablename__)}
    if "package_kind" not in existing:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {TaskRecord.__tablename__} "
                    "ADD COLUMN package_kind VARCHAR(32) NOT NULL DEFAULT 'inspection'"
                )
            )


def _ensure_kpi_measurement_columns(engine: Engine) -> None:
    """为旧 SQLite 目录表补充 021-024 需要的增量字段。"""
    table = KpiMeasurementResource.__tablename__
    if not inspect(engine).has_table(table):
        return
    existing = {column["name"] for column in inspect(engine).get_columns(table)}
    wanted = {
        "display_order": "INTEGER",
        "metric_group": "VARCHAR(64)",
        "direction": "VARCHAR(16)",
        "importance": "VARCHAR(16)",
        "warning_threshold": "FLOAT",
        "critical_threshold": "FLOAT",
        "source": "VARCHAR(16) NOT NULL DEFAULT 'preset'",
        "origin_task_id": "VARCHAR(64)",
        "origin_file": "VARCHAR(512)",
    }
    with engine.begin() as connection:
        for name, ddl in wanted.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


class InventoryDevice(Base):
    """局点设备台账当前状态；设备身份由省份和规范化设备名确定。"""

    __tablename__ = "inventory_devices"
    __table_args__ = (UniqueConstraint("province", "device_key", name="uq_inventory_device_province_key"),)

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_key: Mapped[str] = mapped_column(String(64), index=True)
    province: Mapped[str] = mapped_column(String(64), index=True)
    current_device_name: Mapped[str] = mapped_column(String(256))
    current_site_key: Mapped[str] = mapped_column(String(160), index=True)
    current_operator: Mapped[str] = mapped_column(String(64))
    current_version_raw: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_version_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_version_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_observation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latest_task_id: Mapped[str] = mapped_column(String(64))
    latest_status: Mapped[str] = mapped_column(String(32), default="archived")
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    site_change_count: Mapped[int] = mapped_column(Integer, default=0)
    has_site_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InventoryObservation(Base):
    """一次任务对一台设备的当前生效观测；重跑覆盖并保留审计。"""

    __tablename__ = "inventory_observations"

    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("inventory_devices.device_id"), index=True)
    province: Mapped[str] = mapped_column(String(64), index=True)
    operator: Mapped[str] = mapped_column(String(64), index=True)
    site_key: Mapped[str] = mapped_column(String(160), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    task_status: Mapped[str] = mapped_column(String(32), default="completed")
    device_name: Mapped[str] = mapped_column(String(256))
    identity_status: Mapped[str] = mapped_column(String(32), default="ok")
    version_status: Mapped[str] = mapped_column(String(32), index=True)
    raw_version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    version_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    version_source_files: Mapped[list] = mapped_column(JSON, default=list)
    device_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InventoryParseResult(Base):
    """任务级台账解析证据；与可重建的 inventory.json 互为快照。"""

    __tablename__ = "inventory_parse_results"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    package_kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    parser_id: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    site_status: Mapped[str] = mapped_column(String(32))
    site_source: Mapped[str] = mapped_column(String(32))
    site_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_status: Mapped[str] = mapped_column(String(32), index=True)
    version_status: Mapped[str] = mapped_column(String(32), index=True)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    conflicts: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InventoryChangeAudit(Base):
    """台账观测新增、覆盖或退役的追加审计。"""

    __tablename__ = "inventory_change_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    observation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    before_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiMeasurementResource(Base):
    """新版测量单元/指标/单位资源目录。"""

    __tablename__ = "kpi_measurement_resources"

    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), index=True)
    name_zh: Mapped[str] = mapped_column(String(256))
    name_en: Mapped[str] = mapped_column(String(256))
    filename_fragment: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    display_order: Mapped[int | None] = mapped_column(nullable=True)
    metric_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    importance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    warning_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="preset")
    origin_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
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
