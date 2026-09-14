"""任务服务：output/ 为唯一数据源，SQLite 只保存在线任务元数据。"""

import json
import queue
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.cli import generate_task_id, run_single_rule, run_task
from app.core.checksum import sha256_file
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import TASKS_DURATION, TASKS_TOTAL
from app.models.db import TaskRecord, init_db, session_factory
from app.models.schemas import InspectionTask, TaskCreated, TaskMode, TaskStatus, TaskSummary, TaskTrigger
from app.services import store
from app.services.store import append_log, load_task_meta

logger = get_logger("patrolx.tasks")
NOW = datetime.now


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
            except Exception:  # noqa: BLE001
                logger.exception("task_failed", task_id=task_id)
                append_log(settings.output, task_id, "error", "任务执行失败")
                TASKS_TOTAL.labels(result="failed", mode="online").inc()
                self._update_status(task_id, TaskStatus.FAILED)

    def _update_status(self, task_id: str, status: TaskStatus, completed_at: datetime | None = None) -> None:
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record:
                record.status = status.value
                record.completed_at = completed_at
                session.commit()

    def _execute(self, task_id: str) -> None:
        package, customer, version, name = self._task_info(task_id)
        if package is None:
            return
        self._update_status(task_id, TaskStatus.RUNNING)
        started = NOW(UTC)
        try:
            plan = self._rerun_plan.pop(task_id, None)
            if plan:
                package_checksum = sha256_file(package)
                for code in plan:
                    run_single_rule(
                        code,
                        package=package,
                        task_id=task_id,
                        package_checksum=package_checksum,
                    )
                append_log(settings.output, task_id, "info", "重跑完成，报告已更新")
                current = load_task_meta(settings.output, task_id)
                if current:
                    completed_task = current.model_copy(
                        update={"status": TaskStatus.COMPLETED, "completed_at": NOW(UTC)}
                    )
                    store.save_task_meta(settings.output, completed_task)
            else:
                executed = run_task(
                    package,
                    name=name,
                    customer=customer,
                    version=version,
                    task_id=task_id,
                    mode=TaskMode.ONLINE,
                    trigger=TaskTrigger.API,
                )
                if executed.status == TaskStatus.FAILED:
                    TASKS_DURATION.observe((NOW(UTC) - started).total_seconds())
                    self._update_status(task_id, TaskStatus.FAILED, completed_at=NOW(UTC))
                    return
            TASKS_DURATION.observe((NOW(UTC) - started).total_seconds())
            TASKS_TOTAL.labels(result="completed", mode="online").inc()
            self._update_status(task_id, TaskStatus.COMPLETED, completed_at=NOW(UTC))
        except Exception:  # noqa: BLE001
            failed_task = load_task_meta(settings.output, task_id)
            if failed_task:
                failed = failed_task.model_copy(update={"status": TaskStatus.FAILED, "completed_at": NOW(UTC)})
                store.save_task_meta(settings.output, failed)
            self._update_status(task_id, TaskStatus.FAILED, completed_at=NOW(UTC))
            raise

    def _task_info(self, task_id: str) -> tuple[Path | None, dict, str | None, str | None]:
        """从 SQLite 获取在线任务的执行信息。"""
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                return None, {}, None, None
            return settings.uploads / task_id / record.package_file, record.customer or {}, record.version, record.name

    # ---- 创建 / 查询 ----

    def exists(self, task_id: str) -> bool:
        """检查任务是否已存在（output/ 或 SQLite）。"""
        if (settings.output / task_id / "task.json").exists():
            return True
        with session_factory() as session:
            return session.get(TaskRecord, task_id) is not None

    def reserve(
        self,
        package_file: str,
        name: str | None,
        province: str | None,
        operator: str | None,
        version: str | None,
        product: str | None = None,
    ) -> TaskCreated:
        task_id = generate_task_id(package_file)
        customer: dict[str, str] = {}
        if province:
            customer["province"] = province
        if operator:
            customer["operator"] = operator
        if product:
            customer["product"] = product
        with session_factory() as session:
            session.add(
                TaskRecord(
                    task_id=task_id,
                    name=name or package_file,
                    mode=TaskMode.ONLINE.value,
                    status=TaskStatus.PENDING.value,
                    trigger=TaskTrigger.API.value,
                    package_file=package_file,
                    customer=customer,
                    version=version,
                    stats={},
                    created_at=NOW(UTC),
                )
            )
            session.commit()
        append_log(settings.output, task_id, "info", "任务创建，等待执行", package_file=package_file)
        return TaskCreated(task_id=task_id)

    def submit(self, task_id: str) -> None:
        self._queue.put(task_id)

    def discard(self, task_id: str) -> None:
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record:
                session.delete(record)
                session.commit()

    def get(self, task_id: str) -> InspectionTask | None:
        """读取任务：优先 output/（唯一数据源），SQLite 兜底查状态。"""
        task = load_task_meta(settings.output, task_id)
        if task is not None:
            return task
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                return None
            return InspectionTask(
                task_id=record.task_id,
                name=record.name,
                mode=TaskMode(record.mode),
                status=TaskStatus(record.status),
                trigger=TaskTrigger(record.trigger),
                created_at=record.created_at,
                completed_at=record.completed_at,
                stats={"total": 0, "pass": 0, "warn": 0, "fail": 0, "error": 0, "skip": 0, "systems": 1},
                system=None,
            )

    def list_tasks(self, page: int, page_size: int, status: str | None) -> tuple[list[TaskSummary], int]:
        """列表：扫描 output/ 下所有 task.json + SQLite 中尚无 task.json 的进行中任务。"""
        items: list[TaskSummary] = []
        seen_ids: set[str] = set()
        if settings.output.exists():
            for task_file in sorted(settings.output.glob("*/task.json"), reverse=True):
                try:
                    task = InspectionTask.model_validate(json.loads(task_file.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001 - 列表扫描不能被坏任务中断
                    continue
                if status and task.status.value != status:
                    continue
                customer = task.system.customer if task.system else {}
                items.append(
                    TaskSummary(
                        task_id=task.task_id,
                        name=task.name,
                        mode=task.mode,
                        status=task.status,
                        trigger=task.trigger,
                        created_at=task.created_at,
                        completed_at=task.completed_at,
                        stats=task.stats,
                        system=None,
                        customer_province=customer.get("province"),
                        customer_operator=customer.get("operator"),
                        customer_product=customer.get("product"),
                        customer_version=task.system.version if task.system else None,
                    )
                )
                seen_ids.add(task.task_id)
        with session_factory() as session:
            query = session.query(TaskRecord).filter(
                TaskRecord.status.in_([TaskStatus.PENDING.value, TaskStatus.RUNNING.value])
            )
            for record in query.all():
                if record.task_id in seen_ids:
                    continue
                if status and record.status != status:
                    continue
                items.append(
                    TaskSummary(
                        task_id=record.task_id,
                        name=record.name,
                        mode=TaskMode(record.mode),
                        status=TaskStatus(record.status),
                        trigger=TaskTrigger(record.trigger),
                        created_at=record.created_at,
                        completed_at=record.completed_at,
                        stats={"total": 0, "pass": 0, "warn": 0, "fail": 0, "error": 0, "skip": 0, "systems": 1},
                        system=None,
                        customer_province=record.customer.get("province"),
                        customer_operator=record.customer.get("operator"),
                        customer_product=record.customer.get("product"),
                        customer_version=record.version,
                    )
                )
        items.sort(key=lambda t: t.created_at or "", reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    def delete(self, task_id: str) -> bool:
        """删除任务：SQLite + output/ + uploads/ 级联清理。"""
        found = False
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record:
                session.delete(record)
                session.commit()
                found = True
        for directory in (settings.output / task_id, settings.uploads / task_id):
            if not directory.exists():
                continue
            found = True
            shutil.rmtree(directory)
            if directory.exists():
                raise OSError(f"任务目录删除失败: {directory}")
        return found

    def rerun(self, task_id: str, rule_codes: list[str] | None) -> bool:
        """重跑：从 task.json 获取包信息，兼容在线和离线任务。"""
        task = load_task_meta(settings.output, task_id)
        if task is None or task.system is None:
            return False
        package_file = task.system.package_file
        package = settings.uploads / task_id / package_file
        if not package.exists():
            package = settings.uploads / package_file
        if not package.exists():
            return False
        self._rerun_plan[task_id] = rule_codes
        pending_task = task.model_copy(update={"status": TaskStatus.PENDING, "completed_at": None})
        store.save_task_meta(settings.output, pending_task)
        self._update_status(task_id, TaskStatus.PENDING)
        self._queue.put(task_id)
        return True


task_service = TaskService()
