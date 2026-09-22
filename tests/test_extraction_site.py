"""任务现场、多级子包与 `.log.gz` 展开测试。"""

import gzip
import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError
from app.core.checksum import sha256_file
from app.services import extraction
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
    """构造主包 → KPI 外层子包 → KPI 子包 + 日志子包的样例。"""
    service_zip = env.uploads / "_build" / "ServiceLog_20260901011314.zip"
    _zip(
        service_zip,
        {
            "AppService/logs/paas-node-1/app.log": "2026-09-01T10:00:00Z INFO  app started\n",
            "AppService/logs/paas-node-1/app_history.log": "history",
        },
    )
    kpi_inner_zip = env.uploads / "_build" / "kpi_data.zip"
    _zip(kpi_inner_zip, {"kpi/inner_kpi.csv": "metric,value\nsuccess,99\n"})
    log_inner_zip = env.uploads / "_build" / "ServiceLog_inner.zip"
    _zip(
        log_inner_zip,
        {"InnerService/logs/paas-node-2/error.log.gz": gzip.compress(b"2026-09-01T10:01:00Z ERROR inner failure\n")},
    )
    kpi_outer_zip = env.uploads / "_build" / "kpi_outer.zip"
    _zip(
        kpi_outer_zip,
        {
            "kpi_data.zip": kpi_inner_zip.read_bytes(),
            "ServiceLog_inner.zip": log_inner_zip.read_bytes(),
        },
    )

    package = env.uploads / "nested.zip"
    _zip(
        package,
        {
            "ServiceLog_20260901011314.zip": service_zip.read_bytes(),
            "kpi_outer.zip": kpi_outer_zip.read_bytes(),
            "config/system.ini": "[app]\nname=app\n",
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

    task = run_task(package, task_id="task-extraction")
    task_dir = env.task_dir(task.task_id)
    main_files = _relative_files(task_dir / ".main")

    assert main_files == {
        "ServiceLog_20260901011314.zip",
        "kpi_outer.zip",
        "config/system.ini",
    }
    assert (task_dir / "logs/AppService/logs/paas-node-1/app_history.log").is_file()
    assert (task_dir / "kpi/kpi/inner_kpi.csv").is_file()
    assert (task_dir / "logs/InnerService/logs/paas-node-2/error.log").is_file()

    work_files = _relative_files(task_dir / "logs") | _relative_files(task_dir / "kpi")
    assert not any(name.endswith((".zip", ".tar", ".tar.gz", ".tgz", ".log.gz")) for name in work_files)


def test_nested_evidence_package_does_not_leave_category_tree(tmp_path, monkeypatch) -> None:
    """主包内嵌套目录下的子包展开后，分类目录不保留空的原始路径树。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    service_zip = env.uploads / "_build" / "ServiceLog_nested.zip"
    _zip(
        service_zip,
        {"AppService/logs/node/app.log": "2026-09-01T10:00:00Z INFO  app\n"},
    )
    package = env.uploads / "nested-site.zip"
    _zip(package, {"Problem scene/ServiceLog_nested.zip": service_zip.read_bytes()})

    from app.cli import run_task

    task = run_task(package, task_id="task-empty-site")
    task_dir = env.task_dir(task.task_id)

    assert (task_dir / "logs/AppService/logs/node/app.log").is_file()
    assert not (task_dir / "logs/Problem scene").exists()


def test_extraction_process_is_logged(tmp_path, monkeypatch) -> None:
    """主包、子包和日志 gzip 的关键解压过程写入执行日志。"""

    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    data_dir = env.task_dir("task-logs")
    data_dir.mkdir(parents=True, exist_ok=True)
    logs: list[tuple[str, str, dict]] = []

    def log(level: str, message: str, **detail: object) -> None:
        logs.append((level, message, dict(detail)))

    extraction.extract_main_site(package, data_dir, sha256_file(package), log=log)

    messages = [message for _, message, _ in logs]
    assert "主包解压开始" in messages
    assert "子包解压开始" in messages
    assert "主包解压完成" in messages
    assert "子包解压完成" in messages
    assert "日志 gzip 解压完成" in messages

    main_start = next(i for i, (_, message, _) in enumerate(logs) if message == "主包解压开始")
    main_complete = next(i for i, (_, message, _) in enumerate(logs) if message == "主包解压完成")
    log_subpackage = "ServiceLog_inner.zip"
    sub_start = next(
        i
        for i, (_, message, detail) in enumerate(logs)
        if message == "子包解压开始" and detail["source"] == log_subpackage
    )
    sub_complete = next(
        i
        for i, (_, message, detail) in enumerate(logs)
        if message == "子包解压完成" and detail["source"] == log_subpackage
    )
    gzip_complete = next(
        i
        for i, (_, message, detail) in enumerate(logs)
        if message == "日志 gzip 解压完成" and detail["source"] == "InnerService/logs/paas-node-2/error.log.gz"
    )
    assert main_start < sub_start < gzip_complete < sub_complete < main_complete
    assert logs[-1][2]["task_id"] == "task-logs"


def test_run_task_writes_extraction_logs(tmp_path, monkeypatch) -> None:
    """规则上下文将解压日志写入任务 execution.log。"""
    import json

    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)

    from app.cli import run_task

    task = run_task(package, task_id="task-log-file")
    log_path = env.task_dir(task.task_id) / "execution.log"
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    messages = [entry["message"] for entry in entries]

    assert "主包解压开始" in messages
    assert "子包解压开始" in messages
    assert "子包解压完成" in messages
    assert "日志 gzip 解压完成" in messages
    assert "主包解压完成" in messages
    assert all("task_id" in entry for entry in entries if entry["message"].startswith("主包解压"))

    main_start = next(i for i, entry in enumerate(entries) if entry["message"] == "主包解压开始")
    main_complete = next(i for i, entry in enumerate(entries) if entry["message"] == "主包解压完成")
    log_subpackage = "ServiceLog_inner.zip"
    sub_start = next(
        i for i, entry in enumerate(entries) if entry["message"] == "子包解压开始" and entry["source"] == log_subpackage
    )
    sub_complete = next(
        i for i, entry in enumerate(entries) if entry["message"] == "子包解压完成" and entry["source"] == log_subpackage
    )
    gzip_complete = next(
        i
        for i, entry in enumerate(entries)
        if entry["message"] == "日志 gzip 解压完成" and entry["source"] == "InnerService/logs/paas-node-2/error.log.gz"
    )
    assert main_start < sub_start < gzip_complete < sub_complete < main_complete


def test_log_gz_conflict_and_failure_are_isolated(tmp_path, monkeypatch) -> None:
    """冲突和损坏 gzip 保留证据并记录状态，不阻断其他文件。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    service_zip = env.uploads / "_build" / "ServiceLog.zip"
    _gz(env.uploads / "_build" / "ok.log.gz", "2026-09-01T10:00:00Z INFO  ok\n")
    _gz(env.uploads / "_build" / "conflict.log.gz", "history should not overwrite")
    _gz(env.uploads / "_build" / "bad.log.gz", "will corrupt below")
    bad_bytes = (env.uploads / "_build" / "bad.log.gz").read_bytes()[:-4]
    _zip(
        service_zip,
        {
            "AppService/logs/node/existing.log": "current file\n",
            "AppService/logs/node/existing.log.gz": gzip.compress(b"history\n"),
            "AppService/logs/node/ok.log.gz": gzip.compress(b"2026-09-01T10:00:01Z INFO  ok\n"),
            "AppService/logs/node/bad.log.gz": bad_bytes,
        },
    )
    package = env.uploads / "failure.zip"
    _zip(package, {"ServiceLog.zip": service_zip.read_bytes()})

    from app.cli import run_task

    task = run_task(package, task_id="task-failure")
    task_dir = env.task_dir(task.task_id)
    manifest_path = task_dir / ".patrolx-extracted.json"
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    states = {Path(item["target"]).name: item for item in manifest["log_gz"]}
    logs_dir = task_dir / "logs/AppService/logs/node"

    assert task.status == "completed"
    assert states["ok.log"]["status"] == "extracted"
    assert states["existing.log"]["status"] == "conflict"
    assert states["bad.log"]["status"] == "failed"
    assert (logs_dir / "ok.log").is_file()
    assert (logs_dir / "existing.log").is_file()
    assert not (logs_dir / "ok.log.gz").exists()


def test_second_run_is_idempotent(tmp_path, monkeypatch) -> None:
    """同一包二次执行复用现场，不产生重复文件或变化。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    from app.cli import run_task

    first = run_task(package, task_id="task-rerun")
    task_dir = env.task_dir(first.task_id)
    first_files = _relative_files(task_dir)
    first_manifest = (task_dir / ".patrolx-extracted.json").read_text(encoding="utf-8")

    run_task(package, task_id="task-rerun")
    second_files = _relative_files(task_dir)
    second_manifest = (task_dir / ".patrolx-extracted.json").read_text(encoding="utf-8")

    assert second_files == first_files
    assert second_manifest == first_manifest


def test_normal_rules_do_not_match_main_evidence(tmp_path, monkeypatch) -> None:
    """普通规则匹配入口排除 `.main/` 和 manifest。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    from app.cli import run_task
    from app.services.scanning import TaskFileCatalog

    task = run_task(package, task_id="task-matching")
    task_dir = env.task_dir(task.task_id)
    matched = TaskFileCatalog.build(task_dir).match([r".*"])

    posix_paths = [path.as_posix() for path in matched]

    assert "kpi/kpi/inner_kpi.csv" in posix_paths
    assert not any(path.startswith(".main/") for path in posix_paths)
    assert ".patrolx-extracted.json" not in posix_paths


def test_manifest_structure_and_old_version_are_not_reused(tmp_path, monkeypatch) -> None:
    """manifest v3 结构不完整、损坏或旧版本时必须整体重建现场。"""
    import json

    env = setup_env(tmp_path, monkeypatch)
    package = _multi_level_package(env)
    checksum = sha256_file(package)
    from app.cli import run_task

    first = run_task(package, task_id="task-manifest")
    task_dir = env.task_dir(first.task_id)

    assert extraction.reusable_manifest(task_dir, checksum) is not None
    manifest_path = task_dir / extraction.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert extraction.reusable_manifest(task_dir, checksum) is None

    manifest["version"] = 3
    manifest["subpackages"][0]["status"] = "unknown"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert extraction.reusable_manifest(task_dir, checksum) is None

    files_before = _relative_files(task_dir / ".main")
    second = run_task(package, task_id="task-manifest")
    manifest_after = json.loads((task_dir / extraction.MANIFEST_NAME).read_text(encoding="utf-8"))

    assert second.task_id == first.task_id
    assert manifest_after["main"]["reused"] is False
    assert _relative_files(task_dir / ".main") == files_before


def _budget_package(env: Env) -> Path:
    """构造用于任务级预算测试的普通文件与 gzip 日志包。"""
    package = env.uploads / "budget.zip"
    _zip(
        package,
        {
            "config/system.ini": "[app]\nname=app\n",
            "config/version.ini": "version=1\n",
            "logs/node/app.log.gz": gzip.compress(b"2026-09-01T10:00:00Z INFO  app\n"),
        },
    )
    return package


def test_task_level_budget_allows_3gb() -> None:
    """任务级累计解压预算应为 3GB。"""
    from app.services.extraction.budget import ExtractionBudget

    assert ExtractionBudget.max_total_bytes == 3 * 1024 * 1024 * 1024


def test_task_level_budget_failures_are_isolated_and_recorded(tmp_path, monkeypatch) -> None:
    """任务级文件预算拒绝对应文件，记录 rejected，不中断后续 gzip 处理。"""

    env = setup_env(tmp_path, monkeypatch)
    package = _budget_package(env)
    data_dir = env.task_dir("task-budget")
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(extraction.ExtractionBudget, "max_files", 1)

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert manifest["main"]["count"] == 3
    assert any(
        item["source"] == "config/version.ini" and item["reason"] == "任务累计文件数超限"
        for item in manifest["rejected"]
    )
    assert (data_dir / extraction.MANIFEST_NAME).is_file()


def test_gzip_budget_failure_is_isolated_and_recorded(tmp_path, monkeypatch) -> None:
    """gzip 输出超过任务累计预算时记录失败，不生成目标 .log。"""

    env = setup_env(tmp_path, monkeypatch)
    package = _budget_package(env)
    data_dir = env.task_dir("task-gzip-budget")
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(extraction.ExtractionBudget, "max_total_bytes", 1)

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert len(manifest["log_gz"]) == 1
    assert manifest["log_gz"][0]["status"] == "failed"
    assert manifest["log_gz"][0]["error"] == "任务累计解压总量超限：单任务累计解压上限 1.0 B，请减少包内容或拆分数据包"
    assert any(item["reason"].startswith("任务累计解压总量超限") for item in manifest["rejected"])
    assert not (data_dir / "logs/node/app.log").exists()
    assert manifest["main"]["count"] == 3


def _classified_package(env: Env) -> Path:
    """构造覆盖 logs/kpi/config/resource 的主包与目标冲突来源。"""
    service_zip = env.uploads / "_build" / "ServiceLog_classified.zip"
    _zip(service_zip, {"AppService/logs/node/app.log": "app log\n"})
    package = env.uploads / "classified.zip"
    _zip(
        package,
        {
            "config/system.ini": "[app]\nname=app\n",
            "resource/host.out": '{"host": "node-1"}',
            "AppService_logs.zip": service_zip.read_bytes(),
            "kpi/kpi-api.csv": "metric,value\nsuccess,99\n",
        },
    )
    return package


def test_classified_files_place_directly_by_category(tmp_path, monkeypatch) -> None:
    """普通文件、日志和子包成员直接进入分类根，且原始包内容不变。"""
    import hashlib

    env = setup_env(tmp_path, monkeypatch)
    package = _classified_package(env)
    before = package.read_bytes()
    data_dir = env.task_dir("task-classified")

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert hashlib.sha256(package.read_bytes()).hexdigest() == hashlib.sha256(before).hexdigest()
    assert (data_dir / "config/system.ini").is_file()
    assert (data_dir / "kpi/kpi-api.csv").is_file()
    assert (data_dir / "resource/host.out").is_file()
    assert (data_dir / "logs/AppService/logs/node/app.log").is_file()
    assert manifest["version"] == 4
    assert any(item["target"] == "logs/AppService/logs/node/app.log" for item in manifest["files"])
    assert any(item["target"] == "config/system.ini" for item in manifest["files"])
    assert not (data_dir / "logs/ServiceLog_classified").exists()


def test_path_limit_blocks_main_evidence_before_rebuild(tmp_path, monkeypatch) -> None:
    """主包证据目标命中路径限制时提前失败，不生成新 manifest。"""
    from app.services.extraction.layout import PathLimitPolicy

    env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "too-long-main.zip"
    _zip(package, {"config/system.ini": "ok"})
    data_dir = env.task_dir("task-too-long-main")
    policy = PathLimitPolicy(enabled=True, limit=len(str(data_dir / ".main" / "config/system.ini")))

    with pytest.raises(ArchiveError, match="目标路径长度"):
        extraction.extract_main_site(package, data_dir, sha256_file(package), path_policy=policy)
    assert not (data_dir / extraction.MANIFEST_NAME).exists()


def test_path_limit_records_normal_file_and_cleans_partial_file(tmp_path, monkeypatch) -> None:
    """普通文件路径过长提前失败，记录 path_too_long 且不留下半成品。"""
    from app.services.extraction.budget import ExtractionBudget
    from app.services.extraction.layout import PathLimitPolicy
    from app.services.extraction.nested import _ingest_file

    source = tmp_path / "source.ini"
    source.write_text("ok", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    destination = data_dir / "config/system.ini"
    policy = PathLimitPolicy(enabled=True, limit=len(str(destination)))
    manifest = {"files": [], "rejected": []}

    _ingest_file(
        source,
        Path("config/system.ini"),
        "evidence",
        "",
        data_dir,
        manifest,
        ExtractionBudget(),
        set(),
        1,
        None,
        None,
        policy,
    )

    item = manifest["files"][0]
    assert item["status"] == "failed"
    assert item["error_code"] == "path_too_long"
    assert item["path_length"] == len(str(destination))
    assert item["path_limit"] == len(str(destination))
    assert not destination.exists()


def test_path_limit_records_log_gz_and_nested_staging(tmp_path, monkeypatch) -> None:
    """日志和子包 staging 命中限制时记录失败并清理。"""
    from app.services.extraction.layout import PathLimitPolicy

    env = setup_env(tmp_path, monkeypatch)
    inner_zip = env.uploads / "_build" / "long-inner.zip"
    _zip(inner_zip, {"AppService/logs/node/app.log": "log\n"})
    package = env.uploads / "too-long-items.zip"
    _zip(
        package,
        {
            "logs/node/app.log.gz": gzip.compress(b"log\n"),
            "ServiceLog.zip": inner_zip.read_bytes(),
        },
    )
    data_dir = env.task_dir("task-too-long-items")
    staging_root = data_dir / f".extract-{sha256_file(inner_zip)[:12]}"
    policy = PathLimitPolicy(enabled=True, limit=len(str(staging_root / "AppService/logs/node/app.log")))

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package), path_policy=policy)

    assert manifest["log_gz"][0]["status"] == "extracted"
    assert manifest["subpackages"][0]["status"] == "failed"
    assert manifest["subpackages"][0]["error_code"] == "path_too_long"
    assert not (data_dir / "logs/AppService").exists()
    assert not any(path.name.startswith(".extract-") for path in data_dir.iterdir())
