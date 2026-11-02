"""主包解压现场编排与分类失败汇总。"""

import os
import shutil
from pathlib import Path

from app.core.archive import ArchiveError, unpack
from app.core.checksum import sha256_file
from app.core.config import settings
from app.services.extraction import manifest as manifest_v5
from app.services.extraction.budget import ExtractionLogger, _log_extract
from app.services.extraction.layout import MAIN_EVIDENCE_DIR, PathLimitPolicy
from app.services.extraction.manifest import ManifestReuseContext


def _reject_linked_task_root(data_dir: Path) -> None:
    """拒绝 output 内任务路径链接；允许配置的 output 根及平台祖先链接。"""
    current = Path(os.path.abspath(data_dir))
    output_root = Path(os.path.abspath(settings.output))
    if current.is_relative_to(output_root):
        relative = current.relative_to(output_root)
        candidates = (output_root.joinpath(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1))
    else:
        candidates = (current, current.parent)
    for candidate in candidates:
        if candidate.is_symlink():
            raise ArchiveError(
                f"任务根路径包含链接: {candidate}",
                "link_rejected",
            )


def validate_task_root(data_dir: Path) -> None:
    """供生产入口在读取任何证据路径前执行统一的链接边界校验。"""
    _reject_linked_task_root(data_dir)


def _verify_package_checksum(package: Path, expected_checksum: str) -> str:
    """只读复核原始包 checksum，拒绝当前文件与首次接收值冲突。"""
    try:
        actual_checksum = sha256_file(package)
    except OSError as exc:
        raise ArchiveError(f"无法读取原始数据包: {package}", "archive_corrupt") from exc
    if actual_checksum != expected_checksum:
        raise ArchiveError(
            "原始包 checksum 与任务首次接收值不一致",
            "package_checksum_conflict",
            expected_checksum=expected_checksum,
            actual_checksum=actual_checksum,
        )
    return actual_checksum


def _remove_path(path: Path) -> None:
    """清理普通文件、目录或链接，不跟随链接目标。"""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _replace_main_evidence(staging: Path, evidence: Path) -> None:
    """以已验证 staging 原子替换 `.main/`，不触碰原始包。"""
    backup = evidence.parent / ".main.previous"
    _remove_path(backup)
    replaced = False
    if evidence.is_symlink() or (evidence.exists() and not evidence.is_dir()):
        evidence.unlink()
    elif evidence.exists():
        evidence.rename(backup)
        replaced = True
    try:
        staging.rename(evidence)
    except OSError:
        if replaced and not evidence.exists():
            backup.rename(evidence)
        raise
    if replaced:
        shutil.rmtree(backup, ignore_errors=True)


def _rebuild_main_evidence(
    package: Path,
    data_dir: Path,
    checksum: str,
    *,
    path_policy: PathLimitPolicy,
    log: ExtractionLogger | None,
) -> tuple[dict[str, object], list[ArchiveError]]:
    """从原始包安全重建 `.main/` 并返回 manifest v5 所需证据快照。"""
    _reject_linked_task_root(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    staging = data_dir / ".main.staging"
    _remove_path(staging)
    _log_extract(
        log,
        "info",
        "主包解压开始",
        task_id=data_dir.name,
        package=package.name,
        checksum=checksum,
    )
    try:
        main_member_errors: list[ArchiveError] = []
        extracted_count = unpack(
            package,
            staging,
            path_limit_check=lambda target, label: path_policy.check(
                data_dir / MAIN_EVIDENCE_DIR / target.relative_to(staging.resolve()),
                label,
            ),
            on_member_error=main_member_errors.append,
        )
        if main_member_errors and extracted_count == 0:
            raise main_member_errors[0]
        _verify_package_checksum(package, checksum)
    except ArchiveError as exc:
        _remove_path(staging)
        _log_extract(
            log,
            "error",
            "主包解压失败",
            task_id=data_dir.name,
            package=package.name,
            checksum=checksum,
            error=str(exc),
        )
        raise

    evidence = data_dir / MAIN_EVIDENCE_DIR
    try:
        _replace_main_evidence(staging, evidence)
    except OSError:
        _remove_path(staging)
        raise
    count, fingerprint = manifest_v5.evidence_fingerprint(data_dir)
    return (
        {
            "checksum": checksum,
            "count": count,
            "evidence_path": MAIN_EVIDENCE_DIR,
            "evidence_fingerprint": fingerprint,
            "reused": False,
        },
        main_member_errors,
    )


def _ensure_main_evidence(
    package: Path,
    data_dir: Path,
    checksum: str,
    *,
    log: ExtractionLogger | None = None,
    path_policy: PathLimitPolicy | None = None,
    checksum_verified: bool = False,
) -> tuple[dict[str, object], list[ArchiveError]]:
    """复用有效 v5 证据，否则从原始包重建；返回证据快照与成员错误。"""
    _reject_linked_task_root(data_dir)
    if not checksum_verified:
        _verify_package_checksum(package, checksum)
    existing = manifest_v5.reusable_evidence_manifest(data_dir, checksum)
    if existing is not None:
        main = dict(existing["main"])
        main["reused"] = True
        _log_extract(
            log,
            "info",
            "解压现场复用",
            task_id=data_dir.name,
            checksum=checksum,
        )
        return main, []
    return _rebuild_main_evidence(
        package,
        data_dir,
        checksum,
        path_policy=path_policy or PathLimitPolicy.current(),
        log=log,
    )


def ensure_main_evidence(
    package: Path,
    data_dir: Path,
    checksum: str,
    log: ExtractionLogger | None = None,
    path_policy: PathLimitPolicy | None = None,
) -> dict[str, object]:
    """确保 v5 证据现场可用；损坏时只读复核原包并重建 `.main/`。"""
    _reject_linked_task_root(data_dir)
    main, _ = _ensure_main_evidence(
        package,
        data_dir,
        checksum,
        log=log,
        path_policy=path_policy,
    )
    if not main["reused"]:
        _log_extract(
            log,
            "info",
            "主包证据现场重建完成",
            task_id=data_dir.name,
            package=package.name,
            checksum=checksum,
            count=int(main["count"]),
        )
    return main


def reusable_extraction_site(
    package: Path,
    data_dir: Path,
    context: ManifestReuseContext,
) -> dict | None:
    """当前包 checksum 与完整 v5 分类上下文、证据和 catalog 均一致时复用。"""
    _reject_linked_task_root(data_dir)
    _verify_package_checksum(package, context.checksum)
    return manifest_v5.reusable_manifest(data_dir, context)
