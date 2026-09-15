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
from app.services.extraction import WORK_CATEGORIES, manifest_path, validate_manifest

_MAIN_CODE = "pkg.extract.main"
_CATEGORY_LABELS = {
    "logs": "日志",
    "kpi": "KPI",
    "traffic": "流量",
    "alarm": "告警",
    "config": "配置",
    "resource": "资源",
    "other": "其他",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    """读取 JSON；坏文件由上层统一按准备失败处理。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _rule_result(data_dir: Path, code: str) -> dict[str, Any]:
    """读取隐藏准备规则的已保存结果。"""
    value = _read_json(data_dir / "rules" / f"{code}.json")
    return value or {}


def _manifest(data_dir: Path) -> dict[str, Any] | None:
    """返回有效 manifest；不存在时返回 None。"""
    path = manifest_path(data_dir)
    if not path.exists():
        return None
    value = _read_json(path)
    if value is None or not validate_manifest(value):
        return {}
    return value


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


def _item_status(total: int, extracted: int, issues: list[PreparationIssue]) -> PreparationStatus:
    if any(issue.type in {"failed", "rejected"} for issue in issues):
        return PreparationStatus.FAIL
    if issues:
        return PreparationStatus.WARN
    if total == 0:
        return PreparationStatus.SKIP
    if extracted < total:
        return PreparationStatus.WARN
    return PreparationStatus.PASS


def _issue(item: dict[str, Any], source: str | None) -> PreparationIssue | None:
    status = str(item.get("status", ""))
    if status not in {"conflict", "duplicate", "skipped", "failed", "rejected"}:
        return None
    policy = item.get("policy") if isinstance(item.get("policy"), dict) else {}
    reason = item.get("error") or policy.get("reason") or "数据准备项未成功"
    return PreparationIssue(
        type=status,  # type: ignore[arg-type]
        source=source,
        target=str(item.get("target")) if item.get("target") is not None else None,
        reason=str(reason),
        path_length=item.get("path_length"),
        path_limit=item.get("path_limit"),
    )


def _category_sources(manifest: dict[str, Any], category: str) -> list[dict[str, Any]]:
    sources = [
        item for item in manifest.get("files", []) if isinstance(item, dict) and item.get("category") == category
    ]
    sources.extend(
        item for item in manifest.get("subpackages", []) if isinstance(item, dict) and item.get("category") == category
    )
    if category == "logs":
        sources.extend(item for item in manifest.get("log_gz", []) if isinstance(item, dict))
    return sources


def _category_item(data_dir: Path, manifest: dict[str, Any], category: str) -> PreparationItem:
    code = f"pkg.extract.{category}"
    result = _rule_result(data_dir, code)
    sources = _category_sources(manifest, category)
    issues = [issue for issue in (_issue(item, item.get("source")) for item in sources) if issue is not None]
    extracted = sum(item.get("status") == "extracted" for item in sources)
    total = len(sources)
    status = _item_status(total, extracted, issues)
    if total == 0:
        summary = f"{category} 类无来源数据"
    else:
        summary = f"{category} 类准备 {extracted}/{total}"
    return PreparationItem(
        code=code,
        name=str(result.get("name") or f"{_CATEGORY_LABELS[category]}分类解压"),
        category=category,
        status=status,
        summary=str(result.get("summary") or summary),
        duration_ms=result.get("duration_ms"),
        extracted_count=extracted,
        total_count=total,
        issues=issues,
    )


def _main_item(data_dir: Path, manifest: dict[str, Any]) -> PreparationItem:
    result = _rule_result(data_dir, _MAIN_CODE)
    main = manifest.get("main")
    if not isinstance(main, dict):
        return PreparationItem(
            code=_MAIN_CODE,
            name=str(result.get("name") or "主包解压"),
            category="main",
            status=PreparationStatus.ERROR,
            summary=str(result.get("summary") or "主包解压失败"),
            duration_ms=result.get("duration_ms"),
            extracted_count=0,
            total_count=0,
            issues=[PreparationIssue(type="rejected", reason="主包解压失败")],
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


def _corrupt_preparation() -> DataPreparation:
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
        )
    ]
    for category in WORK_CATEGORIES:
        items.append(
            PreparationItem(
                code=f"pkg.extract.{category}",
                name=f"{_CATEGORY_LABELS[category]}分类解压",
                category=category,
                status=PreparationStatus.SKIP,
                summary=f"{category} 类无来源数据",
                extracted_count=0,
                total_count=0,
                issues=[],
            )
        )
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


def load_preparation(data_dir: Path) -> DataPreparation | None:
    """读取任务数据准备状态；无 manifest 的历史或进行中任务返回 None。"""
    manifest = _manifest(data_dir)
    if manifest is None:
        return None
    if not manifest:
        return _corrupt_preparation()
    items = [
        _main_item(data_dir, manifest),
        *(_category_item(data_dir, manifest, category) for category in WORK_CATEGORIES),
    ]
    return _build_preparation(items)
