"""任务现场、多级子包与 `.log.gz` 展开测试。"""

import gzip
import zipfile
from pathlib import Path

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
    assert (task_dir / "logs/ServiceLog_20260901011314/AppService/logs/paas-node-1/app_history.log").is_file()
    assert (task_dir / "kpi/kpi_data/kpi/inner_kpi.csv").is_file()
    assert (task_dir / "logs/ServiceLog_inner/InnerService/logs/paas-node-2/error.log").is_file()

    work_files = _relative_files(task_dir / "logs") | _relative_files(task_dir / "kpi")
    assert not any(name.endswith((".zip", ".tar", ".tar.gz", ".tgz", ".log.gz")) for name in work_files)


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
    logs_dir = task_dir / "logs/ServiceLog/AppService/logs/node"

    assert task.status == "completed"
    assert states["ok.log"]["status"] == "extracted"
    assert states["existing.log"]["status"] == "conflict"
    assert states["bad.log"]["status"] == "failed"
    assert (logs_dir / "ok.log").is_file()
    assert (logs_dir / "existing.log").is_file()
    assert (logs_dir / "existing.log.gz").is_file()
    assert (logs_dir / "bad.log.gz").is_file()
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
    from app.services.prepare import match_relative_files

    task = run_task(package, task_id="task-matching")
    task_dir = env.task_dir(task.task_id)
    matched = match_relative_files(task_dir, [r"\.main/.*", r"kpi/.*\.csv", r"\.patrolx-extracted\.json"])

    assert [path.as_posix() for path in matched] == ["kpi/kpi_data/kpi/inner_kpi.csv"]


def test_manifest_structure_and_old_version_are_not_reused(tmp_path, monkeypatch) -> None:
    """manifest v3 结构不完整、损坏或旧版本时必须整体重建现场。"""
    import json

    from app.core.checksum import sha256_file
    from app.services import extraction

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


def test_task_level_budget_failures_are_isolated_and_recorded(tmp_path, monkeypatch) -> None:
    """任务级文件预算拒绝对应文件，记录 rejected，不中断后续 gzip 处理。"""
    from app.core.checksum import sha256_file
    from app.services import extraction

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
    from app.core.checksum import sha256_file
    from app.services import extraction

    env = setup_env(tmp_path, monkeypatch)
    package = _budget_package(env)
    data_dir = env.task_dir("task-gzip-budget")
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(extraction.ExtractionBudget, "max_total_bytes", 0)

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert len(manifest["log_gz"]) == 1
    assert manifest["log_gz"][0]["status"] == "failed"
    assert manifest["log_gz"][0]["error"] == "任务累计解压总量超限"
    assert any(item["reason"] == "任务累计解压总量超限" for item in manifest["rejected"])
    assert not (data_dir / "logs/node/app.log").exists()
    assert manifest["main"]["count"] == 3
