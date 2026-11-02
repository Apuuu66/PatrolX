"""任务数据准备状态组装服务。"""

import json
from pathlib import Path
from typing import Any

from app.models.schemas import (
    DataPreparation,
    PreparationIssue,
    PreparationItem,
    PreparationStatus,
)
from app.services.extraction import manifest as manifest_v5

_MAIN_CODE = "pkg.extract.main"
_CLASSIFICATION_CODE = "pkg.extract.classification"
_FAILED_STATUSES = {"conflict", "duplicate", "failed", "rejected"}


def _read_json(path: Path) -> dict[str, Any] | None:
    """读取 JSON；坏文件由上层统一按准备失败处理。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _rule_result(data_dir: Path, code: str) -> dict[str, Any]:
    """读取隐藏准备规则的已保存结果。"""
    value = _read_json(data_dir / "rules" / f"{code}.json")
    return value or {}


def _manifest(data_dir: Path) -> dict[str, Any] | None:
    """返回有效 manifest；不存在时返回 None。"""
    path = manifest_v5.manifest_path(data_dir)
    if not path.exists() and not path.is_symlink():
        return None
    try:
        return manifest_v5.read_manifest(data_dir)
    except (manifest_v5.ManifestV5Error, OSError):
        return {}


def _aggregate_status(statuses: list[PreparationStatus]) -> PreparationStatus:
    if PreparationStatus.ERROR in statuses:
        return PreparationStatus.ERROR
    if PreparationStatus.FAIL in statuses:
        return PreparationStatus.FAIL
    if PreparationStatus.WARN in statuses:
        return PreparationStatus.WARN
    if statuses and all(status == PreparationStatus.SKIP for status in statuses):
        return PreparationStatus.SKIP
    return PreparationStatus.PASS


def _issue(item: dict[str, Any], *, status: str | None = None) -> PreparationIssue | None:
    issue_status = status or str(item.get("status", ""))
    if issue_status not in _FAILED_STATUSES:
        return None
    reason = item.get("error") or item.get("reason") or "数据准备项未成功"
    return PreparationIssue(
        type=issue_status,  # type: ignore[arg-type]
        source=item.get("source_relative") or item.get("source"),
        target=str(item.get("original_target") or item.get("target"))
        if item.get("original_target") is not None or item.get("target") is not None
        else None,
        reason=str(reason),
        path_length=item.get("path_length"),
        path_limit=item.get("path_limit"),
    )


def _saved_issue(result: dict[str, Any]) -> PreparationIssue:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    reason = metadata.get("error") or result.get("summary") or "隐藏解压单元执行失败"
    return PreparationIssue(type="rejected", reason=str(reason))


def _classification_item(data_dir: Path, manifest: dict[str, Any]) -> PreparationItem:
    result = _rule_result(data_dir, _CLASSIFICATION_CODE)
    saved_status = str(result.get("status", ""))
    entries = manifest["entries"]
    ignored = manifest["ignored"]
    conflicts = manifest["conflicts"]
    failures = manifest["failures"]
    issues = [
        issue
        for item, status in [
            *((record, "conflict") for record in conflicts),
            *((record, "failed") for record in failures),
        ]
        if (issue := _issue(item, status=status)) is not None
    ]
    extracted = len(entries)
    total = len(entries) + len(ignored) + len(failures)
    if saved_status == "error":
        status = PreparationStatus.ERROR
        issues = [_saved_issue(result), *issues]
    elif saved_status == "warn" or failures or conflicts:
        status = PreparationStatus.WARN
    else:
        status = PreparationStatus.PASS
    summary = str(result.get("summary")) if result.get("summary") else f"分类完成，{extracted} 项可巡检"
    return PreparationItem(
        code=_CLASSIFICATION_CODE,
        name=str(result.get("name") or "分类落位终态校验"),
        category="classification",
        status=status,
        summary=summary,
        duration_ms=result.get("duration_ms"),
        extracted_count=extracted,
        total_count=total,
        issues=issues,
    )


def _main_item(data_dir: Path, manifest: dict[str, Any]) -> PreparationItem:
    result = _rule_result(data_dir, _MAIN_CODE)
    main = manifest.get("main")
    if not isinstance(main, dict) or str(result.get("status", "")) == "error":
        reason = _saved_issue(result).reason if result else "主包解压失败"
        return PreparationItem(
            code=_MAIN_CODE,
            name=str(result.get("name") or "主包解压"),
            category="main",
            status=PreparationStatus.ERROR,
            summary=str(result.get("summary") or "主包解压失败"),
            duration_ms=result.get("duration_ms"),
            extracted_count=0,
            total_count=0,
            issues=[PreparationIssue(type="rejected", reason=str(reason))],
        )
    total = int(main.get("count", 0))
    return PreparationItem(
        code=_MAIN_CODE,
        name=str(result.get("name") or "主包解压"),
        category="main",
        status=PreparationStatus.PASS,
        summary=str(result.get("summary") or f"主包解压 {total} 个原始文件"),
        duration_ms=result.get("duration_ms"),
        extracted_count=total,
        total_count=total,
        issues=[],
    )


def _corrupt_preparation(data_dir: Path) -> DataPreparation:
    classification_result = _rule_result(data_dir, _CLASSIFICATION_CODE)
    if classification_result.get("status") == "error":
        classification = PreparationItem(
            code=_CLASSIFICATION_CODE,
            name=str(classification_result.get("name") or "分类落位终态校验"),
            category="classification",
            status=PreparationStatus.ERROR,
            summary=str(classification_result.get("summary") or "分类失败"),
            duration_ms=classification_result.get("duration_ms"),
            extracted_count=0,
            total_count=0,
            issues=[_saved_issue(classification_result)],
        )
    else:
        classification = PreparationItem(
            code=_CLASSIFICATION_CODE,
            name="分类落位终态校验",
            category="classification",
            status=PreparationStatus.ERROR,
            summary="数据准备清单损坏",
            extracted_count=0,
            total_count=0,
            issues=[PreparationIssue(type="rejected", reason="manifest 损坏或版本不匹配")],
        )
    items = [
        PreparationItem(
            code=_MAIN_CODE,
            name="主包解压",
            category="main",
            status=PreparationStatus.ERROR,
            summary="数据准备清单损坏",
            extracted_count=0,
            total_count=0,
            issues=[PreparationIssue(type="rejected", reason="manifest 损坏或版本不匹配")],
        ),
        classification,
    ]
    return _build_preparation(items)


def _build_preparation(items: list[PreparationItem]) -> DataPreparation:
    counts = {status: 0 for status in PreparationStatus}
    for item in items:
        counts[item.status] += 1
    return DataPreparation(
        status=_aggregate_status([item.status for item in items]),
        items=items,
        total=len(items),
        success_count=counts[PreparationStatus.PASS],
        warning_count=counts[PreparationStatus.WARN],
        failure_count=counts[PreparationStatus.FAIL] + counts[PreparationStatus.ERROR],
        skip_count=counts[PreparationStatus.SKIP],
    )


def load_task_preparation(task_id: str, *, data_dir: Path | None = None) -> DataPreparation | None:
    """任务详情的准备摘要：``tasks.preparation`` 列优先，历史现场兜底现算。

    展示读取以 SQLite 为唯一来源；仅当任务行尚无准备摘要时按现场计算（未回填的历史任务）。
    """
    from app.core.config import settings
    from app.services import task_db

    task = task_db.get_task(task_id)
    if task is not None and task.preparation is not None:
        return task.preparation
    return load_preparation(data_dir if data_dir is not None else settings.output / task_id)


def load_preparation(data_dir: Path) -> DataPreparation | None:
    """读取任务数据准备状态；无 manifest 的历史或进行中任务返回 None。"""
    manifest = _manifest(data_dir)
    if manifest is None:
        return None
    if not manifest:
        return _corrupt_preparation(data_dir)
    return _build_preparation(
        [
            _main_item(data_dir, manifest),
            _classification_item(data_dir, manifest),
        ]
    )
