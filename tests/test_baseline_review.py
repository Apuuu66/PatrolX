"""在线审查接口：任务摘要 → 系统 → 规则 → 发现逐层一致。"""

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import upload_package, wait_for_task

client = TestClient(app)


def test_review_endpoints_follow_contract(tmp_path: Path, monkeypatch) -> None:
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "partial.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("KPI/kpi.csv", "metric,value\ncall_success_rate,90\nattach_success_rate,96.5\n")
    task_id = upload_package(
        env,
        client,
        package=package,
        name="审查任务",
        province="上海",
        operator="电信",
        version="v2",
    )
    wait_for_task(client, task_id)

    task = client.get(f"/api/v1/tasks/{task_id}")
    assert task.status_code == 200
    task_data = task.json()
    assert task_data["stats"]["total"] > 0

    system = client.get(f"/api/v1/tasks/{task_id}/system")
    assert system.status_code == 200
    system_data = system.json()
    assert system_data["summary"]["total"] == task_data["stats"]["total"]
    assert all(not rule["code"].startswith("pkg.extract.") for rule in system_data["rules"])

    skips = [rule for rule in system_data["rules"] if rule["status"] == "skip"]
    assert skips
    for rule in skips:
        assert rule["skip_reason"]
        assert client.get(f"/api/v1/tasks/{task_id}/rules/{rule['code']}").json()["skip_reason"] == rule["skip_reason"]

    findings = [(rule, finding) for rule in system_data["rules"] for finding in rule["findings"]]
    assert findings
    for rule, finding in findings:
        result = client.get(f"/api/v1/tasks/{task_id}/rules/{rule['code']}")
        assert result.status_code == 200
        remote = result.json()
        assert finding["source_file"]
        assert finding["evidence"]
        assert finding in remote["findings"]

    hidden = client.get(f"/api/v1/tasks/{task_id}/rules/pkg.extract.main")
    assert hidden.status_code == 404

    report = client.get(f"/api/v1/tasks/{task_id}/report")
    logs = client.get(f"/api/v1/tasks/{task_id}/logs")
    assert report.status_code == 200
    assert logs.status_code == 200
