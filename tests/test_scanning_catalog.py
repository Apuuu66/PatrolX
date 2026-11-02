"""TaskFileCatalog 只消费 manifest v5 catalog 的契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.extraction.layout import PathLimitPolicy
from app.services.extraction.manifest import (
    FIXED_BUDGETS,
    ManifestV5Error,
    evidence_fingerprint,
    sha256_file,
    write_manifest,
)
from app.services.scanning import TaskFileCatalog

CONFIG_FINGERPRINT = "a" * 64
EXTRACTION_POLICY_FINGERPRINT = "b" * 64
MAIN_CHECKSUM = "c" * 64


def _manifest(data_dir: Path, targets: list[str]) -> dict:
    """构造 catalog 与 entry 一一对应的最小有效 v5 manifest。"""
    source_root = data_dir / ".main/source"
    source_root.mkdir(parents=True)
    entries: list[dict] = []
    catalog: list[dict] = []
    for index, target in enumerate(targets):
        source = source_root / f"{index}.txt"
        source.write_text(f"source-{index}", encoding="utf-8")
        output = data_dir / target
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"target-{index}", encoding="utf-8")
        digest = sha256_file(output)
        size = output.stat().st_size
        source_relative = f"source/{index}.txt"
        entries.append(
            {
                "source_relative": source_relative,
                "member_relative": None,
                "route_id": "route.catalog",
                "product": "UMF",
                "category": "config",
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
                "category": "config",
                "route_id": "route.catalog",
                "source_relative": source_relative,
                "sha256": digest,
                "size": size,
            }
        )
    count, fingerprint = evidence_fingerprint(data_dir)
    path_limit = PathLimitPolicy().snapshot()
    return {
        "version": 5,
        "main": {
            "checksum": MAIN_CHECKSUM,
            "count": count,
            "evidence_path": ".main",
            "evidence_fingerprint": fingerprint,
            "reused": False,
        },
        "product": "UMF",
        "classification": {
            "config_fingerprint": CONFIG_FINGERPRINT,
            "profile": "UMF",
            "snapshot": {
                "package_kind": "inspection",
                "product": "UMF",
                "profile": "UMF",
                "ruleset": "UMF_ARCHIVE_V1",
                "config_fingerprint": CONFIG_FINGERPRINT,
                "extraction_policy_fingerprint": EXTRACTION_POLICY_FINGERPRINT,
                "path_limit_fingerprint": path_limit["fingerprint"],
                "scene_root": ".main",
                "target_roots": ["basic", "logs"],
                "budgets": dict(FIXED_BUDGETS),
            },
        },
        "path_limit": path_limit,
        "entries": entries,
        "ignored": [],
        "conflicts": [],
        "failures": [],
        "catalog": catalog,
        "summary": {
            "counts": {
                "landed": len(entries),
                "ignored": 0,
                "conflicts": 0,
                "failures": 0,
                "catalog": len(catalog),
            },
            "by_route": {"route.catalog": len(entries)} if entries else {},
            "by_category": {"config": len(entries)} if entries else {},
            "by_action": {"copy": len(entries)} if entries else {},
            "by_status": {"failed": 0, "ignored": 0, "landed": len(entries)},
        },
    }


def _write_valid(data_dir: Path, targets: list[str]) -> dict:
    manifest = _manifest(data_dir, targets)
    write_manifest(data_dir, manifest)
    return manifest


def _write_raw(data_dir: Path, manifest: dict) -> None:
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )


def test_catalog_uses_only_manifest_entries_in_catalog_order(tmp_path: Path) -> None:
    _write_valid(tmp_path, ["basic/a.txt", "logs/z.log"])
    (tmp_path / "alarm/not-in-manifest.log").parent.mkdir(parents=True)
    (tmp_path / "alarm/not-in-manifest.log").write_text("ignored", encoding="utf-8")

    catalog = TaskFileCatalog.build(tmp_path)

    assert [path.as_posix() for path in catalog.paths()] == ["basic/a.txt", "logs/z.log"]


def test_catalog_does_not_fall_back_to_directory_scanning(tmp_path: Path) -> None:
    _write_valid(tmp_path, [])
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/a.log").write_text("not catalogued", encoding="utf-8")

    catalog = TaskFileCatalog.build(tmp_path)

    assert catalog.paths() == []


def test_catalog_requires_manifest_v5(tmp_path: Path) -> None:
    with pytest.raises(ManifestV5Error, match="无法读取"):
        TaskFileCatalog.build(tmp_path)

    (tmp_path / "manifest.json").write_text('{"version": 4}', encoding="utf-8")
    with pytest.raises(ManifestV5Error):
        TaskFileCatalog.build(tmp_path)


@pytest.mark.parametrize("mutation", ["summary", "order", "traversal"])
def test_catalog_rejects_invalid_manifest_and_catalog_order(tmp_path: Path, mutation: str) -> None:
    manifest = _write_valid(tmp_path, ["basic/a.txt", "logs/z.log"])
    if mutation == "summary":
        manifest["summary"]["counts"]["catalog"] = 1
    elif mutation == "order":
        manifest["catalog"].reverse()
    else:
        manifest["catalog"][0]["path"] = "../escape.txt"
    _write_raw(tmp_path, manifest)

    with pytest.raises(ManifestV5Error):
        TaskFileCatalog.build(tmp_path)


def test_catalog_rejects_file_symlink_and_parent_symlink(tmp_path: Path) -> None:
    _write_valid(tmp_path, ["basic/a.txt"])
    outside = tmp_path.parent / "catalog-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    target = tmp_path / "basic/a.txt"
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(ManifestV5Error, match="链接"):
        TaskFileCatalog.build(tmp_path)

    target.unlink()
    target.write_text("target-0", encoding="utf-8")
    basic = tmp_path / "basic"
    basic.rename(tmp_path / "basic-real")
    basic.symlink_to(tmp_path / "basic-real", target_is_directory=True)
    with pytest.raises(ManifestV5Error, match="链接"):
        TaskFileCatalog.build(tmp_path)


def test_catalog_rejects_size_sha_and_non_regular_catalog_entries(tmp_path: Path) -> None:
    _write_valid(tmp_path, ["basic/a.txt"])
    target = tmp_path / "basic/a.txt"
    target.write_text("tampered", encoding="utf-8")

    with pytest.raises(ManifestV5Error, match="摘要|大小"):
        TaskFileCatalog.build(tmp_path)

    target.unlink()
    target.mkdir()
    with pytest.raises(ManifestV5Error, match="普通文件"):
        TaskFileCatalog.build(tmp_path)


def test_catalog_match_and_resolve_are_limited_to_manifest_paths(tmp_path: Path) -> None:
    _write_valid(tmp_path, ["logs/a.log"])

    catalog = TaskFileCatalog.build(tmp_path)

    assert [path.as_posix() for path in catalog.match([r"logs/a\.log"])] == ["logs/a.log"]
    assert catalog.resolve(Path("logs/a.log")) == (tmp_path / "logs/a.log").resolve()
    with pytest.raises(ValueError, match="匹配路径越界"):
        catalog.resolve(Path("../logs/a.log"))
    with pytest.raises(ValueError, match="不在任务文件清单中"):
        catalog.resolve(Path("prepared/a.csv"))
