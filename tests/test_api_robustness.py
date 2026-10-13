"""API 上传、分页与损坏持久化的健壮性测试。"""

import io
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.db import session_factory
from app.models.schemas import InspectionTask, TaskMode, TaskStats, TaskStatus, TaskTrigger
from app.services import task_db
from app.services.store import save_task_meta
from tests.baseline_helpers import SAMPLE, setup_env, wait_for_task

client = TestClient(app)


def _upload(env, *, filename: str = "sample.zip", content: bytes | None = None, **data: str):
    payload = {"package_kind": "inspection", "province": "北京", "operator": "移动", **data}
    with io.BytesIO(content) if content is not None else SAMPLE.open("rb") as package:
        return client.post(
            "/api/v3/tasks",
            files={"package_file": (filename, package, "application/zip")},
            data=payload,
        )


def test_upload_filename_and_empty_package_boundaries(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    empty = _upload(env, filename="empty.zip", content=b"")
    assert empty.status_code == 400
    assert empty.json()["code"] == "invalid_package"

    invalid = _upload(env, filename="package.zip.exe", content=b"x")
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "invalid_package"

    uppercase = _upload(env, filename="PACKAGE2.ZIP")
    assert uppercase.status_code == 202
    wait_for_task(client, uppercase.json()["task_id"])

    boundary = "patrolx-empty-filename"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="package_kind"\r\n\r\ninspection\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="province"\r\n\r\nbeijing\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="operator"\r\n\r\nmobile\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="package_file"; filename=""\r\n'
        "Content-Type: application/zip\r\n\r\n" + SAMPLE.read_text(encoding="latin-1") + f"\r\n--{boundary}--\r\n"
    ).encode("latin-1")
    empty_name = client.post(
        "/api/v3/tasks",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert empty_name.status_code == 202, empty_name.text
    wait_for_task(client, empty_name.json()["task_id"])
    assert (env.uploads / "task-package" / "package.zip").is_file()

    unicode_name = _upload(env, filename="巡检 数据包.zip")
    assert unicode_name.status_code == 202
    wait_for_task(client, unicode_name.json()["task_id"])

    too_long = "a" * 252 + ".zip"
    long_name = _upload(env, filename=too_long)
    assert long_name.status_code == 400
    assert long_name.json()["code"] == "invalid_filename"
    assert not list(env.uploads.glob("task-a*"))


def test_upload_size_boundary_and_temp_cleanup(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "max_upload_mb", 1)

    exact = _upload(env, filename="one-mb.zip", content=b"0" * (1024 * 1024))
    assert exact.status_code == 202

    too_large = _upload(env, filename="too-large.zip", content=b"0" * (1024 * 1024 + 1))
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "package_too_large"
    assert not list(env.uploads.glob(".upload-*"))


def test_same_name_same_checksum_is_reused_and_conflict_is_rejected(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    first = _upload(env)
    assert first.status_code == 202
    task_id = first.json()["task_id"]
    wait_for_task(client, task_id)

    second = _upload(env)
    assert second.status_code == 202
    assert second.json()["task_id"] == task_id
    assert client.get(f"/api/v2/tasks/{task_id}").json()["status"] == "completed"

    conflict = _upload(env, content=SAMPLE.read_bytes() + b"different")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "package_checksum_conflict"


def test_pagination_validates_query_bounds(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    assert client.get("/api/v2/tasks", params={"page": 1, "page_size": 100}).status_code == 200
    for params in (
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": 101},
        {"page_size": -1},
        {"page": "abc"},
        {"page_size": "abc"},
    ):
        response = client.get("/api/v2/tasks", params=params)
        assert response.status_code == 422, (params, response.status_code, response.text)
        body = response.json()
        assert body["code"] == "validation_error", (params, body)
        assert body["message"], (params, body)
        assert body["detail"]["errors"], (params, body)


def test_corrupt_task_json_does_not_break_list(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    corrupt_dir = env.output / "task-corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "task.json").write_text("{broken", encoding="utf-8")

    response = client.get("/api/v2/tasks")
    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()["items"]] == [task_id]


def test_corrupt_scene_system_json_does_not_break_db_backed_display(tmp_path, monkeypatch) -> None:
    """库内快照优先：现场 system.json 损坏不影响已入库任务的展示。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    before = client.get(f"/api/v2/tasks/{task_id}/system")
    assert before.status_code == 200

    (env.task_dir(task_id) / "system.json").write_text("{broken", encoding="utf-8")

    after = client.get(f"/api/v2/tasks/{task_id}/system")
    assert after.status_code == 200
    assert after.json() == before.json()


def test_legacy_corrupt_system_json_returns_actionable_error(tmp_path, monkeypatch) -> None:
    """历史现场（库内无快照且 task.json 无内嵌规则）system.json 损坏时给出明确错误。"""
    env = setup_env(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    save_task_meta(
        env.output,
        InspectionTask(
            task_id="task-legacy-corrupt",
            name="历史任务",
            mode=TaskMode.LOCAL,
            status=TaskStatus.COMPLETED,
            trigger=TaskTrigger.CLI,
            created_at=now,
            completed_at=now,
            stats=TaskStats(total=1, pass_=1, warn=0, fail=0, error=0, skip=0),
            system=None,
        ),
    )
    with session_factory() as session:
        task_db.delete_task_data(session, "task-legacy-corrupt")
        session.commit()
    (env.output / "task-legacy-corrupt" / "system.json").write_text("{broken", encoding="utf-8")

    response = client.get("/api/v2/tasks/task-legacy-corrupt/system")
    assert response.status_code == 503
    assert response.json()["code"] == "corrupt_data"
    assert "重跑" in response.json()["message"]


def test_invalid_execution_log_line_does_not_break_log_api(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    path = env.task_dir(task_id) / "execution.log"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not-json\n")

    response = client.get(f"/api/v2/tasks/{task_id}/logs")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert entries
    assert all(isinstance(entry, dict) and "ts" in entry for entry in entries)


def test_unknown_rerun_rule_is_rejected(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    response = client.post(
        f"/api/v2/tasks/{task_id}/rerun",
        json={"rule_codes": ["rule.does_not_exist"]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "unknown_rule"


def test_rerun_keeps_summary_report_and_contract_consistent(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    before_task = client.get(f"/api/v2/tasks/{task_id}").json()
    before_system = client.get(f"/api/v2/tasks/{task_id}/system").json()

    response = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert response.status_code == 202
    after_task = wait_for_task(client, task_id)
    after_system = client.get(f"/api/v2/tasks/{task_id}/system").json()

    assert after_task["stats"] == before_task["stats"]
    assert after_system["summary"] == before_system["summary"]
    assert len(after_system["rules"]) == len(before_system["rules"])
    assert (env.task_dir(task_id) / "report.html").is_file()


def test_corrupt_rule_result_is_rebuilt_by_single_rule_rerun(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    (env.rules_dir(task_id) / "log.error_density.json").write_text("{broken", encoding="utf-8")

    response = client.post(
        f"/api/v2/tasks/{task_id}/rerun",
        json={"rule_codes": ["log.error_density"]},
    )
    assert response.status_code == 202
    task = wait_for_task(client, task_id)
    system = client.get(f"/api/v2/tasks/{task_id}/system")
    assert task["status"] == "completed"
    assert system.status_code == 200
    assert system.json()["summary"] == {k: v for k, v in task["stats"].items() if k != "systems"}


def test_concurrent_rerun_requests_complete_consistently(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    before = client.get(f"/api/v2/tasks/{task_id}/system").json()

    responses = [
        client.post(
            f"/api/v2/tasks/{task_id}/rerun",
            json={"rule_codes": ["log.error_density"]},
        )
        for _ in range(2)
    ]
    assert [response.status_code for response in responses] == [202, 202]
    task = wait_for_task(client, task_id)
    after = client.get(f"/api/v2/tasks/{task_id}/system").json()
    assert task["status"] == "completed"
    assert after["summary"] == before["summary"]
    assert (env.task_dir(task_id) / "report.html").is_file()
