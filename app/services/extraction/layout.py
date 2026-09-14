"""解压现场分类落位与安全路径 helper。"""

from pathlib import Path

from app.core.archive import ArchiveError
from app.core.classify import classify_file, classify_name
from app.models.schemas import RuleCategory

MANIFEST_NAME = ".patrolx-extracted.json"
MAIN_EVIDENCE_DIR = ".main"
MANIFEST_VERSION = 3
CATEGORY_DIRECTORIES = {
    RuleCategory.LOG.value: "logs",
    RuleCategory.KPI.value: "kpi",
    RuleCategory.TRAFFIC.value: "traffic",
    RuleCategory.ALARM.value: "alarm",
    RuleCategory.CONFIG.value: "config",
    RuleCategory.RESOURCE.value: "resource",
    RuleCategory.OTHER.value: "other",
}
WORK_CATEGORIES = list(CATEGORY_DIRECTORIES.values())


def _relative_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _safe_destination(data_dir: Path, relative: Path) -> Path:
    destination = (data_dir / relative).resolve()
    if not destination.is_relative_to(data_dir.resolve()):
        raise ArchiveError(f"目标路径穿越被拒绝: {relative.as_posix()}")
    if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
        raise ArchiveError(f"目标路径包含链接: {relative.as_posix()}")
    return destination


def _unique_work_path(root: Path, relative: Path, checksum: str) -> Path:
    candidate = root / relative
    if not candidate.exists():
        return candidate
    return root / relative.with_name(f"{relative.name}-{checksum[:8]}")


def _remove_empty_work_site(work_path: Path, category_root: Path) -> None:
    """子包成员已移走后，自底向上清理空工作目录及其空父目录。"""
    descendants = sorted(work_path.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in descendants:
        if not path.is_dir():
            return
        try:
            path.rmdir()
        except OSError:
            return
    try:
        work_path.rmdir()
    except OSError:
        return
    current = work_path.parent.resolve()
    root = category_root.resolve()
    while current != root and current.is_relative_to(root):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _category_of(path: Path, parent_category: str) -> tuple[str, str]:
    category = classify_name(path.name) or classify_file(path)
    if category is not None:
        return category.value, "self:name" if classify_name(path.name) else "self:content"
    if parent_category:
        return parent_category, "parent:category"
    return RuleCategory.OTHER.value, "fallback:other"


def _destination_relative(
    source_relative: Path,
    source_kind: str,
    group: str,
    category: str,
) -> Path:
    if source_kind == "evidence":
        parts = source_relative.parts
        if parts and parts[0] == CATEGORY_DIRECTORIES[category]:
            return Path(CATEGORY_DIRECTORIES[category]) / Path(*parts[1:])
        return Path(CATEGORY_DIRECTORIES[category]) / source_relative
    if group:
        return Path(CATEGORY_DIRECTORIES[category]) / group / source_relative
    return Path(CATEGORY_DIRECTORIES[category]) / source_relative


def _register_rejected(
    manifest: dict,
    source: str,
    reason: str,
    category: str,
    depth: int,
) -> None:
    manifest["rejected"].append(
        {
            "source": source,
            "category": category,
            "reason": reason,
            "depth": depth,
        }
    )
