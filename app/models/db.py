"""SQLAlchemy 任务元数据模型（在线模式；结果数据仍在 output/ 文件）。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, create_engine
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


def session_factory() -> Session:
    """按当前 settings 创建会话，保证测试环境切换 SQLite 生效。"""
    engine = create_engine(f"sqlite:///{settings.sqlite_path}", connect_args={"check_same_thread": False})
    return Session(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    engine = create_engine(f"sqlite:///{settings.sqlite_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
