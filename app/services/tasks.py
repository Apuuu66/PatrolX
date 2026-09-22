"""任务服务：output/ 为唯一数据源，SQLite 只保存在线任务元数据。"""

import json
import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from app.cli import generate_task_id, run_incremental_rebuild, run_single_rule, run_task
from app.core.checksum import sha256_file
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import TASKS_DURATION, TASKS_TOTAL
from app.inspectors.registry import registry
from app.models.db import TaskRecord, init_db, session_factory
from app.models.schemas import (
    InspectionTask,
    RebuildMode,
    RebuildRequest,
    TaskCreated,
    TaskMode,
    TaskStatus,
    TaskSummary,
    TaskTrigger,
)
from app.services import preparation, store
from app.services.extraction.layout import PathLimitPolicy
from app.services.rule_states import RuleStateError, assert_rule_enabled, ensure_rule_states
from app.services.store import append_log, load_task_meta

logger = get_logger("patrolx.tasks")
NOW = datetime.now


class TaskDeleteError(Exception):
    """任务现场删除失败，携带前端恢复与重试所需的上下文。"""

    def __init__(
        self,
        task_id: str,
        locations: list[str],
        failed_path: str,
        reason: str,
        path_length: int | None = None,
        path_limit: int | None = None,
    ) -> None:
        self.task_id = task_id
        self.locations = locations
        self.failed_path = failed_path
        self.reason = reason
        self.path_length = path_length
        self.path_limit = path_limit
        super().__init__(reason)


class TaskRebuildError(Exception):
    """重建预检失败；调用方必须保持任务现场不变。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(slots=True)
class RebuildPlan:
    """一次显式重建重跑的执行计划。"""

    mode: RebuildMode
    rule_codes: list[str] = field(default_factory=list)
    trigger_source: str = "ui"


def _delete_error_details(path: Path, *, treat_as_too_long: bool = False) -> tuple[int | None, int | None]:
    """仅在 Windows 传统 MAX_PATH 生效时返回可可靠判断的路径限制。"""
    policy = PathLimitPolicy.current()
    if not policy.enabled or policy.limit is None:
        return None, None
    length = len(os.path.abspath(os.fspath(path)))
    return length, policy.limit if length >= policy.limit or treat_as_too_long else None


def _remove_tree(directory: Path, task_id: str, locations: list[str]) -> None:
    """删除目录树；Windows 145 做短暂重试，其他失败转为结构化上下文。"""
    last_error: OSError | None = None
    for attempt in range(4):
        try:
            shutil.rmtree(directory)
            return
        except OSError as exc:
            if (getattr(exc, "winerror", None) or exc.errno) != 145:
                last_error = exc
                break
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    assert last_error is not None
    failed_path = Path(last_error.filename or directory)
    winerror = getattr(last_error, "winerror", None) or last_error.errno
    path_length, path_limit = _delete_error_details(failed_path, treat_as_too_long=winerror == 206)
    if winerror == 206:
        reason = "路径过长，无法删除任务现场"
    elif winerror == 145:
        reason = "目录不为空，任务现场删除失败"
    else:
        reason = str(last_error)
    error_code = "path_too_long" if winerror == 206 else "delete_failed"
    logger.error(
        "task_delete_failed",
        task_id=task_id,
        locations=locations,
        failed_path=os.path.abspath(os.fspath(failed_path)),
        status="failed",
        error_code=error_code,
        reason=reason,
        path_length=path_length,
        path_limit=path_limit,
    )
    raise TaskDeleteError(
        task_id=task_id,
        locations=locations,
        failed_path=os.path.abspath(os.fspath(failed_path)),
        reason=reason,
        path_length=path_length,
        path_limit=path_limit,
    ) from last_error


class DeleteResult(StrEnum):
    DELETED = "deleted"
    BUSY = "busy"
    NOT_FOUND = "not_found"


class TaskService:
    def __init__(self) -> None:
        init_db()
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._rerun_plan: dict[str, list[str] | None] = {}
        self._rebuild_plan: dict[str, RebuildPlan] = {}
        self._active_task: str | None = None
        self._cancelled: set[str] = set()
        self._worker = threading.Thread(target=self._worker_loop, name="patrolx-worker", daemon=True)
        self._worker.start()

    # ---- 队列 ----

    def _worker_loop(self) -> None:
        while True:
            task_id = self._queue.get()
            try:
                with self._state_lock:
                    if task_id in self._cancelled:
                        self._cancelled.discard(task_id)
                        continue
                    self._active_task = task_id
                try:
                    with self._lock:
                        self._execute(task_id)
                finally:
                    with self._state_lock:
                        self._active_task = None
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
        package, customer, version, name, mode, trigger = self._task_info(task_id)
        if package is None:
            return
        self._update_status(task_id, TaskStatus.RUNNING)
        started = NOW(UTC)
        try:
            plan = self._rerun_plan.pop(task_id, None)
            rebuild_plan = self._rebuild_plan.pop(task_id, None)
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
            elif rebuild_plan is not None:
                self._execute_rebuild(
                    task_id,
                    rebuild_plan,
                    package=package,
                    customer=customer,
                    version=version,
                    name=name,
                    mode=mode,
                    trigger=trigger,
                )
            else:
                executed = run_task(
                    package,
                    name=name,
                    customer=customer,
                    version=version,
                    task_id=task_id,
                    mode=mode,
                    trigger=trigger,
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

    def _execute_rebuild(
        self,
        task_id: str,
        plan: RebuildPlan,
        *,
        package: Path,
        customer: dict,
        version: str | None,
        name: str | None,
        mode: TaskMode,
        trigger: TaskTrigger,
    ) -> None:
        """执行显式重建重跑；预检和输出清理已经通过 TaskService.rebuild 完成。"""
        old_task = load_task_meta(settings.output, task_id)
        rule_codes = list(plan.rule_codes)
        log_detail = {
            "operation": "rebuild",
            "mode": plan.mode.value,
            "rule_codes": rule_codes,
            "trigger_source": plan.trigger_source,
        }
        if plan.mode == RebuildMode.FULL:
            _remove_tree(settings.output / task_id, task_id, [f"output/{task_id}"])
            # 本地任务没有 SQLite 兜底；全量重建期间必须保留任务元数据，避免列表闪空。
            if old_task:
                pending_task = old_task.model_copy(update={"status": TaskStatus.PENDING, "completed_at": None})
                store.save_task_meta(settings.output, pending_task)
            append_log(settings.output, task_id, "info", "全量重建重跑开始", **log_detail)
            executed = run_task(
                package,
                name=name,
                customer=customer,
                version=version,
                task_id=task_id,
                mode=mode,
                trigger=trigger,
                created_at=old_task.created_at if old_task else None,
            )
            if executed.status != TaskStatus.FAILED:
                append_log(settings.output, task_id, "info", "全量重建重跑完成", **log_detail)
            return

        append_log(settings.output, task_id, "info", "增量重建重跑开始", **log_detail)
        run_incremental_rebuild(
            rule_codes,
            package=package,
            task_id=task_id,
        )
        append_log(settings.output, task_id, "info", "增量重建重跑完成", **log_detail)

    def _task_info(self, task_id: str) -> tuple[Path | None, dict, str | None, str | None, TaskMode, TaskTrigger]:
        """获取任务执行信息；本地任务从 output/ 元数据兜底。"""
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record is not None:
                return (
                    settings.uploads / task_id / record.package_file,
                    record.customer or {},
                    record.version,
                    record.name,
                    TaskMode(record.mode),
                    TaskTrigger(record.trigger),
                )

        task = load_task_meta(settings.output, task_id)
        if task is None or task.system is None:
            return None, {}, None, None, TaskMode.LOCAL, TaskTrigger.CLI
        package_file = task.system.package_file
        package = settings.uploads / task_id / package_file
        if not package.exists():
            package = settings.uploads / package_file
        return package, task.system.customer, task.system.version, task.name, task.mode, task.trigger

    def _rebuild_package(self, task_id: str) -> tuple[InspectionTask, Path]:
        """读取重建请求的既有任务元数据和原始上传包。"""
        task = load_task_meta(settings.output, task_id)
        if task is None or task.system is None:
            raise TaskRebuildError("not_found", "任务不存在", 404)
        package = settings.uploads / task_id / task.system.package_file
        if not package.is_file():
            package = settings.uploads / task.system.package_file
        if not package.is_file() or package.stat().st_size == 0:
            raise TaskRebuildError("package_missing", "原始上传包缺失或为空", 409)
        return task, package

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
            return task.model_copy(update={"preparation": preparation.load_preparation(settings.output / task_id)})
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
                        preparation=preparation.load_preparation(task_file.parent),
                        system=None,
                        customer_province=customer.get("province"),
                        customer_operator=customer.get("operator"),
                        customer_product=customer.get("product"),
                        customer_version=task.system.version if task.system else None,
                    )
                )
                seen_ids.add(task.task_id)
        with session_factory() as session:
            # output/task.json 部分删除失败时，完成态数据库记录仍要兜底返回。
            query = session.query(TaskRecord)
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

        def created_at_key(task: TaskSummary) -> datetime:
            """SQLite 历史记录可能是 naive UTC；排序前统一为 aware UTC。"""
            if task.created_at is None:
                return datetime.min.replace(tzinfo=UTC)
            return task.created_at if task.created_at.tzinfo else task.created_at.replace(tzinfo=UTC)

        items.sort(key=created_at_key, reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    def delete(self, task_id: str) -> DeleteResult:
        """删除任务；文件现场全部成功后才删除数据库记录。"""
        with self._state_lock:
            if self._active_task == task_id:
                return DeleteResult.BUSY
            self._cancelled.add(task_id)
        try:
            with self._lock:
                task_file = settings.output / task_id / "task.json"
                meta_bytes = task_file.read_bytes() if task_file.is_file() else None
                with session_factory() as session:
                    record_exists = session.get(TaskRecord, task_id) is not None
                locations = [f"output/{task_id}", f"uploads/{task_id}"]
                found = record_exists
                for directory in (settings.output / task_id, settings.uploads / task_id):
                    if not directory.exists():
                        continue
                    found = True
                    try:
                        _remove_tree(directory, task_id, locations)
                    except TaskDeleteError:
                        if directory == settings.output / task_id and meta_bytes is not None and not task_file.exists():
                            task_file.parent.mkdir(parents=True, exist_ok=True)
                            task_file.write_bytes(meta_bytes)
                        raise
                if not found:
                    return DeleteResult.NOT_FOUND
                with session_factory() as session:
                    record = session.get(TaskRecord, task_id)
                    if record:
                        session.delete(record)
                        session.commit()
            return DeleteResult.DELETED
        finally:
            with self._state_lock:
                self._cancelled.discard(task_id)

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
        ensure_rule_states()
        for code in rule_codes or []:
            try:
                assert_rule_enabled(code)
            except RuleStateError as exc:
                raise TaskRebuildError(exc.code, exc.message, exc.status_code) from exc
        self._rerun_plan[task_id] = rule_codes
        pending_task = task.model_copy(update={"status": TaskStatus.PENDING, "completed_at": None})
        store.save_task_meta(settings.output, pending_task)
        self._update_status(task_id, TaskStatus.PENDING)
        self._queue.put(task_id)
        return True

    def rebuild(self, task_id: str, request: RebuildRequest) -> bool:
        """预检并受理显式重建重跑；预检失败不修改任务输出。"""
        with self._state_lock:
            if self._active_task == task_id or task_id in self._cancelled:
                raise TaskRebuildError("task_busy", "任务正在排队或执行，不能重建", 409)

        rule_codes: list[str] = []
        if request.mode == RebuildMode.INCREMENTAL:
            registry.load_all()
            registered = set(registry.codes())
            unknown = [code for code in request.rule_codes or [] if code not in registered]
            if unknown:
                raise TaskRebuildError("unknown_rule", f"规则不存在: {', '.join(unknown)}", 400)
            hidden = [
                code
                for code in request.rule_codes or []
                if registry.get(code).hidden or code.startswith("pkg.extract.")
            ]
            if hidden:
                raise TaskRebuildError(
                    "invalid_rebuild_request",
                    f"增量重建只允许普通规则: {', '.join(hidden)}",
                    400,
                )
            rule_codes = list(request.rule_codes or [])
            ensure_rule_states()
            for code in rule_codes:
                try:
                    assert_rule_enabled(code)
                except RuleStateError as exc:
                    raise TaskRebuildError(exc.code, exc.message, exc.status_code) from exc

        task, package = self._rebuild_package(task_id)
        if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise TaskRebuildError("task_busy", "任务正在排队或执行，不能重建", 409)
        plan = RebuildPlan(
            mode=request.mode,
            rule_codes=rule_codes,
            trigger_source=request.trigger_source.value,
        )
        self._rebuild_plan[task_id] = plan
        pending_task = task.model_copy(update={"status": TaskStatus.PENDING, "completed_at": None})
        store.save_task_meta(settings.output, pending_task)
        self._update_status(task_id, TaskStatus.PENDING)
        self._queue.put(task_id)
        return True


task_service = TaskService()
