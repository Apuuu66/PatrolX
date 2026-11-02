"""解压现场安全路径与路径长度限制 helper。"""

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.archive import ArchiveError, PathTooLongError
from app.services.extraction.manifest import MAIN_EVIDENCE_DIR, TARGET_ROOT_ALLOWLIST

__all__ = [
    "MAIN_EVIDENCE_DIR",
    "PathLimitPolicy",
    "_relative_files",
    "_safe_destination",
    "destination_for_target",
]


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
    """返回目录下按相对路径稳定排序的普通文件。"""
    return sorted(path for path in root.rglob("*") if path.is_file())


def _safe_destination(data_dir: Path, relative: Path, path_policy: PathLimitPolicy | None = None) -> Path:
    """解析任务目标，并拒绝越界路径与链接路径。"""
    if data_dir.is_symlink():
        raise ArchiveError(
            f"任务根目录不得是链接: {data_dir}",
            "link_rejected",
        )
    candidate = data_dir / relative
    if not candidate.is_relative_to(data_dir):
        raise ArchiveError(
            f"目标路径穿越被拒绝: {relative.as_posix()}",
            "unsafe_path",
        )

    current = data_dir
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ArchiveError(
                f"目标路径包含链接: {relative.as_posix()}",
                "link_rejected",
            )

    root_resolved = data_dir.resolve()
    destination = candidate.resolve()
    if not destination.is_relative_to(root_resolved):
        raise ArchiveError(
            f"目标路径穿越被拒绝: {relative.as_posix()}",
            "unsafe_path",
        )
    if path_policy is not None:
        path_policy.check(destination)
    return destination


def destination_for_target(data_dir: Path, target: str) -> Path:
    """解析分类目标；仅允许 manifest v5 可发布的目标根。"""
    relative = Path(target)
    if relative.is_absolute() or not relative.parts:
        raise ArchiveError(f"分类目标必须是相对路径: {target}", "unsafe_path")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ArchiveError(f"分类目标路径非法: {target}", "unsafe_path")
    if relative.parts[0] not in TARGET_ROOT_ALLOWLIST:
        raise ArchiveError(f"分类目标根不在 manifest allowlist: {relative.parts[0]}", "target_conflict")
    return _safe_destination(data_dir, relative)
