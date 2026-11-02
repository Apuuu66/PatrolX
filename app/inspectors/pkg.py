"""解压规则族（hidden P0）：主包现场与分类终态校验。"""

import json

from app.core import archive
from app.core.checksum import sha256_file
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services import extraction
from app.services.executor import RuleContext, make_result

EXTRACT_MANIFEST = extraction.MANIFEST_NAME
_FAILED_ITEM_STATUSES = {"conflict", "duplicate", "failed", "rejected"}


def _result_for_manifest(inspector: Inspector, manifest: dict) -> object:
    """主包单元只汇报证据现场状态；局部落位问题由分类单元汇总。"""
    main = manifest.get("main") or {}
    count = int(main.get("count", 0))
    return make_result(
        inspector,
        status=RuleStatus.PASS,
        summary=f"主包解压完成，保留现场并生成 {count} 个原始文件",
        metadata={
            "count": count,
            "checksum": main.get("checksum"),
            "evidence_path": main.get("evidence_path", extraction.MAIN_EVIDENCE_DIR),
            "reused": bool(main.get("reused", False)),
            "subpackages": len(manifest.get("subpackages", [])),
            "log_gz": len(manifest.get("log_gz", [])),
            "rejected": len(manifest.get("rejected", [])),
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
    description="安全解压主数据包到 .main 证据现场，并生成 v4 分类工作现场",
    recommendation="主包无法解压时检查包格式与安全限制",
)


def _run_main(ctx: RuleContext) -> object:
    if ctx.package_path is None or not ctx.package_path.exists():
        return make_result(
            main_inspector,
            status=RuleStatus.ERROR,
            summary="未找到数据包",
            metadata={"package": str(ctx.package_path) if ctx.package_path else None},
        )
    checksum = sha256_file(ctx.package_path)
    try:
        manifest = extraction.extract_main_site(ctx.package_path, ctx.data_dir, checksum, log=ctx.log)
    except archive.ArchiveError as exc:
        ctx.log(
            "error",
            "主包解压失败",
            task_id=ctx.task_id,
            rule_code=main_inspector.code,
            package=ctx.package_path.name,
            checksum=checksum,
            error=str(exc),
        )
        return make_result(
            main_inspector,
            status=RuleStatus.ERROR,
            summary=f"主包解压失败: {exc}",
            metadata={"package": ctx.package_path.name, "checksum": checksum, "error": str(exc)},
        )
    ctx.log(
        "info",
        "主包解压现场已就绪",
        task_id=ctx.task_id,
        rule_code=main_inspector.code,
        checksum=checksum,
        count=int((manifest.get("main") or {}).get("count", 0)),
        reused=bool((manifest.get("main") or {}).get("reused", False)),
    )
    return _result_for_manifest(main_inspector, manifest)


main_inspector.run = _run_main
registry.register(main_inspector)


classification_inspector = Inspector(
    code="pkg.extract.classification",
    name="分类落位终态校验",
    category=RuleCategory.OTHER,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="1.0.0",
    hidden=True,
    description="校验 v4 分类清单并发布本次任务唯一可巡检 catalog",
    recommendation="分类清单无效或 catalog 不一致时检查解压现场",
)


def _manifest_failures(manifest: dict) -> tuple[int, int, list[dict[str, object]]]:
    """汇总 v4 文件、子包、日志 GZIP 与非归档拒绝项的终态。"""
    sources: list[tuple[dict, str | None, bool]] = []
    sources.extend((item, item.get("source"), False) for item in manifest.get("files", []))
    sources.extend((item, item.get("source"), False) for item in manifest.get("subpackages", []))
    sources.extend((item, item.get("source_relative_path"), False) for item in manifest.get("log_gz", []))
    sources.extend((item, item.get("source"), True) for item in manifest.get("rejected", []))

    failures: list[dict[str, object]] = []
    extracted = 0
    for item, source, rejected_entry in sources:
        status = "rejected" if rejected_entry else str(item.get("status", ""))
        if status == "extracted":
            extracted += 1
        if status not in _FAILED_ITEM_STATUSES:
            continue
        failures.append(
            {
                "source": source,
                "target": item.get("target"),
                "status": status,
                "error": item.get("reason") if rejected_entry else item.get("error"),
                "error_code": item.get("error_code"),
            }
        )
    return extracted, len(sources), failures


def _run_classification(ctx: RuleContext) -> object:
    path = extraction.manifest_path(ctx.data_dir)
    try:
        raw = path.read_text(encoding="utf-8")
        manifest = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return make_result(
            classification_inspector,
            status=RuleStatus.ERROR,
            summary=f"分类清单无法读取或解析: {exc}",
            metadata={"error": str(exc), "manifest": str(path)},
        )
    if not isinstance(manifest, dict):
        return make_result(
            classification_inspector,
            status=RuleStatus.ERROR,
            summary="分类清单根节点必须是对象",
            metadata={"error": "manifest_root_not_object", "manifest": str(path)},
        )
    if not extraction.validate_manifest(manifest):
        return make_result(
            classification_inspector,
            status=RuleStatus.ERROR,
            summary="分类清单 v4 校验失败",
            metadata={"error": "invalid_manifest_v4", "manifest": str(path)},
        )

    extracted, total, failures = _manifest_failures(manifest)
    status = RuleStatus.WARN if failures else RuleStatus.PASS
    if failures:
        ctx.log(
            "warn",
            "分类存在局部失败，继续执行 prepare 和 inspect",
            task_id=ctx.task_id,
            rule_code=classification_inspector.code,
            failed=len(failures),
            total=total,
        )
    try:
        ctx.ensure_catalog()
    except Exception as exc:  # noqa: BLE001 - catalog 异常必须转为分类 ERROR
        return make_result(
            classification_inspector,
            status=RuleStatus.ERROR,
            summary=f"分类 catalog 构建失败: {exc}",
            metadata={
                "extracted": extracted,
                "total": total,
                "failed": len(failures),
                "failures": failures,
                "error": str(exc),
            },
        )

    summary = f"分类完成，{total - len(failures)}/{total} 项可巡检" if failures else f"分类完成，{total} 项可巡检"
    return make_result(
        classification_inspector,
        status=status,
        summary=summary,
        metadata={
            "extracted": extracted,
            "total": total,
            "failed": len(failures),
            "failures": failures,
        },
    )


classification_inspector.run = _run_classification
registry.register(classification_inspector)
