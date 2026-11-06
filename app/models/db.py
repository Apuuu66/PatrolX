"""SQLAlchemy 任务元数据模型（在线模式；结果数据仍在 output/ 文件）。"""

from datetime import date, datetime
from pathlib import Path
from threading import Lock

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core.config import settings

SQLITE_BUSY_TIMEOUT_SECONDS = 30

_initialized_schema_signatures: dict[Path, tuple[int, int, int]] = {}
_migration_source_signatures: dict[Path, tuple[tuple[int, int, str], ...]] = {}
_init_db_lock = Lock()

_MIGRATION_SOURCE_TABLES = (
    ("tasks", "created_at"),
    ("kpi_measurement_resources", "updated_at"),
    ("kpi_measurement_bindings", "updated_at"),
    ("kpi_measurement_derived", "updated_at"),
    ("kpi_metric_maintenance_configs", "updated_at"),
)


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
    rule_network_element_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    package_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preparation: Mapped[dict | None] = mapped_column(JSON, nullable=True)


def _sqlite_path() -> Path:
    """返回按项目根解析后的 SQLite 路径。"""
    return settings.resolved(settings.sqlite_path)


def _create_sqlite_engine(path: Path) -> Engine:
    """创建统一配置的 SQLite 引擎，避免并发写短暂重叠时立即失败。"""
    return create_engine(
        f"sqlite:///{path}",
        connect_args={
            "check_same_thread": False,
            "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
        },
    )


def _sqlite_schema_signature(path: Path, engine: Engine) -> tuple[int, int, int]:
    """返回用于判断同一数据库是否已完整初始化的轻量签名。"""
    stat = path.stat()
    with engine.connect() as connection:
        schema_version = int(connection.execute(text("PRAGMA schema_version")).scalar_one())
    return stat.st_dev, stat.st_ino, schema_version


def _migration_source_signature(engine: Engine) -> tuple[tuple[int, int, str], ...]:
    """返回 v5 迁移输入签名，数据未变化时避免重复全量扫描。"""
    signature: list[tuple[int, int, str]] = []
    inspector = inspect(engine)
    with engine.connect() as connection:
        for table, timestamp_column in _MIGRATION_SOURCE_TABLES:
            if not inspector.has_table(table):
                signature.append((-1, -1, ""))
                continue
            row = connection.execute(
                text(f"SELECT COUNT(*), COALESCE(MAX(rowid), 0), COALESCE(MAX({timestamp_column}), '') FROM {table}")
            ).one()
            signature.append((int(row[0]), int(row[1]), str(row[2])))
    return tuple(signature)


def session_factory() -> Session:
    """按当前 settings 创建会话，保证测试环境切换 SQLite 生效。"""
    engine = _create_sqlite_engine(_sqlite_path())
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
    with _init_db_lock:
        engine = _create_sqlite_engine(path)
        try:
            schema_initialized = False
            if path.is_file():
                signature = _sqlite_schema_signature(path, engine)
                if _initialized_schema_signatures.get(path) == signature:
                    schema_initialized = True
            if not schema_initialized:
                with engine.begin() as connection:
                    connection.execute(text("PRAGMA journal_mode=WAL"))
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
                _ensure_kpi_measurement_constraints(engine)
                _ensure_inventory_device_columns(engine)
                _ensure_inventory_observation_columns(engine)
                _initialized_schema_signatures[path] = _sqlite_schema_signature(path, engine)

            # 固定顺序：建表与增量列迁移 → v6 KPI 迁移 → 启动回填。
            from app.services.kpi_v6_migration import migrate_kpi_v6
            from app.services.task_db import ensure_backfilled

            migration_signature = _migration_source_signature(engine)
            if not schema_initialized or _migration_source_signatures.get(path) != migration_signature:
                migrate_kpi_v6()
                _migration_source_signatures[path] = migration_signature
            ensure_backfilled()
            _initialized_schema_signatures[path] = _sqlite_schema_signature(path, engine)
        except Exception:
            _initialized_schema_signatures.pop(path, None)
            _migration_source_signatures.pop(path, None)
            raise
        finally:
            engine.dispose()


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


def _ensure_inventory_observation_columns(engine: Engine) -> None:
    """为旧观测表补充执行时间来源列；旧行按任务完成时间语义取值。"""
    table = InventoryObservation.__tablename__
    if not inspect(engine).has_table(table):
        return
    existing = {column["name"] for column in inspect(engine).get_columns(table)}
    wanted = {
        "time_source": "VARCHAR(16) NOT NULL DEFAULT 'task'",
        "time_source_reason": "VARCHAR(32)",
    }
    with engine.begin() as connection:
        for name, ddl in wanted.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _ensure_task_columns(engine: Engine) -> None:
    """为旧任务表补充台账包类型与运行留存字段；旧行新列保持 NULL。"""
    if not inspect(engine).has_table(TaskRecord.__tablename__):
        return
    existing = {column["name"] for column in inspect(engine).get_columns(TaskRecord.__tablename__)}
    wanted = {
        "package_kind": "VARCHAR(32) NOT NULL DEFAULT 'inspection'",
        "rule_network_element_type": "VARCHAR(32)",
        "last_run_at": "DATETIME",
        "duration_ms": "INTEGER",
        "package_checksum": "VARCHAR(64)",
        "preparation": "JSON",
    }
    with engine.begin() as connection:
        for name, ddl in wanted.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {TaskRecord.__tablename__} ADD COLUMN {name} {ddl}"))


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


def _ensure_kpi_measurement_constraints(engine: Engine) -> None:
    """清理旧派生配置重复行并建立幂等唯一索引。"""
    table = KpiMeasurementDerived.__tablename__
    if not inspect(engine).has_table(table):
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                f"DELETE FROM {table} WHERE id NOT IN ("
                f"SELECT MAX(id) FROM {table} "
                "GROUP BY measurement_unit_id, metric_resource_id)"
            )
        )
        connection.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uq_kpi_measurement_derived_unit_metric "
                f"ON {table} (measurement_unit_id, metric_resource_id)"
            )
        )


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
    time_source: Mapped[str] = mapped_column(String(16), default="task", index=True)
    time_source_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    __table_args__ = (
        Index("uq_kpi_measurement_derived_unit_metric", "measurement_unit_id", "metric_resource_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    numerator_metric_id: Mapped[str] = mapped_column(String(128))
    denominator_metric_id: Mapped[str] = mapped_column(String(128))
    template: Mapped[str] = mapped_column(String(32), default="success_rate")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiMetricMaintenanceConfig(Base):
    """指标维护口径；方向与阈值仍以既有指标资源字段为准。"""

    __tablename__ = "kpi_metric_maintenance_configs"
    __table_args__ = (
        UniqueConstraint("measurement_unit_id", "metric_resource_id", name="uq_kpi_metric_maintenance_unit_metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    metric_resource_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16), default="base")
    daily_aggregation: Mapped[str] = mapped_column(String(16), default="latest")
    daily_change_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_change_threshold_unit: Mapped[str] = mapped_column(String(16), default="auto")
    is_percentage: Mapped[bool] = mapped_column(Boolean, default=False)
    zero_semantics: Mapped[str] = mapped_column(String(32), default="unknown")
    consistency_tolerance: Mapped[float] = mapped_column(Float, default=0.2)
    object_match_mode: Mapped[str] = mapped_column(String(16), default="exact")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiMetricMaintenanceAudit(Base):
    """指标维护配置变更审计；不保存任务值或上传包内容。"""

    __tablename__ = "kpi_metric_maintenance_audits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    metric_resource_id: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    changed_fields: Mapped[list] = mapped_column(JSON, default=list)
    before_values: Mapped[dict] = mapped_column(JSON, default=dict)
    after_values: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiV6MeasurementResource(Base):
    """v6 按网元类型隔离的测量单元/指标/单位资源。"""

    __tablename__ = "kpi_v6_measurement_resources"
    __table_args__ = (
        UniqueConstraint("network_element_type", "resource_id", name="uq_kpi_v6_resource_type_id"),
        UniqueConstraint("network_element_type", "legacy_source_key", name="uq_kpi_v6_resource_type_legacy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(8), index=True)
    name_zh: Mapped[str] = mapped_column(String(256))
    name_en: Mapped[str] = mapped_column(String(256))
    filename_fragment: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metric_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    importance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    warning_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="preset")
    origin_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    legacy_source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiV6MeasurementUnit(Base):
    """v6 测量单元；inspection_enabled 是唯一日常巡检启停粒度。"""

    __tablename__ = "kpi_v6_measurement_units"
    __table_args__ = (
        UniqueConstraint("network_element_type", "measurement_unit_id", name="uq_kpi_v6_unit_type_id"),
        UniqueConstraint("network_element_type", "legacy_source_key", name="uq_kpi_v6_unit_type_legacy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    name_zh: Mapped[str] = mapped_column(String(256))
    name_en: Mapped[str] = mapped_column(String(256))
    inspection_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="preset")
    origin_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legacy_source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiV6MeasurementBinding(Base):
    """v6 自动发现并确认的来源列绑定。"""

    __tablename__ = "kpi_v6_measurement_bindings"
    __table_args__ = (
        UniqueConstraint(
            "network_element_type",
            "measurement_unit_id",
            "raw_source_name",
            name="uq_kpi_v6_binding_type_unit_raw",
        ),
        UniqueConstraint("network_element_type", "legacy_source_key", name="uq_kpi_v6_binding_type_legacy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    raw_source_name: Mapped[str] = mapped_column(String(256))
    base_source_name: Mapped[str] = mapped_column(String(256))
    metric_resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    display_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    binding_state: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    source_file: Mapped[str] = mapped_column(String(512))
    origin_task_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    legacy_source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiV6MeasurementDerived(Base):
    """v6 由 PatrolX 明确定义的派生指标。"""

    __tablename__ = "kpi_v6_measurement_derived"
    __table_args__ = (
        UniqueConstraint(
            "network_element_type",
            "measurement_unit_id",
            "metric_resource_id",
            name="uq_kpi_v6_derived_type_unit_metric",
        ),
        UniqueConstraint("network_element_type", "legacy_source_key", name="uq_kpi_v6_derived_type_legacy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128), index=True)
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    numerator_metric_id: Mapped[str] = mapped_column(String(128))
    denominator_metric_id: Mapped[str] = mapped_column(String(128))
    template: Mapped[str] = mapped_column(String(32))
    definition_state: Mapped[str] = mapped_column(String(16), default="defined")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    legacy_source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiV6MetricMaintenanceConfig(Base):
    """v6 指标维护口径；不包含 enabled 执行门禁。"""

    __tablename__ = "kpi_v6_metric_maintenance_configs"
    __table_args__ = (
        UniqueConstraint(
            "network_element_type",
            "measurement_unit_id",
            "metric_resource_id",
            name="uq_kpi_v6_maintenance_type_unit_metric",
        ),
        UniqueConstraint("network_element_type", "legacy_source_key", name="uq_kpi_v6_maintenance_type_legacy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128))
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="base")
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    warning_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_aggregation: Mapped[str] = mapped_column(String(16), default="latest")
    daily_change_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_change_threshold_unit: Mapped[str] = mapped_column(String(16), default="auto")
    is_percentage: Mapped[bool] = mapped_column(Boolean, default=False)
    zero_semantics: Mapped[str] = mapped_column(String(32), default="unknown")
    consistency_tolerance: Mapped[float] = mapped_column(Float, default=0.2)
    object_match_mode: Mapped[str] = mapped_column(String(16), default="exact")
    config_state: Mapped[str] = mapped_column(String(16), default="ready")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    legacy_source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiTeamFocusRevision(Base):
    """按网元类型共享的团队关注 revision。"""

    __tablename__ = "kpi_team_focus_revisions"

    network_element_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiTeamFocusItem(Base):
    """团队关注项；身份不包含任务、设备或用户。"""

    __tablename__ = "kpi_team_focus_items"
    __table_args__ = (
        UniqueConstraint(
            "network_element_type",
            "measurement_unit_id",
            "metric_resource_id",
            name="uq_kpi_team_focus_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128))
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    added_by: Mapped[str] = mapped_column(String(128))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiRuleAssignmentState(Base):
    """单条业务规则的归属集合 revision。"""

    __tablename__ = "kpi_rule_assignment_states"

    rule_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    assignment_state: Mapped[str] = mapped_column(String(16), default="unassigned")
    updated_by: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiRuleNetworkAssignment(Base):
    """业务规则到网元类型的运行时归属。"""

    __tablename__ = "kpi_rule_network_assignments"
    __table_args__ = (UniqueConstraint("rule_code", "network_element_type", name="uq_kpi_rule_network_assignment"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_code: Mapped[str] = mapped_column(String(128), index=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    rule_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiRuleAssignmentGlobalState(Base):
    """规则归属全局 revision；单行固定为 1。"""

    __tablename__ = "kpi_rule_assignment_global_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiRuleAssignmentAudit(Base):
    """规则归属变更追加审计。"""

    __tablename__ = "kpi_rule_assignment_audits"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_kpi_rule_assignment_audit_idempotency"),)

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(128), index=True)
    before_network_element_types: Mapped[list] = mapped_column(JSON, default=list)
    after_network_element_types: Mapped[list] = mapped_column(JSON, default=list)
    rule_revision: Mapped[int] = mapped_column(Integer)
    global_revision: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskRuleScopeSnapshot(Base):
    """任务启动时冻结的普通规则范围。"""

    __tablename__ = "task_rule_scope_snapshots"

    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.task_id"), primary_key=True)
    network_element_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assignment_revision: Mapped[int] = mapped_column(Integer)
    registry_fingerprint: Mapped[str] = mapped_column(String(64))
    trigger: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot_state: Mapped[str] = mapped_column(String(16), default="frozen")


class TaskRuleScopeItem(Base):
    """任务规则快照中的单条规则。"""

    __tablename__ = "task_rule_scope_items"
    __table_args__ = (UniqueConstraint("task_id", "rule_code", name="uq_task_rule_scope_item"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.task_id"), index=True)
    rule_code: Mapped[str] = mapped_column(String(128))
    rule_version: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer)
    execution_order: Mapped[int] = mapped_column(Integer)
    assignment_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class TaskKpiScopeSnapshot(Base):
    """任务启动时冻结的 KPI 配置范围摘要。"""

    __tablename__ = "task_kpi_scope_snapshots"

    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.task_id"), primary_key=True)
    network_element_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    team_focus_revision: Mapped[int] = mapped_column(Integer)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    data_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class TaskKpiScopeItem(Base):
    """任务 KPI 范围中的单个指标及冻结配置。"""

    __tablename__ = "task_kpi_scope_items"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "measurement_unit_id",
            "metric_resource_id",
            name="uq_task_kpi_scope_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.task_id"), index=True)
    network_element_type: Mapped[str] = mapped_column(String(32))
    measurement_unit_id: Mapped[str] = mapped_column(String(128))
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    metric_kind: Mapped[str] = mapped_column(String(16))
    config_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    scope_status: Mapped[str] = mapped_column(String(16), default="ready")


class TaskKpiMetricResultV6(Base):
    """任务内指标的最终判定与证据摘要。"""

    __tablename__ = "task_kpi_metric_results_v6"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "network_element_type",
            "measurement_unit_id",
            "metric_resource_id",
            name="uq_task_kpi_metric_result_v6_identity",
        ),
        UniqueConstraint("task_id", "result_fingerprint", name="uq_task_kpi_metric_result_v6_fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128))
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    source_rule_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str] = mapped_column(String(16))
    special_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    yesterday_trend: Mapped[str | None] = mapped_column(String(16), nullable=True)
    needs_attention_group: Mapped[str | None] = mapped_column(String(24), nullable=True)
    today_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    yesterday_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    importance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str] = mapped_column(String, default="")
    effective_point_count: Mapped[int] = mapped_column(Integer, default=0)
    result_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result_fingerprint: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskKpiPointV6(Base):
    """v6 复合作用域 KPI 历史点。"""

    __tablename__ = "task_kpi_points_v6"
    __table_args__ = (
        UniqueConstraint("task_id", "point_fingerprint", name="uq_task_kpi_point_v6_fingerprint"),
        Index(
            "ix_task_kpi_points_v6_scope_time",
            "task_id",
            "network_element_type",
            "measurement_unit_id",
            "metric_resource_id",
            "measured_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    network_element_type: Mapped[str] = mapped_column(String(32), index=True)
    source_rule_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    measurement_unit_id: Mapped[str] = mapped_column(String(128))
    metric_resource_id: Mapped[str] = mapped_column(String(128))
    object_key: Mapped[str] = mapped_column(String(256), default="__all__")
    period_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    point_fingerprint: Mapped[str] = mapped_column(String(64))


class KpiLegacyRecoveryAudit(Base):
    """v5 指标/绑定/派生 enabled=false 的恢复审计。"""

    __tablename__ = "kpi_legacy_recovery_audits"
    __table_args__ = (UniqueConstraint("source_key", name="uq_kpi_legacy_recovery_source_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(String(64))
    source_record_id: Mapped[str] = mapped_column(String(128))
    source_key: Mapped[str] = mapped_column(String(256))
    network_element_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measurement_unit_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metric_resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    object_kind: Mapped[str] = mapped_column(String(16))
    before_snapshot: Mapped[dict] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiPendingAttribution(Base):
    """无法唯一证明网元类型的 v5 配置。"""

    __tablename__ = "kpi_pending_attributions"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_kpi_pending_attribution_source_key"),
        UniqueConstraint("idempotency_key", name="uq_kpi_pending_attribution_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(String(64))
    source_record_id: Mapped[str] = mapped_column(String(128))
    source_key: Mapped[str] = mapped_column(String(256))
    source_payload: Mapped[dict] = mapped_column(JSON)
    candidate_network_element_types: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(64))
    resolution_state: Mapped[str] = mapped_column(String(16), default="pending")
    assigned_network_element_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiMaintenanceOperation(Base):
    """恢复重试与待归属解析的幂等维护操作。"""

    __tablename__ = "kpi_maintenance_operations"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_kpi_maintenance_operation_idempotency"),)

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class TaskRuleResult(Base):
    """任务规则结果的长期镜像；同一任务同一规则只保留最新一次执行。"""

    __tablename__ = "task_rule_results"
    __table_args__ = (UniqueConstraint("task_id", "rule_code", name="uq_task_rule_result"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_code: Mapped[str] = mapped_column(String(128))
    priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    execution_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskKpiPoint(Base):
    """任务 KPI 历史点的长期镜像；字段与任务私有 index.jsonl 一一对应。"""

    __tablename__ = "task_kpi_points"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    measurement_unit_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metric_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    object_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    period_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RuleState(Base):
    """界面管理的普通规则启停状态。"""

    __tablename__ = "rule_states"

    rule_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
