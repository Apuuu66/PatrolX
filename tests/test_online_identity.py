"""本地与在线模式使用同一 catalog 匹配模型的定点一致性测试。"""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import (
    SAMPLE,
    setup_env,
    upload_package,
    wait_for_task,
)

client = TestClient(app)


def _source_paths(value: Any) -> set[str]:
    """递归收集契约结果中的任务相对源路径。"""
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_file", "config_source"} and isinstance(item, str):
                paths.add(item)
            if key == "path" and isinstance(item, str) and "/" in item:
                paths.add(item)
            if key in {"files", "processed_files"} and isinstance(item, list):
                paths.update(item for item in item if isinstance(item, str))
            paths.update(_source_paths(item))
    elif isinstance(value, list):
        for item in value:
            paths.update(_source_paths(item))
    return paths


def test_cli_and_online_catalog_source_paths_match(tmp_path: Path, monkeypatch) -> None:
    local_env = setup_env(tmp_path / "local", monkeypatch)
    from app.cli import run_task

    local_task = run_task(SAMPLE, name="Catalog 一致性", customer={"product": "UMF"})
    online_env = setup_env(tmp_path / "online", monkeypatch)
    task_id = upload_package(online_env, client, name="Catalog 一致性")
    wait_for_task(client, task_id)
    system_response = client.get(f"/api/v2/tasks/{task_id}/system")
    assert system_response.status_code == 200

    assert local_task.task_id == task_id
    # system.json 现在只保存规则摘要；大明细从规则结果接口做一致性校验。
    online_rules = {
        rule["code"]: client.get(f"/api/v2/tasks/{task_id}/rules/{rule['code']}").json()
        for rule in system_response.json()["rules"]
    }
    for local_path in local_env.rules_dir(task_id).glob("*.json"):
        local_rule = json.loads(local_path.read_text(encoding="utf-8"))
        if local_rule["code"].startswith("pkg.extract."):
            continue
        online_rule = online_rules[local_rule["code"]]
        assert local_rule["execution_order"] == online_rule["execution_order"]
        assert local_rule["status"] == online_rule["status"]
        assert _source_paths(local_rule) == _source_paths(online_rule)
        assert not any(path.startswith((".main/", "prepared/")) for path in _source_paths(local_rule))


def test_cli_and_online_identity_classification_catalog_and_ledger_match(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """同一包在本地与在线模式必须共享 task_id、profile、catalog 审计和台账过滤。"""
    from app.cli import run_task
    from app.models.schemas import TaskMode, TaskTrigger
    from app.services.extraction.manifest import read_manifest
    from tests.fixtures.inventory.builder import make_inventory_zip, multi_device_lst_me_content

    package = tmp_path / "identity-consistency.zip"
    make_inventory_zip(
        package,
        content=multi_device_lst_me_content(
            [
                {"device_name": "IDENTITY-UMF-001", "network_element_type": "umf", "version": "V1"},
                {"device_name": "IDENTITY-CSP-001", "network_element_type": "csp", "version": "V2"},
            ]
        ),
        member_path="Basic Information About the UMF/LST ME.txt",
    )

    local_env = setup_env(tmp_path / "local", monkeypatch)
    local_task = run_task(
        package,
        name="身份与分类一致性",
        customer={"province": "江苏", "operator": "移动", "product": "UMF"},
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
    )
    local_manifest = read_manifest(local_env.task_dir(local_task.task_id))

    online_env = setup_env(tmp_path / "online", monkeypatch)
    online_task_id = upload_package(
        online_env,
        client,
        package=package,
        name="身份与分类一致性",
        product="umf",
    )
    online_task = wait_for_task(client, online_task_id)
    online_manifest = read_manifest(online_env.task_dir(online_task_id))

    assert local_task.task_id == online_task_id
    assert local_task.package_kind.value == online_task["package_kind"] == "inspection"
    assert local_task.system is not None
    assert local_task.system.customer["product"] == online_task["system"]["customer"]["product"] == "UMF"
    assert local_manifest["classification"]["profile"] == online_manifest["classification"]["profile"]
    assert local_manifest["classification"]["snapshot"] == online_manifest["classification"]["snapshot"]
    assert local_manifest["catalog"] == online_manifest["catalog"]
    assert local_manifest["ignored"] == online_manifest["ignored"]
    assert local_manifest["failures"] == online_manifest["failures"]
    assert local_manifest["summary"] == online_manifest["summary"]

    local_inventory = local_task.inventory
    assert local_inventory is not None
    online_inventory = online_task["inventory"]
    assert local_inventory.device.normalized_name == online_inventory["device"]["normalized_name"]
    assert local_inventory.source_files == online_inventory["source_files"]
    assert local_inventory.device.normalized_name == "IDENTITY-UMF-001"
    assert online_inventory["device"]["normalized_name"] == "IDENTITY-UMF-001"
    devices = client.get("/api/v2/inventory/devices").json()
    assert devices["total"] == 1
    assert {item["device_name"] for item in devices["items"]} == {"IDENTITY-UMF-001"}
