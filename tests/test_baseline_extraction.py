"""解压分类、嵌套子包与容错测试。"""

import json
import zipfile
from pathlib import Path

from tests.baseline_helpers import SAMPLE, Env, load_logs, load_rule, setup_env


def test_sample_extraction_classifies_and_extracts_nested_package(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-sample")
    task_dir = env.task_dir(task.task_id)
    manifest = (task_dir / ".patrolx-extracted.json").read_text(encoding="utf-8")

    assert '"category": "logs"' in manifest
    main_logs = list((task_dir / ".main").rglob("ServiceLog_20260901011314.zip"))
    assert len(main_logs) == 1
    assert not (task_dir / "logs" / "ServiceLog_20260901011314.zip").exists()
    extracted_logs = list((task_dir / "logs").rglob("*.log"))
    assert extracted_logs, "嵌套日志子包未解压"
    assert load_rule(env, task.task_id, "pkg.extract.main")["status"] == "pass"
    assert load_rule(env, task.task_id, "pkg.extract.logs")["status"] == "pass"


def test_repeated_main_extraction_reuses_site(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task_id = "task-sample"
    first = run_task(SAMPLE, task_id=task_id)
    manifest_path = env.task_dir(task_id) / ".patrolx-extracted.json"
    manifest_before = manifest_path.read_text(encoding="utf-8")
    nested_count = len(list((env.task_dir(task_id) / "logs").rglob("*.log")))

    second = run_task(SAMPLE, task_id=task_id)
    manifest_after = manifest_path.read_text(encoding="utf-8")

    assert second.system.package_checksum == first.system.package_checksum
    assert manifest_after == manifest_before
    assert len(list((env.task_dir(task_id) / "logs").rglob("*.log"))) == nested_count


def test_invalid_nested_archive_does_not_abort_task(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "bad-nested.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("logs/bad-service-log.zip", "this is not an archive")
        zf.writestr("kpi/kpi.csv", "name,value\nsuccess,1\n")

    from app.cli import run_task

    task = run_task(package, task_id="task-bad-nested")
    logs = load_logs(env, task.task_id)

    assert task.status == "completed"
    result = load_rule(env, task.task_id, "pkg.extract.logs")
    manifest = json.loads((env.task_dir(task.task_id) / ".patrolx-extracted.json").read_text(encoding="utf-8"))
    failures = [item for item in manifest["subpackages"] if item["status"] != "extracted"]

    assert result["status"] == "warn"
    assert result["metadata"]["failed"] == 1
    assert result["metadata"]["failures"] == [
        {
            "name": "bad-service-log.zip",
            "source": failures[0]["source"],
            "checksum": failures[0]["checksum"],
            "target": "logs",
            "error": failures[0]["error"],
            "error_code": None,
            "status": failures[0]["status"],
            "path_length": None,
            "path_limit": None,
        }
    ]
    assert failures[0]["checksum"]
    assert failures[0]["target"] == "logs"
    assert failures[0]["error"]
    assert any("分类解压项未成功" in entry["message"] for entry in logs)
    assert (env.task_dir(task.task_id) / ".patrolx-extracted.json").exists()
