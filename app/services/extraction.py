"""安全解压现场与递归子包展开服务。"""

import json
import shutil
from pathlib import Path
from typing import Protocol

from app.core.archive import ArchiveError, UnpackLimit, is_archive, unpack, unpack_gzip
from app.core.checksum import sha256_file
from app.core.classify import classify_file, classify_name
from app.models.schemas import RuleCategory

MANIFEST_NAME = ".patrolx-extracted.json"
MAIN_EVIDENCE_DIR = ".main"
MANIFEST_VERSION = 3
CATEGORY_DIRECTORIES = {
    RuleCategory.LOG.value: "logs",
    RuleCategory.KPI.value: "kpi",
    RuleCategory.TRAFFIC.value: "traffic",
    RuleCategory.ALARM.value: "alarm",
    RuleCategory.CONFIG.value: "config",
    RuleCategory.RESOURCE.value: "resource",
    RuleCategory.OTHER.value: "other",
}
WORK_CATEGORIES = list(CATEGORY_DIRECTORIES.values())


class ExtractionLogger(Protocol):
    """解压过程日志回调；与规则上下文日志签名一致。"""

    def __call__(self, level: str, message: str, **detail: object) -> None: ...


def _log_extract(
    log: ExtractionLogger | None,
    level: str,
    message: str,
    **detail: object,
) -> None:
    """写入解压过程日志；未传入回调时保持静默。"""
    if log is not None:
        log(level, message, **detail)


class ExtractionBudget:
    """任务级累计解压预算；固定限额，避免单个安全包叠加耗尽资源。"""

    max_files = 200_000
    max_total_bytes = 2 * 1024 * 1024 * 1024  # 2GB
    max_depth = 8

    def __init__(self) -> None:
        self.files = 0
        self.bytes = 0

    def charge_file(self, path: Path) -> int:
        self.files += 1
        if self.files > self.max_files:
            raise ArchiveError("任务累计文件数超限")
        size = path.stat().st_size
        self.bytes += size
        if self.bytes > self.max_total_bytes:
            raise ArchiveError("任务累计解压总量超限")
        return size

    def charge_gzip_chunk(self, size: int) -> None:
        self.bytes += size
        if self.bytes > self.max_total_bytes:
            raise ArchiveError("任务累计解压总量超限")


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


def _relative_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _safe_destination(data_dir: Path, relative: Path) -> Path:
    destination = (data_dir / relative).resolve()
    if not destination.is_relative_to(data_dir.resolve()):
        raise ArchiveError(f"目标路径穿越被拒绝: {relative.as_posix()}")
    if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
        raise ArchiveError(f"目标路径包含链接: {relative.as_posix()}")
    return destination


def _unique_work_path(root: Path, relative: Path, checksum: str) -> Path:
    candidate = root / relative
    if not candidate.exists():
        return candidate
    return root / relative.with_name(f"{relative.name}-{checksum[:8]}")


def _remove_empty_work_site(work_path: Path, category_root: Path) -> None:
    """子包成员已移走后，自底向上清理空工作目录及其空父目录。"""
    descendants = sorted(work_path.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in descendants:
        if not path.is_dir():
            return
        try:
            path.rmdir()
        except OSError:
            return
    try:
        work_path.rmdir()
    except OSError:
        return
    current = work_path.parent.resolve()
    root = category_root.resolve()
    while current != root and current.is_relative_to(root):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _category_of(path: Path, parent_category: str) -> tuple[str, str]:
    category = classify_name(path.name) or classify_file(path)
    if category is not None:
        return category.value, "self:name" if classify_name(path.name) else "self:content"
    if parent_category:
        return parent_category, "parent:category"
    return RuleCategory.OTHER.value, "fallback:other"


def _destination_relative(
    source_relative: Path,
    source_kind: str,
    group: str,
    category: str,
) -> Path:
    if source_kind == "evidence":
        parts = source_relative.parts
        if parts and parts[0] == CATEGORY_DIRECTORIES[category]:
            return Path(CATEGORY_DIRECTORIES[category]) / Path(*parts[1:])
        return Path(CATEGORY_DIRECTORIES[category]) / source_relative
    if group:
        return Path(CATEGORY_DIRECTORIES[category]) / group / source_relative
    return Path(CATEGORY_DIRECTORIES[category]) / source_relative


def _register_rejected(
    manifest: dict,
    source: str,
    reason: str,
    category: str,
    depth: int,
) -> None:
    manifest["rejected"].append(
        {
            "source": source,
            "category": category,
            "reason": reason,
            "depth": depth,
        }
    )


def _extract_log_gzip(
    source: Path,
    source_relative: Path,
    source_kind: str,
    group: str,
    category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    depth: int,
    log: ExtractionLogger | None = None,
) -> None:
    if category != RuleCategory.LOG.value:
        category = RuleCategory.LOG.value
    relative = _destination_relative(source_relative.with_suffix(""), source_kind, group, category)
    target = _safe_destination(data_dir, relative)
    source_state = (
        f"{MAIN_EVIDENCE_DIR}/{source_relative.as_posix()}" if source_kind == "evidence" else MAIN_EVIDENCE_DIR
    )
    state: dict[str, object] = {
        "source_evidence": source_state,
        "source_relative_path": source_relative.as_posix(),
        "target": relative.as_posix(),
        "depth": depth,
        "status": "extracted",
        "error": None,
    }
    if target.exists():
        state["status"] = "conflict"
        state["error"] = "目标日志已存在，未覆盖"
    else:
        try:
            budget.charge_gzip_chunk(0)
            unpack_gzip(
                source,
                target,
                charge=budget.charge_gzip_chunk,
            )
            budget.files += 1
            if budget.files > budget.max_files:
                raise ArchiveError("任务累计文件数超限")
            if source_kind != "evidence":
                source.unlink(missing_ok=True)
        except ArchiveError as exc:
            target.unlink(missing_ok=True)
            state["status"] = "failed"
            state["error"] = str(exc)
            _register_rejected(
                manifest,
                source_relative.as_posix(),
                str(exc),
                category,
                depth,
            )
    task_id = data_dir.name
    if state["status"] == "extracted":
        _log_extract(
            log,
            "info",
            "日志 gzip 解压完成",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            depth=depth,
        )
    elif state["status"] == "conflict":
        _log_extract(
            log,
            "warn",
            "日志 gzip 目标冲突",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            depth=depth,
            error=state["error"],
        )
    else:
        _log_extract(
            log,
            "error",
            "日志 gzip 解压失败",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            depth=depth,
            error=state["error"],
        )
    manifest["log_gz"].append(state)


def _extract_subpackage(
    source: Path,
    source_relative: Path,
    source_kind: str,
    group: str,
    parent_category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    seen_checksums: set[str],
    depth: int,
    log: ExtractionLogger | None = None,
) -> None:
    limit = UnpackLimit()
    checksum = sha256_file(source)
    category, reason = _category_of(source, parent_category)
    work_relative = source_relative.with_suffix("")
    if source_kind == "evidence":
        work_relative = _destination_relative(
            work_relative,
            source_kind,
            "",
            category,
        ).relative_to(CATEGORY_DIRECTORIES[category])
    state: dict[str, object] = {
        "source": (
            f"{MAIN_EVIDENCE_DIR}/{source_relative.as_posix()}"
            if source_kind == "evidence"
            else source_relative.as_posix()
        ),
        "parent": group or None,
        "category": CATEGORY_DIRECTORIES[category],
        "classification_reason": reason,
        "depth": depth,
        "checksum": checksum,
        "target": None,
        "status": "extracted",
        "error": None,
    }
    if depth > budget.max_depth or depth > limit.max_depth:
        state["status"] = "rejected"
        state["error"] = "嵌套深度超限"
        manifest["subpackages"].append(state)
        _register_rejected(manifest, source_relative.as_posix(), str(state["error"]), category, depth)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
        _log_extract(
            log,
            "error",
            "子包解压拒绝",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            category=CATEGORY_DIRECTORIES[category],
            depth=depth,
            error=state["error"],
        )
        return
    if checksum in seen_checksums:
        state["status"] = "duplicate"
        state["error"] = "相同 checksum 子包已展开"
        manifest["subpackages"].append(state)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
        _log_extract(
            log,
            "info",
            "子包重复，跳过解压",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            category=CATEGORY_DIRECTORIES[category],
            depth=depth,
            checksum=checksum,
        )
        return
    seen_checksums.add(checksum)

    work_path = _unique_work_path(data_dir / CATEGORY_DIRECTORIES[category], work_relative, checksum)
    target_relative = work_path.relative_to(data_dir)
    state["target"] = target_relative.as_posix()
    staging = data_dir / f".extract-{checksum[:12]}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        if budget.files + 1 > budget.max_files:
            raise ArchiveError("任务累计文件数超限")
        unpack(source, staging, limit)
        extracted_files = _relative_files(staging)
        if budget.files + len(extracted_files) > budget.max_files:
            raise ArchiveError("任务累计文件数超限")
        for extracted_file in extracted_files:
            budget.charge_file(extracted_file)
        work_path.parent.mkdir(parents=True, exist_ok=True)
        if work_path.exists():
            shutil.rmtree(work_path)
        staging.rename(work_path)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
        for member in _relative_files(work_path):
            member_relative = member.relative_to(work_path)
            _ingest_file(
                member,
                member_relative,
                "work",
                work_path.name,
                category,
                data_dir,
                manifest,
                budget,
                seen_checksums,
                depth + 1,
                log,
            )
        _remove_empty_work_site(work_path, data_dir / CATEGORY_DIRECTORIES[category])
    except ArchiveError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if work_path.exists():
            shutil.rmtree(work_path, ignore_errors=True)
        state["status"] = "failed"
        state["error"] = str(exc)
        if source_kind != "evidence":
            source.unlink(missing_ok=True)
    task_id = data_dir.name
    if state["status"] == "extracted":
        _log_extract(
            log,
            "info",
            "子包解压完成",
            task_id=task_id,
            source=source_relative.as_posix(),
            target=state["target"],
            category=state["category"],
            depth=depth,
        )
    elif state["status"] != "duplicate":
        _log_extract(
            log,
            "error",
            "子包解压失败",
            task_id=task_id,
            source=source_relative.as_posix(),
            category=state["category"],
            depth=depth,
            error=state["error"],
        )
    manifest["subpackages"].append(state)


def _ingest_file(
    source: Path,
    source_relative: Path,
    source_kind: str,
    group: str,
    parent_category: str,
    data_dir: Path,
    manifest: dict,
    budget: ExtractionBudget,
    seen_checksums: set[str],
    depth: int,
    log: ExtractionLogger | None = None,
) -> None:
    name = source.name.lower()
    if name.endswith(".log.gz"):
        _extract_log_gzip(
            source,
            source_relative,
            source_kind,
            group,
            parent_category,
            data_dir,
            manifest,
            budget,
            depth,
            log,
        )
        return
    if is_archive(source):
        _extract_subpackage(
            source,
            source_relative,
            source_kind,
            group,
            parent_category,
            data_dir,
            manifest,
            budget,
            seen_checksums,
            depth,
            log,
        )
        return

    category, _ = _category_of(source, parent_category)
    relative = _destination_relative(source_relative, source_kind, group, category)
    target = _safe_destination(data_dir, relative)
    try:
        if target == source.resolve():
            budget.charge_file(target)
            return
        if target.exists():
            reason = "目标文件已存在，未覆盖"
            _register_rejected(manifest, source_relative.as_posix(), reason, category, depth)
            _log_extract(
                log,
                "warn",
                "普通文件目标冲突",
                task_id=data_dir.name,
                source=source_relative.as_posix(),
                target=relative.as_posix(),
                category=CATEGORY_DIRECTORIES[category],
                depth=depth,
            )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        budget.charge_file(target)
        if source_kind == "work":
            source.unlink(missing_ok=True)
    except ArchiveError as exc:
        _register_rejected(manifest, source_relative.as_posix(), str(exc), category, depth)
        _log_extract(
            log,
            "error",
            "普通文件处理失败",
            task_id=data_dir.name,
            source=source_relative.as_posix(),
            target=relative.as_posix(),
            category=CATEGORY_DIRECTORIES[category],
            depth=depth,
            error=str(exc),
        )


def extract_main_site(
    package: Path,
    data_dir: Path,
    checksum: str,
    log: ExtractionLogger | None = None,
) -> dict:
    """保留主包证据现场并生成分类工作现场。"""
    existing = reusable_manifest(data_dir, checksum)
    if existing is not None:
        _log_extract(
            log,
            "info",
            "解压现场复用",
            task_id=data_dir.name,
            checksum=checksum,
        )
        return existing

    staging = data_dir / ".main.staging"
    shutil.rmtree(staging, ignore_errors=True)
    _log_extract(
        log,
        "info",
        "主包解压开始",
        task_id=data_dir.name,
        package=package.name,
        checksum=checksum,
    )
    try:
        unpack(package, staging)
    except ArchiveError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        _log_extract(
            log,
            "error",
            "主包解压失败",
            task_id=data_dir.name,
            package=package.name,
            checksum=checksum,
            error=str(exc),
        )
        raise

    evidence = data_dir / MAIN_EVIDENCE_DIR
    backup = data_dir / ".main.previous"
    shutil.rmtree(backup, ignore_errors=True)
    replaced = False
    if evidence.exists():
        evidence.rename(backup)
        replaced = True
    try:
        staging.rename(evidence)
    except OSError:
        if replaced and not evidence.exists():
            backup.rename(evidence)
        raise
    if replaced:
        shutil.rmtree(backup, ignore_errors=True)

    for category in WORK_CATEGORIES:
        shutil.rmtree(data_dir / category, ignore_errors=True)
        (data_dir / category).mkdir(parents=True, exist_ok=True)
    shutil.rmtree(manifest_path(data_dir), ignore_errors=True)

    manifest: dict = {
        "version": MANIFEST_VERSION,
        "main": {
            "checksum": checksum,
            "count": 0,
            "evidence_path": MAIN_EVIDENCE_DIR,
            "reused": False,
        },
        "subpackages": [],
        "log_gz": [],
        "rejected": [],
    }
    budget = ExtractionBudget()
    seen_checksums: set[str] = set()
    for source in _relative_files(evidence):
        source_relative = source.relative_to(evidence)
        manifest["main"]["count"] += 1
        _ingest_file(
            source,
            source_relative,
            "evidence",
            "",
            "",
            data_dir,
            manifest,
            budget,
            seen_checksums,
            1,
            log,
        )
    write_manifest(data_dir, manifest)
    _log_extract(
        log,
        "info",
        "主包解压完成",
        task_id=data_dir.name,
        package=package.name,
        checksum=checksum,
        count=int(manifest["main"]["count"]),
        subpackages=len(manifest["subpackages"]),
        log_gz=len(manifest["log_gz"]),
        rejected=len(manifest["rejected"]),
    )
    return manifest


def category_failures(manifest: dict, category: str) -> list[dict]:
    """读取指定分类的子包和日志 gzip 失败/冲突状态。"""
    failures: list[dict] = []
    for item in manifest.get("subpackages", []):
        if item.get("category") == category and item.get("status") in {"failed", "rejected"}:
            failures.append(
                {
                    "name": Path(str(item.get("source", ""))).name,
                    "checksum": item.get("checksum"),
                    "target": item.get("target"),
                    "error": item.get("error"),
                    "status": item.get("status"),
                }
            )
    if category == "logs":
        for item in manifest.get("log_gz", []):
            if item.get("status") in {"conflict", "failed", "rejected"}:
                failures.append(
                    {
                        "name": Path(str(item.get("target", ""))).name,
                        "source": item.get("source_relative_path"),
                        "target": item.get("target"),
                        "error": item.get("error"),
                        "status": item.get("status"),
                    }
                )
    return failures
