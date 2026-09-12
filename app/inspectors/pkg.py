"""解压规则族（hidden P0）：主包按类落位 + 各类别嵌套子包安全解压。"""

import hashlib
import json
import shutil
from pathlib import Path

from app.core import archive
from app.core.classify import final_category
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

EXTRACT_MANIFEST = ".patrolx-extracted.json"
CATEGORIES = ["logs", "kpi", "traffic", "alarm", "config", "resource", "other"]
CATEGORY_DIRECTORIES = {"log": "logs", **{name: name for name in CATEGORIES if name != "log"}}


def _checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_path(ctx: RuleContext) -> Path:
    return ctx.data_dir / EXTRACT_MANIFEST


def _load_manifest(ctx: RuleContext) -> dict:
    path = _manifest_path(ctx)
    if not path.exists():
        return {"main": None, "subpackages": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(ctx: RuleContext, manifest: dict) -> None:
    _manifest_path(ctx).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _move_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)


main_inspector = Inspector(
    code="pkg.extract.main",
    name="主包解压与按类落位",
    category=RuleCategory.OTHER,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="2.0.0",
    hidden=True,
    description="安全解压主数据包，按分类规则按类落位，登记嵌套子包清单",
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
    task_dir = ctx.data_dir
    for category in CATEGORIES:
        (task_dir / category).mkdir(parents=True, exist_ok=True)
    try:
        tmp = task_dir / ".main"
        shutil.rmtree(tmp, ignore_errors=True)
        archive.unpack(ctx.package_path, tmp)
    except archive.ArchiveError as exc:
        return make_result(
            main_inspector,
            status=RuleStatus.ERROR,
            summary=f"主包解压失败: {exc}",
            metadata={"package": ctx.package_path.name, "error": str(exc)},
        )

    old_manifest = _load_manifest(ctx)
    checksum = _checksum(ctx.package_path)
    if (old_manifest.get("main") or {}).get("checksum") == checksum:
        shutil.rmtree(tmp, ignore_errors=True)
        count = int(old_manifest.get("main", {}).get("count", 0))
        ctx.log("info", "主包已解压，复用任务现场", checksum=checksum, count=count)
        return make_result(
            main_inspector,
            status=RuleStatus.PASS,
            summary=f"主包已解压，共 {count} 个文件",
            metadata={"count": count, "checksum": checksum, "reused": True},
        )

    manifest: dict = {
        "main": {"checksum": checksum, "count": 0},
        "subpackages": [],
        "rejected": [],
    }
    seen_checksums: set[str] = set()
    for src in sorted(tmp.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(tmp)
        category = final_category(rel.name, src)
        directory = CATEGORY_DIRECTORIES[category.value]
        dest = task_dir / directory / rel.name
        if dest.exists() and _checksum(dest) == _checksum(src):
            manifest["main"]["count"] += 1
            continue
        _move_file(src, dest)
        if archive.is_archive(dest):
            item = {
                "name": rel.name,
                "category": directory,
                "checksum": _checksum(dest),
                "extracted": False,
                "path": str(dest.relative_to(task_dir)),
                "error": None,
            }
            if item["checksum"] in seen_checksums:
                ctx.log("info", "嵌套子包 checksum 重复，跳过解压", package=item["name"], checksum=item["checksum"])
                item["extracted"] = True
                item["duplicate"] = True
            else:
                seen_checksums.add(item["checksum"])
            manifest["subpackages"].append(item)
        manifest["main"]["count"] += 1
    shutil.rmtree(tmp, ignore_errors=True)
    _save_manifest(ctx, manifest)
    ctx.log("info", "主包解压完成", count=manifest["main"]["count"], package=ctx.package_path.name)
    return make_result(
        main_inspector,
        status=RuleStatus.PASS,
        summary=f"主包解压完成，共 {manifest['main']['count']} 个文件",
        metadata={"count": manifest["main"]["count"], "checksum": checksum},
    )


main_inspector.run = _run_main
registry.register(main_inspector)


def _make_category_inspector(category: str) -> Inspector:
    inspector = Inspector(
        code=f"pkg.extract.{category}",
        name=f"{category} 类子包解压",
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P0,
        rule_version="2.0.0",
        hidden=True,
        description=f"按需解压 {category} 类嵌套子包（checksum 去重、只解压一次）",
        recommendation="子包解压失败时检查包完整性与安全限制",
    )

    def run(ctx: RuleContext) -> object:
        manifest = _load_manifest(ctx)
        pending = [p for p in manifest.get("subpackages", []) if p["category"] == category]
        if not pending:
            return make_result(inspector, status=RuleStatus.PASS, summary=f"{category} 类无嵌套子包")
        extracted = 0
        failed = 0
        for item in pending:
            if item.get("extracted"):
                extracted += 1
                continue
            src = ctx.data_dir / item["path"]
            target = ctx.data_dir / category / item["name"].rsplit(".", 1)[0]
            try:
                archive.unpack(src, target)
                item["extracted"] = True
                item["error"] = None
                item["target"] = str(target.relative_to(ctx.data_dir))
                extracted += 1
                ctx.log("info", "嵌套子包解压完成", package=item["name"], target=item["target"])
            except archive.ArchiveError as exc:
                item["extracted"] = False
                item["error"] = str(exc)
                failed += 1
                ctx.log("error", "嵌套子包解压失败", package=item["name"], error=str(exc))
        _save_manifest(ctx, manifest)
        status = RuleStatus.PASS if failed == 0 else RuleStatus.WARN
        return make_result(
            inspector,
            status=status,
            summary=f"{category} 类嵌套子包解压 {extracted}/{len(pending)}",
            metadata={"extracted": extracted, "total": len(pending), "failed": failed},
        )

    inspector.run = run
    registry.register(inspector)
    return inspector


for _cat in CATEGORIES:
    _make_category_inspector(_cat)
