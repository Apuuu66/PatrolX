"""解压现场分类落位与安全路径 helper。"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.archive import ArchiveError, PathTooLongError
from app.core.classify import classify_content, classify_member, classify_name
from app.models.schemas import RuleCategory

MANIFEST_NAME = ".patrolx-extracted.json"
MAIN_EVIDENCE_DIR = ".main"
MANIFEST_VERSION = 4
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


@dataclass(frozen=True)
class PathLimitPolicy:
    """注入式路径长度限制策略。"""

    enabled: bool = False
    limit: int | None = None

    @classmethod
    def current(cls) -> "PathLimitPolicy":
        """读取当前系统限制；仅 Windows 传统 MAX_PATH 生效时启用。"""
        if sys.platform != "win32":
            return cls(enabled=False, limit=None)
        limit = 260
        try:
            import winreg  # noqa: PLC0415

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\FileSystem",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            if value == 1:
                return cls(enabled=False, limit=None)
        except OSError:
            return cls(enabled=True, limit=limit)
        return cls(enabled=True, limit=limit)

    @property
    def fingerprint(self) -> str:
        """返回用于 manifest 复用判断的稳定指纹。"""
        payload = {"enabled": self.enabled, "limit": self.limit}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        import hashlib

        return hashlib.sha256(encoded).hexdigest()

    def snapshot(self) -> dict[str, object]:
        """返回 manifest 路径限制上下文。"""
        return {"enabled": self.enabled, "limit": self.limit, "fingerprint": self.fingerprint}

    def check(self, destination: Path, _label: str | None = None) -> None:
        """目标完整路径超过限制时提前失败。"""
        if not self.enabled or self.limit is None:
            return
        full_path = os.path.abspath(os.fspath(destination))
        length = len(full_path)
        if length >= self.limit:
            raise PathTooLongError(full_path, length, self.limit)


def _relative_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _safe_destination(data_dir: Path, relative: Path, path_policy: PathLimitPolicy | None = None) -> Path:
    destination = (data_dir / relative).resolve()
    if not destination.is_relative_to(data_dir.resolve()):
        raise ArchiveError(f"目标路径穿越被拒绝: {relative.as_posix()}")
    if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
        raise ArchiveError(f"目标路径包含链接: {relative.as_posix()}")
    if path_policy is not None:
        path_policy.check(destination)
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


def _category_of(path: Path, parent_category: str, archive_name: str | None = None) -> tuple[str, str]:
    locked_category = classify_member(archive_name)
    if locked_category is not None:
        return locked_category.value, "archive:member"
    name_category = classify_name(path.name)
    category = name_category or classify_content(path)
    if category is not None:
        return category.value, "self:name" if name_category is not None else "self:content"
    if parent_category:
        return parent_category, "parent:category"
    return RuleCategory.OTHER.value, "fallback:other"


def _destination_relative(
    source_relative: Path,
    source_kind: str,
    category: str,
) -> Path:
    category_root = Path(CATEGORY_DIRECTORIES[category])
    if source_kind == "evidence":
        parts = source_relative.parts
        if parts and len(parts) > 1 and parts[0] == CATEGORY_DIRECTORIES[category]:
            return category_root / Path(*parts[1:])
        return category_root / source_relative
    return category_root / source_relative


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
