"""在线模式任务服务：单线程队列顺序执行 + SQLite 元数据管理。"""

import queue
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.cli import clean_system_id, new_task_id, run_single_rule, run_task
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import TASKS_DURATION, TASKS_TOTAL
from app.models.db import SessionLocal, TaskRecord, init_db
from app.models.schemas import InspectionTask, TaskCreated, TaskMode, TaskStatus, TaskSummary, TaskTrigger
from app.services.report import render_report
from app.services.store import append_log, load_system

logger = get_logger("patrolx.tasks")


def _now() -> datetime:
    return datetime.now(UTC)


class TaskService:
    def __init__(self) -> None:
        init_db()
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._rerun_plan: dict[str, list[str] | None] = {}
        self._worker = threading.Thread(target=self._worker_loop, name="patrolx-worker", daemon=True)
        self._worker.start()

    # ---- 队列 ----

    def _worker_loop(self) -> None:
        while True:
            task_id = self._queue.get()
            try:
                with self._lock:
                    self._execute(task_id)
            except Exception:  # noqa: BLE001 - 任务失败记录状态，不中断 worker
                logger.exception("task_failed", task_id=task_id)
                append_log(settings.output, task_id, "error", "任务执行失败")
                TASKS_TOTAL.labels(result="failed", mode="online").inc()
                self._update_status(task_id, TaskStatus.FAILED)

    def _update_status(self, task_id: str, status: TaskStatus, completed_at: datetime | None = None) -> None:
        with SessionLocal() as session:
            record = session.get(TaskRecord, task_id)
            if record:
                record.status = status.value
                record.completed_at = completed_at
                session.commit()

    def _execute(self, task_id: str) -> None:
        with SessionLocal() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                return
            package = settings.uploads / task_id / record.package_file
            customer = record.customer or {}
            version = record.version
            name = record.name
            system_id = record.system_id
        self._update_status(task_id, TaskStatus.RUNNING)
        started = datetime.now(UTC)
        try:
            plan = self._rerun_plan.pop(task_id, None)
            if plan:
                for code in plan:
                    run_single_rule(code, system_id=system_id, package=package, task_id=task_id)
                system = load_system(settings.output, task_id, system_id)
                if system:
                    report = render_report(settings.output, task_id, system)
                    append_log(settings.output, task_id, "info", "重跑完成，报告已更新", report=str(report))
                task = self.get(task_id)
            else:
                task = run_task(
                    package,
                    name=name,
                    customer=customer,
                    version=version,
                    task_id=task_id,
                    mode=TaskMode.ONLINE,
                    trigger=TaskTrigger.API,
                )
            append_log(
                settings.output,
                task_id,
                "info",
                "任务完成",
                stats=task.stats.model_dump(by_alias=True, mode="json") if task else None,
            )
            TASKS_DURATION.observe((datetime.now(UTC) - started).total_seconds())
            TASKS_TOTAL.labels(result="completed", mode="online").inc()
            with SessionLocal() as session:
                record = session.get(TaskRecord, task_id)
                if record:
                    record.status = TaskStatus.COMPLETED.value
                    record.completed_at = _now()
                    record.stats = task.stats.model_dump(by_alias=True, mode="json") if task else record.stats
                    session.commit()
        except Exception:  # noqa: BLE001
            self._update_status(task_id, TaskStatus.FAILED, completed_at=_now())
            raise

    # ---- 创建 / 查询 ----

    def reserve(
        self,
        package_file: str,
        name: str | None,
        province: str | None,
        operator: str | None,
        version: str | None,
    ) -> TaskCreated:
        task_id = new_task_id()
        system_id = clean_system_id(package_file)
        customer: dict[str, str] = {}
        if province:
            customer["province"] = province
            system_id = province
        if operator:
            customer["operator"] = operator
            system_id = f"{system_id}_{operator}"
        with SessionLocal() as session:
            session.add(
                TaskRecord(
                    task_id=task_id,
                    name=name or package_file,
                    mode=TaskMode.ONLINE.value,
                    status=TaskStatus.PENDING.value,
                    trigger=TaskTrigger.API.value,
                    system_id=system_id,
                    package_file=package_file,
                    customer=customer,
                    version=version,
                    stats={},
                    created_at=_now(),
                )
            )
            session.commit()
        append_log(
            settings.output,
            task_id,
            "info",
            "任务创建，等待执行",
            package_file=package_file,
            name=name or package_file,
            customer=customer or None,
            version=version or None,
        )
        return TaskCreated(task_id=task_id)

    def submit(self, task_id: str) -> None:
        self._queue.put(task_id)

    def discard(self, task_id: str) -> None:
        with SessionLocal() as session:
            record = session.get(TaskRecord, task_id)
            if record:
                session.delete(record)
                session.commit()

    def get(self, task_id: str) -> InspectionTask | None:
        with SessionLocal() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                return None
            return self._to_inspection_task(record)

    def _task_fields(self, record: TaskRecord) -> dict:
        return {
            "task_id": record.task_id,
            "name": record.name,
            "mode": record.mode,
            "status": record.status,
            "trigger": record.trigger,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
            "stats": {
                "total": record.stats.get("total", 0),
                "pass": record.stats.get("pass", 0),
                "warn": record.stats.get("warn", 0),
                "fail": record.stats.get("fail", 0),
                "error": record.stats.get("error", 0),
                "skip": record.stats.get("skip", 0),
                "systems": 1,
            },
        }

    def _to_inspection_task(self, record: TaskRecord) -> InspectionTask:
        return InspectionTask(**self._task_fields(record), system=None)

    def _to_summary(self, record: TaskRecord) -> TaskSummary:
        return TaskSummary(**self._task_fields(record), system=None)

    def list_tasks(
        self, page: int, page_size: int, status: str | None, system_id: str | None
    ) -> tuple[list[TaskSummary], int]:
        with SessionLocal() as session:
            query = session.query(TaskRecord)
            if status:
                query = query.filter(TaskRecord.status == status)
            if system_id:
                query = query.filter(TaskRecord.system_id == system_id)
            total = query.count()
            records = query.order_by(TaskRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
            return [self._to_summary(r) for r in records], total

    def delete(self, task_id: str) -> bool:
        with SessionLocal() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                return False
            session.delete(record)
            session.commit()
        for root in (settings.uploads / task_id, settings.output / task_id):
            import shutil

            shutil.rmtree(root, ignore_errors=True)
        return True

    def rerun(self, task_id: str, rule_codes: list[str] | None) -> bool:
        with SessionLocal() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                return False
            package = settings.uploads / task_id / record.package_file
        if not package.exists():
            return False
        self._rerun_plan[task_id] = rule_codes
        self._update_status(task_id, TaskStatus.PENDING)
        self._queue.put(task_id)
        return True

    def system_dir(self, task_id: str, system_id: str) -> Path:
        return settings.output / task_id / system_id


task_service = TaskService()
