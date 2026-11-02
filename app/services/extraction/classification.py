"""配置驱动的证据分类、场景根推导与安全落位。"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.archive import ArchiveError
from app.services.extraction.audit import (
    ConflictRecord,
    FailureRecord,
    IgnoredRecord,
    LandedEntry,
    make_conflict_record,
    make_failure_record,
    make_ignored_record,
    make_landed_entry,
    resolve_target,
)
from app.services.extraction.config import (
    ClassificationConfig,
    Route,
    load_classification_config,
)
from app.services.extraction.layout import destination_for_target
from app.services.extraction.manifest import sha256_file
from app.services.extraction.nested import expand_archive_members

_PHASE_ORDER = ("alarm", "precise", "ignore", "fallback")
_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip", ".tar", ".gz")


@dataclass(frozen=True, slots=True)
class SceneRoot:
    """当前 profile 推导出的场景根及命中的 anchor。"""

    relative_to_evidence: Path
    matched_anchors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """只允许普通规则读取的成功落位文件。"""

    path: str
    category: str
    route_id: str
    source_relative: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ClassificationRun:
    """一次分类运行的落位结果与完整审计集合。"""

    data_dir: Path
    scene_root: SceneRoot
    entries: tuple[LandedEntry, ...]
    ignored: tuple[IgnoredRecord, ...]
    conflicts: tuple[ConflictRecord, ...]
    failures: tuple[FailureRecord, ...]
    catalog: tuple[CatalogEntry, ...]


def _normalized_parts(path: Path) -> tuple[str, ...]:
    return () if path == Path(".") else path.parts


def _relative_to_scene(source_relative: Path, scene_relative: Path) -> Path | None:
    """按大小写不敏感目录段计算来源相对场景根的路径。"""
    source_parts = _normalized_parts(source_relative)
    scene_parts = _normalized_parts(scene_relative)
    if len(source_parts) < len(scene_parts):
        return None
    if any(
        source.casefold() != scene.casefold()
        for source, scene in zip(source_parts[: len(scene_parts)], scene_parts, strict=True)
    ):
        return None
    remainder = source_parts[len(scene_parts) :]
    return Path(*remainder) if remainder else Path(".")


def _common_parent(paths: list[Path]) -> Path:
    if not paths:
        return Path(".")
    common = list(_normalized_parts(paths[0]))
    for path in paths[1:]:
        parts = _normalized_parts(path)
        limit = min(len(common), len(parts))
        index = 0
        while index < limit and common[index].casefold() == parts[index].casefold():
            index += 1
        common = common[:index]
    return Path(*common) if common else Path(".")


def infer_scene_root(evidence_root: Path, anchors: tuple[str, ...]) -> SceneRoot:
    """以 profile anchor 父目录的最长公共父目录推导场景根。"""
    candidates: list[Path] = []
    matched: dict[str, str] = {}
    normalized_anchors = tuple((anchor, anchor.strip().casefold()) for anchor in anchors if anchor.strip())
    if not evidence_root.is_dir() or evidence_root.is_symlink():
        return SceneRoot(relative_to_evidence=Path("."), matched_anchors=())

    for source in sorted(evidence_root.rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        parent_parts = source.parent.relative_to(evidence_root).parts
        for anchor, normalized in normalized_anchors:
            for index, part in enumerate(parent_parts):
                if part.casefold() != normalized:
                    continue
                candidates.append(Path(*parent_parts[:index]) if index else Path("."))
                matched.setdefault(normalized, anchor.strip())
    return SceneRoot(
        relative_to_evidence=_common_parent(candidates),
        matched_anchors=tuple(sorted(matched.values())),
    )


def _directory_matches(pattern: str, actual: tuple[str, ...]) -> bool:
    pattern_parts = tuple(part.strip().casefold() for part in pattern.split("/") if part.strip())
    actual_parts = tuple(part.casefold() for part in actual)

    def match(pattern_index: int, actual_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return actual_index == len(actual_parts)
        segment = pattern_parts[pattern_index]
        if segment == "**":
            return match(pattern_index + 1, actual_index) or (
                actual_index < len(actual_parts) and match(pattern_index, actual_index + 1)
            )
        return (
            actual_index < len(actual_parts)
            and segment == actual_parts[actual_index]
            and match(pattern_index + 1, actual_index + 1)
        )

    return match(0, 0)


def _source_suffix(scope_relative: Path, capture_root: str | None) -> str | None:
    if capture_root is None:
        return scope_relative.as_posix()
    directory_parts = scope_relative.parent.parts
    normalized = capture_root.strip().casefold()
    matches = [index for index, part in enumerate(directory_parts) if part.casefold() == normalized]
    if not matches:
        return None
    suffix_parts = (*directory_parts[matches[-1] + 1 :], scope_relative.name)
    return Path(*suffix_parts).as_posix()


def _route_match(
    route: Route,
    *,
    source_relative: Path,
    scene_relative: Path | None,
) -> str | None:
    scope_relative = source_relative if route.source.scope == "evidence" else scene_relative
    if scope_relative is None:
        return None
    if not _directory_matches(route.source.directory, scope_relative.parent.parts):
        return None
    if not _file_matches(route.source.file, scope_relative.name):
        return None
    return _source_suffix(scope_relative, route.source.capture_root)


def _file_matches(pattern: str, filename: str) -> bool:
    from fnmatch import fnmatchcase

    return fnmatchcase(filename.casefold(), pattern.strip().casefold())


def _select_route(
    config: ClassificationConfig,
    *,
    profile: str,
    source_relative: Path,
    scene_relative: Path | None,
) -> tuple[Route, str] | None:
    for phase in _PHASE_ORDER:
        candidates = sorted(
            (route for route in config.routes if route.phase == phase and profile in route.profiles),
            key=lambda route: (-route.priority, route.id),
        )
        for route in candidates:
            suffix = _route_match(
                route,
                source_relative=source_relative,
                scene_relative=scene_relative,
            )
            if suffix is not None:
                return route, suffix
    return None


def _archive_stem(filename: str) -> str:
    lowered = filename.casefold()
    for suffix in _ARCHIVE_SUFFIXES:
        if lowered.endswith(suffix):
            return filename[: -len(suffix)]
    return Path(filename).stem


def _render_target(route: Route, **values: str) -> str:
    target = route.target
    if target is None:
        raise ValueError("非 ignore route 缺少 target")
    rendered = target
    for name, value in values.items():
        rendered = rendered.replace(f"{{{name}}}", value)
    return rendered


def _failure(
    *,
    source_relative: Path,
    route: Route,
    error_code: str,
    reason: str,
    member_relative: str | None = None,
) -> FailureRecord:
    return make_failure_record(
        source_relative=source_relative.as_posix(),
        member_relative=member_relative,
        route_id=route.id,
        category=route.category,
        action=route.action,
        error_code=error_code,
        reason=reason,
    )


def _available_destination(
    data_dir: Path,
    *,
    original_target: str,
    product: str | None,
    source_relative: Path,
    member_relative: str,
    used_targets: set[str],
) -> tuple[str, str, Path]:
    target, digest = resolve_target(
        original_target=original_target,
        product=product,
        source_relative=source_relative.as_posix(),
        member_relative=member_relative,
        used_targets=used_targets,
    )
    destination = destination_for_target(data_dir, target)
    while destination.exists():
        used_targets.add(target)
        target, digest = resolve_target(
            original_target=original_target,
            product=product,
            source_relative=source_relative.as_posix(),
            member_relative=member_relative,
            used_targets=used_targets,
        )
        destination = destination_for_target(data_dir, target)
    return target, digest, destination


def _land_copy(
    *,
    source: Path,
    source_relative: Path,
    route: Route,
    suffix: str,
    data_dir: Path,
    product: str | None,
    used_targets: set[str],
) -> tuple[LandedEntry, ConflictRecord | None]:
    original_target = _render_target(route, suffix=suffix)
    target, digest, destination = _available_destination(
        data_dir,
        original_target=original_target,
        product=product,
        source_relative=source_relative,
        member_relative="",
        used_targets=used_targets,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    entry = make_landed_entry(
        source_relative=source_relative.as_posix(),
        member_relative=None,
        route_id=route.id,
        product=product,
        category=route.category or "other",
        original_target=original_target,
        target=target,
        action=route.action,
        sha256=sha256_file(destination),
        size=destination.stat().st_size,
    )
    used_targets.add(target)
    conflict = make_conflict_record(entry, digest) if target != original_target else None
    return entry, conflict


def _land_member(
    *,
    member: Path,
    source_relative: Path,
    member_relative: str,
    route: Route,
    data_dir: Path,
    product: str | None,
    used_targets: set[str],
) -> tuple[LandedEntry, ConflictRecord | None]:
    original_target = _render_target(
        route,
        member=member_relative,
        archive_stem=_archive_stem(source_relative.name),
    )
    target, digest, destination = _available_destination(
        data_dir,
        original_target=original_target,
        product=product,
        source_relative=source_relative,
        member_relative=member_relative,
        used_targets=used_targets,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(member, destination)
    entry = make_landed_entry(
        source_relative=source_relative.as_posix(),
        member_relative=member_relative,
        route_id=route.id,
        product=product,
        category=route.category or "other",
        original_target=original_target,
        target=target,
        action=route.action,
        sha256=sha256_file(destination),
        size=destination.stat().st_size,
    )
    used_targets.add(target)
    conflict = make_conflict_record(entry, digest) if target != original_target else None
    return entry, conflict


def _process_copy_route(
    *,
    source: Path,
    source_relative: Path,
    route: Route,
    suffix: str,
    data_dir: Path,
    product: str | None,
    used_targets: set[str],
) -> tuple[LandedEntry | None, ConflictRecord | None, FailureRecord | None]:
    try:
        entry, conflict = _land_copy(
            source=source,
            source_relative=source_relative,
            route=route,
            suffix=suffix,
            data_dir=data_dir,
            product=product,
            used_targets=used_targets,
        )
        return entry, conflict, None
    except ArchiveError as exc:
        return (
            None,
            None,
            _failure(
                source_relative=source_relative,
                route=route,
                error_code=exc.error_code or "unsafe_path",
                reason=str(exc),
            ),
        )
    except OSError as exc:
        return (
            None,
            None,
            _failure(
                source_relative=source_relative,
                route=route,
                error_code="unsafe_path",
                reason=f"目标文件写入失败: {exc}",
            ),
        )


def _process_expand_route(
    *,
    source: Path,
    source_relative: Path,
    route: Route,
    data_dir: Path,
    product: str | None,
    used_targets: set[str],
) -> tuple[list[LandedEntry], list[ConflictRecord], list[FailureRecord]]:
    entries: list[LandedEntry] = []
    conflicts: list[ConflictRecord] = []
    failures: list[FailureRecord] = []
    try:
        with tempfile.TemporaryDirectory(prefix=".classification-expand-", dir=data_dir) as temporary:
            staging_root = Path(temporary)
            expanded = expand_archive_members(source, staging_root)
            for member_error in expanded.member_errors:
                failures.append(
                    _failure(
                        source_relative=source_relative,
                        route=route,
                        member_relative=member_error.member_relative,
                        error_code=member_error.error.error_code or "archive_corrupt",
                        reason=str(member_error.error),
                    )
                )
            for member in expanded.files:
                member_relative = member.relative_to(staging_root).as_posix()
                try:
                    entry, conflict = _land_member(
                        member=member,
                        source_relative=source_relative,
                        member_relative=member_relative,
                        route=route,
                        data_dir=data_dir,
                        product=product,
                        used_targets=used_targets,
                    )
                    entries.append(entry)
                    if conflict is not None:
                        conflicts.append(conflict)
                except ArchiveError as exc:
                    member.unlink(missing_ok=True)
                    failures.append(
                        _failure(
                            source_relative=source_relative,
                            route=route,
                            member_relative=member_relative,
                            error_code=exc.error_code or "unsafe_path",
                            reason=str(exc),
                        )
                    )
                except OSError as exc:
                    member.unlink(missing_ok=True)
                    failures.append(
                        _failure(
                            source_relative=source_relative,
                            route=route,
                            member_relative=member_relative,
                            error_code="unsafe_path",
                            reason=f"归档成员写入失败: {exc}",
                        )
                    )
    except ArchiveError as exc:
        failures.append(
            _failure(
                source_relative=source_relative,
                route=route,
                error_code=exc.error_code or "archive_corrupt",
                reason=str(exc),
            )
        )
    return entries, conflicts, failures


def _profile_for_product(config: ClassificationConfig, product: str) -> tuple[str, str | None]:
    normalized = product.strip().upper()
    if normalized not in config.profiles:
        raise ValueError("product 必须是 UMF、CSP 或 GENERIC")
    return normalized, normalized if normalized in {"UMF", "CSP"} else None


def classify_main_evidence(
    data_dir: Path,
    *,
    product: str,
    config: ClassificationConfig | None = None,
) -> ClassificationRun:
    """按当前 product profile 分类 ``.main/`` 证据，并返回落位与审计结果。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    active_config = config or load_classification_config()
    profile, audit_product = _profile_for_product(active_config, product)
    evidence_root = data_dir / ".main"
    scene = infer_scene_root(evidence_root, active_config.profiles[profile].scene_anchors)

    entries: list[LandedEntry] = []
    ignored: list[IgnoredRecord] = []
    conflicts: list[ConflictRecord] = []
    failures: list[FailureRecord] = []
    used_targets: set[str] = set()

    for source in sorted(evidence_root.rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        source_relative = source.relative_to(evidence_root)
        scene_relative = _relative_to_scene(source_relative, scene.relative_to_evidence)
        selected = _select_route(
            active_config,
            profile=profile,
            source_relative=source_relative,
            scene_relative=scene_relative,
        )
        if selected is None:
            ignored.append(
                make_ignored_record(
                    source_relative=source_relative.as_posix(),
                    route_id=None,
                    action="ignore",
                    reason="route_not_matched",
                    product=audit_product,
                )
            )
            continue

        route, suffix = selected
        if route.action == "ignore":
            ignored.append(
                make_ignored_record(
                    source_relative=source_relative.as_posix(),
                    route_id=route.id,
                    action=route.action,
                    reason="route_ignored",
                    product=audit_product,
                )
            )
            continue
        if route.action in {"copy", "fallback"}:
            entry, conflict, failure = _process_copy_route(
                source=source,
                source_relative=source_relative,
                route=route,
                suffix=suffix,
                data_dir=data_dir,
                product=audit_product,
                used_targets=used_targets,
            )
            if entry is not None:
                entries.append(entry)
            if conflict is not None:
                conflicts.append(conflict)
            if failure is not None:
                failures.append(failure)
            continue
        if route.action == "expand":
            expanded_entries, expanded_conflicts, expanded_failures = _process_expand_route(
                source=source,
                source_relative=source_relative,
                route=route,
                data_dir=data_dir,
                product=audit_product,
                used_targets=used_targets,
            )
            entries.extend(expanded_entries)
            conflicts.extend(expanded_conflicts)
            failures.extend(expanded_failures)
            continue

        failures.append(
            _failure(
                source_relative=source_relative,
                route=route,
                error_code="archive_corrupt",
                reason=f"当前实现不支持动作: {route.action}",
            )
        )

    catalog = tuple(
        sorted(
            (
                CatalogEntry(
                    path=entry.target,
                    category=entry.category,
                    route_id=entry.route_id,
                    source_relative=entry.source_relative,
                    sha256=entry.sha256,
                    size=entry.size,
                )
                for entry in entries
            ),
            key=lambda entry: entry.path,
        )
    )
    return ClassificationRun(
        data_dir=data_dir,
        scene_root=scene,
        entries=tuple(entries),
        ignored=tuple(ignored),
        conflicts=tuple(conflicts),
        failures=tuple(failures),
        catalog=catalog,
    )
