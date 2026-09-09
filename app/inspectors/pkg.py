"""解压规则族（hidden P0）：主包按类落位 + 各类别子包懒解压。"""

import hashlib
import json
import shutil
from pathlib import Path

from app.core import archive
from app.core.classify import classify_name, final_category
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

EXTRACT_MANIFEST = ".patrolx-extracted.json"
CATEGORIES = ["log", "kpi", "traffic", "alarm", "config", "resource", "other"]


def _checksum(path: Path) -> str:
    h = hashlib.md5()
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
    rule_version="1.0.0",
    hidden=True,
    description="解压主数据包，按分类规则按类落位，登记嵌套子包清单",
    recommendation="主包无法解压时检查包格式与安全限制",
    outputs_artifacts=["pkg.extract.main.ready"],
)


def _run_main(ctx: RuleContext) -> object:
    if ctx.package_path is None or not ctx.package_path.exists():
        return make_result(
            main_inspector,
            status=RuleStatus.ERROR,
            summary="未找到数据包",
            metadata={"package": str(ctx.package_path) if ctx.package_path else None},
        )
    try:
        tmp = ctx.data_dir / ".main"
        archive.unpack(ctx.package_path, tmp)
    except archive.ArchiveError as exc:
        return make_result(
            main_inspector,
            status=RuleStatus.ERROR,
            summary=f"主包解压失败: {exc}",
            metadata={"package": ctx.package_path.name},
        )

    manifest: dict = {"main": {"checksum": _checksum(ctx.package_path), "count": 0}, "subpackages": []}
    for src in sorted(tmp.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(tmp)
        if archive.is_archive(src):
            category = final_category(rel.name, src)
            dest = ctx.data_dir / category.value / rel.name
            _move_file(src, dest)
            manifest["subpackages"].append(
                {
                    "name": rel.name,
                    "category": category.value,
                    "checksum": _checksum(dest),
                    "extracted": False,
                    "path": str(dest.relative_to(ctx.data_dir)),
                }
            )
            manifest["main"]["count"] += 1
        else:
            category = classify_name(rel.name) or RuleCategory.OTHER
            parts = list(rel.parts)
            if parts and parts[0] == category.value:
                parts = parts[1:]
            dest = ctx.data_dir / category.value / Path(*parts) if parts else ctx.data_dir / category.value
            _move_file(src, dest)
            manifest["main"]["count"] += 1
    shutil.rmtree(tmp, ignore_errors=True)
    _save_manifest(ctx, manifest)
    marker = ctx.rule_artifact_path(main_inspector.code, main_inspector.outputs_artifacts[0])
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    ctx.log("info", "主包解压完成", count=manifest["main"]["count"], package=ctx.package_path.name)
    return make_result(
        main_inspector,
        status=RuleStatus.PASS,
        summary=f"主包解压完成，共 {manifest['main']['count']} 个文件",
        metadata={"count": manifest["main"]["count"]},
    )


main_inspector.run = _run_main
registry.register(main_inspector)


def _make_category_inspector(category: str) -> Inspector:
    ready_key = f"pkg.extract.{category}.ready"

    def run(ctx: RuleContext) -> object:
        manifest = _load_manifest(ctx)
        pending = [p for p in manifest.get("subpackages", []) if p["category"] == category and not p["extracted"]]
        marker = ctx.rule_artifact_path(inspector.code, ready_key)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")
        if not pending:
            return make_result(
                inspector,
                status=RuleStatus.PASS,
                summary=f"{category} 类无待解压子包",
            )
        extracted = 0
        for item in pending:
            src = ctx.data_dir / item["path"]
            if not src.exists():
                continue
            target = ctx.data_dir / category / item["name"].rsplit(".", 1)[0]
            try:
                archive.unpack(src, target)
                item["extracted"] = True
                extracted += 1
            except archive.ArchiveError as exc:
                ctx.log("warn", f"子包解压失败: {item['name']}", error=str(exc))
        _save_manifest(ctx, manifest)
        return make_result(
            inspector,
            status=RuleStatus.PASS if extracted == len(pending) else RuleStatus.WARN,
            summary=f"{category} 类子包解压 {extracted}/{len(pending)}",
            metadata={"extracted": extracted, "total": len(pending)},
        )

    inspector = Inspector(
        code=f"pkg.extract.{category}",
        name=f"{category} 类子包解压",
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P0,
        rule_version="1.0.0",
        hidden=True,
        description=f"按需解压 {category} 类嵌套子包（清单去重、只解压一次）",
        recommendation="子包解压失败时检查包完整性",
        inputs=["pkg.extract.main.ready"],
        outputs_artifacts=[ready_key],
    )
    inspector.run = run
    registry.register(inspector)
    return inspector


for _cat in CATEGORIES:
    _make_category_inspector(_cat)
