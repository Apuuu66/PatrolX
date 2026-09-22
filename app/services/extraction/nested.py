"""子压缩包与日志 gzip 的有界递归展开。"""

import shutil
from pathlib import Path

from app.core.archive import ArchiveError, PathTooLongError, UnpackLimit, is_archive, unpack, unpack_gzip
from app.core.checksum import sha256_file
from app.core.classify import classify_name
from app.models.schemas import RuleCategory
from app.services.extraction.budget import ExtractionBudget, ExtractionLogger, _log_extract
from app.services.extraction.layout import (
    CATEGORY_DIRECTORIES,
    MAIN_EVIDENCE_DIR,
    PathLimitPolicy,
    _category_of,
    _destination_relative,
    _register_rejected,
    _relative_files,
    _safe_destination,
)
from app.services.extraction.policy import ExtractPolicyConfig, PolicyDecision, evaluate_extract_policy


def _policy_detail(decision: PolicyDecision | None) -> dict[str, object] | None:
    if decision is None:
        return None
    return {
        "action": decision.action,
        "reason": decision.reason,
        "scope": decision.scope,
        "keyword": decision.keyword,
    }


def _name_category(source: Path, parent_category: str) -> str:
    """策略跳过只按名称分类，避免读取压缩成员或触发损坏包解析。"""
    category = classify_name(source.name)
    if category is not None:
        return category.value
    return parent_category or "other"


def _source_display(source_relative: Path, source_kind: str) -> str:
    if source_kind == "evidence":
        return f"{MAIN_EVIDENCE_DIR}/{source_relative.as_posix()}"
    return source_relative.as_posix()


def _set_path_error(state: dict[str, object], exc: Exception) -> None:
    state["status"] = "failed"
    state["error"] = str(exc)
    if isinstance(exc, PathTooLongError):
        state["error_code"] = "path_too_long"
        state["path_length"] = exc.length
        state["path_limit"] = exc.limit


def _retain_evidence(
    source: Path,
    source_relative: Path,
    category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    depth: int,
    decision: PolicyDecision,
    log: ExtractionLogger | None,
    path_policy: PathLimitPolicy | None = None,
) -> dict[str, object]:
    """把策略命中的压缩项按原文件保留到 category 现场。"""
    relative = _destination_relative(source_relative, "evidence", category)
    state: dict[str, object] = {
        "target": relative.as_posix(),
        "status": "skipped",
        "error": None,
        "error_code": "policy_skip",
        "policy": _policy_detail(decision),
    }
    try:
        target = _safe_destination(data_dir, relative, path_policy)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ArchiveError("目标文件已存在，未覆盖")
        shutil.copy2(source, target)
        budget.charge_file(target)
        _log_extract(
            log,
            "info",
            "压缩项按策略保留",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            status="skipped",
            reason=decision.reason,
            scope=decision.scope,
            keyword=decision.keyword,
        )
    except (ArchiveError, OSError) as exc:
        target = locals().get("target")
        if target is not None:
            target.unlink(missing_ok=True)
        _set_path_error(state, exc)
        _register_rejected(manifest, source_relative.as_posix(), str(exc), category, depth)
        _log_extract(
            log,
            "error",
            "策略保留压缩项失败",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            status="failed",
            reason=decision.reason,
            scope=decision.scope,
            keyword=decision.keyword,
            error=str(exc),
        )
    return state


def _evidence_policy(
    source_relative: Path,
    policy: ExtractPolicyConfig | None,
    is_compressed: bool,
) -> PolicyDecision | None:
    if policy is None:
        return None
    return evaluate_extract_policy(policy, source_relative.as_posix(), is_compressed=is_compressed)


def _extract_log_gzip(
    source: Path,
    source_relative: Path,
    source_kind: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    depth: int,
    log: ExtractionLogger | None = None,
    policy: ExtractPolicyConfig | None = None,
    path_policy: PathLimitPolicy | None = None,
) -> None:
    category = RuleCategory.LOG.value
    decision = _evidence_policy(source_relative, policy, True) if source_kind == "evidence" else None
    if decision is not None and decision.action == "skip":
        state = {
            "source_evidence": _source_display(source_relative, source_kind),
            "source_relative_path": source_relative.as_posix(),
            "category": CATEGORY_DIRECTORIES[category],
            "depth": depth,
            **_retain_evidence(
                source,
                source_relative,
                category,
                data_dir,
                manifest,
                budget,
                depth,
                decision,
                log,
                path_policy,
            ),
        }
        manifest["log_gz"].append(state)
        return
    relative = _destination_relative(source_relative.with_suffix(""), source_kind, category)
    source_state = _source_display(source_relative, source_kind)
    state: dict[str, object] = {
        "source_relative_path": source_relative.as_posix(),
        "source": source_state,
        "category": CATEGORY_DIRECTORIES[category],
        "target": relative.as_posix(),
        "depth": depth,
        "status": "extracted",
        "error": None,
    }
    if decision is not None:
        state["policy"] = _policy_detail(decision)
    if decision is not None and decision.action == "whitelist":
        _log_extract(
            log,
            "info",
            "压缩项按白名单恢复",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            reason=decision.reason,
            scope=decision.scope,
            keyword=decision.keyword,
        )
    try:
        target = _safe_destination(data_dir, relative, path_policy)
        if target.exists():
            state["status"] = "conflict"
            state["error"] = "目标日志已存在，未覆盖"
            state["error_code"] = "target_conflict"
        else:
            budget.charge_gzip_chunk(0)
            unpack_gzip(
                source,
                target,
                charge=budget.charge_gzip_chunk,
            )
            budget.files += 1
            if budget.files > budget.max_files:
                raise ArchiveError("任务累计文件数超限")
            if source_kind != "evidence":
                source.unlink(missing_ok=True)
    except (ArchiveError, OSError) as exc:
        target = locals().get("target")
        if target is not None:
            target.unlink(missing_ok=True)
        _set_path_error(state, exc)
        if state["status"] != "conflict":
            _register_rejected(manifest, source_relative.as_posix(), str(exc), category, depth)
    task_id = data_dir.name
    if state["status"] == "extracted":
        _log_extract(
            log,
            "info",
            "日志 gzip 解压完成",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            depth=depth,
        )
    elif state["status"] == "conflict":
        _log_extract(
            log,
            "warn",
            "日志 gzip 目标冲突",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            depth=depth,
            error=state["error"],
        )
    else:
        _log_extract(
            log,
            "error",
            "日志 gzip 解压失败",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            depth=depth,
            error=state["error"],
        )
    manifest["log_gz"].append(state)


def _extract_subpackage(
    source: Path,
    source_relative: Path,
    source_kind: str,
    parent_category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    seen_checksums: set[str],
    depth: int,
    log: ExtractionLogger | None = None,
    policy: ExtractPolicyConfig | None = None,
    path_policy: PathLimitPolicy | None = None,
) -> None:
    limit = UnpackLimit()
    checksum = sha256_file(source)
    decision = _evidence_policy(source_relative, policy, True) if source_kind == "evidence" else None
    if decision is not None and decision.action == "skip":
        category = _name_category(source, parent_category)
        state: dict[str, object] = {
            "source": _source_display(source_relative, source_kind),
            "parent": None,
            "category": CATEGORY_DIRECTORIES[category],
            "classification_reason": "policy:name",
            "depth": depth,
            "checksum": checksum,
            **_retain_evidence(
                source,
                source_relative,
                category,
                data_dir,
                manifest,
                budget,
                depth,
                decision,
                log,
                path_policy,
            ),
        }
        manifest["subpackages"].append(state)
        return
    category, reason = _category_of(source, parent_category)
    state: dict[str, object] = {
        "source": _source_display(source_relative, source_kind),
        "parent": None,
        "category": CATEGORY_DIRECTORIES[category],
        "classification_reason": reason,
        "depth": depth,
        "checksum": checksum,
        "target": CATEGORY_DIRECTORIES[category],
        "status": "extracted",
        "error": None,
    }
    if decision is not None:
        state["policy"] = _policy_detail(decision)
    if depth > budget.max_depth or depth > limit.max_depth:
        state["status"] = "rejected"
        state["error"] = "嵌套深度超限"
        manifest["subpackages"].append(state)
        _register_rejected(manifest, source_relative.as_posix(), str(state["error"]), category, depth)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
        _log_extract(
            log,
            "error",
            "子包解压拒绝",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            category=CATEGORY_DIRECTORIES[category],
            depth=depth,
            error=state["error"],
        )
        return
    if checksum in seen_checksums:
        state["status"] = "duplicate"
        state["error"] = "相同 checksum 子包已展开"
        state["error_code"] = "duplicate"
        manifest["subpackages"].append(state)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
        _log_extract(
            log,
            "info",
            "子包重复，跳过解压",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            category=CATEGORY_DIRECTORIES[category],
            depth=depth,
            checksum=checksum,
        )
        return
    seen_checksums.add(checksum)
    target_relative = CATEGORY_DIRECTORIES[category]
    staging = data_dir / f".extract-{checksum[:12]}"
    shutil.rmtree(staging, ignore_errors=True)
    if decision is not None and decision.action == "whitelist":
        _log_extract(
            log,
            "info",
            "压缩项按白名单恢复",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            target=target_relative,
            reason=decision.reason,
            scope=decision.scope,
            keyword=decision.keyword,
        )
    _log_extract(
        log,
        "info",
        "子包解压开始",
        task_id=data_dir.name,
        source=source_relative.as_posix(),
        target=target_relative,
        category=state["category"],
        depth=depth,
        checksum=checksum,
    )
    try:
        if budget.files + 1 > budget.max_files:
            raise ArchiveError("任务累计文件数超限")
        unpack(source, staging, limit, path_policy.check if path_policy is not None else None)
        extracted_files = _relative_files(staging)
        if budget.files + len(extracted_files) > budget.max_files:
            raise ArchiveError("任务累计文件数超限")
        for extracted_file in extracted_files:
            budget.charge_file(extracted_file)
        for member in extracted_files:
            member_relative = member.relative_to(staging)
            _ingest_file(
                member,
                member_relative,
                "work",
                category,
                data_dir,
                manifest,
                budget,
                seen_checksums,
                depth + 1,
                log,
                policy,
                path_policy,
                source.name,
            )
        shutil.rmtree(staging, ignore_errors=True)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
    except (ArchiveError, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        _set_path_error(state, exc)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
    task_id = data_dir.name
    if state["status"] == "extracted":
        _log_extract(
            log,
            "info",
            "子包解压完成",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=state["target"],
            category=state["category"],
            depth=depth,
        )
    elif state["status"] != "duplicate":
        _log_extract(
            log,
            "error",
            "子包解压失败",
            task_id=task_id,
            source=source_relative.as_posix(),
            category=state["category"],
            depth=depth,
            error=state["error"],
        )
    manifest["subpackages"].append(state)


def _ingest_file(
    source: Path,
    source_relative: Path,
    source_kind: str,
    parent_category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    seen_checksums: set[str],
    depth: int,
    log: ExtractionLogger | None = None,
    policy: ExtractPolicyConfig | None = None,
    path_policy: PathLimitPolicy | None = None,
    archive_name: str | None = None,
) -> None:
    name = source.name.lower()
    if name.endswith(".log.gz"):
        _extract_log_gzip(
            source,
            source_relative,
            source_kind,
            data_dir,
            manifest,
            budget,
            depth,
            log,
            policy,
            path_policy,
        )
        return
    if is_archive(source):
        _extract_subpackage(
            source,
            source_relative,
            source_kind,
            parent_category,
            data_dir,
            manifest,
            budget,
            seen_checksums,
            depth,
            log,
            policy,
            path_policy,
        )
        return

    decision = _evidence_policy(source_relative, policy, False) if source_kind == "evidence" else None
    category, reason = _category_of(source, parent_category, archive_name)
    # 主包内非语义根目录下的普通文件平铺；完整原始路径仍保留在 .main 证据现场。
    destination_source = source_relative
    if (
        source_kind == "evidence"
        and category != RuleCategory.LOG.value
        and source_relative.parts[:-1]
        and source_relative.parts[0] != CATEGORY_DIRECTORIES[category]
    ):
        destination_source = Path(source_relative.name)
    relative = _destination_relative(destination_source, source_kind, category)
    state: dict[str, object] = {
        "source": _source_display(source_relative, source_kind),
        "category": CATEGORY_DIRECTORIES[category],
        "target": relative.as_posix(),
        "depth": depth,
        "classification_reason": reason,
        "status": "extracted",
        "error": None,
    }
    try:
        target = _safe_destination(data_dir, relative, path_policy)
        if target == source.resolve():
            budget.charge_file(target)
            return
        if target.exists():
            reason_text = "目标文件已存在，未覆盖"
            state["status"] = "conflict"
            state["error"] = reason_text
            state["error_code"] = "target_conflict"
            manifest["files"].append(state)
            _register_rejected(manifest, source_relative.as_posix(), reason_text, category, depth)
            _log_extract(
                log,
                "warn",
                "普通文件目标冲突",
                task_id=data_dir.name,
                source=source_relative.as_posix(),
                target=relative.as_posix(),
                category=CATEGORY_DIRECTORIES[category],
                depth=depth,
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            budget.charge_file(target)
            if source_kind == "work":
                source.unlink(missing_ok=True)
            manifest["files"].append(state)
            if decision is not None and decision.action == "whitelist":
                counters = (manifest.get("policy") or {}).setdefault("counters", {})
                if isinstance(counters, dict):
                    counters["whitelisted_files"] = int(counters.get("whitelisted_files", 0)) + 1
                _log_extract(
                    log,
                    "info",
                    "extract.policy.whitelist",
                    task_id=data_dir.name,
                    source=source_relative.as_posix(),
                    target=relative.as_posix(),
                    reason=decision.reason,
                    scope=decision.scope,
                    keyword=decision.keyword,
                )
    except (ArchiveError, OSError) as exc:
        target = locals().get("target")
        if target is not None and state["status"] == "extracted":
            target.unlink(missing_ok=True)
        _set_path_error(state, exc)
        manifest["files"].append(state)
        _register_rejected(manifest, source_relative.as_posix(), str(exc), category, depth)
        _log_extract(
            log,
            "error",
            "普通文件处理失败",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            category=CATEGORY_DIRECTORIES[category],
            depth=depth,
            error=str(exc),
        )
