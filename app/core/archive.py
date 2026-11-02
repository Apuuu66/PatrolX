"""安全解压：路径穿越、符号链接与解压炸弹防护。"""

from __future__ import annotations

import gzip
import re
import stat
import struct
import tarfile
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath


class ArchiveError(Exception):
    """压缩包解析错误；error_code 是调用方唯一应依赖的稳定标识。"""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        **details: object,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details


MemberErrorHandler = Callable[[ArchiveError], None]


class PathTooLongError(ArchiveError):
    """目标完整路径超过当前操作系统生效限制。"""

    def __init__(self, path: str, length: int, limit: int) -> None:
        self.path = path
        self.length = length
        self.limit = limit
        message = f"目标路径长度 {length} 超过限制 {limit}: {path}"
        super().__init__(message, "unsafe_path", path=path, length=length, limit=limit)


class UnpackLimit:
    """解压安全限制（默认值固定，不提供任务级配置入口）。"""

    max_depth: int = 8
    max_member_path_depth: int = 12
    max_files: int = 100_000
    max_single_file: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    max_total_bytes: int = 3 * 1024 * 1024 * 1024  # 3 GiB


def format_bytes(size: int) -> str:
    """将字节数格式化为用户可读的容量。"""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _expansion_budget(limit: UnpackLimit) -> int:
    """返回当前单归档允许写入的最大总字节数。"""
    return limit.max_total_bytes


def _total_budget_error(max_total: int) -> ArchiveError:
    """生成包含预算、原因和处理建议的总量超限错误。"""
    message = f"解压总量超限：单包解压上限 {format_bytes(max_total)}；请减少包内容或拆分数据包"
    return ArchiveError(message, "total_bytes_exceeded", limit=max_total)


def _normalize_member_path(member_path: str) -> tuple[list[str], str]:
    """严格规范化成员路径，并在源头拒绝绝对路径、穿越和危险段。"""
    if not isinstance(member_path, str):
        raise ArchiveError("成员路径必须是字符串", "unsafe_path")
    if "\x00" in member_path:
        raise ArchiveError(f"成员路径包含 NUL: {member_path!r}", "unsafe_path")

    candidate = member_path.strip()
    if not candidate:
        raise ArchiveError("成员路径不能为空", "unsafe_path")
    if candidate.startswith(("/", "\\")):
        raise ArchiveError(f"成员路径不得是绝对路径: {member_path}", "unsafe_path")
    if re.match(r"[A-Za-z]:", candidate):
        raise ArchiveError(f"成员路径不得使用 Windows 盘符: {member_path}", "unsafe_path")

    # 归档成员中的反斜杠统一按目录分隔符处理，避免 Windows 风格路径绕过校验。
    normalized = candidate.replace("\\", "/")
    parts: list[str] = []
    for raw_part in normalized.split("/"):
        part = raw_part.strip()
        if not part:
            raise ArchiveError(f"成员路径不得包含空段: {member_path}", "unsafe_path")
        if part == ".":
            continue
        if part == "..":
            raise ArchiveError(f"成员路径不得包含父目录跳转: {member_path}", "unsafe_path")
        parts.append(part)

    if not parts:
        raise ArchiveError(f"成员路径不能为空: {member_path}", "unsafe_path")
    return parts, "/".join(parts)


def _member_key(canonical_path: str) -> str:
    """对大小写归一，确保不同大小写路径不会绕过重复成员检测。"""
    return canonical_path.casefold()


def _resolve_member_target(root: Path, parts: list[str], member_path: str) -> Path:
    """解析成员目标并确认其仍位于归档输出根内。"""
    if root.is_symlink():
        raise ArchiveError(f"目标路径包含链接: {member_path}", "link_rejected")

    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ArchiveError(f"目标路径包含链接: {member_path}", "link_rejected")

    root_resolved = root.resolve()
    target = current
    target_resolved = target.resolve()
    if not target_resolved.is_relative_to(root_resolved):
        raise ArchiveError(f"路径穿越被拒绝: {member_path}", "unsafe_path")
    return target


def _ensure_target_paths(target: Path, member_path: str) -> None:
    """拒绝已有目标、链接目标以及文件和目录位置冲突。"""
    if target.is_symlink():
        raise ArchiveError(f"目标路径是链接: {member_path}", "link_rejected")
    if target.exists():
        raise ArchiveError(f"目标路径已存在: {member_path}", "duplicate_member")
    if target.parent.exists() and not target.parent.is_dir():
        raise ArchiveError(f"目标父路径不是目录: {member_path}", "unsafe_path")


def _read_at(fp, offset: int, size: int) -> bytes:
    """从指定偏移读取定长字节；截断时按归档损坏处理。"""
    fp.seek(offset)
    payload = fp.read(size)
    if len(payload) != size:
        raise ArchiveError(f"压缩包读取失败: {fp.name}", "archive_corrupt")
    return payload


def _zip64_central_directory(fp, tail: bytes, archive_size: int) -> tuple[int, int]:
    """读取 ZIP64 中央目录偏移和大小。"""
    locator_pos = tail.rfind(b"PK\x06\x07")
    if locator_pos < 0:
        raise ArchiveError(f"压缩包读取失败: {fp.name}", "archive_corrupt")
    locator = tail[locator_pos : locator_pos + 20]
    if len(locator) < 20:
        raise ArchiveError(f"压缩包读取失败: {fp.name}", "archive_corrupt")
    zip64_eocd_offset = struct.unpack_from("<Q", locator, 8)[0]
    zip64_eocd = _read_at(fp, zip64_eocd_offset, 56)
    if zip64_eocd[:4] != b"PK\x06\x06":
        raise ArchiveError(f"压缩包读取失败: {fp.name}", "archive_corrupt")
    cd_size = struct.unpack_from("<Q", zip64_eocd, 40)[0]
    cd_offset = struct.unpack_from("<Q", zip64_eocd, 48)[0]
    if cd_offset > archive_size or cd_size > archive_size - cd_offset:
        raise ArchiveError(f"压缩包读取失败: {fp.name}", "archive_corrupt")
    return cd_size, cd_offset


def _reject_unsafe_zip_raw_names(archive: Path) -> None:
    """扫描中央目录原始成员名，拒绝标准库会在 NUL 处截断的路径。"""
    with archive.open("rb") as fp:
        fp.seek(0, 2)
        archive_size = fp.tell()
        tail_size = min(archive_size, 65557)
        fp.seek(archive_size - tail_size)
        tail = fp.read(tail_size)
        eocd_pos = tail.rfind(b"PK\x05\x06")
        if eocd_pos < 0:
            raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt")
        eocd = tail[eocd_pos : eocd_pos + 22]
        if len(eocd) < 22:
            raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt")
        cd_size = struct.unpack_from("<I", eocd, 12)[0]
        cd_offset = struct.unpack_from("<I", eocd, 16)[0]
        if cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
            cd_size, cd_offset = _zip64_central_directory(fp, tail, archive_size)
        elif cd_offset > archive_size or cd_size > archive_size - cd_offset:
            raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt")

        fp.seek(cd_offset)
        consumed = 0
        while consumed < cd_size:
            header = fp.read(46)
            if len(header) < 46 or header[:4] != b"PK\x01\x02":
                raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt")
            name_length, extra_length, comment_length = struct.unpack_from("<HHH", header, 28)
            raw_name = fp.read(name_length)
            if len(raw_name) != name_length:
                raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt")
            if b"\x00" in raw_name:
                raise ArchiveError(f"成员路径包含 NUL: {raw_name!r}", "unsafe_path")
            next_entry = cd_offset + consumed + 46 + name_length + extra_length + comment_length
            if fp.seek(extra_length + comment_length, 1) != next_entry:
                raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt")
            consumed += 46 + name_length + extra_length + comment_length
        if consumed != cd_size:
            raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt")


def _zip_member_is_directory(member: zipfile.ZipInfo) -> bool:
    """识别带或不带结尾斜杠的 ZIP 目录成员。"""
    if member.is_dir():
        return True
    if member.create_system == 3:
        unix_mode = (member.external_attr >> 16) & 0xFFFF
        return stat.S_ISDIR(unix_mode)
    return False


def _validate_zip_member(
    member: zipfile.ZipInfo,
    limit: UnpackLimit,
) -> tuple[list[str], str] | None:
    """校验 ZIP 成员路径和类型；目录成员只做安全检查，不计入文件数。"""
    is_directory = _zip_member_is_directory(member)
    display_name = member.filename.rstrip("/\\") if is_directory else member.filename
    parts, canonical = _normalize_member_path(display_name)

    if member.create_system == 3:
        unix_mode = (member.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(unix_mode):
            raise ArchiveError(f"链接文件被拒绝: {member.filename}", "link_rejected")
        member_type = stat.S_IFMT(unix_mode)
        if not is_directory and member_type not in (0, stat.S_IFREG):
            raise ArchiveError(f"不支持的 ZIP 成员类型: {member.filename}", "unsafe_path")

    if len(parts) > limit.max_member_path_depth:
        message = f"成员路径深度超限: {member.filename}"
        raise ArchiveError(message, "member_path_depth_exceeded", depth=len(parts))

    if is_directory:
        return None
    return parts, canonical


def _validate_zip_metadata(member: zipfile.ZipInfo, limit: UnpackLimit) -> None:
    """在展开前根据 ZIP 元数据检查单文件大小。"""
    if member.file_size > limit.max_single_file:
        message = f"单文件超限: {member.filename}"
        raise ArchiveError(message, "file_too_large", size=member.file_size, limit=limit.max_single_file)


def _record_member_error(
    handler: MemberErrorHandler | None,
    error: ArchiveError,
) -> None:
    """记录单个成员错误；未提供记录器时保持整体抛出的兼容行为。"""
    if handler is None:
        raise error
    handler(error)


def _delete_partial_target(target: Path | None) -> None:
    """清理未完成成员；父路径不是目录时说明成员文件不可能存在。"""
    if target is not None and target.parent.is_dir():
        target.unlink(missing_ok=True)


def _prepare_archive_root(root: Path) -> Path:
    """在解析路径前拒绝根链接，并返回创建完成后的规范目录。"""
    if root.is_symlink():
        raise ArchiveError(f"归档输出根目录不得是链接: {root}", "link_rejected")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ArchiveError(f"归档输出根目录不得是链接: {root}", "link_rejected")
    return root.resolve()


def unpack_zip(
    archive: Path,
    root: Path,
    limit: UnpackLimit | None = None,
    path_limit_check: Callable[[Path, str], None] | None = None,
    on_member_error: MemberErrorHandler | None = None,
) -> int:
    """安全展开 ZIP，返回成功写入的普通文件数。"""
    limit = limit or UnpackLimit()
    root = _prepare_archive_root(root)
    count = 0
    max_total = _expansion_budget(limit)
    total_written = 0

    try:
        _reject_unsafe_zip_raw_names(archive)
        with zipfile.ZipFile(archive) as zf:
            members = zf.infolist()
            file_members = [member for member in members if not _zip_member_is_directory(member)]
            if len(file_members) > limit.max_files:
                message = f"文件数超限: {len(file_members)}"
                raise ArchiveError(message, "file_count_exceeded", count=len(file_members))

            prepared_members: list[tuple[zipfile.ZipInfo, list[str], str]] = []
            for member in members:
                try:
                    prepared = _validate_zip_member(member, limit)
                except ArchiveError as member_error:
                    _record_member_error(on_member_error, member_error)
                    continue
                if prepared is not None:
                    prepared_members.append((member, prepared[0], prepared[1]))

            seen_members: set[str] = set()
            for member, parts, canonical in prepared_members:
                target: Path | None = None
                member_written = 0
                try:
                    key = _member_key(canonical)
                    if key in seen_members:
                        raise ArchiveError(f"重复路径被拒绝: {member.filename}", "duplicate_member")
                    seen_members.add(key)

                    _validate_zip_metadata(member, limit)
                    if len(parts) > limit.max_member_path_depth:
                        message = f"成员路径深度超限: {member.filename}"
                        raise ArchiveError(message, "member_path_depth_exceeded", depth=len(parts))

                    target = _resolve_member_target(root, parts, member.filename)
                    if path_limit_check is not None:
                        path_limit_check(target, member.filename)
                    _ensure_target_paths(target, member.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, target.open("wb") as dst:
                        written = 0
                        while chunk := src.read(1024 * 1024):
                            written += len(chunk)
                            member_written = written
                            total_written += len(chunk)
                            if written > limit.max_single_file:
                                raise ArchiveError(f"解压单文件超限: {member.filename}", "file_too_large")
                            if total_written > max_total:
                                raise _total_budget_error(max_total)
                            dst.write(chunk)
                    count += 1
                except ArchiveError as member_error:
                    total_written -= member_written
                    _delete_partial_target(target)
                    _record_member_error(on_member_error, member_error)
                except (
                    zipfile.BadZipFile,
                    zlib.error,
                    OSError,
                    RuntimeError,
                    NotImplementedError,
                    struct.error,
                    EOFError,
                ) as exc:
                    total_written -= member_written
                    _delete_partial_target(target)
                    error = ArchiveError(
                        f"压缩包读取失败: {archive.name}",
                        "archive_corrupt",
                    )
                    error.__cause__ = exc
                    _record_member_error(on_member_error, error)
    except ArchiveError:
        raise
    except (
        zipfile.BadZipFile,
        zlib.error,
        OSError,
        RuntimeError,
        NotImplementedError,
        struct.error,
        EOFError,
    ) as exc:
        raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt") from exc
    return count


def _validate_tar_member(member: tarfile.TarInfo) -> tuple[list[str], str] | None:
    """校验 TAR 成员路径和类型；目录成员只做安全检查，不计入文件数。"""
    if member.issym() or member.islnk():
        raise ArchiveError(f"链接文件被拒绝: {member.name}", "link_rejected")

    display_name = member.name.rstrip("/\\") if member.isdir() else member.name
    parts, canonical = _normalize_member_path(display_name)
    if member.isdir():
        return None
    if not member.isreg():
        raise ArchiveError(f"不支持的 TAR 成员类型: {member.name}", "unsafe_path")
    return parts, canonical


def _validate_tar_metadata(member: tarfile.TarInfo, limit: UnpackLimit) -> None:
    """在展开前根据 TAR 元数据检查单文件大小。"""
    if member.size > limit.max_single_file:
        message = f"单文件超限: {member.name}"
        raise ArchiveError(message, "file_too_large", size=member.size, limit=limit.max_single_file)


def unpack_tar(
    archive: Path,
    root: Path,
    limit: UnpackLimit | None = None,
    path_limit_check: Callable[[Path, str], None] | None = None,
    on_member_error: MemberErrorHandler | None = None,
) -> int:
    """安全展开 TAR/TAR.GZ，返回成功写入的普通文件数。"""
    limit = limit or UnpackLimit()
    root = _prepare_archive_root(root)
    count = 0
    max_total = _expansion_budget(limit)
    total_written = 0

    try:
        with tarfile.open(archive, "r:*") as tf:
            members = tf.getmembers()
            file_members = [member for member in members if not member.isdir()]
            if len(file_members) > limit.max_files:
                message = f"文件数超限: {len(file_members)}"
                raise ArchiveError(message, "file_count_exceeded", count=len(file_members))

            prepared_members: list[tuple[tarfile.TarInfo, list[str], str]] = []
            for member in members:
                try:
                    prepared = _validate_tar_member(member)
                except ArchiveError as member_error:
                    _record_member_error(on_member_error, member_error)
                    continue
                if prepared is not None:
                    prepared_members.append((member, prepared[0], prepared[1]))

            seen_members: set[str] = set()
            for member, parts, canonical in prepared_members:
                target: Path | None = None
                member_written = 0
                try:
                    key = _member_key(canonical)
                    if key in seen_members:
                        raise ArchiveError(f"重复路径被拒绝: {member.name}", "duplicate_member")
                    seen_members.add(key)

                    _validate_tar_metadata(member, limit)
                    if len(parts) > limit.max_member_path_depth:
                        message = f"成员路径深度超限: {member.name}"
                        raise ArchiveError(message, "member_path_depth_exceeded", depth=len(parts))

                    target = _resolve_member_target(root, parts, member.name)
                    if path_limit_check is not None:
                        path_limit_check(target, member.name)
                    _ensure_target_paths(target, member.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(member)
                    if src is None:
                        raise ArchiveError(f"无法读取 TAR 成员: {member.name}", "archive_corrupt")
                    with src, target.open("wb") as dst:
                        written = 0
                        while chunk := src.read(1024 * 1024):
                            written += len(chunk)
                            member_written = written
                            total_written += len(chunk)
                            if written > limit.max_single_file:
                                raise ArchiveError(f"解压单文件超限: {member.name}", "file_too_large")
                            if total_written > max_total:
                                raise _total_budget_error(max_total)
                            dst.write(chunk)
                    count += 1
                except ArchiveError as member_error:
                    total_written -= member_written
                    _delete_partial_target(target)
                    _record_member_error(on_member_error, member_error)
                except (
                    tarfile.TarError,
                    zlib.error,
                    OSError,
                    RuntimeError,
                    NotImplementedError,
                    struct.error,
                    EOFError,
                ) as exc:
                    total_written -= member_written
                    _delete_partial_target(target)
                    error = ArchiveError(
                        f"压缩包读取失败: {archive.name}",
                        "archive_corrupt",
                    )
                    error.__cause__ = exc
                    _record_member_error(on_member_error, error)
    except ArchiveError:
        raise
    except (
        tarfile.TarError,
        zlib.error,
        OSError,
        RuntimeError,
        NotImplementedError,
        struct.error,
        EOFError,
    ) as exc:
        raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt") from exc
    return count


def unpack_gzip(
    archive: Path,
    target: Path,
    limit: UnpackLimit | None = None,
    charge: Callable[[int], None] | None = None,
    path_limit_check: Callable[[Path, str], None] | None = None,
) -> int:
    """受控流式展开单个 gzip 文件，返回输出字节数。"""
    limit = limit or UnpackLimit()
    if path_limit_check is not None:
        path_limit_check(target, target.name)

    parts, _canonical = _normalize_member_path(target.name)
    safe_target = _resolve_member_target(target.parent, parts, target.name)
    if safe_target.is_symlink() or any(parent.is_symlink() for parent in safe_target.parents):
        raise ArchiveError(f"目标路径是链接: {target.name}", "link_rejected")
    safe_target.parent.mkdir(parents=True, exist_ok=True)
    total = 0

    try:
        with gzip.open(archive, "rb") as src, safe_target.open("xb") as dst:
            while chunk := src.read(1024 * 1024):
                total += len(chunk)
                if charge is not None:
                    charge(len(chunk))
                if total > limit.max_single_file:
                    raise ArchiveError(f"解压单文件超限: {archive.name}", "file_too_large")
                dst.write(chunk)
    except ArchiveError:
        safe_target.unlink(missing_ok=True)
        raise
    except (OSError, EOFError, zlib.error) as exc:
        safe_target.unlink(missing_ok=True)
        code = "target_conflict" if isinstance(exc, FileExistsError) else "archive_corrupt"
        message = "目标文件已存在" if code == "target_conflict" else f"gzip 解压失败: {archive.name}"
        raise ArchiveError(message, code) from exc
    return total


def is_archive(path: Path) -> bool:
    """根据扩展名判断是否为需要受控展开的归档或压缩文件。"""
    name = path.name.lower()
    if name.endswith(".log.gz"):
        return False
    return path.suffix.lower() in {".zip", ".tar", ".gz", ".tgz"} or name.endswith(".tar.gz")


def unpack(
    archive: Path,
    root: Path,
    limit: UnpackLimit | None = None,
    path_limit_check: Callable[[Path, str], None] | None = None,
    on_member_error: MemberErrorHandler | None = None,
) -> int:
    """按扩展名分派到 ZIP 或 TAR 安全展开器。"""
    name = archive.name.lower()
    if name.endswith(".zip"):
        return unpack_zip(archive, root, limit, path_limit_check, on_member_error)
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        return unpack_tar(archive, root, limit, path_limit_check, on_member_error)
    raise ArchiveError(f"不支持的压缩格式: {archive.name}", "archive_corrupt")


def archive_bytes(path: Path) -> bytes:
    """读取小压缩包字节（用于子包登记）。"""
    return path.read_bytes()


def peek_zip_members(archive: Path, limit: int = 20) -> list[str]:
    """读取 zip 内部文件名（前 limit 个），用于旧链路的只读内容判断。"""
    try:
        _reject_unsafe_zip_raw_names(archive)
        with zipfile.ZipFile(archive) as zf:
            return [m.filename for m in zf.infolist()[:limit]]
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt") from exc


def peek_tar_members(archive: Path, limit: int = 20) -> list[str]:
    """读取 tar 内部文件名（前 limit 个），用于旧链路的只读内容判断。"""
    try:
        with tarfile.open(archive, "r:*") as tf:
            return [m.name for m in tf.getmembers()[:limit]]
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveError(f"压缩包读取失败: {archive.name}", "archive_corrupt") from exc


def peek_members(archive: Path, limit: int = 20) -> list[str]:
    """按扩展名读取归档成员名；不执行写入。"""
    name = archive.name.lower()
    if name.endswith(".zip"):
        return peek_zip_members(archive, limit)
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        return peek_tar_members(archive, limit)
    return []


# 兼容旧调用方对 POSIX 路径 helper 的导入；新代码应使用 _normalize_member_path。
__all__ = [
    "ArchiveError",
    "PathTooLongError",
    "UnpackLimit",
    "format_bytes",
    "unpack",
    "unpack_gzip",
    "unpack_tar",
    "unpack_zip",
    "PurePosixPath",
]
