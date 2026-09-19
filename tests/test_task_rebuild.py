"""任务重建重跑契约与保护语义测试。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.checksum import sha256_file
from app.main import app
from app.models.schemas import RebuildMode, RebuildRequest
from app.services import store
from app.services.tasks import task_service
from tests.baseline_helpers import load_rule, setup_env, strip_volatile, wait_for_task


def test_full_rebuild_request_is_valid() -> None:
    request = RebuildRequest(mode=RebuildMode.FULL, confirmed=True)
    assert request.trigger_source == "ui"
    assert request.rule_codes is None


def test_incremental_rebuild_request_is_valid() -> None:
    request = RebuildRequest(
        mode=RebuildMode.INCREMENTAL,
        confirmed=True,
        rule_codes=["log.error_density", "config.check"],
        trigger_source="api",
    )
    assert request.rule_codes == ["log.error_density", "config.check"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": RebuildMode.FULL, "confirmed": False},
        {"mode": RebuildMode.INCREMENTAL, "confirmed": True},
        {"mode": RebuildMode.INCREMENTAL, "confirmed": True, "rule_codes": []},
        {"mode": RebuildMode.FULL, "confirmed": True, "rule_codes": ["log.error_density"]},
        {"mode": RebuildMode.FULL, "confirmed": True, "trigger_source": "cli"},
    ],
)
def test_invalid_rebuild_requests_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        RebuildRequest(**kwargs)


def _rebuild(client: TestClient, task_id: str, **body) -> dict:
    response = client.post(f"/api/v2/tasks/{task_id}/rebuild", json=body)
    assert response.status_code == 202, response.text
    assert response.headers["Location"] == f"/api/v2/tasks/{task_id}"
    return response.json()


def _setup_task(tmp_path, monkeypatch):
    env = setup_env(tmp_path, monkeypatch)
    client = TestClient(app)
    task_id = None
    sample = Path(__file__).parent / "fixtures" / "sample" / "sample.zip"
    (env.uploads / "rebuild-sample.zip").write_bytes(sample.read_bytes())
    with client:
        with (env.uploads / "rebuild-sample.zip").open("rb") as package:
            response = client.post(
                "/api/v2/tasks",
                files={"package_file": ("rebuild-sample.zip", package, "application/zip")},
                data={"name": "重建任务"},
            )
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]
        wait_for_task(client, task_id)
    return env, client, task_id


def test_full_rebuild_refreshes_snapshot_and_protects_package(tmp_path, monkeypatch) -> None:
    env, client, task_id = _setup_task(tmp_path, monkeypatch)
    package = env.uploads / task_id / "rebuild-sample.zip"
    package_checksum = sha256_file(package)
    snapshot_path = env.task_dir(task_id) / "kpi" / "kpi_catalog_snapshot.json"
    old_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    old_snapshot["base_data_version"] = "old-config"
    snapshot_path.write_text(json.dumps(old_snapshot, ensure_ascii=False), encoding="utf-8")

    with client:
        result = _rebuild(
            client,
            task_id,
            mode="full",
            confirmed=True,
            trigger_source="api",
        )
        assert result["task_id"] == task_id
        task = wait_for_task(client, task_id)

    assert task["status"] == "completed"
    refreshed = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert refreshed["base_data_version"] != "old-config"
    assert sha256_file(package) == package_checksum


def test_incremental_rebuild_rebuilds_site_and_preserves_other_results(tmp_path, monkeypatch) -> None:
    env, client, task_id = _setup_task(tmp_path, monkeypatch)
    system = client.get(f"/api/v2/tasks/{task_id}/system").json()
    target = "log.umf_acc"
    assert any(rule["code"] == target for rule in system["rules"])
    others = [rule["code"] for rule in system["rules"] if rule["code"] != target]
    target_path = env.rules_dir(task_id) / f"{target}.json"
    target_path.write_text(json.dumps({"code": target, "sentinel": "old"}, ensure_ascii=False), encoding="utf-8")
    before_others = {code: strip_volatile(load_rule(env, task_id, code)) for code in others}
    snapshot_path = env.task_dir(task_id) / "kpi" / "kpi_catalog_snapshot.json"
    snapshot_path.write_text(
        snapshot_path.read_text(encoding="utf-8").replace('"captured_at"', '"captured_at"'),
        encoding="utf-8",
    )

    with client:
        _rebuild(
            client,
            task_id,
            mode="incremental",
            confirmed=True,
            rule_codes=[target],
            trigger_source="ui",
        )
        task = wait_for_task(client, task_id)

    assert task["status"] == "completed"
    refreshed_target = load_rule(env, task_id, target)
    assert refreshed_target.get("sentinel") is None
    assert refreshed_target["code"] == target
    for code in others:
        assert strip_volatile(load_rule(env, task_id, code)) == before_others[code]

    log_lines = (env.task_dir(task_id) / "execution.log").read_text(encoding="utf-8").splitlines()
    logs = [json.loads(line) for line in log_lines]
    rebuild_logs = [entry for entry in logs if entry.get("operation") == "rebuild"]
    assert rebuild_logs
    assert all(entry["mode"] == "incremental" and entry["rule_codes"] == [target] for entry in rebuild_logs)
    assert any(entry.get("rule_code") == target and entry.get("prepare_state") == "REBUILT" for entry in logs)


def test_rebuild_prechecks_reject_without_output_change(tmp_path, monkeypatch) -> None:
    env, client, task_id = _setup_task(tmp_path, monkeypatch)
    task_dir = env.task_dir(task_id)

    def tree_digest() -> bytes:
        digest = b""
        for path in sorted(task_dir.rglob("*")):
            digest += str(path.relative_to(task_dir)).encode()
            if path.is_file():
                digest += path.read_bytes()
        return digest

    with client:
        metrics_path = env.root / "kpi" / "base" / "metrics.json"
        original_metrics = metrics_path.read_bytes()
        metrics_path.write_bytes(b"{broken")
        try:
            response = client.post(f"/api/v2/tasks/{task_id}/rebuild", json={"mode": "full", "confirmed": True})
            assert response.status_code == 400
            assert response.json()["code"] == "invalid_rebuild_request"
        finally:
            metrics_path.write_bytes(original_metrics)

        response = client.post(
            f"/api/v2/tasks/{task_id}/rebuild",
            json={"mode": "incremental", "confirmed": True, "rule_codes": ["pkg.extract.main"]},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_rebuild_request"

        response = client.post(
            f"/api/v2/tasks/{task_id}/rebuild",
            json={"mode": "incremental", "confirmed": True, "rule_codes": ["not.registered"]},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "unknown_rule"

        original_active = task_service._active_task
        task_service._active_task = task_id
        try:
            response = client.post(f"/api/v2/tasks/{task_id}/rebuild", json={"mode": "full", "confirmed": True})
            assert response.status_code == 409
            assert response.json()["code"] == "task_busy"
        finally:
            task_service._active_task = original_active

        snapshot_path = task_dir / "kpi" / "kpi_catalog_snapshot.json"
        original_snapshot = snapshot_path.read_bytes()
        snapshot_path.write_bytes(b"{broken")
        response = client.post(
            f"/api/v2/tasks/{task_id}/rebuild",
            json={"mode": "incremental", "confirmed": True, "rule_codes": ["log.error_density"]},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "kpi_snapshot_invalid"
        snapshot_path.write_bytes(original_snapshot)

        before = tree_digest()
        uploads_dir = env.uploads / task_id
        root_package = env.uploads / "rebuild-sample.zip"
        root_package.unlink()
        uploads_dir.rename(env.uploads / f"{task_id}-hidden")
        try:
            response = client.post(f"/api/v2/tasks/{task_id}/rebuild", json={"mode": "full", "confirmed": True})
            assert response.status_code == 409
            assert response.json()["code"] == "package_missing"
        finally:
            (env.uploads / f"{task_id}-hidden").rename(uploads_dir)

    assert tree_digest() == before
    assert store.load_task_meta(env.output, task_id) is not None
