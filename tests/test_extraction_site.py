"""任务现场、多级子包与 `.log.gz` 展开测试。"""

import gzip
import hashlib
import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.archive import ArchiveError
from app.core.checksum import sha256_file
from app.core.config import settings
from app.models.schemas import RuleStatus
from app.services import extraction
from app.services.executor import RuleContext
from app.services.extraction.classification import infer_scene_root
from app.services.extraction.config import load_classification_config
from app.services.extraction.layout import PathLimitPolicy
from app.services.extraction.manifest import (
    FIXED_BUDGETS,
    ManifestReuseContext,
    ManifestV5Error,
    evidence_fingerprint,
    extraction_policy_fingerprint,
    write_manifest,
)
from tests.baseline_helpers import Env, setup_env


def _zip(path: Path, files: dict[str, str | bytes]) -> None:
    """创建用于测试的 zip 子包。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def _gz(path: Path, content: str) -> None:
    """创建用于测试的 gzip 日志。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(content.encode("utf-8")))


def _multi_level_package(env: Env) -> Path:
    """构造主包 → KPI 子包和 Service Logs 子包的真实 UMF 样例。"""
    service_zip = env.uploads / "_build" / "ServiceLogs_20260901011314.zip"
    _zip(
        service_zip,
        {
            "UMFACC/logs/paas-node-1/UMFAcc.log": "2026-09-01T10:00:00Z INFO  app started\n",
            "UMFACC/logs/paas-node-2/UMFAcc_20260901010101.log.gz": gzip.compress(
                b"2026-09-01T10:01:00Z INFO  rolling log\n"
            ),
        },
    )
    kpi_zip = env.uploads / "_build" / "PerfResult_20260901011314.zip"
    _zip(kpi_zip, {"kpi_data/inner_kpi.csv": "metric,value\nsuccess,99\n"})

    package = env.uploads / "nested.zip"
    _zip(
        package,
        {
            "Service Logs (Problem)/ServiceLogs_20260901011314.zip": service_zip.read_bytes(),
            "Performance Measurement Results/PerfResult_20260901011314.zip": kpi_zip.read_bytes(),
            "Basic Information About the UMF/system.ini": "[app]\nname=app\n",
        },
    )
    return package


def _relative_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_main_site_is_retained_and_nested_packages_are_finalized(tmp_path, monkeypatch) -> None:
    """`.main/` 保留原始现场，多级子包按自身分类展开并只保留最终文件。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    from app.cli import run_task

    task = run_task(package, task_id="task-extraction", customer={"product": "UMF"})
    task_dir = env.task_dir(task.task_id)
    main_files = _relative_files(task_dir / ".main")

    assert main_files == {
        "Service Logs (Problem)/ServiceLogs_20260901011314.zip",
        "Performance Measurement Results/PerfResult_20260901011314.zip",
        "Basic Information About the UMF/system.ini",
    }
    assert (task_dir / "basic/system.ini").is_file()
    assert (task_dir / "kpi/kpi_data/inner_kpi.csv").is_file()
    assert (task_dir / "logs/UMFACC/logs/paas-node-1/UMFAcc.log").is_file()
    assert (task_dir / "logs/UMFACC/logs/paas-node-2/UMFAcc_20260901010101.log").is_file()

    work_files = (
        _relative_files(task_dir / "basic") | _relative_files(task_dir / "logs") | _relative_files(task_dir / "kpi")
    )
    assert not any(name.endswith((".zip", ".tar", ".tar.gz", ".tgz", ".log.gz")) for name in work_files)


def test_nested_evidence_package_does_not_leave_category_tree(tmp_path, monkeypatch) -> None:
    """主包内嵌套目录下的子包展开后，分类目录不保留空的原始路径树。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    service_zip = env.uploads / "_build" / "ServiceLogs_nested.zip"
    _zip(
        service_zip,
        {"UMFACC/logs/node/UMFAcc.log": "2026-09-01T10:00:00Z INFO  app\n"},
    )
    package = env.uploads / "nested-site.zip"
    _zip(package, {"Problem scene/Service Logs (Problem)/ServiceLogs_nested.zip": service_zip.read_bytes()})

    from app.cli import run_task

    task = run_task(package, task_id="task-empty-site", customer={"product": "UMF"})
    task_dir = env.task_dir(task.task_id)

    assert (task_dir / "logs/UMFACC/logs/node/UMFAcc.log").is_file()
    assert not (task_dir / "logs/Problem scene").exists()


def test_extraction_process_is_logged(tmp_path, monkeypatch) -> None:
    """主包证据现场的关键过程写入结构化日志。"""
    from app.services.extraction import site as site_module

    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    data_dir = env.task_dir("task-logs")
    data_dir.mkdir(parents=True, exist_ok=True)
    logs: list[tuple[str, str, dict]] = []

    def log(level: str, message: str, **detail: object) -> None:
        logs.append((level, message, dict(detail)))

    site_module.ensure_main_evidence(package, data_dir, sha256_file(package), log=log)

    messages = [message for _, message, _ in logs]
    assert "主包解压开始" in messages
    assert "主包证据现场重建完成" in messages

    main_start = next(i for i, (_, message, _) in enumerate(logs) if message == "主包解压开始")
    main_complete = next(i for i, (_, message, _) in enumerate(logs) if message == "主包证据现场重建完成")
    assert main_start < main_complete
    assert logs[-1][2]["task_id"] == "task-logs"


def test_run_task_writes_extraction_logs(tmp_path, monkeypatch) -> None:
    """规则上下文将解压日志写入任务 execution.log。"""
    import json

    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)

    from app.cli import run_task

    task = run_task(package, task_id="task-log-file", customer={"product": "UMF"})
    log_path = env.task_dir(task.task_id) / "execution.log"
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    messages = [entry["message"] for entry in entries]

    assert "主包解压开始" in messages
    assert "主包证据现场重建完成" in messages
    assert "主包解压现场已就绪" in messages
    assert "执行规则 pkg.extract.classification" in messages
    assert all("task_id" in entry for entry in entries if entry["message"].startswith("主包解压"))

    main_start = next(i for i, entry in enumerate(entries) if entry["message"] == "主包解压开始")
    classification_start = next(
        i for i, entry in enumerate(entries) if entry["message"] == "执行规则 pkg.extract.classification"
    )
    assert main_start < classification_start


def test_log_gz_conflict_and_failure_are_isolated(tmp_path, monkeypatch) -> None:
    """冲突和损坏 gzip 保留证据并记录状态，不阻断其他文件。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    valid_gzip = gzip.compress(b"2026-09-01T10:00:01Z INFO  ok\n")
    bad_gzip = gzip.compress(b"corrupt me\n")[:-4]
    first_zip = env.uploads / "_build" / "ServiceLogs_first.zip"
    _zip(
        first_zip,
        {
            "UMFACC/logs/node/UMFAcc_202609.log.gz": valid_gzip,
            "UMFSERVICE/logs/node/UMFService.log": "2026-09-01T10:00:02Z INFO  service\n",
        },
    )
    conflict_zip = env.uploads / "_build" / "ServiceLogs_conflict.zip"
    _zip(conflict_zip, {"UMFACC/logs/node/UMFAcc_202609.log.gz": valid_gzip})
    bad_zip = env.uploads / "_build" / "ServiceLogs_bad.zip"
    _zip(bad_zip, {"UMFACC/logs/node/UMFAcc_bad.log.gz": bad_gzip})
    package = env.uploads / "failure.zip"
    _zip(
        package,
        {
            "Service Logs (Problem)/ServiceLogs_first.zip": first_zip.read_bytes(),
            "Service Logs (Problem)/ServiceLogs_conflict.zip": conflict_zip.read_bytes(),
            "Service Logs (Problem)/ServiceLogs_bad.zip": bad_zip.read_bytes(),
        },
    )

    from app.cli import run_task

    task = run_task(package, task_id="task-failure", customer={"product": "UMF"})
    task_dir = env.task_dir(task.task_id)
    manifest = json.loads((task_dir / "manifest.json").read_text(encoding="utf-8"))
    logs_dir = task_dir / "logs/UMFACC/logs/node"

    assert task.status == "completed"
    assert len(manifest["conflicts"]) == 1
    assert len(manifest["failures"]) == 1
    assert manifest["failures"][0]["error_code"] == "archive_corrupt"
    assert (logs_dir / "UMFAcc_202609.log").is_file()
    assert (task_dir / "logs/UMFSERVICE/logs/node/UMFService.log").is_file()
    assert not any(path.suffix == ".gz" for path in task_dir.rglob("*.gz"))


def test_second_run_is_idempotent(tmp_path, monkeypatch) -> None:
    """同一包二次执行复用现场，不产生重复文件或变化。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    from app.cli import run_task

    first = run_task(package, task_id="task-rerun", customer={"product": "UMF"})
    task_dir = env.task_dir(first.task_id)
    first_files = _relative_files(task_dir)
    first_manifest = (task_dir / "manifest.json").read_bytes()
    first_catalog = json.loads(first_manifest)["catalog"]

    run_task(package, task_id="task-rerun", customer={"product": "UMF"})
    second_files = _relative_files(task_dir)
    second_manifest = (task_dir / "manifest.json").read_bytes()

    assert second_files == first_files
    assert second_manifest == first_manifest
    assert json.loads(second_manifest)["catalog"] == first_catalog


def test_normal_rules_do_not_match_main_evidence(tmp_path, monkeypatch) -> None:
    """普通规则匹配入口排除 `.main/` 和 manifest。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    from app.cli import run_task
    from app.services.scanning import TaskFileCatalog

    task = run_task(package, task_id="task-matching", customer={"product": "UMF"})
    task_dir = env.task_dir(task.task_id)
    matched = TaskFileCatalog.build(task_dir).match([r".*"])

    posix_paths = [path.as_posix() for path in matched]

    assert "kpi/kpi_data/inner_kpi.csv" in posix_paths
    assert not any(path.startswith(".main/") for path in posix_paths)
    assert "manifest.json" not in posix_paths


def test_manifest_structure_and_old_version_are_not_reused(tmp_path, monkeypatch) -> None:
    """manifest v3 结构不完整、损坏或旧版本时必须整体重建现场。"""
    import json

    env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    checksum = sha256_file(package)
    from app.cli import run_task

    first = run_task(package, task_id="task-manifest", customer={"product": "UMF"})
    task_dir = env.task_dir(first.task_id)

    context = _production_reuse_context(task_dir, checksum)
    assert extraction.manifest.reusable_manifest(task_dir, context) is not None
    manifest_path = task_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert extraction.manifest.reusable_manifest(task_dir, context) is None

    manifest["version"] = 3
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert extraction.manifest.reusable_manifest(task_dir, context) is None

    files_before = _relative_files(task_dir / ".main")
    second = run_task(package, task_id="task-manifest", customer={"product": "UMF"})
    manifest_after = json.loads((task_dir / "manifest.json").read_text(encoding="utf-8"))

    assert second.task_id == first.task_id
    assert manifest_after["version"] == 5
    assert _relative_files(task_dir / ".main") == files_before
    assert not (task_dir / ".patrolx-extracted.json").exists()


V5_BUDGETS = {
    "max_archive_depth": 8,
    "max_member_path_depth": 12,
    "max_archive_files": 100_000,
    "max_task_files": 200_000,
    "max_file_bytes": 2 * 1024 * 1024 * 1024,
    "max_total_bytes": 3 * 1024 * 1024 * 1024,
}
V5_CONFIG_FINGERPRINT = "c" * 64
V5_EXTRACTION_POLICY_FINGERPRINT = "d" * 64


def _write_v5_site(package: Path, data_dir: Path) -> tuple[str, ManifestReuseContext]:
    """构造含真实证据与 catalog 的最小有效 v5 现场。"""
    checksum = sha256_file(package)
    evidence = data_dir / ".main/payload.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("evidence", encoding="utf-8")
    target = data_dir / "basic/payload.txt"
    target.parent.mkdir(parents=True)
    target.write_text("evidence", encoding="utf-8")
    count, fingerprint = evidence_fingerprint(data_dir)
    path_limit = PathLimitPolicy().snapshot()
    context = ManifestReuseContext(
        checksum=checksum,
        product="UMF",
        package_kind="inspection",
        profile="UMF",
        config_fingerprint=V5_CONFIG_FINGERPRINT,
        extraction_policy_fingerprint=V5_EXTRACTION_POLICY_FINGERPRINT,
        path_limit=path_limit,
        scene_root=".main",
        target_roots=("basic",),
        budgets=dict(V5_BUDGETS),
    )
    manifest = {
        "version": 5,
        "main": {
            "checksum": checksum,
            "count": count,
            "evidence_path": ".main",
            "evidence_fingerprint": fingerprint,
            "reused": False,
        },
        "product": "UMF",
        "classification": {
            "config_fingerprint": V5_CONFIG_FINGERPRINT,
            "profile": "UMF",
            "snapshot": {
                "package_kind": "inspection",
                "product": "UMF",
                "profile": "UMF",
                "ruleset": "UMF_ARCHIVE_V1",
                "config_fingerprint": V5_CONFIG_FINGERPRINT,
                "extraction_policy_fingerprint": V5_EXTRACTION_POLICY_FINGERPRINT,
                "path_limit_fingerprint": path_limit["fingerprint"],
                "scene_root": ".main",
                "target_roots": ["basic"],
                "budgets": dict(V5_BUDGETS),
            },
        },
        "path_limit": path_limit,
        "entries": [
            {
                "source_relative": "payload.txt",
                "member_relative": None,
                "route_id": "route.payload",
                "product": "UMF",
                "category": "config",
                "original_target": "basic/payload.txt",
                "target": "basic/payload.txt",
                "action": "copy",
                "status": "landed",
                "reason": None,
                "error_code": None,
                "sha256": sha256_file(target),
                "size": target.stat().st_size,
            }
        ],
        "ignored": [],
        "conflicts": [],
        "failures": [],
        "catalog": [
            {
                "path": "basic/payload.txt",
                "category": "config",
                "route_id": "route.payload",
                "source_relative": "payload.txt",
                "sha256": sha256_file(target),
                "size": target.stat().st_size,
            }
        ],
        "summary": {
            "counts": {"landed": 1, "ignored": 0, "conflicts": 0, "failures": 0, "catalog": 1},
            "by_route": {"route.payload": 1},
            "by_category": {"config": 1},
            "by_action": {"copy": 1},
            "by_status": {"failed": 0, "ignored": 0, "landed": 1},
        },
    }
    write_manifest(data_dir, manifest)
    return checksum, context


def _production_reuse_context(data_dir: Path, checksum: str) -> ManifestReuseContext:
    """按生产分类配置构造当前 UMF 任务的完整复用上下文。"""
    config = load_classification_config(settings.config / "classify_rules.yaml")
    profile = "UMF"
    scene = infer_scene_root(data_dir / ".main", config.profiles[profile].scene_anchors).relative_to_evidence
    scene_root = ".main" if scene == Path(".") else f".main/{scene.as_posix()}"
    target_roots = tuple(
        sorted(
            {
                route.target.split("/", 1)[0]
                for route in config.routes
                if profile in route.profiles and route.action != "ignore" and route.target
            }
        )
    )
    return ManifestReuseContext(
        checksum=checksum,
        product=profile,
        package_kind="inspection",
        profile=profile,
        config_fingerprint=config.fingerprint,
        extraction_policy_fingerprint=extraction_policy_fingerprint(),
        path_limit=PathLimitPolicy.current().snapshot(),
        scene_root=scene_root,
        target_roots=target_roots,
        budgets=dict(FIXED_BUDGETS),
    )


def _use_production_classification_config(monkeypatch) -> None:
    """setup_env 切换 cwd 后仍使用 worktree 中冻结的分类配置。"""
    monkeypatch.setattr(settings, "config_dir", Path(__file__).resolve().parents[1] / "deploy/config")


def _write_production_v5_site(package: Path, data_dir: Path) -> tuple[str, ManifestReuseContext]:
    """把最小 v5 现场升级为生产入口可识别的真实当前上下文。"""
    checksum, _ = _write_v5_site(package, data_dir)
    context = _production_reuse_context(data_dir, checksum)
    path = data_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["path_limit"] = context.path_limit
    manifest["classification"] = {
        "config_fingerprint": context.config_fingerprint,
        "profile": context.profile,
        "snapshot": {
            "package_kind": context.package_kind,
            "product": context.product,
            "profile": context.profile,
            "ruleset": "UMF_ARCHIVE_V1",
            "config_fingerprint": context.config_fingerprint,
            "extraction_policy_fingerprint": context.extraction_policy_fingerprint,
            "path_limit_fingerprint": context.path_limit["fingerprint"],
            "scene_root": context.scene_root,
            "target_roots": list(context.target_roots),
            "budgets": context.budgets,
        },
    }
    write_manifest(data_dir, manifest)
    return checksum, context


def _v5_package(env: Env, name: str = "evidence-v5.zip") -> Path:
    package = env.uploads / name
    _zip(package, {"payload.txt": "evidence"})
    return package


def test_evidence_fingerprint_detects_content_path_and_size_changes(tmp_path: Path) -> None:
    """证据指纹应稳定，并在任一内容、路径或大小变化后失效。"""
    data_dir = tmp_path / "task-fingerprint"
    evidence = data_dir / ".main/nested/payload.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("evidence", encoding="utf-8")

    original = evidence_fingerprint(data_dir)
    assert original == evidence_fingerprint(data_dir)

    evidence.write_text("tampered", encoding="utf-8")
    content_changed = evidence_fingerprint(data_dir)
    assert content_changed != original

    renamed = evidence.with_name("renamed.txt")
    evidence.rename(renamed)
    path_changed = evidence_fingerprint(data_dir)
    assert path_changed not in {original, content_changed}

    renamed.write_bytes(renamed.read_bytes() + b"!")
    assert evidence_fingerprint(data_dir) not in {original, content_changed, path_changed}


def test_evidence_fingerprint_rejects_root_and_nested_links(tmp_path: Path) -> None:
    """`.main/` 非目录、根链接与内部链接都属于证据损坏。"""
    data_dir = tmp_path / "task-links"
    external = tmp_path / "external"
    external.mkdir()
    data_dir.mkdir()
    (data_dir / ".main").write_text("not a directory", encoding="utf-8")

    with pytest.raises(ManifestV5Error, match="证据现场"):
        evidence_fingerprint(data_dir)

    (data_dir / ".main").unlink()
    (data_dir / ".main").symlink_to(external, target_is_directory=True)

    with pytest.raises(ManifestV5Error, match="证据现场"):
        evidence_fingerprint(data_dir)

    (data_dir / ".main").unlink()
    (data_dir / ".main/nested").mkdir(parents=True)
    (data_dir / ".main/nested/payload.txt").symlink_to(external)
    with pytest.raises(ManifestV5Error, match="链接"):
        evidence_fingerprint(data_dir)


@pytest.mark.parametrize("mutation", ["content", "path", "size", "link", "root_link"])
def test_damaged_v5_evidence_is_rebuilt_without_changing_package(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    """证据损坏时从原始包重建，且原包前后哈希完全一致。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env)
    data_dir = env.task_dir("task-rebuild-v5")
    checksum, _ = _write_v5_site(package, data_dir)
    evidence = data_dir / ".main/payload.txt"
    if mutation == "content":
        evidence.write_text("tampered", encoding="utf-8")
    elif mutation == "path":
        evidence.rename(evidence.with_name("moved.txt"))
    elif mutation == "size":
        evidence.write_bytes(evidence.read_bytes() + b"!")
    elif mutation == "link":
        evidence.unlink()
        evidence.symlink_to(package)
    else:
        external = tmp_path / "external-main"
        (data_dir / ".main").rename(external)
        (data_dir / ".main").symlink_to(external, target_is_directory=True)
    before = sha256_file(package)
    unpack_calls: list[Path] = []
    real_unpack = site_module.unpack

    def tracked_unpack(package_path: Path, destination: Path, **kwargs) -> int:
        unpack_calls.append(package_path)
        return real_unpack(package_path, destination, **kwargs)

    monkeypatch.setattr(site_module, "unpack", tracked_unpack)

    main = site_module.ensure_main_evidence(package, data_dir, checksum)

    assert main["reused"] is False
    assert main["count"] == 1
    assert evidence.read_text(encoding="utf-8") == "evidence"
    assert not (data_dir / ".main").is_symlink()
    assert not any(path.is_symlink() for path in (data_dir / ".main").rglob("*"))
    assert sha256_file(package) == before == checksum
    assert unpack_calls == [package]


def test_v5_evidence_is_reused_only_with_matching_manifest(tmp_path: Path, monkeypatch) -> None:
    """只有有效 v5 manifest 的 checksum 与证据指纹均匹配时才复用现场。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env)
    data_dir = env.task_dir("task-reuse-v5")
    checksum, _ = _write_v5_site(package, data_dir)

    assert site_module.ensure_main_evidence(package, data_dir, checksum)["reused"] is True

    (data_dir / "manifest.json").write_text(
        '{"version": 4, "main": {"checksum": "'
        + checksum
        + '", "count": 1, "evidence_path": ".main", "reused": false}}',
        encoding="utf-8",
    )
    assert site_module.ensure_main_evidence(package, data_dir, checksum)["reused"] is False


def test_classification_reuse_requires_full_v5_context_and_catalog(tmp_path: Path, monkeypatch) -> None:
    """v5 分类复用必须同时匹配完整 snapshot 上下文与 catalog 摘要。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env)
    data_dir = env.task_dir("task-matrix-v5")
    checksum, context = _write_v5_site(package, data_dir)
    before = sha256_file(package)

    reused = site_module.reusable_extraction_site(package, data_dir, context)
    assert reused is not None
    assert reused["main"]["reused"] is True

    with pytest.raises(ArchiveError) as error:
        site_module.reusable_extraction_site(package, data_dir, replace(context, checksum="e" * 64))
    assert error.value.error_code == "package_checksum_conflict"

    variants = [
        replace(context, product="CSP"),
        replace(context, package_kind="log_supplement"),
        replace(context, profile="CSP"),
        replace(context, config_fingerprint="e" * 64),
        replace(context, extraction_policy_fingerprint="e" * 64),
        replace(context, path_limit={**context.path_limit, "fingerprint": "e" * 64}),
        replace(context, scene_root=".main/other"),
        replace(context, target_roots=("alarm",)),
        replace(context, budgets={**context.budgets, "max_archive_depth": 7}),
    ]
    assert all(site_module.reusable_extraction_site(package, data_dir, variant) is None for variant in variants)

    evidence = data_dir / ".main/payload.txt"
    evidence.write_text("tampered", encoding="utf-8")
    assert site_module.reusable_extraction_site(package, data_dir, context) is None

    evidence.write_text("evidence", encoding="utf-8")
    (data_dir / "basic/payload.txt").write_text("tampered", encoding="utf-8")
    assert site_module.reusable_extraction_site(package, data_dir, context) is None
    assert sha256_file(package) == before == checksum


def test_package_checksum_conflict_does_not_trust_or_modify_site(tmp_path: Path, monkeypatch) -> None:
    """当前原包与首次接收 checksum 冲突时稳定拒绝，且不修改任何现场。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env)
    data_dir = env.task_dir("task-checksum-conflict")
    checksum, _ = _write_v5_site(package, data_dir)
    before = sha256_file(package)
    evidence_before = (data_dir / ".main/payload.txt").read_bytes()
    manifest_before = (data_dir / "manifest.json").read_bytes()

    with pytest.raises(ArchiveError) as error:
        site_module.ensure_main_evidence(package, data_dir, "0" * 64)

    assert error.value.error_code == "package_checksum_conflict"
    assert sha256_file(package) == before == checksum
    assert (data_dir / ".main/payload.txt").read_bytes() == evidence_before
    assert (data_dir / "manifest.json").read_bytes() == manifest_before


def test_evidence_fingerprint_matches_fixed_utf8_contract_fixture(tmp_path: Path) -> None:
    """固定 `.main/中文.txt` 样例必须命中契约规定的 UTF-8 canonical JSON 指纹。"""
    data_dir = tmp_path / "task-fixed-fingerprint"
    evidence = data_dir / ".main/中文.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"x")

    assert evidence_fingerprint(data_dir) == (
        1,
        "c7e15440e6b6286173859327e98855767a3e55bb5de97b0ec7fd0c352c689583",
    )


def test_extraction_policy_fingerprint_matches_fixed_contract_payload(monkeypatch) -> None:
    """解压策略指纹必须复用 canonical_json，并对固定语义 payload 输出稳定 SHA-256。"""
    from app.services.extraction import manifest as manifest_module

    captured: list[dict[str, object]] = []
    real_canonical_json = manifest_module.canonical_json

    def tracked_canonical_json(payload: dict[str, object]) -> bytes:
        captured.append(payload)
        return real_canonical_json(payload)

    monkeypatch.setattr(manifest_module, "canonical_json", tracked_canonical_json)

    assert manifest_module.extraction_policy_fingerprint() == (
        "622523f62c27b8ac5da4b4d334953d4571d97e30e2960e1e877e21804f2f4235"
    )
    assert captured == [
        {
            "version": 1,
            "actions": [
                "copy",
                "decompress",
                "expand",
                "expand_recursive",
                "fallback",
                "ignore",
                "select_and_decompress",
            ],
            "budgets": V5_BUDGETS,
            "error_codes": [
                "archive_corrupt",
                "archive_depth_exceeded",
                "duplicate_member",
                "file_count_exceeded",
                "file_too_large",
                "invalid_classification_config",
                "link_rejected",
                "member_path_depth_exceeded",
                "target_conflict",
                "task_file_count_exceeded",
                "total_bytes_exceeded",
                "unsafe_path",
            ],
            "publication": "manifest-v5:staging+atomic-replace",
        }
    ]


def test_evidence_fingerprint_uses_canonical_json_and_utf8_path_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """证据指纹必须调用 canonical_json，并按 UTF-8 路径字节序提交文件数组。"""
    from app.services.extraction import manifest as manifest_module

    data_dir = tmp_path / "task-canonical-fingerprint"
    evidence = data_dir / ".main"
    evidence.mkdir(parents=True)
    names = ["z.txt", "é.txt", "中文.txt", "a.txt"]
    for name in names:
        (evidence / name).write_bytes(b"x")

    captured: list[dict[str, object]] = []

    def canonical(payload: list[dict[str, object]]) -> bytes:
        captured.extend(payload)
        return b"canonical-json"

    monkeypatch.setattr(manifest_module, "canonical_json", canonical, raising=False)

    assert evidence_fingerprint(data_dir) == (len(names), hashlib.sha256(b"canonical-json").hexdigest())
    assert [item["path"] for item in captured] == sorted(names, key=lambda name: name.encode("utf-8"))


def test_evidence_fingerprint_detects_size_change_with_identical_digest(tmp_path: Path, monkeypatch) -> None:
    """即使 SHA-256 被固定，仅文件大小变化也必须改变证据指纹。"""
    from app.services.extraction import manifest as manifest_module

    data_dir = tmp_path / "task-size-fingerprint"
    evidence = data_dir / ".main/payload.txt"
    evidence.parent.mkdir(parents=True)
    monkeypatch.setattr(manifest_module, "sha256_file", lambda _path: "a" * 64)

    evidence.write_bytes(b"x")
    original = evidence_fingerprint(data_dir)
    evidence.write_bytes(b"xx")

    assert evidence_fingerprint(data_dir) != original


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="当前平台不支持 FIFO")
def test_evidence_fingerprint_rejects_fifo(tmp_path: Path) -> None:
    """FIFO 不是普通文件，必须被证据指纹拒绝且不能阻塞读取。"""
    data_dir = tmp_path / "task-fifo-fingerprint"
    evidence = data_dir / ".main"
    evidence.mkdir(parents=True)
    os.mkfifo(evidence / "named-pipe")

    with pytest.raises(ManifestV5Error, match="非普通文件"):
        evidence_fingerprint(data_dir)


def test_production_main_inspector_consumes_v5_evidence_reuse(tmp_path: Path, monkeypatch) -> None:
    """生产 pkg.extract.main 只复用 checksum 与证据均匹配的 v5 `.main/` 现场。"""
    from app.inspectors.pkg import main_inspector
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    _use_production_classification_config(monkeypatch)
    package = _v5_package(env, name="main-inspector-reuse.zip")
    data_dir = env.task_dir("task-main-inspector-reuse")
    checksum, _ = _write_production_v5_site(package, data_dir)
    evidence_calls: list[tuple[Path, Path, str]] = []
    real_ensure_main_evidence = site_module.ensure_main_evidence

    def tracked_ensure_main_evidence(
        package_path: Path,
        task_root: Path,
        package_checksum: str,
        **kwargs,
    ) -> dict[str, object]:
        evidence_calls.append((package_path, task_root, package_checksum))
        return real_ensure_main_evidence(package_path, task_root, package_checksum, **kwargs)

    monkeypatch.setattr(site_module, "ensure_main_evidence", tracked_ensure_main_evidence)
    monkeypatch.setattr(site_module, "unpack", lambda *_args, **_kwargs: pytest.fail("有效 v5 现场不得重新解压"))
    ctx = RuleContext(
        task_id="task-main-inspector-reuse",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum=checksum,
        product="UMF",
    )

    result = main_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["reused"] is True
    assert evidence_calls == [(package, data_dir, checksum)]


@pytest.mark.parametrize("mutation", ["missing", "content", "size", "path", "fifo", "root_link"])
def test_production_main_inspector_rebuilds_damaged_evidence_from_package(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    """生产主包入口遇到任意证据损坏时只从原包恢复，且不修改原包或链接目标。"""
    import shutil

    from app.inspectors.pkg import main_inspector
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    _use_production_classification_config(monkeypatch)
    package = _v5_package(env, name=f"main-inspector-damaged-{mutation}.zip")
    data_dir = env.task_dir(f"task-main-inspector-damaged-{mutation}")
    checksum, _ = _write_production_v5_site(package, data_dir)
    evidence = data_dir / ".main/payload.txt"
    external: Path | None = None
    external_before: dict[str, bytes] | None = None
    moved: Path | None = None

    if mutation == "missing":
        shutil.rmtree(data_dir / ".main")
    elif mutation == "content":
        evidence.write_text("tampered", encoding="utf-8")
    elif mutation == "size":
        evidence.write_bytes(evidence.read_bytes() + b"!")
    elif mutation == "path":
        moved = evidence.with_name("moved.txt")
        evidence.rename(moved)
    elif mutation == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("当前平台不支持 FIFO")
        os.mkfifo(data_dir / ".main/named-pipe")
    else:
        external = tmp_path / "external-main"
        (data_dir / ".main").rename(external)
        (external / "sentinel.txt").write_bytes(b"outside")
        external_before = {
            path.relative_to(external).as_posix(): path.read_bytes() for path in external.rglob("*") if path.is_file()
        }
        (data_dir / ".main").symlink_to(external, target_is_directory=True)

    package_before = sha256_file(package)
    unpack_calls: list[Path] = []
    real_unpack = site_module.unpack

    def tracked_unpack(package_path: Path, destination: Path, **kwargs) -> int:
        unpack_calls.append(package_path)
        return real_unpack(package_path, destination, **kwargs)

    monkeypatch.setattr(site_module, "unpack", tracked_unpack)
    ctx = RuleContext(
        task_id=data_dir.name,
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum=checksum,
        product="UMF",
    )

    result = main_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["reused"] is False
    assert evidence.read_text(encoding="utf-8") == "evidence"
    assert not (data_dir / ".main").is_symlink()
    assert not (data_dir / ".main.staging").exists()
    assert not (data_dir / ".main.previous").exists()
    assert unpack_calls == [package]
    assert sha256_file(package) == package_before == checksum
    if moved is not None:
        assert not moved.exists()
    if external is not None and external_before is not None:
        assert {
            path.relative_to(external).as_posix(): path.read_bytes() for path in external.rglob("*") if path.is_file()
        } == external_before


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_production_main_inspector_never_reuses_legacy_manifest(
    tmp_path: Path,
    monkeypatch,
    version: int,
) -> None:
    """生产 pkg.extract.main 即使遇到同 checksum 的 v1-v4 也必须从原包重建。"""
    from app.inspectors.pkg import main_inspector
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    _use_production_classification_config(monkeypatch)
    package = _v5_package(env, name=f"main-inspector-v{version}.zip")
    data_dir = env.task_dir(f"task-main-inspector-v{version}")
    checksum, _ = _write_production_v5_site(package, data_dir)
    manifest_path = data_dir / "manifest.json"
    legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_manifest["version"] = version
    manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")
    unpack_calls: list[Path] = []
    real_unpack = site_module.unpack

    def tracked_unpack(package_path: Path, destination: Path, **kwargs) -> int:
        unpack_calls.append(package_path)
        return real_unpack(package_path, destination, **kwargs)

    monkeypatch.setattr(site_module, "unpack", tracked_unpack)
    ctx = RuleContext(
        task_id=f"task-main-inspector-v{version}",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum=checksum,
        product="UMF",
    )

    result = main_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["reused"] is False
    assert unpack_calls == [package]
    assert sha256_file(package) == checksum


def test_production_main_inspector_reports_checksum_conflict_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """生产入口必须使用首次接收 checksum，冲突时 ERROR 且不修改证据或原包。"""
    from app.inspectors.pkg import main_inspector

    env = setup_env(tmp_path, monkeypatch)
    _use_production_classification_config(monkeypatch)
    package = _v5_package(env, name="main-inspector-conflict.zip")
    data_dir = env.task_dir("task-main-inspector-conflict")
    checksum, _ = _write_production_v5_site(package, data_dir)
    package_before = sha256_file(package)
    manifest_before = (data_dir / "manifest.json").read_bytes()
    evidence_before = {
        path.relative_to(data_dir / ".main").as_posix(): path.read_bytes()
        for path in (data_dir / ".main").rglob("*")
        if path.is_file()
    }
    ctx = RuleContext(
        task_id="task-main-inspector-conflict",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum="0" * 64,
        product="UMF",
    )

    result = main_inspector.run(ctx)

    assert result.status == RuleStatus.ERROR
    assert result.metadata["error_code"] == "package_checksum_conflict"
    assert sha256_file(package) == package_before == checksum
    assert (data_dir / "manifest.json").read_bytes() == manifest_before
    assert {
        path.relative_to(data_dir / ".main").as_posix(): path.read_bytes()
        for path in (data_dir / ".main").rglob("*")
        if path.is_file()
    } == evidence_before


def test_production_classification_inspector_reports_invalid_config_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """分类配置无效时必须返回稳定错误码，且不得复用或改动既有证据现场。"""
    from app.inspectors import pkg as pkg_module
    from app.inspectors.pkg import classification_inspector
    from app.services.extraction import site as site_module
    from app.services.extraction.config import ClassificationConfigError

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env, name="classification-inspector-invalid-config.zip")
    data_dir = env.task_dir("task-classification-inspector-invalid-config")
    evidence = data_dir / ".main/payload.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"existing evidence")
    manifest = data_dir / "manifest.json"
    manifest.write_bytes(b"existing manifest")
    package_before = sha256_file(package)

    def invalid_config(*_args, **_kwargs) -> object:
        raise ClassificationConfigError(
            "目标首段不在 allowlist",
            path="routes[3].target",
            route_id="umf.basic",
        )

    monkeypatch.setattr(pkg_module, "load_classification_config", invalid_config)
    monkeypatch.setattr(
        site_module,
        "reusable_extraction_site",
        lambda *_args, **_kwargs: pytest.fail("无效配置不得复用分类现场"),
    )
    monkeypatch.setattr(
        pkg_module,
        "classify_main_evidence",
        lambda *_args, **_kwargs: pytest.fail("无效配置不得重建分类现场"),
    )
    ctx = RuleContext(
        task_id="task-classification-inspector-invalid-config",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum=package_before,
        product="UMF",
    )

    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.ERROR
    assert result.metadata["error_code"] == "invalid_classification_config"
    assert result.metadata["detail"]["path"] == "routes[3].target"
    assert result.metadata["detail"]["route_id"] == "umf.basic"
    assert evidence.read_bytes() == b"existing evidence"
    assert manifest.read_bytes() == b"existing manifest"
    assert sha256_file(package) == package_before


def test_production_main_inspector_caches_context_checksum_and_verifies_once_per_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """上下文 checksum 只计算一次，每次生产主包执行仍由现场入口复核一次。"""
    import app.core.checksum as checksum_module
    from app.inspectors.pkg import main_inspector
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    _use_production_classification_config(monkeypatch)
    package = _v5_package(env, name="main-inspector-checksum-once.zip")
    data_dir = env.task_dir("task-main-inspector-checksum-once")
    checksum, _ = _write_production_v5_site(package, data_dir)
    context_checksum_calls: list[Path] = []
    site_checksum_calls: list[Path] = []
    real_context_sha256_file = checksum_module.sha256_file
    real_site_sha256_file = site_module.sha256_file

    def counting_context_sha256_file(path: Path) -> str:
        context_checksum_calls.append(path)
        return real_context_sha256_file(path)

    def counting_site_sha256_file(path: Path) -> str:
        site_checksum_calls.append(path)
        return real_site_sha256_file(path)

    monkeypatch.setattr(checksum_module, "sha256_file", counting_context_sha256_file)
    monkeypatch.setattr(site_module, "sha256_file", counting_site_sha256_file)
    monkeypatch.setattr(site_module, "unpack", lambda *_args, **_kwargs: pytest.fail("有效 v5 现场不得重新解压"))
    ctx = RuleContext(
        task_id="task-main-inspector-checksum-once",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        product="UMF",
    )

    first = main_inspector.run(ctx)
    second = main_inspector.run(ctx)

    assert first.status == RuleStatus.PASS
    assert second.status == RuleStatus.PASS
    assert first.metadata["reused"] is True
    assert second.metadata["reused"] is True
    assert context_checksum_calls == [package]
    assert site_checksum_calls == [package, package]
    assert ctx.package_checksum == checksum


def _external_main_controls(root: Path) -> dict[Path, bytes]:
    """在任务根外构造三类控制路径哨兵，用于验证不会被越界清理。"""
    sentinels = {
        root / ".main.staging/sentinel.txt": b"staging",
        root / ".main.previous/sentinel.txt": b"previous",
        root / ".main/payload.txt": b"main",
    }
    for path, content in sentinels.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return sentinels


def test_production_main_inspector_rejects_linked_task_root_before_evidence_discovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """生产入口必须在推导场景根前拒绝链接任务根，避免扫描外部 .main。"""
    from app.inspectors import pkg as pkg_module
    from app.inspectors.pkg import main_inspector

    env = setup_env(tmp_path, monkeypatch)
    _use_production_classification_config(monkeypatch)
    package = _v5_package(env, name="linked-production-root.zip")
    external_task = tmp_path / "external-production-root/task"
    sentinels = _external_main_controls(external_task)
    data_dir = env.task_dir("task-linked-production-root")
    data_dir.symlink_to(external_task, target_is_directory=True)
    infer_calls: list[Path] = []

    def track_infer(evidence_root: Path, _anchors: tuple[str, ...]) -> object:
        infer_calls.append(evidence_root)
        raise AssertionError("链接任务根不得进入场景根扫描")

    monkeypatch.setattr(pkg_module, "infer_scene_root", track_infer)
    ctx = RuleContext(
        task_id="task-linked-production-root",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum=sha256_file(package),
        product="UMF",
    )

    result = main_inspector.run(ctx)

    assert result.status == RuleStatus.ERROR
    assert result.metadata["error_code"] == "link_rejected"
    assert infer_calls == []
    assert {path: path.read_bytes() for path in sentinels} == sentinels


@pytest.mark.parametrize("link_kind", ["task-root", "direct-parent", "nested-output-ancestor"])
def test_ensure_main_evidence_rejects_linked_task_root_before_touching_controls(
    tmp_path: Path,
    monkeypatch,
    link_kind: str,
) -> None:
    """任务根或其祖先为链接时，不得越界读取、删除或覆盖控制路径。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env, name=f"linked-{link_kind}.zip")
    external_task = tmp_path / f"external-{link_kind}/task"
    sentinels = _external_main_controls(external_task)
    if link_kind == "task-root":
        data_dir = env.task_dir(f"task-{link_kind}")
        data_dir.symlink_to(external_task, target_is_directory=True)
    elif link_kind == "direct-parent":
        linked_parent = tmp_path / "linked-parent"
        linked_parent.symlink_to(external_task.parent, target_is_directory=True)
        data_dir = linked_parent / external_task.name
    else:
        linked_parent = env.output / "linked-parent"
        linked_parent.symlink_to(external_task.parent.parent, target_is_directory=True)
        data_dir = linked_parent / "nested" / "task"

    with pytest.raises(ArchiveError) as error:
        site_module.ensure_main_evidence(package, data_dir, sha256_file(package))

    assert error.value.error_code == "link_rejected"
    assert {path: path.read_bytes() for path in sentinels} == sentinels


def test_ensure_main_evidence_allows_output_root_symlink(tmp_path: Path, monkeypatch) -> None:
    """只允许配置的 output 根本身是链接，任务根及其下方仍必须逐段校验。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env, name="output-root-link.zip")
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    env.output.rmdir()
    env.output.symlink_to(real_output, target_is_directory=True)
    data_dir = env.output / "task-output-root-link"

    main = site_module.ensure_main_evidence(package, data_dir, sha256_file(package))

    assert main["reused"] is False
    assert (real_output / "task-output-root-link/.main/payload.txt").read_text(encoding="utf-8") == "evidence"
    assert env.output.is_symlink()


def test_ensure_main_evidence_allows_link_above_task_output_root(tmp_path: Path, monkeypatch) -> None:
    """平台级祖先后缀链接不应阻断正常任务，只校验任务根与直接输出根。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env, name="platform-ancestor-link.zip")
    real_parent = tmp_path / "real-platform-parent"
    real_parent.mkdir()
    platform_link = tmp_path / "platform-link"
    platform_link.symlink_to(real_parent, target_is_directory=True)
    data_dir = platform_link / "output" / "task-platform-link"

    main = site_module.ensure_main_evidence(package, data_dir, sha256_file(package))

    assert main["reused"] is False
    assert (data_dir / ".main/payload.txt").read_text(encoding="utf-8") == "evidence"
    assert (real_parent / "output/task-platform-link/.main/payload.txt").is_file()


@pytest.mark.parametrize("control_name", [".main.staging", ".main.previous", ".main"])
def test_ensure_main_evidence_unlinks_control_symlink_without_touching_target(
    tmp_path: Path,
    monkeypatch,
    control_name: str,
) -> None:
    """控制路径本身为链接时只移除链接，绝不读取或清理其外部目标。"""
    from app.services.extraction import site as site_module

    env = setup_env(tmp_path, monkeypatch)
    package = _v5_package(env, name=f"control-{control_name.removeprefix('.')}.zip")
    data_dir = env.task_dir(f"task-control-{control_name.removeprefix('.')}")
    data_dir.mkdir(parents=True)
    external = tmp_path / f"external-{control_name.removeprefix('.')}"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_bytes(b"outside")
    (data_dir / control_name).symlink_to(external, target_is_directory=True)
    before = sha256_file(package)

    main = site_module.ensure_main_evidence(package, data_dir, sha256_file(package))

    assert main["reused"] is False
    assert sentinel.read_bytes() == b"outside"
    assert (data_dir / ".main/payload.txt").read_text(encoding="utf-8") == "evidence"
    assert not (data_dir / control_name).is_symlink()
    assert sha256_file(package) == before
