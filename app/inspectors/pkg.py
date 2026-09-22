"""解压规则族（hidden P0）：统一调用安全解压现场服务。"""

from app.core import archive
from app.core.checksum import sha256_file
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services import extraction
from app.services.executor import RuleContext, make_result

EXTRACT_MANIFEST = extraction.MANIFEST_NAME
CATEGORIES = ["logs", "kpi", "traffic", "alarm", "config", "resource", "other"]


def _result_for_manifest(
    inspector: Inspector,
    manifest: dict,
    *,
    category: str | None = None,
) -> object:
    if category is None:
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

    items = [
        *[item for item in manifest.get("files", []) if item.get("category") == category],
        *[item for item in manifest.get("subpackages", []) if item.get("category") == category],
    ]
    if category == "logs":
        items.extend(manifest.get("log_gz", []))
    failures = extraction.category_failures(manifest, category)
    total = len(items)
    failed = len(failures)
    completed = sum(item.get("status") == "extracted" for item in items)
    status = RuleStatus.PASS if failed == 0 else RuleStatus.WARN
    return make_result(
        inspector,
        status=status,
        summary=f"{category} 类解压 {completed}/{total}",
        metadata={
            "extracted": completed,
            "total": total,
            "failed": failed,
            "failures": failures,
        },
    )


main_inspector = Inspector(
    code="pkg.extract.main",
    name="主包解压与证据现场保留",
    category=RuleCategory.OTHER,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="3.1.0",
    hidden=True,
    description="安全解压主数据包到 .main 证据现场，并递归生成分类工作现场",
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


def _make_category_inspector(category: str) -> Inspector:
    inspector = Inspector(
        code=f"pkg.extract.{category}",
        name=f"{category} 类解压状态检查",
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P0,
        rule_version="3.0.0",
        hidden=True,
        description=f"汇总 {category} 类子包与日志 gzip 解压状态",
        recommendation="解压失败或冲突时查看 manifest 与 .main 原始现场",
    )

    def run(ctx: RuleContext) -> object:
        manifest = extraction.read_manifest(ctx.data_dir)
        failures = extraction.category_failures(manifest, category)
        if failures:
            for failure in failures:
                ctx.log(
                    "error",
                    "分类解压项未成功",
                    task_id=ctx.task_id,
                    rule_code=inspector.code,
                    category=category,
                    target=failure.get("target"),
                    error=failure.get("error"),
                )
        return _result_for_manifest(inspector, manifest, category=category)

    inspector.run = run
    registry.register(inspector)
    return inspector


for _category in CATEGORIES:
    _make_category_inspector(_category)
