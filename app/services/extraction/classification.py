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
from app.services.extraction.nested import (
    decompress_matching_members,
    expand_archive_members,
    expand_recursive,
    is_recursive_archive_source,
    select_and_decompress,
)

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


def infer_scene_root(evidence_root: Path, anchors: tuple[str, ...]) -> SceneRoot:
    """以最可信的 profile anchor 父目录组推导场景根。

    真实包可能同时包含其他网元目录。共享 anchor（例如 ``Operation Logs``）若落在
    另一棵孤立目录中，不能参与当前网元场景根计算。因此先按 anchor 父目录
    精确聚类，选择覆盖 anchor 种类最多、命中最多且最具体的一组。
    """
    candidates: dict[Path, dict[str, int]] = {}
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
                candidate = Path(*parent_parts[:index]) if index else Path(".")
                matches = candidates.setdefault(candidate, {})
                matches[anchor.strip()] = matches.get(anchor.strip(), 0) + 1
    if not candidates:
        return SceneRoot(relative_to_evidence=Path("."), matched_anchors=())

    best_candidate, best_matches = max(
        candidates.items(),
        key=lambda item: (
            len(item[1]),
            sum(item[1].values()),
            len(item[0].parts),
            tuple(part.casefold() for part in item[0].parts),
        ),
    )
    return SceneRoot(
        relative_to_evidence=best_candidate,
        matched_anchors=tuple(sorted(best_matches)),
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
    return "/".join(segment for segment in rendered.split("/") if segment)


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
    service: str | None = None,
) -> tuple[LandedEntry, ConflictRecord | None]:
    member_parts = member_relative.split("/")
    service_name = (service or "").upper()
    node_parts = member_parts[:-1]
    if service_name and node_parts and node_parts[0].casefold() == service_name.casefold():
        node_parts = node_parts[1:]
    original_target = _render_target(
        route,
        member=member_relative,
        archive_stem=_archive_stem(source_relative.name),
        service=service_name,
        node_path="/".join(node_parts),
        name_without_gz=member_parts[-1],
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


def _land_recursive_plain_file(
    *,
    source: Path,
    source_relative: Path,
    route: Route,
    suffix: str,
    data_dir: Path,
    product: str | None,
    used_targets: set[str],
) -> tuple[LandedEntry, ConflictRecord | None]:
    """把告警来源目录下的普通文件按目录后缀落位，不标记为归档成员。"""
    original_target = _render_target(route, member=suffix)
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
            member_files = expanded.files
            member_errors = list(expanded.member_errors)
            if route.member_decompress:
                decompressed = decompress_matching_members(
                    expanded.files,
                    staging_root,
                    patterns=route.member_decompress,
                )
                member_files = decompressed.files
                member_errors.extend(decompressed.member_errors)
            for member_error in member_errors:
                failures.append(
                    _failure(
                        source_relative=source_relative,
                        route=route,
                        member_relative=member_error.member_relative,
                        error_code=member_error.error.error_code or "archive_corrupt",
                        reason=str(member_error.error),
                    )
                )
            for member in member_files:
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


def _process_expand_recursive_route(
    *,
    source: Path,
    source_relative: Path,
    route: Route,
    suffix: str,
    data_dir: Path,
    product: str | None,
    used_targets: set[str],
) -> tuple[list[LandedEntry], list[ConflictRecord], list[FailureRecord]]:
    """递归展开告警归档；普通文件原样落位，单来源失败不影响其他告警文件。"""
    entries: list[LandedEntry] = []
    conflicts: list[ConflictRecord] = []
    failures: list[FailureRecord] = []

    if not is_recursive_archive_source(source):
        try:
            entry, conflict = _land_recursive_plain_file(
                source=source,
                source_relative=source_relative,
                route=route,
                suffix=suffix,
                data_dir=data_dir,
                product=product,
                used_targets=used_targets,
            )
            entries.append(entry)
            if conflict is not None:
                conflicts.append(conflict)
        except ArchiveError as exc:
            failures.append(
                _failure(
                    source_relative=source_relative,
                    route=route,
                    error_code=exc.error_code or "unsafe_path",
                    reason=str(exc),
                )
            )
        except OSError as exc:
            failures.append(
                _failure(
                    source_relative=source_relative,
                    route=route,
                    error_code="unsafe_path",
                    reason=f"告警文件写入失败: {exc}",
                )
            )
        return entries, conflicts, failures

    try:
        with tempfile.TemporaryDirectory(prefix=".classification-recursive-", dir=data_dir) as temporary:
            staging_root = Path(temporary)
            expanded = expand_recursive(
                source,
                staging_root,
                source_member_relative=suffix,
            )
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
                            reason=f"告警归档成员写入失败: {exc}",
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
    except OSError as exc:
        failures.append(
            _failure(
                source_relative=source_relative,
                route=route,
                error_code="unsafe_path",
                reason=f"告警归档暂存失败: {exc}",
            )
        )
    return entries, conflicts, failures


def _process_select_and_decompress_route(
    *,
    source: Path,
    source_relative: Path,
    route: Route,
    data_dir: Path,
    product: str | None,
    used_targets: set[str],
) -> tuple[list[LandedEntry], list[IgnoredRecord], list[ConflictRecord], list[FailureRecord]]:
    """按成员配置选择日志并解压，未选成员和单个 GZIP 失败均保留审计。"""
    entries: list[LandedEntry] = []
    ignored: list[IgnoredRecord] = []
    conflicts: list[ConflictRecord] = []
    failures: list[FailureRecord] = []
    if route.selection is None:
        failures.append(
            _failure(
                source_relative=source_relative,
                route=route,
                error_code="invalid_classification_config",
                reason="select_and_decompress route 缺少 selection",
            )
        )
        return entries, ignored, conflicts, failures

    try:
        with tempfile.TemporaryDirectory(prefix=".classification-select-", dir=data_dir) as temporary:
            staging_root = Path(temporary)
            selected = select_and_decompress(
                source,
                staging_root,
                include=route.selection.include,
                exclude=route.selection.exclude,
            )
            for ignored_member in selected.ignored:
                ignored.append(
                    make_ignored_record(
                        source_relative=source_relative.as_posix(),
                        member_relative=ignored_member.member_relative,
                        route_id=route.id,
                        action=route.action,
                        reason=ignored_member.reason,
                        product=product,
                        category=route.category,
                    )
                )
            for member_error in selected.member_errors:
                failures.append(
                    _failure(
                        source_relative=source_relative,
                        route=route,
                        member_relative=member_error.member_relative,
                        error_code=member_error.error.error_code or "archive_corrupt",
                        reason=str(member_error.error),
                    )
                )
            for selected_member in selected.files:
                try:
                    entry, conflict = _land_member(
                        member=selected_member.path,
                        source_relative=source_relative,
                        member_relative=selected_member.member_relative,
                        route=route,
                        data_dir=data_dir,
                        product=product,
                        used_targets=used_targets,
                        service=selected_member.service,
                    )
                    entries.append(entry)
                    if conflict is not None:
                        conflicts.append(conflict)
                except ArchiveError as exc:
                    selected_member.path.unlink(missing_ok=True)
                    failures.append(
                        _failure(
                            source_relative=source_relative,
                            route=route,
                            member_relative=selected_member.member_relative,
                            error_code=exc.error_code or "unsafe_path",
                            reason=str(exc),
                        )
                    )
                except OSError as exc:
                    selected_member.path.unlink(missing_ok=True)
                    failures.append(
                        _failure(
                            source_relative=source_relative,
                            route=route,
                            member_relative=selected_member.member_relative,
                            error_code="unsafe_path",
                            reason=f"选中日志写入失败: {exc}",
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
    except OSError as exc:
        failures.append(
            _failure(
                source_relative=source_relative,
                route=route,
                error_code="unsafe_path",
                reason=f"日志归档暂存失败: {exc}",
            )
        )
    return entries, ignored, conflicts, failures


def _profile_for_product(config: ClassificationConfig, product: str | None) -> tuple[str, str | None]:
    if product is None:
        return "GENERIC", None
    normalized = product.strip().upper()
    if normalized not in config.profiles:
        raise ValueError("product 必须是 UMF、CSP 或 GENERIC")
    return normalized, normalized if normalized in {"UMF", "CSP"} else None


def classify_main_evidence(
    data_dir: Path,
    *,
    product: str | None,
    config: ClassificationConfig | None = None,
    output_dir: Path | None = None,
) -> ClassificationRun:
    """按当前 product profile 分类 ``.main/`` 证据，并返回落位与审计结果。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(output_dir) if output_dir is not None else data_dir
    output_dir.mkdir(parents=True, exist_ok=True)
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
                data_dir=output_dir,
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
                data_dir=output_dir,
                product=audit_product,
                used_targets=used_targets,
            )
            entries.extend(expanded_entries)
            conflicts.extend(expanded_conflicts)
            failures.extend(expanded_failures)
            continue
        if route.action == "select_and_decompress":
            selected_entries, selected_ignored, selected_conflicts, selected_failures = (
                _process_select_and_decompress_route(
                    source=source,
                    source_relative=source_relative,
                    route=route,
                    data_dir=output_dir,
                    product=audit_product,
                    used_targets=used_targets,
                )
            )
            entries.extend(selected_entries)
            ignored.extend(selected_ignored)
            conflicts.extend(selected_conflicts)
            failures.extend(selected_failures)
            continue
        if route.action == "expand_recursive":
            expanded_entries, expanded_conflicts, expanded_failures = _process_expand_recursive_route(
                source=source,
                source_relative=source_relative,
                route=route,
                suffix=suffix,
                data_dir=output_dir,
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
        data_dir=output_dir,
        scene_root=scene,
        entries=tuple(entries),
        ignored=tuple(ignored),
        conflicts=tuple(conflicts),
        failures=tuple(failures),
        catalog=catalog,
    )
