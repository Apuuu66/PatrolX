"""解压规则族（hidden P0）：主包证据现场与配置驱动分类发布。"""

from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core import archive
from app.core.config import settings
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import PackageKind, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result
from app.services.extraction import manifest as manifest_v5
from app.services.extraction import site
from app.services.extraction.audit import (
    ConflictRecord,
    FailureRecord,
    IgnoredRecord,
    LandedEntry,
    Summary,
    SummaryCounts,
    build_audit_event,
    build_summary,
)
from app.services.extraction.classification import (
    ClassificationRun,
    classify_main_evidence,
    infer_scene_root,
)
from app.services.extraction.config import (
    ClassificationConfig,
    ClassificationConfigError,
    load_classification_config,
)
from app.services.extraction.layout import MAIN_EVIDENCE_DIR, PathLimitPolicy
from app.services.extraction.manifest import (
    FIXED_BUDGETS,
    ManifestReuseContext,
    ManifestV5Error,
    extraction_policy_fingerprint,
)

EXTRACT_MANIFEST = manifest_v5.MANIFEST_NAME


class _ClassificationContextError(ValueError):
    """任务元数据不足以构造确定性分类上下文。"""

    def __init__(self, message: str, code: str) -> None:
        self.code = code
        super().__init__(message)


def _error_result(
    inspector: Inspector,
    summary: str,
    *,
    error_code: str,
    error: str,
    **metadata: object,
) -> object:
    """构造带稳定错误码的隐藏单元失败结果。"""
    return make_result(
        inspector,
        status=RuleStatus.ERROR,
        summary=summary,
        metadata={
            **metadata,
            "error_code": error_code,
            "error": error,
        },
    )


main_inspector = Inspector(
    code="pkg.extract.main",
    name="主包解压与证据现场保留",
    category=RuleCategory.OTHER,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="4.0.0",
    hidden=True,
    description="安全解压主数据包到 .main 证据现场；不读取分类配置，不发布分类清单",
    recommendation="主包无法解压时检查包格式与安全限制",
)


def _main_result(inspector: Inspector, main: dict[str, object]) -> object:
    """只发布冻结的五个主包证据字段。"""
    count = int(main.get("count", 0))
    return make_result(
        inspector,
        status=RuleStatus.PASS,
        summary=f"主包解压完成，保留现场并生成 {count} 个原始文件",
        metadata={
            "count": count,
            "checksum": main.get("checksum"),
            "evidence_fingerprint": main.get("evidence_fingerprint"),
            "evidence_path": main.get("evidence_path", MAIN_EVIDENCE_DIR),
            "reused": bool(main.get("reused", False)),
        },
    )


def _run_main(ctx: RuleContext) -> object:
    if ctx.package_path is None or not ctx.package_path.exists():
        return _error_result(
            main_inspector,
            "未找到数据包",
            error_code="archive_corrupt",
            error=f"数据包不存在: {ctx.package_path}",
            package=str(ctx.package_path) if ctx.package_path else None,
        )
    checksum = ctx.package_checksum
    try:
        checksum = ctx.ensure_package_checksum()
        main = site.ensure_main_evidence(
            ctx.package_path,
            ctx.data_dir,
            checksum,
            log=ctx.log,
        )
    except (archive.ArchiveError, ManifestV5Error, OSError, ValueError) as exc:
        error_code = getattr(exc, "error_code", None) or "archive_corrupt"
        ctx.log(
            "error",
            "主包解压失败",
            task_id=ctx.task_id,
            rule_code=main_inspector.code,
            package=ctx.package_path.name,
            checksum=checksum,
            error_code=error_code,
            error=str(exc),
        )
        return _error_result(
            main_inspector,
            f"主包解压失败: {exc}",
            error_code=error_code,
            error=str(exc),
            package=ctx.package_path.name,
            checksum=checksum,
        )
    ctx.log(
        "info",
        "主包解压现场已就绪",
        task_id=ctx.task_id,
        rule_code=main_inspector.code,
        checksum=checksum,
        count=int(main.get("count", 0)),
        reused=bool(main.get("reused", False)),
    )
    return _main_result(main_inspector, main)


main_inspector.run = _run_main
registry.register(main_inspector)


classification_inspector = Inspector(
    code="pkg.extract.classification",
    name="分类落位与 catalog 发布",
    category=RuleCategory.OTHER,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="1.0.0",
    hidden=True,
    description="按任务 product 加载分类配置，构建并原子发布 manifest v5，随后重建 catalog",
    recommendation="分类配置、manifest 或 catalog 无效时检查分类现场与产品元数据",
)


def _profile_for_context(ctx: RuleContext) -> tuple[str, str | None]:
    """按任务声明推导 profile；缺失或冲突元数据不得降级猜测。"""
    if ctx.package_kind is PackageKind.LOG_SUPPLEMENT:
        if ctx.product is not None:
            raise _ClassificationContextError("日志补充包不得携带 product", "metadata_not_applicable")
        return "GENERIC", None
    if ctx.product is None:
        raise _ClassificationContextError("巡检包缺少 product", "missing_product")
    product = str(ctx.product).strip().upper()
    if product not in {"UMF", "CSP"}:
        raise _ClassificationContextError(f"不支持的 product: {product}", "invalid_product")
    return product, product


def _current_reuse_context(
    ctx: RuleContext,
    checksum: str,
    *,
    config: ClassificationConfig,
    path_policy: PathLimitPolicy,
) -> ManifestReuseContext:
    """按冻结的 manifest v5 快照构造完整复用上下文。"""
    site.validate_task_root(ctx.data_dir)
    profile, product = _profile_for_context(ctx)
    scene = infer_scene_root(
        ctx.data_dir / MAIN_EVIDENCE_DIR,
        config.profiles[profile].scene_anchors,
    ).relative_to_evidence
    scene_root = MAIN_EVIDENCE_DIR if scene == Path(".") else f"{MAIN_EVIDENCE_DIR}/{scene.as_posix()}"
    target_roots = tuple(
        sorted(
            {
                route.target.split("/", 1)[0]
                for route in config.routes
                if profile in route.profiles and route.action != "ignore" and route.target
            }
        )
    )
    return ManifestReuseContext(
        checksum=checksum,
        product=product,
        package_kind=ctx.package_kind.value,
        profile=profile,
        config_fingerprint=config.fingerprint,
        extraction_policy_fingerprint=extraction_policy_fingerprint(),
        path_limit=path_policy.snapshot(),
        scene_root=scene_root,
        target_roots=target_roots,
        budgets=dict(FIXED_BUDGETS),
    )


def _remove_control_path(path: Path) -> None:
    """清理分类 staging，不跟随链接。"""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _main_snapshot(data_dir: Path, checksum: str) -> dict[str, object]:
    """从已存在的 `.main/` 构造 manifest 主包证据段，不重复解压。"""
    count, fingerprint = manifest_v5.evidence_fingerprint(data_dir)
    evidence_manifest = manifest_v5.reusable_evidence_manifest(data_dir, checksum)
    return {
        "checksum": checksum,
        "count": count,
        "evidence_path": MAIN_EVIDENCE_DIR,
        "evidence_fingerprint": fingerprint,
        "reused": evidence_manifest is not None,
    }


def _manifest_for_run(
    *,
    data_dir: Path,
    checksum: str,
    context: ManifestReuseContext,
    config: ClassificationConfig,
    path_policy: PathLimitPolicy,
    run: ClassificationRun,
) -> dict[str, Any]:
    """把分类运行转换为严格 manifest v5，不补猜任何业务字段。"""
    return {
        "version": manifest_v5.MANIFEST_VERSION,
        "main": _main_snapshot(data_dir, checksum),
        "product": context.product,
        "classification": {
            "config_fingerprint": config.fingerprint,
            "profile": context.profile,
            "snapshot": {
                "package_kind": context.package_kind,
                "product": context.product,
                "profile": context.profile,
                "ruleset": manifest_v5.RULESETS[context.profile],
                "config_fingerprint": context.config_fingerprint,
                "extraction_policy_fingerprint": context.extraction_policy_fingerprint,
                "path_limit_fingerprint": path_policy.fingerprint,
                "scene_root": context.scene_root,
                "target_roots": list(context.target_roots),
                "budgets": dict(context.budgets),
            },
        },
        "path_limit": path_policy.snapshot(),
        "entries": [asdict(entry) for entry in run.entries],
        "ignored": [asdict(record) for record in run.ignored],
        "conflicts": [asdict(record) for record in run.conflicts],
        "failures": [asdict(record) for record in run.failures],
        "catalog": [asdict(entry) for entry in run.catalog],
        "summary": asdict(
            build_summary(
                entries=list(run.entries),
                ignored=list(run.ignored),
                conflicts_count=len(run.conflicts),
                failures=list(run.failures),
                catalog_count=len(run.catalog),
            )
        ),
    }


def _classification_result(
    inspector: Inspector,
    manifest: dict[str, Any],
    *,
    reused: bool,
) -> object:
    """按 manifest 审计数组生成 PASS/WARN 结果。"""
    counts = manifest["summary"]["counts"]
    failures = list(manifest["failures"])
    status = RuleStatus.WARN if failures else RuleStatus.PASS
    catalog_count = int(counts["catalog"])
    total = int(counts["landed"]) + int(counts["ignored"]) + int(counts["failures"])
    summary = f"分类完成，{catalog_count} 项可巡检"
    if failures:
        summary += f"；{len(failures)} 项局部失败已隔离"
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metadata={
            "reused": reused,
            "profile": manifest["classification"]["profile"],
            "config_fingerprint": manifest["classification"]["config_fingerprint"],
            "extracted": catalog_count,
            "total": total,
            "failed": len(failures),
            "failures": failures,
            "ignored": int(counts["ignored"]),
            "conflicts": int(counts["conflicts"]),
            "catalog_count": catalog_count,
        },
    )


def _log_classification_audit(
    ctx: RuleContext,
    manifest: dict[str, Any],
    *,
    reused: bool,
) -> None:
    """输出可逐项追溯的分类审计事件。"""
    summary_data = manifest["summary"]
    summary = Summary(
        counts=SummaryCounts(**summary_data["counts"]),
        by_route=dict(summary_data["by_route"]),
        by_category=dict(summary_data["by_category"]),
        by_action=dict(summary_data["by_action"]),
        by_status=dict(summary_data["by_status"]),
    )
    event = build_audit_event(
        entries=[LandedEntry(**item) for item in manifest["entries"]],
        ignored=[IgnoredRecord(**item) for item in manifest["ignored"]],
        conflicts=[ConflictRecord(**item) for item in manifest["conflicts"]],
        failures=[FailureRecord(**item) for item in manifest["failures"]],
        catalog_count=len(manifest["catalog"]),
        summary=summary,
    )
    ctx.log(
        "warn" if event["counts"]["failures"] else "info",
        "classification_audit",
        task_id=ctx.task_id,
        rule_code=classification_inspector.code,
        reused=reused,
        **event,
    )


def _run_classification(ctx: RuleContext) -> object:
    if ctx.package_path is None or not ctx.package_path.exists():
        return _error_result(
            classification_inspector,
            "分类失败: 未找到数据包",
            error_code="archive_corrupt",
            error=f"数据包不存在: {ctx.package_path}",
            package=str(ctx.package_path) if ctx.package_path else None,
        )

    checksum = ctx.package_checksum
    try:
        checksum = ctx.ensure_package_checksum()
        config = load_classification_config(settings.config / "classify_rules.yaml")
        path_policy = PathLimitPolicy.current()
        context = _current_reuse_context(
            ctx,
            checksum,
            config=config,
            path_policy=path_policy,
        )
        reusable = site.reusable_extraction_site(ctx.package_path, ctx.data_dir, context)
    except ClassificationConfigError as exc:
        detail = exc.to_detail()
        ctx.log(
            "error",
            "分类配置无效",
            task_id=ctx.task_id,
            rule_code=classification_inspector.code,
            checksum=checksum,
            detail=detail,
        )
        return _error_result(
            classification_inspector,
            f"分类配置无效: {exc}",
            error_code=exc.code,
            error=str(exc),
            detail=detail,
        )
    except _ClassificationContextError as exc:
        return _error_result(
            classification_inspector,
            f"分类元数据无效: {exc}",
            error_code=exc.code,
            error=str(exc),
        )
    except (archive.ArchiveError, ManifestV5Error, OSError, ValueError) as exc:
        error_code = getattr(exc, "error_code", None) or "archive_corrupt"
        return _error_result(
            classification_inspector,
            f"分类复用校验失败: {exc}",
            error_code=error_code,
            error=str(exc),
            checksum=checksum,
        )

    if reusable is not None:
        try:
            ctx.catalog = None
            ctx.ensure_catalog()
        except Exception as exc:  # noqa: BLE001 - catalog 异常必须转为分类 ERROR
            return _error_result(
                classification_inspector,
                f"分类 catalog 构建失败: {exc}",
                error_code="archive_corrupt",
                error=str(exc),
                checksum=checksum,
                reused=True,
            )
        result = _classification_result(classification_inspector, reusable, reused=True)
        _log_classification_audit(ctx, reusable, reused=True)
        return result

    staging = ctx.data_dir / manifest_v5.CLASSIFICATION_STAGING_NAME
    _remove_control_path(staging)
    try:
        run = classify_main_evidence(
            ctx.data_dir,
            product=context.product,
            config=config,
            output_dir=staging,
        )
        manifest = _manifest_for_run(
            data_dir=ctx.data_dir,
            checksum=checksum,
            context=context,
            config=config,
            path_policy=path_policy,
            run=run,
        )
        manifest_v5.publish_classification_run(
            ctx.data_dir,
            manifest,
            staging_dir=staging,
        )
        published = manifest_v5.read_manifest(ctx.data_dir)
        ctx.catalog = None
        ctx.ensure_catalog()
    except (archive.ArchiveError, ManifestV5Error, OSError, ValueError) as exc:
        _remove_control_path(staging)
        error_code = getattr(exc, "error_code", None) or "archive_corrupt"
        ctx.log(
            "error",
            "分类发布失败",
            task_id=ctx.task_id,
            rule_code=classification_inspector.code,
            checksum=checksum,
            error_code=error_code,
            error=str(exc),
        )
        return _error_result(
            classification_inspector,
            f"分类发布失败: {exc}",
            error_code=error_code,
            error=str(exc),
            checksum=checksum,
        )
    except Exception as exc:  # noqa: BLE001 - 隐藏单元必须回传结构化错误而非中断任务
        _remove_control_path(staging)
        ctx.log(
            "error",
            "分类执行异常",
            task_id=ctx.task_id,
            rule_code=classification_inspector.code,
            checksum=checksum,
            error=str(exc),
        )
        return _error_result(
            classification_inspector,
            f"分类执行异常: {exc}",
            error_code="archive_corrupt",
            error=str(exc),
            checksum=checksum,
        )

    result = _classification_result(classification_inspector, published, reused=False)
    _log_classification_audit(ctx, published, reused=False)
    if result.status == RuleStatus.WARN:
        ctx.log(
            "warn",
            "分类存在局部失败，继续执行 prepare 和 inspect",
            task_id=ctx.task_id,
            rule_code=classification_inspector.code,
            failed=result.metadata["failed"],
            ignored=result.metadata["ignored"],
            catalog=result.metadata["catalog_count"],
        )
    return result


classification_inspector.run = _run_classification
registry.register(classification_inspector)
