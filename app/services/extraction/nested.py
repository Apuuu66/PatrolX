"""子压缩包与日志 gzip 的有界递归展开。"""

import shutil
import tempfile
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from app.core.archive import (
    ArchiveError,
    UnpackLimit,
    _normalize_member_path,
    unpack,
    unpack_gzip,
)
from app.services.extraction.audit import MEMBER_NOT_SELECTED
from app.services.extraction.config import SelectionExclude, SelectionInclude


@dataclass(frozen=True, slots=True)
class ExpandedArchiveMemberError:
    """单个展开成员失败及其安全相对路径。"""

    member_relative: str | None
    error: ArchiveError


@dataclass(frozen=True, slots=True)
class ExpandedArchiveMembers:
    """单层安全展开后的普通成员及成员级错误。"""

    files: tuple[Path, ...]
    member_errors: tuple[ExpandedArchiveMemberError, ...]


@dataclass(frozen=True, slots=True)
class SelectedArchiveMember:
    """按配置选中的归档成员及其最终相对路径。"""

    path: Path
    member_relative: str
    service: str | None


@dataclass(frozen=True, slots=True)
class IgnoredArchiveMember:
    """未选或明确排除的归档成员及稳定原因。"""

    member_relative: str
    reason: str


@dataclass(frozen=True, slots=True)
class SelectedArchiveMembers:
    """一次成员选择、GZIP 解压后的成功项与审计项。"""

    files: tuple[SelectedArchiveMember, ...]
    ignored: tuple[IgnoredArchiveMember, ...]
    member_errors: tuple[ExpandedArchiveMemberError, ...]


_RECURSIVE_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip", ".tar")
_UNSUPPORTED_ARCHIVE_SUFFIXES = (
    ".tar.bz",
    ".tar.bz2",
    ".tar.lz",
    ".tar.lzma",
    ".tar.xz",
    ".tar.zst",
    ".tbz",
    ".tbz2",
    ".rar",
    ".7z",
    ".bz2",
    ".xz",
    ".zst",
)


def _safe_member_relative(error: ArchiveError) -> str | None:
    """从解压错误中提取可用于审计的安全成员相对路径。"""
    raw_path = error.details.get("member_path")
    if not isinstance(raw_path, str):
        return None
    try:
        _parts, canonical = _normalize_member_path(raw_path)
    except ArchiveError:
        return None
    return canonical


def expand_archive_members(
    archive: Path,
    staging_root: Path,
    limit: UnpackLimit | None = None,
) -> ExpandedArchiveMembers:
    """安全展开单个归档；成员只落 staging，不按名称或内容二次分类。"""
    member_errors: list[ExpandedArchiveMemberError] = []

    def record_member_error(error: ArchiveError) -> None:
        member_errors.append(
            ExpandedArchiveMemberError(
                member_relative=_safe_member_relative(error),
                error=error,
            )
        )

    unpack(archive, staging_root, limit=limit, on_member_error=record_member_error)
    files = sorted(
        (path for path in staging_root.rglob("*") if path.is_file() and not path.is_symlink()),
        key=lambda path: path.relative_to(staging_root).as_posix(),
    )
    return ExpandedArchiveMembers(files=tuple(files), member_errors=tuple(member_errors))


def _is_recursive_archive(path: Path) -> bool:
    """判断文件是否属于 expand_recursive 支持的归档格式。"""
    return path.name.casefold().endswith(_RECURSIVE_ARCHIVE_SUFFIXES)


def _is_single_file_gzip(path: Path) -> bool:
    """识别普通 GZIP；TAR.GZ 仍按归档处理。"""
    name = path.name.casefold()
    return name.endswith(".gz") and not name.endswith(".tar.gz")


def _is_unsupported_archive(path: Path) -> bool:
    """识别明确的归档后缀，避免把不支持的归档静默当作普通文件落位。"""
    return path.name.casefold().endswith(_UNSUPPORTED_ARCHIVE_SUFFIXES)


def is_recursive_archive_source(path: Path) -> bool:
    """判断来源是否必须交给告警递归展开，包括需要局部报错的不支持格式。"""
    return _is_recursive_archive(path) or _is_single_file_gzip(path) or _is_unsupported_archive(path)


def _gzip_output_relative(member_relative: str) -> str:
    """把 GZIP 来源路径去掉最后一层 ``.gz``，并保持安全相对路径。"""
    parts, canonical = _normalize_member_path(member_relative)
    if not canonical.casefold().endswith(".gz") or canonical.casefold().endswith(".tar.gz"):
        raise ArchiveError(f"不支持的 GZIP 路径: {member_relative}", "archive_corrupt")
    parts[-1] = parts[-1][:-3]
    if not parts[-1]:
        raise ArchiveError(f"GZIP 输出路径为空: {member_relative}", "unsafe_path")
    return "/".join(parts)


def _member_pattern_matches(pattern: str, member_relative: str) -> bool:
    """按目录段和最后一段文件 glob 匹配成员，且大小写不敏感。"""
    pattern_parts = tuple(part.strip().casefold() for part in pattern.split("/") if part.strip())
    _parts, canonical = _normalize_member_path(member_relative)
    actual_parts = tuple(part.casefold() for part in canonical.split("/"))
    if not pattern_parts:
        return False

    def match(pattern_index: int, actual_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return actual_index == len(actual_parts)
        segment = pattern_parts[pattern_index]
        if segment == "**":
            if pattern_index == len(pattern_parts) - 1:
                return actual_index < len(actual_parts)
            return match(pattern_index + 1, actual_index) or (
                actual_index < len(actual_parts) and match(pattern_index, actual_index + 1)
            )
        if actual_index >= len(actual_parts):
            return False
        if pattern_index == len(pattern_parts) - 1:
            return actual_index == len(actual_parts) - 1 and fnmatchcase(
                actual_parts[actual_index],
                segment,
            )
        return actual_parts[actual_index] == segment and match(pattern_index + 1, actual_index + 1)

    return match(0, 0)


def _selected_include(
    member_relative: str,
    include: tuple[SelectionInclude, ...],
) -> SelectionInclude | None:
    """返回唯一 include；不同 service 的重叠配置视为配置错误，不静默取一条。"""
    matches = [item for item in include if _member_pattern_matches(item.pattern, member_relative)]
    if not matches:
        return None
    services = {item.service for item in matches}
    if len(services) > 1:
        raise ArchiveError(
            f"成员同时命中不同 service 的 include: {member_relative}",
            "invalid_classification_config",
        )
    return matches[0]


def _decompress_member_gzip(
    member: Path,
    staging_root: Path,
    member_relative: str,
    limit: UnpackLimit,
) -> tuple[Path, str]:
    """解压单个入选 GZIP 一层，返回去掉 .gz 后的路径和相对路径。"""
    output_relative = _gzip_output_relative(member_relative)
    target = staging_root / output_relative
    try:
        unpack_gzip(member, target, limit=limit)
        member.unlink()
    except ArchiveError:
        raise
    except OSError as exc:
        raise ArchiveError(f"GZIP 成员解压失败: {member_relative}", "unsafe_path") from exc
    return target, output_relative


def select_and_decompress(
    archive: Path,
    staging_root: Path,
    *,
    include: tuple[SelectionInclude, ...],
    exclude: tuple[SelectionExclude, ...],
    limit: UnpackLimit | None = None,
) -> SelectedArchiveMembers:
    """安全展开归档，先排除后选择，并仅解压入选的单文件 GZIP。"""
    active_limit = limit or UnpackLimit()
    expanded = expand_archive_members(archive, staging_root, limit=active_limit)
    selected: list[SelectedArchiveMember] = []
    ignored: list[IgnoredArchiveMember] = []
    member_errors = list(expanded.member_errors)

    for member in expanded.files:
        member_relative = member.relative_to(staging_root).as_posix()
        exclusion = next(
            (item for item in exclude if _member_pattern_matches(item.pattern, member_relative)),
            None,
        )
        if exclusion is not None:
            ignored.append(IgnoredArchiveMember(member_relative=member_relative, reason=exclusion.reason))
            continue
        selected_include = _selected_include(member_relative, include)
        if selected_include is None:
            ignored.append(IgnoredArchiveMember(member_relative=member_relative, reason=MEMBER_NOT_SELECTED))
            continue
        try:
            if _is_single_file_gzip(member):
                member, member_relative = _decompress_member_gzip(
                    member,
                    staging_root,
                    member_relative,
                    active_limit,
                )
        except ArchiveError as exc:
            member_errors.append(
                ExpandedArchiveMemberError(
                    member_relative=member_relative,
                    error=exc,
                )
            )
            continue
        selected.append(
            SelectedArchiveMember(
                path=member,
                member_relative=member_relative,
                service=selected_include.service,
            )
        )

    return SelectedArchiveMembers(
        files=tuple(selected),
        ignored=tuple(ignored),
        member_errors=tuple(member_errors),
    )


def decompress_matching_members(
    files: tuple[Path, ...],
    staging_root: Path,
    *,
    patterns: tuple[str, ...],
    limit: UnpackLimit | None = None,
) -> ExpandedArchiveMembers:
    """对 expand 路线的匹配成员 GZIP 解压；失败文件不进入最终落位集合。"""
    active_limit = limit or UnpackLimit()
    output: list[Path] = []
    member_errors: list[ExpandedArchiveMemberError] = []
    for member in sorted(files, key=lambda path: path.relative_to(staging_root).as_posix()):
        member_relative = member.relative_to(staging_root).as_posix()
        if _is_single_file_gzip(member) and any(
            _member_pattern_matches(pattern, member_relative) for pattern in patterns
        ):
            try:
                member, _output_relative = _decompress_member_gzip(
                    member,
                    staging_root,
                    member_relative,
                    active_limit,
                )
            except ArchiveError as exc:
                member_errors.append(
                    ExpandedArchiveMemberError(
                        member_relative=member_relative,
                        error=exc,
                    )
                )
                continue
        output.append(member)
    return ExpandedArchiveMembers(files=tuple(output), member_errors=tuple(member_errors))


def _prefix_member_path(prefix: Path, member_relative: str | None) -> str | None:
    """把嵌套成员路径拼接到其所在归档的父目录。"""
    prefix_text = "" if prefix == Path(".") else prefix.as_posix()
    if not prefix_text:
        return member_relative
    if member_relative is None:
        return prefix_text
    return f"{prefix_text}/{member_relative}"


def _recursive_files(root: Path) -> tuple[Path, ...]:
    """返回递归展开后仍存在的普通文件，排除链接。"""
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file() and not path.is_symlink()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def _expand_nested_archives(
    root: Path,
    *,
    depth: int,
    limit: UnpackLimit,
    member_errors: list[ExpandedArchiveMemberError],
) -> None:
    """递归展开当前输出根内的嵌套归档；单个成员失败不阻断其他文件。"""
    for child in _recursive_files(root):
        if not (_is_recursive_archive(child) or _is_single_file_gzip(child) or _is_unsupported_archive(child)):
            continue
        child_relative = child.relative_to(root)
        if _is_unsupported_archive(child):
            member_errors.append(
                ExpandedArchiveMemberError(
                    member_relative=child_relative.as_posix(),
                    error=ArchiveError(f"不支持的压缩格式: {child.name}", "archive_corrupt"),
                )
            )
            child.unlink(missing_ok=True)
            continue
        if depth + 1 > limit.max_depth:
            member_errors.append(
                ExpandedArchiveMemberError(
                    member_relative=child_relative.as_posix(),
                    error=ArchiveError(
                        f"嵌套归档深度超限: {child.name}",
                        "archive_depth_exceeded",
                        depth=depth + 1,
                        limit=limit.max_depth,
                    ),
                )
            )
            child.unlink(missing_ok=True)
            continue

        with tempfile.TemporaryDirectory(prefix=".recursive-expand-", dir=root) as temporary:
            nested_root = Path(temporary)
            nested = _expand_recursive_tree(
                child,
                nested_root,
                gzip_member_relative=None,
                error_member_relative=child.name,
                depth=depth + 1,
                limit=limit,
            )
            for nested_error in nested.member_errors:
                member_errors.append(
                    ExpandedArchiveMemberError(
                        member_relative=_prefix_member_path(child_relative.parent, nested_error.member_relative),
                        error=nested_error.error,
                    )
                )
            destination_root = root / child_relative.parent
            for nested_file in nested.files:
                nested_relative = nested_file.relative_to(nested_root)
                destination = destination_root / nested_relative
                destination_member = _prefix_member_path(child_relative.parent, nested_relative.as_posix())
                try:
                    if destination.exists():
                        raise ArchiveError(f"嵌套归档成员目标已存在: {destination_member}", "target_conflict")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(nested_file), destination)
                except (ArchiveError, OSError) as exc:
                    error = (
                        exc
                        if isinstance(exc, ArchiveError)
                        else ArchiveError(
                            f"嵌套归档成员写入失败: {exc}",
                            "unsafe_path",
                        )
                    )
                    member_errors.append(
                        ExpandedArchiveMemberError(
                            member_relative=destination_member,
                            error=error,
                        )
                    )
        child.unlink(missing_ok=True)


def _expand_recursive_tree(
    source: Path,
    output_root: Path,
    *,
    gzip_member_relative: str | None,
    error_member_relative: str | None,
    depth: int,
    limit: UnpackLimit,
) -> ExpandedArchiveMembers:
    """递归展开一个来源，返回最终普通文件和组合后的成员错误。"""
    output_root.mkdir(parents=True, exist_ok=True)
    member_errors: list[ExpandedArchiveMemberError] = []

    if _is_single_file_gzip(source):
        gzip_relative = gzip_member_relative or source.name
        try:
            output_relative = _gzip_output_relative(gzip_relative)
            target = output_root / output_relative
            unpack_gzip(source, target, limit=limit)
        except ArchiveError as exc:
            member_errors.append(
                ExpandedArchiveMemberError(
                    member_relative=gzip_relative,
                    error=exc,
                )
            )
        except OSError as exc:
            member_errors.append(
                ExpandedArchiveMemberError(
                    member_relative=gzip_relative,
                    error=ArchiveError(f"GZIP 输出失败: {exc}", "unsafe_path"),
                )
            )
        else:
            _expand_nested_archives(
                output_root,
                depth=depth,
                limit=limit,
                member_errors=member_errors,
            )
        return ExpandedArchiveMembers(files=_recursive_files(output_root), member_errors=tuple(member_errors))

    if not _is_recursive_archive(source):
        member_errors.append(
            ExpandedArchiveMemberError(
                member_relative=error_member_relative,
                error=ArchiveError(f"不支持的压缩格式: {source.name}", "archive_corrupt"),
            )
        )
        return ExpandedArchiveMembers(files=(), member_errors=tuple(member_errors))

    def record_member_error(error: ArchiveError) -> None:
        member_errors.append(
            ExpandedArchiveMemberError(
                member_relative=_safe_member_relative(error),
                error=error,
            )
        )

    try:
        unpack(source, output_root, limit=limit, on_member_error=record_member_error)
    except ArchiveError as exc:
        member_errors.append(
            ExpandedArchiveMemberError(
                member_relative=error_member_relative,
                error=exc,
            )
        )
    else:
        _expand_nested_archives(
            output_root,
            depth=depth,
            limit=limit,
            member_errors=member_errors,
        )
    return ExpandedArchiveMembers(files=_recursive_files(output_root), member_errors=tuple(member_errors))


def expand_recursive(
    source: Path,
    staging_root: Path,
    *,
    source_member_relative: str | None = None,
    limit: UnpackLimit | None = None,
) -> ExpandedArchiveMembers:
    """递归展开告警归档和 GZIP，返回去掉归档外层后的安全成员路径。"""
    active_limit = limit or UnpackLimit()
    staging_root.mkdir(parents=True, exist_ok=True)
    return _expand_recursive_tree(
        source,
        staging_root,
        gzip_member_relative=source_member_relative,
        error_member_relative=None,
        depth=0,
        limit=active_limit,
    )
