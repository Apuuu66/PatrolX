"""磁盘现场留存治理：只保留最近 N 个任务现场，数据库长期保留。

保留集合 = 按 ``COALESCE(last_run_at, created_at)`` 倒序前 50 个任务 ∪ 所有
``pending``/``running`` 任务。清理只删磁盘，不删除或修改任何数据库行；单次删除失败
只记录结构化日志，由下一次任务结束时的清理重试。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.core.archive import is_archive
from app.core.config import settings
from app.core.logging import get_logger
from app.services import task_db

logger = get_logger("patrolx.retention")

MAX_RETAINED_SCENES = 50
_EXEMPT_STATUSES = {"pending", "running"}


def _task_id_for_package(package_name: str) -> str:
    """由包名派生 task_id；延迟导入避免 cli ↔ services 的模块级导入环。"""
    from app.cli import generate_task_id

    return generate_task_id(package_name)


def _sort_key(record: task_db.TaskRecordView) -> tuple[datetime, str]:
    """排序键：最近一次运行开始时刻优先，从未运行回退创建时刻。"""
    value = record.last_run_at or record.created_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value, record.task_id


def retained_task_ids(records: list[task_db.TaskRecordView] | None = None) -> set[str]:
    """计算保留集合：最近 N 个任务 ∪ 执行中任务。"""
    rows = task_db.list_task_records() if records is None else records
    ordered = sorted(rows, key=_sort_key, reverse=True)
    retained = {record.task_id for record in ordered[:MAX_RETAINED_SCENES]}
    retained |= {record.task_id for record in rows if record.status in _EXEMPT_STATUSES}
    return retained


@dataclass(slots=True)
class CleanupResult:
    """一次留存清理的结果，供调用方记录日志。"""

    retained: set[str] = field(default_factory=set)
    removed_directories: list[str] = field(default_factory=list)
    removed_packages: list[str] = field(default_factory=list)
    failed_paths: list[str] = field(default_factory=list)
    skipped_unknown: list[str] = field(default_factory=list)


def _remove_directory(path: Path, result: CleanupResult) -> None:
    try:
        shutil.rmtree(path)
    except OSError as exc:
        logger.warning("scene_cleanup_failed", path=str(path), error=str(exc), status="failed")
        result.failed_paths.append(str(path))
        return
    result.removed_directories.append(str(path))


def cleanup(
    *,
    output: Path | None = None,
    uploads: Path | None = None,
    records: list[task_db.TaskRecordView] | None = None,
) -> CleanupResult:
    """清理不在保留集合内的任务现场；只删磁盘，不碰数据库。"""
    output_dir = output or settings.output
    uploads_dir = uploads or settings.uploads
    rows = task_db.list_task_records() if records is None else records
    known_ids = {record.task_id for record in rows}
    retained = retained_task_ids(rows)
    result = CleanupResult(retained=retained)

    for base in (uploads_dir, output_dir):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            task_id = child.name
            if task_id not in known_ids:
                result.skipped_unknown.append(str(child))
                continue
            if task_id in retained:
                continue
            _remove_directory(child, result)

    if uploads_dir.is_dir():
        for path in sorted(uploads_dir.iterdir()):
            if not path.is_file() or not is_archive(path):
                continue
            derived_id = _task_id_for_package(path.name)
            if derived_id not in known_ids or derived_id in retained:
                continue
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("scene_cleanup_failed", path=str(path), error=str(exc), status="failed")
                result.failed_paths.append(str(path))
                continue
            result.removed_packages.append(str(path))

    logger.info(
        "scene_cleanup_done",
        retained_count=len(retained),
        removed_directory_count=len(result.removed_directories),
        removed_package_count=len(result.removed_packages),
        failed_count=len(result.failed_paths),
    )
    return result


def cleanup_safely(
    *,
    output: Path | None = None,
    uploads: Path | None = None,
    records: list[task_db.TaskRecordView] | None = None,
) -> CleanupResult | None:
    """终态收口使用的安全清理入口：任何异常只记日志，不改变任务终态。"""
    try:
        return cleanup(output=output, uploads=uploads, records=records)
    except Exception as exc:  # noqa: BLE001 - 清理失败不得影响任务终态与已发布数据
        logger.warning("scene_cleanup_error", error=str(exc), status="failed")
        return None
