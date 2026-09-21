"""本地与在线模式使用同一执行契约的一致性测试。"""

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.extraction import read_manifest
from tests.baseline_helpers import (
    SAMPLE,
    load_logs,
    setup_env,
    strip_volatile,
    upload_package,
    wait_for_task,
)

client = TestClient(app)


def test_local_and_online_contract_results_match(tmp_path: Path, monkeypatch) -> None:
    local_env = setup_env(tmp_path / "local", monkeypatch)
    from app.cli import run_task

    local_task = run_task(
        SAMPLE,
        name="一致性",
        customer={"province": "北京", "operator": "移动"},
        version="v1",
    )
    local_system = local_task.system.model_dump(by_alias=True, mode="json")

    online_env = setup_env(tmp_path / "online", monkeypatch)
    task_id = upload_package(
        online_env,
        client,
        name="一致性",
        province="北京",
        operator="移动",
        version="v1",
    )
    wait_for_task(client, task_id)
    task_response = client.get(f"/api/v2/tasks/{task_id}")
    assert task_response.status_code == 200
    system_response = client.get(f"/api/v2/tasks/{task_id}/system")
    assert system_response.status_code == 200
    online_task = task_response.json()
    online_system = system_response.json()

    assert local_task.task_id == task_id
    assert online_task["task_id"] == local_task.task_id
    assert online_task["stats"] == local_task.stats.model_dump(by_alias=True, mode="json")

    local_stripped = strip_volatile(local_system)
    online_stripped = strip_volatile(online_system)
    assert local_stripped["summary"] == online_stripped["summary"]
    assert local_stripped["package_file"] == online_stripped["package_file"]
    assert local_stripped["customer"] == online_stripped["customer"]
    assert local_stripped["version"] == online_stripped["version"]
    for index, (local_rule, online_rule) in enumerate(
        zip(local_stripped["rules"], online_stripped["rules"], strict=False)
    ):
        assert local_rule == online_rule, {
            "index": index,
            "differences": {
                key: (local_rule.get(key), online_rule.get(key))
                for key in local_rule.keys() | online_rule.keys()
                if local_rule.get(key) != online_rule.get(key)
            },
        }
    assert len(local_stripped["rules"]) == len(online_stripped["rules"])
    assert local_env.task_dir(task_id).is_dir()
    assert online_env.task_dir(task_id).is_dir()

    local_manifest = read_manifest(local_env.task_dir(task_id))
    online_manifest = read_manifest(online_env.task_dir(task_id))
    assert local_manifest["policy"] == online_manifest["policy"]
    assert local_manifest["subpackages"] == online_manifest["subpackages"]
    assert local_manifest["log_gz"] == online_manifest["log_gz"]


def test_same_metadata_packages_remain_isolated(tmp_path: Path, monkeypatch) -> None:
    """相同系统元数据下，不同包名必须形成互不覆盖的任务现场。"""
    env = setup_env(tmp_path, monkeypatch)
    first_package = tmp_path / "metadata-a.zip"
    second_package = tmp_path / "metadata-b.zip"
    shutil.copyfile(SAMPLE, first_package)
    shutil.copyfile(SAMPLE, second_package)

    first_id = upload_package(
        env,
        client,
        package=first_package,
        name="同一元数据",
        province="北京",
        operator="移动",
        version="v1",
    )
    second_id = upload_package(
        env,
        client,
        package=second_package,
        name="同一元数据",
        province="北京",
        operator="移动",
        version="v1",
    )
    assert first_id != second_id
    wait_for_task(client, first_id)
    wait_for_task(client, second_id)

    for task_id in (first_id, second_id):
        task_dir = env.task_dir(task_id)
        assert task_dir.is_dir()
        assert (task_dir / "task.json").is_file()
        assert (task_dir / "system.json").is_file()
        assert (task_dir / "rules" / "kpi.measurement_units.json").is_file()
        assert (task_dir / "report.html").is_file()
        assert load_logs(env, task_id)

    first = client.get(f"/api/v2/tasks/{first_id}").json()
    second = client.get(f"/api/v2/tasks/{second_id}").json()
    assert first["task_id"] == first_id
    assert second["task_id"] == second_id
    assert first["system"]["package_file"] == first_package.name
    assert second["system"]["package_file"] == second_package.name
