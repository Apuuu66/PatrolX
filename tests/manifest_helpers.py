"""测试用 manifest v5 现场构造器；生产代码不得依赖。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.extraction.audit import resolve_target
from app.services.extraction.layout import PathLimitPolicy
from app.services.extraction.manifest import (
    FIXED_BUDGETS,
    evidence_fingerprint,
    sha256_file,
    write_manifest,
)

CONFIG_FINGERPRINT = "a" * 64
EXTRACTION_POLICY_FINGERPRINT = "b" * 64
PACKAGE_CHECKSUM = "c" * 64
ROUTE_ID = "route.test"


_CATEGORY_BY_ROOT = {
    "alarm": "alarm",
    "basic": "config",
    "chr": "chr",
    "debug": "status",
    "host-debug": "log",
    "host-system": "log",
    "kpi": "kpi",
    "logs": "log",
    "mml": "config",
    "operation-log": "operation",
    "other": "other",
    "resource": "status",
    "status": "status",
    "traffic": "other",
}


def write_catalog_manifest(
    data_dir: Path,
    paths: list[str] | tuple[str, ...],
    *,
    ignored: list[dict[str, Any]] | None = None,
    failures: list[dict[str, Any]] | None = None,
    product: str = "UMF",
    profile: str = "UMF",
    package_kind: str = "inspection",
    resolved_conflicts: int = 0,
) -> dict[str, Any]:
    """为给定工作文件构造可通过严格校验的 manifest v5。"""
    evidence_root = data_dir / ".main"
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "test-evidence.bin").write_bytes(b"test evidence")
    entries: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    for index, raw_target in enumerate(sorted(paths)):
        target = raw_target.lstrip("/")
        path = data_dir / target
        if not path.is_file() or path.is_symlink():
            raise AssertionError(f"测试 catalog 文件必须是普通文件: {target}")
        source_relative = f"source/{index}.bin"
        category = _CATEGORY_BY_ROOT.get(Path(target).parts[0], "other")
        digest = sha256_file(path)
        size = path.stat().st_size
        entries.append(
            {
                "source_relative": source_relative,
                "member_relative": None,
                "route_id": ROUTE_ID,
                "product": product,
                "category": category,
                "original_target": target,
                "target": target,
                "action": "copy",
                "status": "landed",
                "reason": None,
                "error_code": None,
                "sha256": digest,
                "size": size,
            }
        )
        catalog.append(
            {
                "path": target,
                "category": category,
                "route_id": ROUTE_ID,
                "source_relative": source_relative,
                "sha256": digest,
                "size": size,
            }
        )
    ignored = ignored or []
    failures = failures or []
    if isinstance(resolved_conflicts, bool) or not isinstance(resolved_conflicts, int):
        raise AssertionError("resolved_conflicts 必须是非负整数")
    if resolved_conflicts < 0 or resolved_conflicts > len(entries):
        raise AssertionError("resolved_conflicts 超出 catalog 条目范围")
    conflicts: list[dict[str, Any]] = []
    for index in range(resolved_conflicts):
        entry = entries[index]
        catalog_item = catalog[index]
        original_target = str(entry["target"])
        target, digest = resolve_target(
            original_target=original_target,
            product=product,
            source_relative=str(entry["source_relative"]),
            member_relative="",
            used_targets={original_target},
        )
        original_path = data_dir / original_target
        target_path = data_dir / target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.replace(target_path)
        entry["target"] = target
        catalog_item["path"] = target
        conflicts.append(
            {
                "source_relative": entry["source_relative"],
                "member_relative": entry["member_relative"],
                "original_target": original_target,
                "target": target,
                "digest": digest,
                "status": "resolved",
            }
        )
    catalog.sort(key=lambda item: item["path"])
    count, fingerprint = evidence_fingerprint(data_dir)
    path_limit = PathLimitPolicy().snapshot()
    target_roots = sorted({Path(item["path"]).parts[0] for item in catalog})
    by_route: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for item in entries:
        by_route[item["route_id"]] = by_route.get(item["route_id"], 0) + 1
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        by_action[item["action"]] = by_action.get(item["action"], 0) + 1
    for item in ignored:
        route_id = item.get("route_id")
        if route_id is not None:
            by_route[route_id] = by_route.get(route_id, 0) + 1
        category = item.get("category")
        if category is not None:
            by_category[category] = by_category.get(category, 0) + 1
        by_action[item["action"]] = by_action.get(item["action"], 0) + 1
    for item in failures:
        by_route[item["route_id"]] = by_route.get(item["route_id"], 0) + 1
        if item["action"] is not None:
            by_action[item["action"]] = by_action.get(item["action"], 0) + 1
    manifest = {
        "version": 5,
        "main": {
            "checksum": PACKAGE_CHECKSUM,
            "count": count,
            "evidence_path": ".main",
            "evidence_fingerprint": fingerprint,
            "reused": False,
        },
        "product": product,
        "classification": {
            "config_fingerprint": CONFIG_FINGERPRINT,
            "profile": profile,
            "snapshot": {
                "package_kind": package_kind,
                "product": product,
                "profile": profile,
                "ruleset": "UMF_ARCHIVE_V1" if profile == "UMF" else "CSP_ARCHIVE_V1",
                "config_fingerprint": CONFIG_FINGERPRINT,
                "extraction_policy_fingerprint": EXTRACTION_POLICY_FINGERPRINT,
                "path_limit_fingerprint": path_limit["fingerprint"],
                "scene_root": ".main",
                "target_roots": target_roots,
                "budgets": dict(FIXED_BUDGETS),
            },
        },
        "path_limit": path_limit,
        "entries": entries,
        "ignored": ignored,
        "conflicts": conflicts,
        "failures": failures,
        "catalog": catalog,
        "summary": {
            "counts": {
                "landed": len(entries),
                "ignored": len(ignored),
                "conflicts": len(conflicts),
                "failures": len(failures),
                "catalog": len(catalog),
            },
            "by_route": dict(sorted(by_route.items())),
            "by_category": dict(sorted(by_category.items())),
            "by_action": dict(sorted(by_action.items())),
            "by_status": {"failed": len(failures), "ignored": len(ignored), "landed": len(entries)},
        },
    }
    write_manifest(data_dir, manifest)
    return manifest
