"""任务服务：SQLite 是界面展示唯一数据源，output/ 为执行期现场。"""

import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session

from app.cli import generate_task_id, run_incremental_rebuild, run_single_rule, run_task
from app.core.checksum import sha256_file
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import TASKS_DURATION, TASKS_TOTAL
from app.inspectors.registry import registry
from app.models.db import InventoryDevice, InventoryParseResult, TaskRecord, init_db, session_factory
from app.models.schemas import (
    InspectionTask,
    PackageKind,
    RebuildMode,
    RebuildRequest,
    TaskCreated,
    TaskInventory,
    TaskMode,
    TaskStatus,
    TaskSummary,
    TaskTrigger,
)
from app.services import preparation, retention, store, task_db
from app.services.extraction.layout import PathLimitPolicy
from app.services.rule_states import RuleStateError, assert_rule_enabled, ensure_rule_states
from app.services.store import append_log, load_task_meta, write_json_atomic

logger = get_logger("patrolx.tasks")
NOW = datetime.now
SCENE_CLEANED_MESSAGE = "任务现场已按留存策略清理，需重新上传同名且校验和一致的原始包恢复现场后执行"
PACKAGE_MISSING_MESSAGE = "原始上传包缺失或为空，需重新上传同名且校验和一致的原始包恢复现场后执行"


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


class TaskDeviceIdError(Exception):
    """设备 ID 更新业务错误。"""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


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
                self._finish_run(task_id, TaskStatus.FAILED)

    def _publish_terminal(self, task: InspectionTask) -> None:
        """在线任务终态发布：SQLite 快照先收敛，再写 task.json。

        终态发布是任务现场的最后一次写入：读方看到 completed 时，报告、收尾日志、
        台账归档与 SQLite 快照（任务行 + 规则结果 + KPI 点 + 准备摘要）均已就绪。
        运行字段以 ``save_run_start`` 写入的本次开始时刻为准，现场旧值不得回退。
        """
        last_run_at, _, _ = task_db.get_run_fields(task.task_id)
        completed_at = task.completed_at or NOW(UTC)
        published = task.model_copy(
            update={
                "completed_at": completed_at,
                "last_run_at": last_run_at or task.last_run_at,
                "duration_ms": task_db.elapsed_ms(last_run_at or task.last_run_at, completed_at),
            }
        )
        # 任务行、规则结果、KPI 点与本次耗时在同一发布事务内收敛，终态一旦可见数据即完整。
        task_db.publish_from_scene(published, output=settings.output)
        store.save_task_meta(settings.output, published)
        # 终态发布完成后执行磁盘留存清理；清理失败只记日志，不改变任务终态。
        retention.cleanup_safely(output=settings.output, uploads=settings.uploads)

    def _finish_run(
        self,
        task_id: str,
        status: TaskStatus,
        completed_at: datetime | None = None,
    ) -> None:
        """运行终态收口：写终态、结束时刻与本次运行耗时（毫秒）。"""
        finished_at = completed_at or NOW(UTC)
        last_run_at, _, _ = task_db.get_run_fields(task_id)
        task_db.save_run_end(
            task_id,
            status=status,
            completed_at=finished_at,
            duration_ms=task_db.elapsed_ms(last_run_at, finished_at),
        )
        # 失败收尾同样触发留存清理；清理失败只记日志，不改变任务终态。
        retention.cleanup_safely(output=settings.output, uploads=settings.uploads)

    def _update_status(self, task_id: str, status: TaskStatus, completed_at: datetime | None = None) -> None:
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record:
                record.status = status.value
                record.completed_at = completed_at
                if status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                    # 排队/运行中不展示上一次耗时，终态由 _finish_run 写入本次值。
                    record.duration_ms = None
                session.commit()

    def _execute(self, task_id: str) -> None:
        package, customer, version, name, mode, trigger, package_kind, created_at = self._task_info(task_id)
        if package is None:
            return
        started = NOW(UTC)
        self._update_status(task_id, TaskStatus.RUNNING)
        task_db.save_run_start(task_id, started)
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
                        trigger_retention=False,
                    )
                append_log(settings.output, task_id, "info", "重跑完成，报告已更新")
                current = load_task_meta(settings.output, task_id)
                if current:
                    completed_task = current.model_copy(
                        update={"status": TaskStatus.COMPLETED, "completed_at": NOW(UTC)}
                    )
                    self._publish_terminal(completed_task)
                else:
                    self._finish_run(task_id, TaskStatus.COMPLETED)
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
                    package_kind=package_kind,
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
                    created_at=created_at,
                    package_kind=package_kind,
                    publish=self._publish_terminal,
                )
                if executed.status == TaskStatus.FAILED:
                    TASKS_DURATION.observe((NOW(UTC) - started).total_seconds())
                    return
            # 终态已由 _publish_terminal 落库并发布，此处不再回写，避免终态可见后再改写记录。
            TASKS_DURATION.observe((NOW(UTC) - started).total_seconds())
            TASKS_TOTAL.labels(result="completed", mode="online").inc()
        except Exception:  # noqa: BLE001
            failed_task = load_task_meta(settings.output, task_id)
            failed_at = NOW(UTC)
            self._finish_run(task_id, TaskStatus.FAILED, failed_at)
            if failed_task:
                failed = failed_task.model_copy(update={"status": TaskStatus.FAILED, "completed_at": failed_at})
                store.save_task_meta(settings.output, failed)
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
        package_kind: PackageKind = PackageKind.INSPECTION,
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
                package_kind=package_kind,
                publish=self._publish_terminal,
            )
            if executed.status != TaskStatus.FAILED:
                append_log(settings.output, task_id, "info", "全量重建重跑完成", **log_detail)
            return

        append_log(settings.output, task_id, "info", "增量重建重跑开始", **log_detail)
        run_incremental_rebuild(
            rule_codes,
            package=package,
            task_id=task_id,
            publish=self._publish_terminal,
        )
        append_log(settings.output, task_id, "info", "增量重建重跑完成", **log_detail)

    def _task_info(
        self, task_id: str
    ) -> tuple[Path | None, dict, str | None, str | None, TaskMode, TaskTrigger, PackageKind, datetime | None]:
        """获取任务执行信息；本地任务从 output/ 元数据兜底。

        ``created_at`` 是任务创建时刻，执行期只透传、不得覆盖；现场元数据与库内任务行
        必须记录同一创建时间，回退读才不会出现两套口径。
        """
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
                    PackageKind(getattr(record, "package_kind", "inspection")),
                    record.created_at,
                )

        task = load_task_meta(settings.output, task_id)
        if task is None or task.system is None:
            return None, {}, None, None, TaskMode.LOCAL, TaskTrigger.CLI, PackageKind.INSPECTION, None
        package_file = task.system.package_file
        package = settings.uploads / task_id / package_file
        if not package.exists():
            package = settings.uploads / package_file
        package_kind = task.package_kind or PackageKind.INSPECTION
        return (
            package,
            task.system.customer,
            task.system.version,
            task.name,
            task.mode,
            task.trigger,
            package_kind,
            task.created_at,
        )

    def _scene_or_db_task(self, task_id: str) -> InspectionTask | None:
        """重跑/重建元数据：现场 task.json 优先；现场已清理时使用 SQLite 快照。"""
        task = load_task_meta(settings.output, task_id)
        if task is not None and task.system is not None:
            return task
        snapshot = task_db.get_task(task_id)
        if snapshot is not None and snapshot.system is not None:
            return snapshot
        return None

    def _resolve_run_package(self, task_id: str, task: InspectionTask) -> Path:
        """定位原始上传包；包缺失时按现场是否仍在区分「待恢复」与「包缺失」。"""
        assert task.system is not None
        package_file = task.system.package_file
        package = settings.uploads / task_id / package_file
        if not package.is_file():
            package = settings.uploads / package_file
        if not package.is_file() or package.stat().st_size == 0:
            if (settings.output / task_id).is_dir():
                raise TaskRebuildError("package_missing", PACKAGE_MISSING_MESSAGE, 409)
            raise TaskRebuildError("scene_cleaned", SCENE_CLEANED_MESSAGE, 410)
        return package

    def _rebuild_package(self, task_id: str) -> tuple[InspectionTask, Path]:
        """读取重建请求的既有任务元数据和原始上传包；现场缺失给出恢复提示。"""
        task = self._scene_or_db_task(task_id)
        if task is None or task.system is None:
            raise TaskRebuildError("not_found", "任务不存在", 404)
        return task, self._resolve_run_package(task_id, task)

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
        device_id: str | None = None,
        package_kind: PackageKind = PackageKind.INSPECTION,
    ) -> TaskCreated:
        task_id = generate_task_id(package_file)
        customer: dict[str, str] = {}
        if province:
            customer["province"] = province
        if operator:
            customer["operator"] = operator
        if product:
            customer["product"] = product
        normalized_device_id = self._validate_device_id(device_id or "")
        # 手动指定的设备 ID 必须是台账内设备；校验在写库、写现场之前完成（FR-010、SC-005）。
        self._assert_device_id_in_ledger(normalized_device_id)
        if normalized_device_id:
            customer["device_id"] = normalized_device_id
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
                    package_kind=package_kind.value,
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

    @staticmethod
    def _record_package_kind(record: TaskRecord) -> PackageKind:
        """SQLite 兜底读：package_kind 必须与创建请求一致，非法历史值降级为 inspection。"""
        raw = getattr(record, "package_kind", None) or PackageKind.INSPECTION.value
        try:
            return PackageKind(str(raw))
        except ValueError:
            return PackageKind.INSPECTION

    @staticmethod
    def _fallback_inventory(session: Session, task_id: str) -> TaskInventory | None:
        """SQLite 兜底读：从任务级台账证据快照重建 inventory，坏快照只降级不报错。"""
        result = session.get(InventoryParseResult, task_id)
        snapshot = result.snapshot if result is not None else None
        if not isinstance(snapshot, dict):
            return None
        try:
            return TaskInventory.model_validate(snapshot)
        except Exception:  # noqa: BLE001 - 坏快照不得阻断任务兜底读取
            return None

    def get(self, task_id: str) -> InspectionTask | None:
        """读取任务详情：SQLite 快照优先；未回填的历史现场兜底并机会式补齐快照。"""
        snapshot = task_db.get_task(task_id)
        if snapshot is not None and snapshot.system is not None:
            return snapshot
        task = load_task_meta(settings.output, task_id)
        if task is None:
            return snapshot
        # 现场仍在但库里没有快照（历史任务尚未回填）：先按现场补齐快照，之后读取不再依赖文件。
        if snapshot is None:
            try:
                task_db.import_task_from_output(task_id, output=settings.output, force=True)
            except Exception:  # noqa: BLE001 - 回填失败只降级为现场读取
                logger.warning("task_scene_backfill_failed", task_id=task_id)
            repaired = task_db.get_task(task_id)
            if repaired is not None and repaired.system is not None:
                return repaired
        if snapshot is not None and snapshot.preparation is not None:
            # 库内任务行可能因历史原因缺少规则行，但准备摘要仍以列为准。
            return task.model_copy(update={"preparation": snapshot.preparation})
        return task.model_copy(update={"preparation": preparation.load_preparation(settings.output / task_id)})

    def list_tasks(self, page: int, page_size: int, status: str | None) -> tuple[list[TaskSummary], int]:
        """列表：全部来自 SQLite 任务行，现场文件不参与展示读取。"""
        start = (page - 1) * page_size
        return task_db.list_task_summaries(status, limit=page_size, offset=start)

    @staticmethod
    def _validate_device_id(device_id: str) -> str:
        normalized = device_id.strip()
        if normalized and not 1 <= len(normalized) <= 128:
            raise TaskDeviceIdError("invalid_device_id", "设备 ID 长度必须为 1-128", 400)
        return normalized

    @staticmethod
    def _assert_device_id_in_ledger(device_id: str) -> None:
        """手动指定的设备 ID 必须已存在于设备台账；空值表示解绑，不做校验（FR-010、R9）。"""
        if not device_id:
            return
        with session_factory() as session:
            exists = session.get(InventoryDevice, device_id) is not None
        if not exists:
            raise TaskDeviceIdError("device_not_found", "设备 ID 不存在于设备台账", 400)

    def update_device_id(self, task_id: str, device_id: str) -> TaskSummary:
        """修改任务设备 ID，并同步 SQLite 与任务输出元数据。"""
        normalized = self._validate_device_id(device_id)
        task = load_task_meta(settings.output, task_id)
        if task is None:
            raise TaskDeviceIdError("not_found", "任务不存在", 404)
        if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise TaskDeviceIdError("task_busy", "任务正在排队或执行，不能修改设备 ID", 409)
        if task.system is None:
            raise TaskDeviceIdError("not_found", "任务不存在", 404)
        # 存在性与忙碌判断通过后才校验台账，且校验在写库、写现场之前完成（FR-010、SC-005）。
        self._assert_device_id_in_ledger(normalized)

        customer = dict(task.system.customer)
        customer["device_id"] = normalized
        updated_task = task.model_copy(
            update={
                "system": task.system.model_copy(update={"customer": customer}),
            }
        )
        store.save_task_meta(settings.output, updated_task)
        write_json_atomic(
            settings.output / task_id / "system.json",
            updated_task.system.model_dump(by_alias=True, mode="json"),
        )
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record:
                record.customer = {**(record.customer or {}), "device_id": normalized}
                session.commit()

        # 展示读取一律走库：任务行已同步，直接返回库内摘要，避免现场与库两套口径。
        summary = task_db.get_task_summary(task_id)
        if summary is not None:
            return summary
        customer = updated_task.system.customer if updated_task.system else {}
        return TaskSummary(
            task_id=updated_task.task_id,
            name=updated_task.name,
            mode=updated_task.mode,
            status=updated_task.status,
            trigger=updated_task.trigger,
            created_at=updated_task.created_at,
            completed_at=updated_task.completed_at,
            stats=updated_task.stats,
            preparation=preparation.load_task_preparation(task_id),
            system=None,
            customer_province=customer.get("province"),
            customer_operator=customer.get("operator"),
            customer_product=customer.get("product"),
            customer_version=updated_task.system.version if updated_task.system else None,
            device_id=customer.get("device_id"),
        )

    def delete(self, task_id: str) -> DeleteResult:
        """删除任务；文件现场全部成功后才级联删除库内任务行、规则结果与 KPI 点。"""
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
                # 文件现场全部删除成功后才删除库内数据：任务行 + 规则结果 + KPI 点一次级联。
                with session_factory() as session:
                    task_db.delete_task_data(session, task_id)
                    session.commit()
            return DeleteResult.DELETED
        finally:
            with self._state_lock:
                self._cancelled.discard(task_id)

    def rerun(self, task_id: str, rule_codes: list[str] | None) -> bool:
        """重跑：元数据现场优先、库快照兜底；包缺失按现场是否仍在区分 410/409。"""
        task = self._scene_or_db_task(task_id)
        if task is None or task.system is None:
            return False
        # 预检原始包：包缺失时按现场是否仍在抛 409/410，不发起重跑。
        self._resolve_run_package(task_id, task)
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
