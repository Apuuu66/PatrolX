"""在线审查接口：任务摘要 → 系统 → 规则 → 发现逐层一致。"""

import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    InspectionTask,
    Priority,
    RuleCategory,
    RuleResult,
    RuleStatus,
    Severity,
    Summary,
    SystemInspection,
    SystemStatus,
    TaskMode,
    TaskStats,
    TaskStatus,
    TaskTrigger,
)
from app.services.store import save_task_meta
from tests.baseline_helpers import setup_env, upload_package, wait_for_task

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

    task = client.get(f"/api/v2/tasks/{task_id}")
    assert task.status_code == 200
    task_data = task.json()
    assert task_data["stats"]["total"] > 0

    system = client.get(f"/api/v2/tasks/{task_id}/system")
    assert system.status_code == 200
    system_data = system.json()
    assert system_data["summary"]["total"] == task_data["stats"]["total"]
    assert all(not rule["code"].startswith("pkg.extract.") for rule in system_data["rules"])

    skips = [rule for rule in system_data["rules"] if rule["status"] == "skip"]
    assert skips
    for rule in skips:
        assert rule["skip_reason"]
        assert client.get(f"/api/v2/tasks/{task_id}/rules/{rule['code']}").json()["skip_reason"] == rule["skip_reason"]

    findings = [(rule, finding) for rule in system_data["rules"] for finding in rule["findings"]]
    assert findings
    for rule, finding in findings:
        result = client.get(f"/api/v2/tasks/{task_id}/rules/{rule['code']}")
        assert result.status_code == 200
        remote = result.json()
        assert finding["source_file"]
        assert finding["evidence"]
        assert finding["recommendation"]
        assert finding in remote["findings"]

    hidden = client.get(f"/api/v2/tasks/{task_id}/rules/pkg.extract.main")
    assert hidden.status_code == 404

    report = client.get(f"/api/v2/tasks/{task_id}/report")
    logs = client.get(f"/api/v2/tasks/{task_id}/logs")
    assert report.status_code == 200
    assert logs.status_code == 200


def test_system_endpoint_falls_back_to_task_json_for_legacy_tasks(tmp_path: Path, monkeypatch) -> None:
    """旧任务只有 task.json 时，系统与规则接口仍应读取内嵌结果。"""
    env = setup_env(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    rule = RuleResult(
        code="log.error_density",
        name="日志错误密度",
        category=RuleCategory.LOG,
        priority=Priority.P1,
        execution_order=0,
        status=RuleStatus.PASS,
        severity=Severity.LOW,
        summary="无异常",
    )
    summary = Summary(total=1, pass_=1, warn=0, fail=0, error=0, skip=0)
    system = SystemInspection(
        package_file="legacy.zip",
        status=SystemStatus.COMPLETED,
        summary=summary,
        rules=[rule],
    )
    save_task_meta(
        env.output,
        InspectionTask(
            task_id="task-legacy",
            name="旧版本任务",
            mode=TaskMode.LOCAL,
            status=TaskStatus.COMPLETED,
            trigger=TaskTrigger.CLI,
            created_at=now,
            completed_at=now,
            stats=TaskStats(total=1, pass_=1, warn=0, fail=0, error=0, skip=0, systems=1),
            system=system,
        ),
    )

    client = TestClient(app)
    response = client.get("/api/v2/tasks/task-legacy/system")
    assert response.status_code == 200
    assert response.json()["rules"][0]["code"] == "log.error_density"

    response = client.get("/api/v2/tasks/task-legacy/rules/log.error_density")
    assert response.status_code == 200
    assert response.json()["code"] == "log.error_density"
