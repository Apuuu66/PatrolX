"""SQLAlchemy 任务元数据模型（在线模式；结果数据仍在 output/ 文件）。"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, DateTime, Engine, Float, String, UniqueConstraint, create_engine, inspect, text
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


class KpiClassification(Base):
    """KPI 指标的当前分类状态；metric_key 可指向已移除的基础资源。"""

    __tablename__ = "kpi_classifications"

    metric_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiClassificationRevision(Base):
    """KPI 分类全局修订单行表，id 固定为 1。"""

    __tablename__ = "kpi_classification_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiClassificationAudit(Base):
    """KPI 分类成功操作的审计流水。"""

    __tablename__ = "kpi_classification_audits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    metric_key: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(128), index=True)
    previous_domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[str] = mapped_column(String(32), default="success")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class KpiMetricRule(Base):
    """KPI 指标的动态计算口径；基础资源仍只能离线维护。"""

    __tablename__ = "kpi_metric_rules"

    metric_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    metric_type: Mapped[str] = mapped_column(String(32), default="count")
    semantic_group: Mapped[str] = mapped_column(String(32), default="other")
    display_role: Mapped[str] = mapped_column(String(32), default="context")
    unit: Mapped[str] = mapped_column(String(64), default="")
    source_type: Mapped[str] = mapped_column(String(16), default="raw")
    aggregation_kind: Mapped[str] = mapped_column(String(32), default="sum")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiMetricFormula(Base):
    """KPI 受控比率公式；与指标规则一对一。"""

    __tablename__ = "kpi_metric_formulas"

    metric_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    numerator: Mapped[str] = mapped_column(String(128))
    denominator: Mapped[str] = mapped_column(String(128))
    denominator_fallback_inputs: Mapped[list] = mapped_column(JSON, default=list)
    scale: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiThresholdRule(Base):
    """按业务域和指标维护的默认与周期阈值。"""

    __tablename__ = "kpi_thresholds"
    __table_args__ = (UniqueConstraint("domain", "metric_key", name="uq_kpi_threshold_domain_metric"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(32), index=True)
    metric_key: Mapped[str] = mapped_column(String(128), index=True)
    label: Mapped[str] = mapped_column(String(128))
    direction: Mapped[str] = mapped_column(String(8))
    unit: Mapped[str] = mapped_column(String(64))
    default_value: Mapped[float] = mapped_column(Float)
    periods: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiCapacityRule(Base):
    """KPI 容量列映射规则。"""

    __tablename__ = "kpi_capacity_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(256), unique=True)
    metric_key: Mapped[str] = mapped_column(String(128), index=True)
    domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    semantics: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiDisplayRule(Base):
    """KPI 展示角色规则。"""

    __tablename__ = "kpi_display_rules"
    __table_args__ = (UniqueConstraint("domain", "metric_key", name="uq_kpi_display_domain_metric"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(32), index=True)
    metric_key: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16), default="context")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiCommonConfig(Base):
    """KPI 输入时区与解析预算的单行配置。"""

    __tablename__ = "kpi_common_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    input_timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    max_files: Mapped[int] = mapped_column(default=1000)
    max_records: Mapped[int] = mapped_column(default=200000)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiRuleConfigRevision(Base):
    """KPI 动态配置全局修订单行表。"""

    __tablename__ = "kpi_rule_config_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KpiRuleConfigAudit(Base):
    """KPI 动态配置成功变更的审计流水。"""

    __tablename__ = "kpi_rule_config_audits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_key: Mapped[str] = mapped_column(String(256), index=True)
    operation: Mapped[str] = mapped_column(String(16))
    operator: Mapped[str] = mapped_column(String(128), index=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="success")
    rule_config_version: Mapped[int] = mapped_column(default=0)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


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
