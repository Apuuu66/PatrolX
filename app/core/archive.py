"""安全解压：路径穿越、符号链接与解压炸弹防护。"""

import gzip
import stat
import tarfile
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath


class ArchiveError(Exception):
    """压缩包解析错误。"""


class UnpackLimit:
    """解压安全限制（默认值，固定不配置化）。"""

    max_depth: int = 12
    max_files: int = 100_000
    max_single_file: int = 2 * 1024 * 1024 * 1024  # 2GB
    max_total_bytes: int = 3 * 1024 * 1024 * 1024  # 3GB 硬上限


def format_bytes(size: int) -> str:
    """将字节数格式化为用户可读的容量。"""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _expansion_budget(limit: UnpackLimit) -> int:
    """允许写入的最大总字节数：单包硬上限。"""
    return limit.max_total_bytes


def _total_budget_error(max_total: int) -> ArchiveError:
    """生成包含预算、原因和处理建议的总量超限错误。"""
    return ArchiveError(f"解压总量超限：单包解压上限 {format_bytes(max_total)}；请减少包内容或拆分数据包")


def _safe_target(root: Path, member_path: str) -> Path:
    if PureWindowsPath(member_path).is_absolute() or PurePosixPath(member_path).is_absolute():
        raise ArchiveError(f"路径穿越被拒绝: {member_path}")
    target = (root / member_path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ArchiveError(f"路径穿越被拒绝: {member_path}")
    return target


def _is_link(name: str) -> bool:
    return name.startswith(("symlink", "link")) or "->" in name


def _path_depth(member_path: str) -> int:
    """返回归一化前的成员路径深度，用于一致限制 zip/tar 嵌套层级。"""
    return len([part for part in PureWindowsPath(member_path.replace("\\", "/")).parts if part not in {"", "."}])


def _member_key(member_path: str) -> str:
    """归一化 zip/tar 常见的 POSIX 与 Windows 分隔符，用于重复路径检测。"""
    return PureWindowsPath(member_path.replace("\\", "/")).as_posix()


def _ensure_target_paths(target: Path, member_path: str) -> None:
    """拒绝压缩包内部同名与文件/目录位置冲突。"""
    if target.exists():
        raise ArchiveError(f"重复路径被拒绝: {member_path}")
    if target.parent.exists() and not target.parent.is_dir():
        raise ArchiveError(f"路径冲突被拒绝: {member_path}")


def _validate_zip(member: zipfile.ZipInfo, limit: UnpackLimit) -> None:
    if member.is_dir():
        return
    unix_mode = (member.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(unix_mode) or _is_link(member.filename):
        raise ArchiveError(f"链接文件被拒绝: {member.filename}")
    if member.file_size > limit.max_single_file:
        raise ArchiveError(f"单文件超限: {member.filename}")


def unpack_zip(archive: Path, root: Path, limit: UnpackLimit | None = None) -> int:
    limit = limit or UnpackLimit()
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    max_total = _expansion_budget(limit)
    total_written = 0
    try:
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) > limit.max_files:
                raise ArchiveError(f"文件数超限: {len(members)}")
            member_names: set[str] = set()
            for member in members:
                key = _member_key(member.filename)
                if key in member_names:
                    raise ArchiveError(f"重复路径被拒绝: {member.filename}")
                member_names.add(key)
                _validate_zip(member, limit)
                depth = _path_depth(member.filename)
                if depth > limit.max_depth:
                    raise ArchiveError(f"嵌套深度超限: {member.filename}")
                target = _safe_target(root, member.filename)
                _ensure_target_paths(target, member.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    written = 0
                    while chunk := src.read(1024 * 1024):
                        written += len(chunk)
                        total_written += len(chunk)
                        if written > limit.max_single_file:
                            raise ArchiveError(f"解压单文件超限: {member.filename}")
                        if total_written > max_total:
                            raise _total_budget_error(max_total)
                        dst.write(chunk)
                count += 1
    except (zipfile.BadZipFile, zlib.error, OSError) as exc:
        raise ArchiveError(f"压缩包读取失败: {archive.name}") from exc
    return count


def _validate_tar(member: tarfile.TarInfo, limit: UnpackLimit) -> None:
    if member.isdir():
        return
    if member.issym() or member.islnk():
        raise ArchiveError(f"链接文件被拒绝: {member.name}")
    if member.size > limit.max_single_file:
        raise ArchiveError(f"单文件超限: {member.name}")


def unpack_tar(archive: Path, root: Path, limit: UnpackLimit | None = None) -> int:
    limit = limit or UnpackLimit()
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    max_total = _expansion_budget(limit)
    total_written = 0
    try:
        with tarfile.open(archive, "r:*") as tf:
            members = [m for m in tf.getmembers() if not m.isdir()]
            if len(members) > limit.max_files:
                raise ArchiveError(f"文件数超限: {len(members)}")
            member_names: set[str] = set()
            for member in members:
                key = _member_key(member.name)
                if key in member_names:
                    raise ArchiveError(f"重复路径被拒绝: {member.name}")
                member_names.add(key)
                _validate_tar(member, limit)
                depth = _path_depth(member.name)
                if depth > limit.max_depth:
                    raise ArchiveError(f"嵌套深度超限: {member.name}")
                target = _safe_target(root, member.name)
                _ensure_target_paths(target, member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src, target.open("wb") as dst:
                    written = 0
                    while chunk := src.read(1024 * 1024):
                        written += len(chunk)
                        total_written += len(chunk)
                        if written > limit.max_single_file:
                            raise ArchiveError(f"解压单文件超限: {member.name}")
                        if total_written > max_total:
                            raise _total_budget_error(max_total)
                        dst.write(chunk)
                count += 1
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveError(f"压缩包读取失败: {archive.name}") from exc
    return count


def unpack_gzip(
    archive: Path,
    target: Path,
    limit: UnpackLimit | None = None,
    charge: Callable[[int], None] | None = None,
) -> int:
    """受控流式展开单个 gzip 文件，返回输出字节数。"""
    limit = limit or UnpackLimit()
    target = _safe_target(target.parent, target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with gzip.open(archive, "rb") as src, target.open("xb") as dst:
            while chunk := src.read(1024 * 1024):
                total += len(chunk)
                if charge is not None:
                    charge(len(chunk))
                if total > limit.max_single_file:
                    raise ArchiveError(f"解压单文件超限: {archive.name}")
                dst.write(chunk)
    except (OSError, EOFError, zlib.error) as exc:
        target.unlink(missing_ok=True)
        raise ArchiveError(f"gzip 解压失败: {archive.name}") from exc
    return total


def is_archive(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".log.gz"):
        return False
    return path.suffix.lower() in {".zip", ".tar", ".gz", ".tgz"} or name.endswith(".tar.gz")


def unpack(archive: Path, root: Path, limit: UnpackLimit | None = None) -> int:
    name = archive.name.lower()
    if name.endswith(".zip"):
        return unpack_zip(archive, root, limit)
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        return unpack_tar(archive, root, limit)
    raise ArchiveError(f"不支持的压缩格式: {archive.name}")


def archive_bytes(path: Path) -> bytes:
    """读取小压缩包字节（用于子包登记与嗅探）。"""
    return path.read_bytes()


def peek_zip_members(archive: Path, limit: int = 20) -> list[str]:
    """读取 zip 内部文件名（前 limit 个），用于内容嗅探。"""
    with zipfile.ZipFile(archive) as zf:
        return [m.filename for m in zf.infolist()[:limit]]


def peek_tar_members(archive: Path, limit: int = 20) -> list[str]:
    with tarfile.open(archive, "r:*") as tf:
        return [m.name for m in tf.getmembers()[:limit]]


def peek_members(archive: Path, limit: int = 20) -> list[str]:
    name = archive.name.lower()
    if name.endswith(".zip"):
        return peek_zip_members(archive, limit)
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        return peek_tar_members(archive, limit)
    return []
