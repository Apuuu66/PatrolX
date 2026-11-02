"""任务解压与分类清单 v5 的严格读写、校验与复用判断。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 5
MAIN_EVIDENCE_DIR = ".main"

PRODUCTS = frozenset({"UMF", "CSP"})
PROFILES = frozenset({"UMF", "CSP", "GENERIC"})
PACKAGE_KINDS = frozenset({"inspection", "log_supplement"})
RULESETS = {
    "UMF": "UMF_ARCHIVE_V1",
    "CSP": "CSP_ARCHIVE_V1",
    "GENERIC": "GENERIC_LOG_V1",
}
LANDED_ACTIONS = frozenset({"copy", "expand", "decompress", "expand_recursive", "select_and_decompress", "fallback"})
IGNORE_ACTIONS = frozenset({"ignore"})
IGNORED_RECORD_ACTIONS = LANDED_ACTIONS | IGNORE_ACTIONS
FAILURE_ACTIONS = frozenset(
    {"copy", "expand", "decompress", "expand_recursive", "select_and_decompress", "fallback", "ignore"}
)
CATEGORIES = frozenset({"config", "status", "operation", "kpi", "alarm", "log", "chr", "other"})
ERROR_CODES = frozenset(
    {
        "archive_depth_exceeded",
        "member_path_depth_exceeded",
        "file_count_exceeded",
        "task_file_count_exceeded",
        "file_too_large",
        "total_bytes_exceeded",
        "archive_corrupt",
        "unsafe_path",
        "link_rejected",
        "duplicate_member",
        "target_conflict",
        "invalid_classification_config",
    }
)
FIXED_BUDGETS = {
    "max_archive_depth": 8,
    "max_member_path_depth": 12,
    "max_archive_files": 100_000,
    "max_task_files": 200_000,
    "max_file_bytes": 2 * 1024 * 1024 * 1024,
    "max_total_bytes": 3 * 1024 * 1024 * 1024,
}
TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "main",
        "product",
        "classification",
        "path_limit",
        "entries",
        "ignored",
        "conflicts",
        "failures",
        "catalog",
        "summary",
    }
)
ENTRY_KEYS = frozenset(
    {
        "source_relative",
        "member_relative",
        "route_id",
        "product",
        "category",
        "original_target",
        "target",
        "action",
        "status",
        "reason",
        "error_code",
        "sha256",
        "size",
    }
)
IGNORED_KEYS = frozenset(
    {
        "source_relative",
        "member_relative",
        "route_id",
        "product",
        "category",
        "original_target",
        "target",
        "action",
        "status",
        "reason",
        "error_code",
    }
)
CONFLICT_KEYS = frozenset({"source_relative", "member_relative", "original_target", "target", "digest", "status"})
FAILURE_KEYS = frozenset(
    {"source_relative", "member_relative", "route_id", "category", "action", "error_code", "reason"}
)
CATALOG_KEYS = frozenset({"path", "category", "route_id", "source_relative", "sha256", "size"})

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ROUTE_ID_RE = re.compile(r"[a-z0-9._-]+")
_DIGEST_RE = re.compile(r"[0-9a-f]{12}")


class ManifestV5Error(ValueError):
    """manifest v5 损坏、 schema 非法或现场不可复用时抛出。"""


class _DuplicateKeyDetector(dict):
    """JSON object_pairs_hook：递归拒绝任意层级重复 key。"""

    def __init__(self, pairs: list[tuple[str, Any]]) -> None:
        super().__init__()
        seen: set[str] = set()
        for key, value in pairs:
            if key in seen:
                raise ManifestV5Error(f"重复 JSON key: {key}")
            seen.add(key)
            self[key] = value


def manifest_path(data_dir: Path | str) -> Path:
    """返回分类现场唯一发布凭据路径。"""
    return Path(data_dir) / MANIFEST_NAME


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _exact_keys(value: object, keys: frozenset[str]) -> bool:
    return isinstance(value, dict) and frozenset(value) == keys


def _is_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("/") or "\\" in value or "\x00" in value:
        return False
    segments = value.split("/")
    return not any(segment in {"", ".", ".."} for segment in segments)


def _is_route_id(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 128 and _ROUTE_ID_RE.fullmatch(value) is not None


def _is_optional_relative_path(value: object) -> bool:
    return value is None or _is_relative_path(value)


def _path_limit_fingerprint(enabled: bool, limit: int | None) -> str:
    payload = json.dumps(
        {"enabled": enabled, "limit": limit},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_main(main: object) -> bool:
    if not _exact_keys(main, frozenset({"checksum", "count", "evidence_path", "evidence_fingerprint", "reused"})):
        return False
    return (
        _is_sha256(main["checksum"])
        and _is_int(main["count"])
        and main["count"] >= 0
        and main["evidence_path"] == MAIN_EVIDENCE_DIR
        and _is_sha256(main["evidence_fingerprint"])
        and isinstance(main["reused"], bool)
    )


def _validate_path_limit(path_limit: object) -> bool:
    if not _exact_keys(path_limit, frozenset({"enabled", "limit", "fingerprint"})):
        return False
    enabled = path_limit["enabled"]
    limit = path_limit["limit"]
    if not isinstance(enabled, bool):
        return False
    if enabled:
        if not _is_int(limit) or limit <= 0:
            return False
    elif limit is not None:
        return False
    return _is_sha256(path_limit["fingerprint"]) and path_limit["fingerprint"] == _path_limit_fingerprint(
        enabled,
        limit,
    )


def _validate_scene_root(value: object, profile: str) -> bool:
    if not isinstance(value, str):
        return False
    if profile == "GENERIC":
        return value == MAIN_EVIDENCE_DIR
    if value == MAIN_EVIDENCE_DIR:
        return True
    if not value.startswith(f"{MAIN_EVIDENCE_DIR}/"):
        return False
    relative = value[len(MAIN_EVIDENCE_DIR) + 1 :]
    return _is_relative_path(relative)


def _validate_classification(classification: object, product: object, path_limit: dict) -> tuple[bool, dict | None]:
    if not _exact_keys(classification, frozenset({"config_fingerprint", "profile", "snapshot"})):
        return False, None
    profile = classification["profile"]
    snapshot = classification["snapshot"]
    snapshot_keys = frozenset(
        {
            "package_kind",
            "product",
            "profile",
            "ruleset",
            "config_fingerprint",
            "extraction_policy_fingerprint",
            "path_limit_fingerprint",
            "scene_root",
            "target_roots",
            "budgets",
        }
    )
    if profile not in PROFILES or not _exact_keys(snapshot, snapshot_keys):
        return False, None
    if classification["config_fingerprint"] != snapshot["config_fingerprint"]:
        return False, None
    if profile != snapshot["profile"]:
        return False, None
    if not _is_sha256(classification["config_fingerprint"]):
        return False, None
    if not _is_sha256(snapshot["extraction_policy_fingerprint"]):
        return False, None
    if snapshot["path_limit_fingerprint"] != path_limit["fingerprint"]:
        return False, None
    package_kind = snapshot["package_kind"]
    if package_kind not in PACKAGE_KINDS:
        return False, None
    if snapshot["ruleset"] != RULESETS[profile]:
        return False, None
    if package_kind == "inspection":
        if product not in PRODUCTS or snapshot["product"] != product or profile != product:
            return False, None
    elif snapshot["product"] is not None or product is not None or profile != "GENERIC":
        return False, None
    if not _validate_scene_root(snapshot["scene_root"], profile):
        return False, None
    target_roots = snapshot["target_roots"]
    if (
        not isinstance(target_roots, list)
        or not target_roots
        or len(target_roots) != len(set(target_roots))
        or target_roots != sorted(target_roots)
        or not all(isinstance(item, str) and _is_relative_path(item) and "/" not in item for item in target_roots)
    ):
        return False, None
    if snapshot["budgets"] != FIXED_BUDGETS:
        return False, None
    return True, snapshot


def _validate_entry(item: object, expected_product: object, target_roots: set[str]) -> bool:
    if not _exact_keys(item, ENTRY_KEYS):
        return False
    return (
        _is_relative_path(item["source_relative"])
        and _is_optional_relative_path(item["member_relative"])
        and _is_route_id(item["route_id"])
        and item["product"] == expected_product
        and item["category"] in CATEGORIES
        and _is_relative_path(item["original_target"])
        and _is_relative_path(item["target"])
        and item["target"].split("/", 1)[0] in target_roots
        and item["original_target"].split("/", 1)[0] in target_roots
        and item["action"] in LANDED_ACTIONS
        and item["status"] == "landed"
        and (item["reason"] is None or isinstance(item["reason"], str))
        and item["error_code"] is None
        and _is_sha256(item["sha256"])
        and _is_int(item["size"])
        and item["size"] >= 0
    )


def _validate_ignored(item: object, expected_product: object) -> bool:
    if not _exact_keys(item, IGNORED_KEYS):
        return False
    return (
        _is_relative_path(item["source_relative"])
        and _is_optional_relative_path(item["member_relative"])
        and (item["route_id"] is None or _is_route_id(item["route_id"]))
        and item["product"] == expected_product
        and (item["category"] is None or item["category"] in CATEGORIES)
        and _is_optional_relative_path(item["original_target"])
        and _is_optional_relative_path(item["target"])
        and item["action"] in IGNORED_RECORD_ACTIONS
        and item["status"] == "ignored"
        and isinstance(item["reason"], str)
        and bool(item["reason"])
        and item["error_code"] is None
    )


def _validate_conflict(item: object) -> bool:
    if not _exact_keys(item, CONFLICT_KEYS):
        return False
    return (
        _is_relative_path(item["source_relative"])
        and _is_optional_relative_path(item["member_relative"])
        and _is_relative_path(item["original_target"])
        and _is_relative_path(item["target"])
        and isinstance(item["digest"], str)
        and _DIGEST_RE.fullmatch(item["digest"]) is not None
        and item["status"] == "resolved"
    )


def _validate_failure(item: object) -> bool:
    if not _exact_keys(item, FAILURE_KEYS):
        return False
    return (
        _is_relative_path(item["source_relative"])
        and _is_optional_relative_path(item["member_relative"])
        and _is_route_id(item["route_id"])
        and (item["category"] is None or item["category"] in CATEGORIES)
        and (item["action"] is None or item["action"] in FAILURE_ACTIONS)
        and item["error_code"] in ERROR_CODES
        and isinstance(item["reason"], str)
        and bool(item["reason"])
    )


def _validate_catalog_item(item: object, entries: list[dict], target_roots: set[str]) -> bool:
    if not _exact_keys(item, CATALOG_KEYS):
        return False
    if not (
        _is_relative_path(item["path"])
        and item["path"].split("/", 1)[0] in target_roots
        and item["category"] in CATEGORIES
        and _is_route_id(item["route_id"])
        and _is_relative_path(item["source_relative"])
        and _is_sha256(item["sha256"])
        and _is_int(item["size"])
        and item["size"] >= 0
    ):
        return False
    return any(
        entry["target"] == item["path"]
        and entry["category"] == item["category"]
        and entry["route_id"] == item["route_id"]
        and entry["source_relative"] == item["source_relative"]
        and entry["sha256"] == item["sha256"]
        and entry["size"] == item["size"]
        for entry in entries
    )


def _increase(mapping: dict[str, int], key: object) -> None:
    if isinstance(key, str) and key:
        mapping[key] = mapping.get(key, 0) + 1


def _is_count_mapping(value: object, expected: dict[str, int]) -> bool:
    return (
        isinstance(value, dict)
        and frozenset(value) == frozenset(expected)
        and all(_is_int(number) and number >= 0 for number in value.values())
        and all(value[key] == expected[key] for key in expected)
    )


def _is_string_int_mapping(value: object) -> bool:
    return (
        isinstance(value, dict)
        and all(isinstance(key, str) and key for key in value)
        and all(_is_int(number) and number >= 0 for number in value.values())
    )


def _validate_summary(manifest: dict) -> bool:
    summary = manifest["summary"]
    entries: list[dict] = manifest["entries"]
    ignored: list[dict] = manifest["ignored"]
    conflicts: list[dict] = manifest["conflicts"]
    failures: list[dict] = manifest["failures"]
    catalog: list[dict] = manifest["catalog"]
    if not _exact_keys(summary, frozenset({"counts", "by_route", "by_category", "by_action", "by_status"})):
        return False
    expected_counts = {
        "landed": len(entries),
        "ignored": len(ignored),
        "conflicts": len(conflicts),
        "failures": len(failures),
        "catalog": len(catalog),
    }
    if not _is_count_mapping(summary["counts"], expected_counts):
        return False
    by_route: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for item in entries:
        _increase(by_route, item["route_id"])
        _increase(by_category, item["category"])
        _increase(by_action, item["action"])
    for item in ignored:
        _increase(by_route, item["route_id"])
        _increase(by_category, item["category"])
        _increase(by_action, item["action"])
    for item in failures:
        _increase(by_route, item["route_id"])
        _increase(by_action, item["action"])
    expected_status = {"landed": len(entries), "ignored": len(ignored), "failed": len(failures)}
    return (
        _is_string_int_mapping(summary["by_route"])
        and summary["by_route"] == dict(sorted(by_route.items()))
        and _is_string_int_mapping(summary["by_category"])
        and summary["by_category"] == dict(sorted(by_category.items()))
        and _is_string_int_mapping(summary["by_action"])
        and summary["by_action"] == dict(sorted(by_action.items()))
        and _is_count_mapping(summary["by_status"], expected_status)
    )


def _validate_record_relations(manifest: dict, snapshot: dict) -> bool:
    entries: list[dict] = manifest["entries"]
    conflicts: list[dict] = manifest["conflicts"]
    catalog: list[dict] = manifest["catalog"]
    target_roots = set(snapshot["target_roots"])
    expected_product = snapshot["product"]
    if not all(_validate_entry(item, expected_product, target_roots) for item in entries):
        return False
    if not all(_validate_ignored(item, expected_product) for item in manifest["ignored"]):
        return False
    if not all(_validate_failure(item) for item in manifest["failures"]):
        return False
    identities = [(item["source_relative"], item["member_relative"]) for item in entries]
    if len(identities) != len(set(identities)):
        return False
    targets = [item["target"] for item in entries]
    if len(targets) != len(set(targets)):
        return False
    if not all(_validate_conflict(item) for item in conflicts):
        return False
    entry_index = {
        (item["source_relative"], item["member_relative"], item["original_target"], item["target"]): item
        for item in entries
    }
    for conflict in conflicts:
        key = (
            conflict["source_relative"],
            conflict["member_relative"],
            conflict["original_target"],
            conflict["target"],
        )
        if key not in entry_index:
            return False
    catalog_paths = [item["path"] for item in catalog]
    if catalog_paths != sorted(catalog_paths) or len(catalog_paths) != len(set(catalog_paths)):
        return False
    return all(_validate_catalog_item(item, entries, target_roots) for item in catalog)


def validate_manifest(manifest: object) -> bool:
    """仅校验 manifest v5 内存结构和内部一致性；不读取磁盘文件。"""
    if not _exact_keys(manifest, TOP_LEVEL_KEYS) or manifest["version"] != MANIFEST_VERSION:
        return False
    if not _validate_main(manifest["main"]):
        return False
    product = manifest["product"]
    if product is not None and product not in PRODUCTS:
        return False
    if not _validate_path_limit(manifest["path_limit"]):
        return False
    classification_ok, snapshot = _validate_classification(
        manifest["classification"],
        product,
        manifest["path_limit"],
    )
    if not classification_ok or snapshot is None:
        return False
    for key in ("entries", "ignored", "conflicts", "failures", "catalog"):
        if not isinstance(manifest[key], list):
            return False
    if not _validate_record_relations(manifest, snapshot):
        return False
    return _validate_summary(manifest)


def _check_top_level_keys(manifest: object) -> None:
    """提供顶层键错误的稳定中文原因。"""
    if not isinstance(manifest, dict):
        raise ManifestV5Error("manifest v5 根节点必须是对象")
    unknown = sorted(frozenset(manifest) - TOP_LEVEL_KEYS)
    if unknown:
        raise ManifestV5Error(f"未知顶层字段: {', '.join(unknown)}")
    missing = sorted(TOP_LEVEL_KEYS - frozenset(manifest))
    if missing:
        raise ManifestV5Error(f"缺少顶层字段: {', '.join(missing)}")


def loads_manifest(text: str | bytes) -> dict[str, Any]:
    """解析重复 key 时即失败，并执行完整 v5 schema 校验。"""
    try:
        manifest = json.loads(text, object_pairs_hook=_DuplicateKeyDetector)
    except (json.JSONDecodeError, ManifestV5Error) as exc:
        raise ManifestV5Error(str(exc)) from exc
    _check_top_level_keys(manifest)
    if not validate_manifest(manifest):
        raise ManifestV5Error("manifest v5 结构校验失败")
    return manifest


def read_manifest(data_dir: Path | str) -> dict[str, Any]:
    """读取并严格校验 manifest.json；缺失或损坏均抛出 ManifestV5Error。"""
    path = manifest_path(data_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestV5Error(f"无法读取 manifest v5: {path}") from exc
    return loads_manifest(text)


def write_manifest(data_dir: Path | str, manifest: dict[str, Any]) -> None:
    """完整校验通过后将 v5 payload 发布到 manifest.json。"""
    if not validate_manifest(manifest):
        raise ManifestV5Error("拒绝写入无效 manifest v5")
    path = manifest_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _scan_evidence(root: Path) -> tuple[int, str]:
    files: list[dict[str, object]] = []

    def scan(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_symlink():
                    raise ManifestV5Error(f"证据现场包含链接: {path}")
                if entry.is_dir(follow_symlinks=False):
                    scan(path)
                elif entry.is_file(follow_symlinks=False):
                    relative = path.relative_to(root).as_posix()
                    files.append(
                        {
                            "path": relative,
                            "size": entry.stat(follow_symlinks=False).st_size,
                            "sha256": sha256_file(path),
                        }
                    )
                else:
                    raise ManifestV5Error(f"证据现场包含非普通文件: {path}")

    scan(root)
    files.sort(key=lambda item: item["path"])
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return len(files), hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """计算普通文件 SHA-256；调用方必须先确认其不是链接。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_fingerprint(data_dir: Path | str) -> tuple[int, str]:
    """计算 `.main/` 证据现场的普通文件数与内容指纹。"""
    root = Path(data_dir) / MAIN_EVIDENCE_DIR
    if not root.is_dir() or root.is_symlink():
        raise ManifestV5Error("证据现场 .main 不存在或不是普通目录")
    return _scan_evidence(root)


def _verify_catalog_files(data_dir: Path, manifest: dict[str, Any]) -> bool:
    for item in manifest["catalog"]:
        path = data_dir / item["path"]
        if (
            not path.is_relative_to(data_dir.resolve())
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != item["size"]
            or sha256_file(path) != item["sha256"]
        ):
            return False
    return True


def reusable_manifest(data_dir: Path | str, checksum: str) -> dict[str, Any] | None:
    """仅在 v5 schema、主包校验和、证据指纹与 catalog 摘要全部一致时复用。"""
    root = Path(data_dir)
    try:
        manifest = read_manifest(root)
        if manifest["main"]["checksum"] != checksum or not _is_sha256(checksum):
            return None
        count, fingerprint = evidence_fingerprint(root)
        if manifest["main"]["count"] != count or manifest["main"]["evidence_fingerprint"] != fingerprint:
            return None
        if not _verify_catalog_files(root.resolve(), manifest):
            return None
    except (ManifestV5Error, OSError):
        return None
    return manifest
