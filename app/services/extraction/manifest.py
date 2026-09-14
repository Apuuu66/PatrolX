"""解压清单 v4 的读写、校验与复用。"""

import json
from pathlib import Path

from app.services.extraction.layout import (
    MAIN_EVIDENCE_DIR,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    WORK_CATEGORIES,
)

_ITEM_STATUSES = {"extracted", "conflict", "duplicate", "skipped", "failed", "rejected"}
_POLICY_REASONS = {"global_retain", "skip_path", "whitelist_path", "whitelist_keyword"}
_POLICY_COUNTERS = {
    "skipped_subpackages",
    "skipped_log_gz",
    "whitelisted_subpackages",
    "whitelisted_log_gz",
    "whitelisted_files",
}
_ERROR_CODES = {"path_too_long", "target_conflict", "duplicate", "budget_exceeded", "policy_skip"}


def manifest_path(data_dir: Path) -> Path:
    """返回任务解压 manifest 路径。"""
    return data_dir / MANIFEST_NAME


def read_manifest(data_dir: Path) -> dict:
    """读取 manifest；损坏时返回空结构。"""
    empty: dict = {
        "version": MANIFEST_VERSION,
        "main": None,
        "files": [],
        "subpackages": [],
        "log_gz": [],
        "rejected": [],
    }
    path = manifest_path(data_dir)
    if not path.exists():
        return empty
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    return value if isinstance(value, dict) else empty


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_optional_nonnegative_int(item: dict, key: str) -> bool:
    return item.get(key) is None or _is_nonnegative_int(item.get(key))


def _is_valid_policy_item(policy: object) -> bool:
    return (
        isinstance(policy, dict)
        and set(policy) == {"action", "reason", "scope", "keyword"}
        and policy.get("action") in {"skip", "whitelist"}
        and policy.get("reason") in _POLICY_REASONS
        and (policy.get("scope") is None or isinstance(policy.get("scope"), str))
        and (policy.get("keyword") is None or isinstance(policy.get("keyword"), str))
    )


def _is_valid_policy_snapshot(policy: object) -> bool:
    if not isinstance(policy, dict) or set(policy) != {
        "fingerprint",
        "skip_all",
        "skip_paths",
        "whitelist_paths",
        "whitelist_keywords",
        "counters",
    }:
        return False
    fingerprint = policy.get("fingerprint")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in fingerprint)
        or not isinstance(policy.get("skip_all"), bool)
    ):
        return False
    for key in ("skip_paths", "whitelist_paths", "whitelist_keywords"):
        value = policy.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            return False
    counters = policy.get("counters")
    return (
        isinstance(counters, dict)
        and set(counters) == _POLICY_COUNTERS
        and all(_is_nonnegative_int(counters.get(key)) for key in _POLICY_COUNTERS)
    )


def _is_valid_path_limit(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"enabled", "limit", "fingerprint"}
        and isinstance(value.get("enabled"), bool)
        and (value.get("limit") is None or _is_nonnegative_int(value.get("limit")))
        and isinstance(value.get("fingerprint"), str)
        and len(value["fingerprint"]) == 64
        and all(char in "0123456789abcdef" for char in value["fingerprint"])
    )


def _item_error_fields(item: dict) -> bool:
    if item.get("error") is not None and not isinstance(item.get("error"), str):
        return False
    if item.get("error_code") is not None and item.get("error_code") not in _ERROR_CODES:
        return False
    return _is_optional_nonnegative_int(item, "path_length") and _is_optional_nonnegative_int(item, "path_limit")


def _is_valid_policy_entry(item: dict, status: str) -> bool:
    if "policy" in item and not _is_valid_policy_item(item["policy"]):
        return False
    if status == "skipped":
        target = item.get("target")
        return isinstance(target, str) and bool(target) and item.get("error") is None
    return True


def sync_policy_counters(manifest: dict) -> dict[str, int]:
    """根据 manifest 条目重建策略成功保留/恢复计数；普通文件计数保留原值。"""
    counters = (manifest.get("policy") or {}).get("counters")
    whitelisted_files = counters.get("whitelisted_files", 0) if isinstance(counters, dict) else 0
    result = {
        "skipped_subpackages": sum(
            1 for item in manifest.get("subpackages", []) if isinstance(item, dict) and item.get("status") == "skipped"
        ),
        "skipped_log_gz": sum(
            1 for item in manifest.get("log_gz", []) if isinstance(item, dict) and item.get("status") == "skipped"
        ),
        "whitelisted_subpackages": sum(
            1
            for item in manifest.get("subpackages", [])
            if isinstance(item, dict)
            and item.get("status") == "extracted"
            and isinstance(item.get("policy"), dict)
            and item["policy"].get("action") == "whitelist"
        ),
        "whitelisted_log_gz": sum(
            1
            for item in manifest.get("log_gz", [])
            if isinstance(item, dict)
            and item.get("status") == "extracted"
            and isinstance(item.get("policy"), dict)
            and item["policy"].get("action") == "whitelist"
        ),
        "whitelisted_files": whitelisted_files if _is_nonnegative_int(whitelisted_files) else 0,
    }
    if isinstance(manifest.get("policy"), dict):
        manifest["policy"]["counters"] = result
    return result


def _validate_file(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    status = item.get("status")
    if (
        not isinstance(item.get("source"), str)
        or not item["source"]
        or not isinstance(item.get("target"), str)
        or not item["target"]
        or item.get("category") not in WORK_CATEGORIES
        or status not in _ITEM_STATUSES
        or (status not in {"extracted", "conflict", "skipped"} and not isinstance(item.get("error"), str))
        or (status in {"extracted", "skipped"} and item.get("error") is not None)
        or (status == "conflict" and not isinstance(item.get("error"), str))
    ):
        return False
    return _item_error_fields(item)


def _validate_subpackage(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    status = item.get("status")
    if (
        not isinstance(item.get("source"), str)
        or not item["source"]
        or item.get("category") not in WORK_CATEGORIES
        or not _is_nonnegative_int(item.get("depth"))
        or status not in _ITEM_STATUSES
        or (status in {"failed", "rejected", "conflict"} and not isinstance(item.get("error"), str))
        or (status == "extracted" and not isinstance(item.get("target"), str))
    ):
        return False
    return _item_error_fields(item) and _is_valid_policy_entry(item, str(status))


def _validate_log_gz(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    status = item.get("status")
    if (
        not isinstance(item.get("source_relative_path"), str)
        or not item["source_relative_path"]
        or not isinstance(item.get("target"), str)
        or not _is_nonnegative_int(item.get("depth"))
        or status not in _ITEM_STATUSES
        or (status in {"conflict", "failed", "rejected"} and not isinstance(item.get("error"), str))
    ):
        return False
    return _item_error_fields(item) and _is_valid_policy_entry(item, str(status))


def validate_manifest(manifest: dict, *, require_policy: bool = False) -> bool:
    """校验 manifest v4；新现场必须包含策略和路径限制上下文。"""
    main = manifest.get("main")
    if (
        manifest.get("version") != MANIFEST_VERSION
        or not isinstance(main, dict)
        or not isinstance(main.get("checksum"), str)
        or not main["checksum"]
        or not _is_nonnegative_int(main.get("count"))
        or main.get("evidence_path") != MAIN_EVIDENCE_DIR
        or not isinstance(main.get("reused"), bool)
    ):
        return False
    for key in ("files", "subpackages", "log_gz", "rejected"):
        if not isinstance(manifest.get(key), list):
            return False
    if "path_limit" in manifest and not _is_valid_path_limit(manifest["path_limit"]):
        return False
    if not all(_validate_file(item) for item in manifest["files"]):
        return False
    if not all(_validate_subpackage(item) for item in manifest["subpackages"]):
        return False
    if not all(_validate_log_gz(item) for item in manifest["log_gz"]):
        return False

    for item in manifest["rejected"]:
        if not isinstance(item, dict):
            return False
        if (
            not isinstance(item.get("source"), str)
            or item.get("category") not in {*WORK_CATEGORIES, "log"}
            or not isinstance(item.get("reason"), str)
            or not _is_nonnegative_int(item.get("depth"))
        ):
            return False

    if "policy" in manifest and not _is_valid_policy_snapshot(manifest["policy"]):
        return False
    return not require_policy or (
        _is_valid_policy_snapshot(manifest.get("policy")) and _is_valid_path_limit(manifest.get("path_limit"))
    )


def _is_valid_manifest(manifest: dict) -> bool:
    """manifest 复用前的完整结构校验。"""
    return validate_manifest(manifest, require_policy=False)


def write_manifest(data_dir: Path, manifest: dict) -> None:
    """写入新 manifest；新现场必须携带完整策略快照和路径限制上下文。"""
    if not validate_manifest(manifest, require_policy=True):
        raise ValueError("manifest v4 缺少策略快照、路径限制上下文或包含无效状态")
    sync_policy_counters(manifest)
    manifest_path(data_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def reusable_manifest(data_dir: Path, checksum: str) -> dict | None:
    """校验 manifest v4、证据现场、checksum 和路径限制上下文是否可复用。"""
    manifest = read_manifest(data_dir)
    main = manifest.get("main")
    if (
        not _is_valid_manifest(manifest)
        or not isinstance(main, dict)
        or main.get("checksum") != checksum
        or not (data_dir / MAIN_EVIDENCE_DIR).is_dir()
    ):
        return None
    return manifest
