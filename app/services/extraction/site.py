"""主包解压现场编排与分类失败汇总。"""

import shutil
from pathlib import Path

from app.core.archive import ArchiveError, unpack
from app.services.extraction.budget import ExtractionBudget, ExtractionLogger, _log_extract
from app.services.extraction.layout import (
    MAIN_EVIDENCE_DIR,
    WORK_CATEGORIES,
    PathLimitPolicy,
    _relative_files,
)
from app.services.extraction.manifest import (
    MANIFEST_VERSION,
    manifest_path,
    reusable_manifest,
    write_manifest,
)
from app.services.extraction.nested import _ingest_file
from app.services.extraction.policy import ExtractPolicyConfig, load_extract_policy, policy_manifest_snapshot


def extract_main_site(
    package: Path,
    data_dir: Path,
    checksum: str,
    log: ExtractionLogger | None = None,
    policy_path: Path | None = None,
    path_policy: PathLimitPolicy | None = None,
) -> dict:
    """保留主包证据现场并生成分类工作现场。"""
    path_policy = path_policy or PathLimitPolicy.current()
    existing = reusable_manifest(data_dir, checksum)
    if existing is not None and existing.get("path_limit") != path_policy.snapshot():
        existing = None
    if existing is not None:
        _log_extract(
            log,
            "info",
            "解压现场复用",
            task_id=data_dir.name,
            checksum=checksum,
        )
        main = existing.get("main")
        if isinstance(main, dict):
            main["reused"] = True
        return existing

    policy: ExtractPolicyConfig = load_extract_policy(policy_path)
    staging = data_dir / ".main.staging"
    shutil.rmtree(staging, ignore_errors=True)
    _log_extract(
        log,
        "info",
        "主包解压开始",
        task_id=data_dir.name,
        package=package.name,
        checksum=checksum,
    )
    try:
        unpack(
            package,
            staging,
            path_limit_check=lambda target, label: path_policy.check(
                data_dir / MAIN_EVIDENCE_DIR / target.relative_to(staging.resolve()),
                label,
            ),
        )
    except ArchiveError as exc:
        shutil.rmtree(staging, ignore_errors=True)
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
    backup = data_dir / ".main.previous"
    shutil.rmtree(backup, ignore_errors=True)
    replaced = False
    if evidence.exists():
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

    for category in WORK_CATEGORIES:
        shutil.rmtree(data_dir / category, ignore_errors=True)
        (data_dir / category).mkdir(parents=True, exist_ok=True)
    shutil.rmtree(manifest_path(data_dir), ignore_errors=True)

    manifest: dict = {
        "version": MANIFEST_VERSION,
        "main": {
            "checksum": checksum,
            "count": 0,
            "evidence_path": MAIN_EVIDENCE_DIR,
            "reused": False,
        },
        "files": [],
        "subpackages": [],
        "log_gz": [],
        "rejected": [],
        "policy": policy_manifest_snapshot(policy),
        "path_limit": path_policy.snapshot(),
    }
    budget = ExtractionBudget()
    seen_checksums: set[str] = set()
    for source in _relative_files(evidence):
        source_relative = source.relative_to(evidence)
        manifest["main"]["count"] += 1
        _ingest_file(
            source,
            source_relative,
            "evidence",
            "",
            data_dir,
            manifest,
            budget,
            seen_checksums,
            1,
            log,
            policy,
            path_policy,
        )
    write_manifest(data_dir, manifest)
    _log_extract(
        log,
        "info",
        "主包解压完成",
        task_id=data_dir.name,
        package=package.name,
        checksum=checksum,
        count=int(manifest["main"]["count"]),
        subpackages=len(manifest["subpackages"]),
        log_gz=len(manifest["log_gz"]),
        rejected=len(manifest["rejected"]),
    )
    return manifest


def category_failures(manifest: dict, category: str) -> list[dict]:
    """读取指定分类的子包和日志 gzip 异常明细，保留状态与路径限制上下文。"""
    failures: list[dict] = []
    statuses = {"conflict", "duplicate", "failed", "rejected"}
    for item in manifest.get("files", []):
        if item.get("category") != category or item.get("status") not in statuses:
            continue
        source = item.get("source")
        failures.append(
            {
                "name": Path(str(source or "")).name,
                "source": source,
                "target": item.get("target"),
                "error": item.get("error"),
                "error_code": item.get("error_code"),
                "status": item.get("status"),
                "path_length": item.get("path_length"),
                "path_limit": item.get("path_limit"),
            }
        )
    for item in manifest.get("subpackages", []):
        if item.get("category") != category or item.get("status") not in statuses:
            continue
        source = item.get("source")
        failures.append(
            {
                "name": Path(str(source or "")).name,
                "source": source,
                "checksum": item.get("checksum"),
                "target": item.get("target"),
                "error": item.get("error"),
                "error_code": item.get("error_code"),
                "status": item.get("status"),
                "path_length": item.get("path_length"),
                "path_limit": item.get("path_limit"),
            }
        )
    if category == "logs":
        for item in manifest.get("log_gz", []):
            if item.get("status") not in statuses:
                continue
            source = item.get("source_relative_path")
            failures.append(
                {
                    "name": Path(str(item.get("target", ""))).name,
                    "source": source,
                    "target": item.get("target"),
                    "error": item.get("error"),
                    "error_code": item.get("error_code"),
                    "status": item.get("status"),
                    "path_length": item.get("path_length"),
                    "path_limit": item.get("path_limit"),
                }
            )
    return failures


def policy_skipped_summary(manifest: dict, category: str) -> list[dict]:
    """返回指定分类策略成功保留的压缩项摘要，仅供执行器组织可读提示。"""
    summary: list[dict] = []
    for key, source_key, name_source in (
        ("subpackages", "source", "source"),
        ("log_gz", "source_relative_path", "source_relative_path"),
    ):
        for item in manifest.get(key, []):
            if item.get("category") != category:
                continue
            if item.get("status") != "skipped":
                continue
            decision = item.get("policy") or {}
            source = item.get(source_key)
            summary.append(
                {
                    "name": Path(str(name_source and item.get(name_source) or item.get("target", ""))).name,
                    "source": source,
                    "target": item.get("target"),
                    "reason": decision.get("reason"),
                    "scope": decision.get("scope"),
                    "keyword": decision.get("keyword"),
                }
            )
    return summary
