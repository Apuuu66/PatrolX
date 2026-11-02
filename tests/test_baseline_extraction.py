"""manifest v5 下的分类、嵌套展开与局部失败容错测试。"""

import zipfile
from pathlib import Path

from app.services.extraction.manifest import read_manifest
from tests.baseline_helpers import SAMPLE, Env, load_logs, load_rule, setup_env


def test_sample_extraction_classifies_and_expands_nested_package(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-sample", customer={"product": "UMF"})
    task_dir = env.task_dir(task.task_id)
    manifest = read_manifest(task_dir)

    assert manifest["version"] == 5
    assert manifest["product"] == "UMF"
    assert manifest["classification"]["profile"] == "UMF"
    assert manifest["summary"]["counts"]["failures"] == 0
    assert any(entry["category"] == "log" for entry in manifest["entries"])
    main_archives = list((task_dir / ".main").rglob("ServiceLogs_20260901011314.zip"))
    assert len(main_archives) == 1
    assert not (task_dir / "logs" / "ServiceLogs_20260901011314.zip").exists()
    extracted_logs = list((task_dir / "logs").rglob("*.log"))
    assert len(extracted_logs) == 3
    assert load_rule(env, task.task_id, "pkg.extract.main")["status"] == "pass"
    assert load_rule(env, task.task_id, "pkg.extract.classification")["status"] == "pass"


def test_repeated_main_extraction_reuses_site(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task_id = "task-sample"
    first = run_task(SAMPLE, task_id=task_id, customer={"product": "UMF"})
    manifest_before = read_manifest(env.task_dir(task_id))
    nested_count = len(list((env.task_dir(task_id) / "logs").rglob("*.log")))

    second = run_task(SAMPLE, task_id=task_id, customer={"product": "UMF"})
    manifest_after = read_manifest(env.task_dir(task_id))

    assert second.system.package_checksum == first.system.package_checksum
    assert manifest_after == manifest_before
    assert len(list((env.task_dir(task_id) / "logs").rglob("*.log"))) == nested_count


def test_invalid_nested_archive_does_not_abort_task(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "bad-nested.zip"
    bad_member = "UMF Problem Scene/Service Logs (Problem)/ServiceLogs_bad.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr(bad_member, "this is not an archive")

    from app.cli import run_task

    task = run_task(package, task_id="task-bad-nested", customer={"product": "UMF"})
    logs = load_logs(env, task.task_id)
    manifest = read_manifest(env.task_dir(task.task_id))
    result = load_rule(env, task.task_id, "pkg.extract.classification")

    assert task.status == "completed"
    assert result["status"] == "warn"
    assert result["metadata"]["failed"] == len(manifest["failures"]) == 1
    assert result["metadata"]["failures"] == manifest["failures"]
    failure = manifest["failures"][0]
    assert failure["source_relative"] == bad_member
    assert failure["route_id"] == "umf.service-logs"
    assert failure["error_code"] == "archive_corrupt"
    assert failure["reason"]
    assert any("分类存在局部失败，继续执行 prepare 和 inspect" in entry["message"] for entry in logs)
    assert (env.task_dir(task.task_id) / "manifest.json").is_file()
