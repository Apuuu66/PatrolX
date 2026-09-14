"""SQLAlchemy 任务元数据模型（在线模式；结果数据仍在 output/ 文件）。"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, DateTime, Engine, String, create_engine, inspect, text
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
