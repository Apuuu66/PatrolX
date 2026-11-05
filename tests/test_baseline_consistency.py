"""本地与在线模式使用同一执行契约的一致性测试。"""

import io
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.extraction.manifest import read_manifest
from tests.baseline_helpers import (
    SAMPLE,
    load_logs,
    load_rule,
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
        customer={"province": "北京", "operator": "移动", "product": "UMF"},
    )
    local_system = local_task.system.model_dump(by_alias=True, mode="json")

    online_env = setup_env(tmp_path / "online", monkeypatch)
    task_id = upload_package(
        online_env,
        client,
        name="一致性",
        province="北京",
        operator="移动",
        product="UMF",
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
    for key in ("classification", "entries", "ignored", "conflicts", "failures", "catalog", "summary"):
        assert local_manifest[key] == online_manifest[key]


def test_cli_and_api_daily_health_results_match(tmp_path: Path, monkeypatch) -> None:
    """同一合成任务经 CLI 执行后，API 必须返回完全一致的日健康结论。"""
    from app.cli import run_task
    from app.services.kpi_measurement_units import import_resource_csv

    resource_csv = (
        "资源id,中文描述,英文描述\n"
        "MU_CALL,呼叫会话统计,Call Session API Statistics\n"
        "ME_CALL,呼叫请求次数,Call Requests\n"
    )

    local_env = setup_env(tmp_path / "local", monkeypatch)
    import_resource_csv(io.StringIO(resource_csv))
    local_task = run_task(
        SAMPLE,
        name="日健康一致性",
        customer={"province": "北京", "operator": "移动", "product": "UMF"},
    )
    local_rule = load_rule(local_env, local_task.task_id, "kpi.measurement_units")

    online_env = setup_env(tmp_path / "online", monkeypatch)
    import_resource_csv(io.StringIO(resource_csv))
    task_id = upload_package(
        online_env,
        client,
        name="日健康一致性",
        province="北京",
        operator="移动",
        product="UMF",
    )
    wait_for_task(client, task_id)
    response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.measurement_units")

    assert response.status_code == 200, response.text
    online_rule = response.json()
    local_daily_health = local_rule["metadata"]["daily_health"]
    online_daily_health = online_rule["metadata"]["daily_health"]
    assert local_daily_health["metrics"]
    assert sum(local_daily_health["current_counts"].values()) == len(local_daily_health["metrics"])
    assert sum(local_daily_health["trend_counts"].values()) == len(local_daily_health["metrics"])
    assert online_daily_health == local_daily_health


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
        product="UMF",
    )
    second_id = upload_package(
        env,
        client,
        package=second_package,
        name="同一元数据",
        province="北京",
        operator="移动",
        product="UMF",
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
