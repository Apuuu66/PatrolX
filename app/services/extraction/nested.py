"""子压缩包与日志 gzip 的有界递归展开。"""

import shutil
from pathlib import Path

from app.core.archive import ArchiveError, UnpackLimit, is_archive, unpack, unpack_gzip
from app.core.checksum import sha256_file
from app.models.schemas import RuleCategory
from app.services.extraction.budget import ExtractionBudget, ExtractionLogger, _log_extract
from app.services.extraction.layout import (
    CATEGORY_DIRECTORIES,
    MAIN_EVIDENCE_DIR,
    _category_of,
    _destination_relative,
    _register_rejected,
    _relative_files,
    _remove_empty_work_site,
    _safe_destination,
    _unique_work_path,
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
    from app.core.classify import classify_name

    category = classify_name(source.name)
    if category is not None:
        return category.value
    return parent_category or "other"


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
) -> dict[str, object]:
    """把策略命中的压缩项按原文件保留到 category 现场。"""
    relative = _destination_relative(source_relative, "evidence", "", category)
    state: dict[str, object] = {
        "target": relative.as_posix(),
        "status": "skipped",
        "error": None,
        "policy": _policy_detail(decision),
    }
    try:
        target = _safe_destination(data_dir, relative)
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
        state["status"] = "failed"
        state["error"] = str(exc)
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
    group: str,
    category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    depth: int,
    log: ExtractionLogger | None = None,
    policy: ExtractPolicyConfig | None = None,
) -> None:
    if category != RuleCategory.LOG.value:
        category = RuleCategory.LOG.value
    decision = _evidence_policy(source_relative, policy, True) if source_kind == "evidence" else None
    if decision is not None and decision.action == "skip":
        state = {
            "source_evidence": f"{MAIN_EVIDENCE_DIR}/{source_relative.as_posix()}",
            "source_relative_path": source_relative.as_posix(),
            "category": CATEGORY_DIRECTORIES[category],
            "depth": depth,
            **_retain_evidence(source, source_relative, category, data_dir, manifest, budget, depth, decision, log),
        }
        manifest["log_gz"].append(state)
        return
    relative = _destination_relative(source_relative.with_suffix(""), source_kind, group, category)
    target = _safe_destination(data_dir, relative)
    source_state = (
        f"{MAIN_EVIDENCE_DIR}/{source_relative.as_posix()}" if source_kind == "evidence" else MAIN_EVIDENCE_DIR
    )
    state: dict[str, object] = {
        "source_evidence": source_state,
        "source_relative_path": source_relative.as_posix(),
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
    if target.exists():
        state["status"] = "conflict"
        state["error"] = "目标日志已存在，未覆盖"
    else:
        try:
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
        except ArchiveError as exc:
            target.unlink(missing_ok=True)
            state["status"] = "failed"
            state["error"] = str(exc)
            _register_rejected(
                manifest,
                source_relative.as_posix(),
                str(exc),
                category,
                depth,
            )
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
    group: str,
    parent_category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    seen_checksums: set[str],
    depth: int,
    log: ExtractionLogger | None = None,
    policy: ExtractPolicyConfig | None = None,
) -> None:
    limit = UnpackLimit()
    checksum = sha256_file(source)
    decision = _evidence_policy(source_relative, policy, True) if source_kind == "evidence" else None
    if decision is not None and decision.action == "skip":
        category = _name_category(source, parent_category)
        state: dict[str, object] = {
            "source": (
                f"{MAIN_EVIDENCE_DIR}/{source_relative.as_posix()}"
                if source_kind == "evidence"
                else source_relative.as_posix()
            ),
            "parent": group or None,
            "category": CATEGORY_DIRECTORIES[category],
            "classification_reason": "policy:name",
            "depth": depth,
            "checksum": checksum,
            **_retain_evidence(source, source_relative, category, data_dir, manifest, budget, depth, decision, log),
        }
        manifest["subpackages"].append(state)
        return
    category, reason = _category_of(source, parent_category)
    work_relative = source_relative.with_suffix("")
    if source_kind == "evidence":
        work_relative = _destination_relative(
            work_relative,
            source_kind,
            "",
            category,
        ).relative_to(CATEGORY_DIRECTORIES[category])
    state: dict[str, object] = {
        "source": (
            f"{MAIN_EVIDENCE_DIR}/{source_relative.as_posix()}"
            if source_kind == "evidence"
            else source_relative.as_posix()
        ),
        "parent": group or None,
        "category": CATEGORY_DIRECTORIES[category],
        "classification_reason": reason,
        "depth": depth,
        "checksum": checksum,
        "target": None,
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

    work_path = _unique_work_path(data_dir / CATEGORY_DIRECTORIES[category], work_relative, checksum)
    target_relative = work_path.relative_to(data_dir)
    state["target"] = target_relative.as_posix()
    staging = data_dir / f".extract-{checksum[:12]}"
    shutil.rmtree(staging, ignore_errors=True)
    if decision is not None and decision.action == "whitelist":
        _log_extract(
            log,
            "info",
            "压缩项按白名单恢复",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            target=target_relative.as_posix(),
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
        target=target_relative.as_posix(),
        category=state["category"],
        depth=depth,
        checksum=checksum,
    )
    try:
        if budget.files + 1 > budget.max_files:
            raise ArchiveError("任务累计文件数超限")
        unpack(source, staging, limit)
        extracted_files = _relative_files(staging)
        if budget.files + len(extracted_files) > budget.max_files:
            raise ArchiveError("任务累计文件数超限")
        for extracted_file in extracted_files:
            budget.charge_file(extracted_file)
        work_path.parent.mkdir(parents=True, exist_ok=True)
        if work_path.exists():
            shutil.rmtree(work_path)
        staging.rename(work_path)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
        for member in _relative_files(work_path):
            member_relative = member.relative_to(work_path)
            _ingest_file(
                member,
                member_relative,
                "work",
                work_path.name,
                category,
                data_dir,
                manifest,
                budget,
                seen_checksums,
                depth + 1,
                log,
            )
        _remove_empty_work_site(work_path, data_dir / CATEGORY_DIRECTORIES[category])
    except ArchiveError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if work_path.exists():
            shutil.rmtree(work_path, ignore_errors=True)
        state["status"] = "failed"
        state["error"] = str(exc)
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
    group: str,
    parent_category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    seen_checksums: set[str],
    depth: int,
    log: ExtractionLogger | None = None,
    policy: ExtractPolicyConfig | None = None,
) -> None:
    name = source.name.lower()
    if name.endswith(".log.gz"):
        _extract_log_gzip(
            source,
            source_relative,
            source_kind,
            group,
            parent_category,
            data_dir,
            manifest,
            budget,
            depth,
            log,
            policy,
        )
        return
    if is_archive(source):
        _extract_subpackage(
            source,
            source_relative,
            source_kind,
            group,
            parent_category,
            data_dir,
            manifest,
            budget,
            seen_checksums,
            depth,
            log,
            policy,
        )
        return

    decision = _evidence_policy(source_relative, policy, False) if source_kind == "evidence" else None
    category, _ = _category_of(source, parent_category)
    relative = _destination_relative(source_relative, source_kind, group, category)
    target = _safe_destination(data_dir, relative)
    try:
        if target == source.resolve():
            budget.charge_file(target)
            return
        if target.exists():
            reason = "目标文件已存在，未覆盖"
            _register_rejected(manifest, source_relative.as_posix(), reason, category, depth)
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
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        budget.charge_file(target)
        if source_kind == "work":
            source.unlink(missing_ok=True)
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
