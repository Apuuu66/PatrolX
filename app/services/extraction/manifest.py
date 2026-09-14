"""解压清单 v3 的读写、校验与复用。"""

import json
from pathlib import Path

from app.services.extraction.layout import MAIN_EVIDENCE_DIR, MANIFEST_NAME, MANIFEST_VERSION, WORK_CATEGORIES


def manifest_path(data_dir: Path) -> Path:
    """返回任务解压 manifest 路径。"""
    return data_dir / MANIFEST_NAME


def read_manifest(data_dir: Path) -> dict:
    """读取 manifest；损坏时返回空结构。"""
    path = manifest_path(data_dir)
    if not path.exists():
        return {"version": MANIFEST_VERSION, "main": None, "subpackages": [], "log_gz": [], "rejected": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": MANIFEST_VERSION, "main": None, "subpackages": [], "log_gz": [], "rejected": []}
    if not isinstance(value, dict):
        return {"version": MANIFEST_VERSION, "main": None, "subpackages": [], "log_gz": [], "rejected": []}
    return value


def write_manifest(data_dir: Path, manifest: dict) -> None:
    """写入 manifest，路径固定在任务目录根。"""
    manifest_path(data_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_valid_manifest(manifest: dict) -> bool:
    """校验 manifest v3 的最小结构，避免损坏状态被误复用。"""
    main = manifest.get("main")
    if (
        manifest.get("version") != MANIFEST_VERSION
        or not isinstance(main, dict)
        or not isinstance(main.get("checksum"), str)
        or not main["checksum"]
        or not isinstance(main.get("count"), int)
        or isinstance(main.get("count"), bool)
        or main["count"] < 0
        or main.get("evidence_path") != MAIN_EVIDENCE_DIR
        or not isinstance(main.get("reused"), bool)
    ):
        return False
    for key in ("subpackages", "log_gz", "rejected"):
        if not isinstance(manifest.get(key), list):
            return False

    for item in manifest["subpackages"]:
        if not isinstance(item, dict):
            return False
        if (
            not isinstance(item.get("source"), str)
            or item.get("category") not in WORK_CATEGORIES
            or not isinstance(item.get("depth"), int)
            or isinstance(item.get("depth"), bool)
            or item.get("status") not in {"extracted", "duplicate", "failed", "rejected"}
            or (item["status"] in {"failed", "rejected"} and not isinstance(item.get("error"), str))
            or (item["status"] == "extracted" and not isinstance(item.get("target"), str))
        ):
            return False

    for item in manifest["log_gz"]:
        if not isinstance(item, dict):
            return False
        if (
            not isinstance(item.get("source_relative_path"), str)
            or not isinstance(item.get("target"), str)
            or not isinstance(item.get("depth"), int)
            or isinstance(item.get("depth"), bool)
            or item.get("status") not in {"extracted", "conflict", "failed", "rejected"}
            or (item["status"] != "extracted" and not isinstance(item.get("error"), str))
        ):
            return False

    for item in manifest["rejected"]:
        if not isinstance(item, dict):
            return False
        if (
            not isinstance(item.get("source"), str)
            or item.get("category") not in WORK_CATEGORIES
            or not isinstance(item.get("reason"), str)
            or not isinstance(item.get("depth"), int)
            or isinstance(item.get("depth"), bool)
        ):
            return False
    return True


def reusable_manifest(data_dir: Path, checksum: str) -> dict | None:
    """校验 manifest v3 和证据现场是否可复用。"""
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
