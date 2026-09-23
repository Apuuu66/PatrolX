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

    local_task = run_task(SAMPLE, name="Catalog 一致性")
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
