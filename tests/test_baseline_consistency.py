"""本地与在线模式使用同一执行契约的一致性测试。"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import (
    SAMPLE,
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
    response = client.get(f"/api/v1/tasks/{task_id}/system")
    assert response.status_code == 200
    online_system = response.json()

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
