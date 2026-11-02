"""迁移保护：生产 extraction 包不得导出 v4 解压与 manifest 入口。"""

from __future__ import annotations

import app.services.extraction as extraction

LEGACY_EXPORTS = {
    "CATEGORY_DIRECTORIES",
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "WORK_CATEGORIES",
    "category_failures",
    "extract_main_site",
    "manifest_path",
    "policy_skipped_summary",
    "read_manifest",
    "reusable_manifest",
    "validate_manifest",
    "write_manifest",
}


def test_extraction_package_exposes_only_v5_entrypoints() -> None:
    """调用方不能通过稳定包入口重新接入 v4 分类目录或旧 manifest。"""
    assert LEGACY_EXPORTS.isdisjoint(extraction.__all__)
    assert not hasattr(extraction, "extract_main_site")
    assert not hasattr(extraction, "WORK_CATEGORIES")
