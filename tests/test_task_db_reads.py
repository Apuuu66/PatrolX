"""US1：现场清理后列表、详情、系统、规则与准备摘要仍从 SQLite 完整可读（034 / T019、T022）。

独立测试口径：删除 ``output/<task_id>`` 与 ``uploads/<task_id>`` 后，展示读取结果必须与清理前逐字段一致；
磁盘现场不再参与展示读取（执行日志与报告文件除外）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import setup_env, upload_package, wait_for_task

client = TestClient(app)
RULE_CODE = "kpi.measurement_units"


def _snapshot(task_id: str) -> dict[str, object]:
    return {
        "task": client.get(f"/api/v2/tasks/{task_id}").json(),
        "system": client.get(f"/api/v2/tasks/{task_id}/system").json(),
        "rule": client.get(f"/api/v2/tasks/{task_id}/rules/{RULE_CODE}").json(),
    }


def _list_item(task_id: str) -> dict:
    listing = client.get("/api/v2/tasks", params={"page_size": 100}).json()
    return next(item for item in listing["items"] if item["task_id"] == task_id)


def test_display_reads_survive_scene_cleanup(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="清理后追溯")
    wait_for_task(client, task_id)

    before = _snapshot(task_id)
    before_item = _list_item(task_id)
    assert before["system"]["rules"], "现场未清理时必须有规则结果"
    assert before["task"]["preparation"] is not None

    shutil.rmtree(env.task_dir(task_id))
    shutil.rmtree(env.uploads / task_id)
    assert not env.task_dir(task_id).exists()

    after = _snapshot(task_id)
    assert after["task"] == before["task"], "清理现场后任务详情必须与清理前一致"
    assert after["system"] == before["system"], "清理现场后系统结果必须与清理前一致"
    assert after["rule"] == before["rule"], "清理现场后规则详情必须与清理前一致"
    assert _list_item(task_id) == before_item, "清理现场后列表摘要必须与清理前一致"


def test_rule_detail_falls_back_to_db_when_rule_file_missing(tmp_path: Path, monkeypatch) -> None:
    """现场规则文件被删除（未清理整目录）时，规则详情仍从库中读取。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="规则文件缺失")
    wait_for_task(client, task_id)

    before = client.get(f"/api/v2/tasks/{task_id}/rules/{RULE_CODE}").json()
    assert before["code"] == RULE_CODE
    (env.rules_dir(task_id) / f"{RULE_CODE}.json").unlink()

    after = client.get(f"/api/v2/tasks/{task_id}/rules/{RULE_CODE}").json()
    assert after == before


def test_legacy_scene_without_snapshot_is_readable_and_backfilled(tmp_path: Path, monkeypatch) -> None:
    """未入库的历史现场（只有 task.json / rules）仍可读，并在读取后补齐库内快照。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="历史现场")
    wait_for_task(client, task_id)
    before = _snapshot(task_id)

    from app.models.db import TaskRecord, TaskRuleResult, session_factory
    from app.services import task_db

    with session_factory() as session:
        session.query(TaskRuleResult).filter(TaskRuleResult.task_id == task_id).delete()
        record = session.get(TaskRecord, task_id)
        assert record is not None
        session.delete(record)
        session.commit()

    after = _snapshot(task_id)
    assert after["task"] == before["task"], "历史现场兜底读必须与库内快照一致"
    assert after["system"] == before["system"]
    assert after["rule"] == before["rule"]

    with session_factory() as session:
        assert session.get(TaskRecord, task_id) is not None, "兜底读必须机会式补齐任务行"
    assert task_db.get_rule_result(task_id, RULE_CODE) is not None
