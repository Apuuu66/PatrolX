"""任务重跑必须使用冻结规则快照，不得回退到规则启停门禁。"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect

from app.cli import run_incremental_rebuild, run_task
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.main import app
from app.models import kpi_v6 as kpi_schemas
from app.models.db import (
    InventoryChangeAudit,
    InventoryDevice,
    InventoryObservation,
    InventoryParseResult,
    TaskKpiScopeSnapshot,
    session_factory,
)
from app.models.schemas import (
    Priority,
    RebuildMode,
    RebuildRequest,
    RuleCategory,
    Severity,
    TaskMode,
    TaskTrigger,
)
from app.services import rule_network_assignments, task_db
from app.services.auth import AuthSession
from app.services.rule_scope import RuleScopeError
from app.services.tasks import RebuildPlan, TaskRebuildError, task_service
from tests.baseline_helpers import SAMPLE, setup_env

_ADMIN = AuthSession(token="rebuild-v6-admin", username="rebuild-v6-admin", role="admin")


def _assign(rule_code: str, network_element_types: list[str]) -> None:
    current = rule_network_assignments.list_rule_assignments(
        page=1,
        page_size=200,
        actor=_ADMIN,
    )
    item = next(candidate for candidate in current.items if candidate.rule_code == rule_code)
    rule_network_assignments.update_rule_assignment(
        rule_code,
        kpi_schemas.KpiRuleAssignmentPatchRequestV6(
            expected_revision=item.revision,
            network_element_types=network_element_types,
            confirm_unassign=not network_element_types,
        ),
        actor=_ADMIN,
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _scope_snapshot_payload(task_id: str) -> str:
    rule_snapshot = task_db.get_rule_scope_snapshot(task_id, network_element_type="UMF")
    kpi_snapshot = task_db.get_kpi_scope_snapshot(task_id, network_element_type="UMF")
    return json.dumps(
        {
            "rule": asdict(rule_snapshot) if rule_snapshot is not None else None,
            "kpi": asdict(kpi_snapshot) if kpi_snapshot is not None else None,
        },
        default=str,
        sort_keys=True,
    )


def _setup_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    env = setup_env(tmp_path, monkeypatch)
    _assign("kpi.measurement_units", ["UMF"])
    task = run_task(SAMPLE, task_id="task-rebuild-v6", customer={"product": "UMF"})
    assert task.status.value == "completed"
    snapshot = task_db.get_rule_scope_snapshot(task.task_id, network_element_type="UMF")
    assert snapshot is not None
    assert "kpi.measurement_units" in {item.rule_code for item in snapshot.items}
    return env.output, task.task_id


def test_incremental_rebuild_rejects_frozen_version_mismatch_before_output_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    before = _tree_digest(output / task_id)
    rule = registry.get("kpi.measurement_units")
    monkeypatch.setattr(rule, "rule_version", "9.9.9")

    with pytest.raises(RuleScopeError) as exc_info:
        run_incremental_rebuild(
            ["kpi.measurement_units"],
            package=SAMPLE,
            task_id=task_id,
            product="UMF",
        )

    assert exc_info.value.code == "rule_snapshot_version_mismatch"
    assert exc_info.value.status_code == 409
    assert _tree_digest(output / task_id) == before


def test_incremental_rebuild_rejects_rule_outside_frozen_snapshot_before_output_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    outsider = Inspector(
        code="test.rebuild_scope_outside",
        name="快照外规则",
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P1,
        rule_version="1.0.0",
        description="仅用于验证冻结规则范围",
        recommendation="无需处理",
        source_patterns=[r"^logs/.*\.log$"],
        run=lambda _ctx: None,
    )
    monkeypatch.setitem(registry._rules, outsider.code, outsider)
    before = _tree_digest(output / task_id)

    with pytest.raises(RuleScopeError) as exc_info:
        run_incremental_rebuild(
            [outsider.code],
            package=SAMPLE,
            task_id=task_id,
            product="UMF",
        )

    assert exc_info.value.code == "rule_not_in_task_scope"
    assert exc_info.value.status_code == 409
    assert _tree_digest(output / task_id) == before


def test_task_service_rebuild_rejects_version_mismatch_before_status_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    before = _tree_digest(output / task_id)
    rule = registry.get("kpi.measurement_units")
    monkeypatch.setattr(rule, "rule_version", "9.9.9")

    with pytest.raises(TaskRebuildError) as exc_info:
        task_service.rebuild(
            task_id,
            RebuildRequest(
                mode=RebuildMode.INCREMENTAL,
                confirmed=True,
                rule_codes=["kpi.measurement_units"],
            ),
        )

    assert exc_info.value.code == "rule_snapshot_version_mismatch"
    assert exc_info.value.status_code == 409
    assert _tree_digest(output / task_id) == before


def test_failed_full_rebuild_preserves_previous_output_snapshots_and_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    task_dir = output / task_id
    output_before = _tree_digest(task_dir)
    snapshots_before = _scope_snapshot_payload(task_id)

    broken_package = tmp_path / "broken.zip"
    broken_package.write_bytes(b"not a zip archive")
    package_before = hashlib.sha256(broken_package.read_bytes()).hexdigest()
    _assign("kpi.measurement_units", ["CSP"])

    task_service._execute_rebuild(
        task_id,
        RebuildPlan(mode=RebuildMode.FULL, trigger_source="ui"),
        package=broken_package,
        customer={"product": "UMF"},
        version=None,
        name="失败重建",
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
    )

    assert _tree_digest(task_dir) == output_before
    assert _scope_snapshot_payload(task_id) == snapshots_before
    assert hashlib.sha256(broken_package.read_bytes()).hexdigest() == package_before


def test_full_rebuild_keeps_task_id_refreshes_scope_output_and_preserves_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    task_dir = output / task_id
    stale_output = task_dir / "stale-rebuild-marker.txt"
    stale_output.write_text("old output", encoding="utf-8")
    package_before = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    snapshot_before = task_db.get_rule_scope_snapshot(task_id, network_element_type="UMF")
    assert snapshot_before is not None
    assert "alarm.active_state" not in {item.rule_code for item in snapshot_before.items}

    _assign("alarm.active_state", ["UMF"])

    succeeded = task_service._execute_rebuild(
        task_id,
        RebuildPlan(mode=RebuildMode.FULL, trigger_source="ui"),
        package=SAMPLE,
        customer={"product": "UMF"},
        version=None,
        name="成功重建",
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
    )

    assert succeeded is True
    assert task_id == "task-rebuild-v6"
    assert task_dir.is_dir()
    assert not stale_output.exists()
    snapshot_after = task_db.get_rule_scope_snapshot(task_id, network_element_type="UMF")
    assert snapshot_after is not None
    assert "alarm.active_state" in {item.rule_code for item in snapshot_after.items}
    rebuilt_task = task_db.get_task(task_id)
    assert rebuilt_task is not None
    assert rebuilt_task.task_id == task_id
    assert rebuilt_task.status.value == "completed"
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == package_before


def test_full_rebuild_publishes_kpi_history_index_from_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    history_index = output / task_id / "kpi" / "history" / "index.jsonl"
    assert history_index.is_file()

    succeeded = task_service._execute_rebuild(
        task_id,
        RebuildPlan(mode=RebuildMode.FULL, trigger_source="ui"),
        package=SAMPLE,
        customer={"product": "UMF"},
        version=None,
        name="历史索引重建",
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
    )

    assert succeeded is True
    assert history_index.is_file(), "全量重建后不得丢失 staging 中生成的 KPI 历史索引"


def _inventory_rows(model) -> list[dict[str, object]]:
    columns = [column.key for column in sa_inspect(model).columns]
    with session_factory() as session:
        rows = session.query(model).all()
        payload = [{column: getattr(row, column) for column in columns} for row in rows]
    return sorted(
        payload,
        key=lambda item: json.dumps(item, default=str, sort_keys=True, ensure_ascii=False),
    )


def _inventory_ledger_snapshot() -> dict[str, object]:
    return {
        model.__name__: _inventory_rows(model)
        for model in (InventoryParseResult, InventoryObservation, InventoryDevice, InventoryChangeAudit)
    }


def test_full_rebuild_staging_keeps_inventory_ledger_unpublished_until_output_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    evidence_file = output / task_id / "inventory.json"
    evidence_before = evidence_file.read_bytes()
    ledger_before = _inventory_ledger_snapshot()
    _assign("kpi.measurement_units", ["CSP"])

    def stop_before_output_swap(_final_task_dir: Path, _staged_task_dir: Path) -> Path | None:
        raise RuntimeError("test stops before output swap")

    monkeypatch.setattr(task_service, "_replace_task_output", stop_before_output_swap)

    succeeded = task_service._execute_rebuild(
        task_id,
        RebuildPlan(mode=RebuildMode.FULL, trigger_source="ui"),
        package=SAMPLE,
        customer={"product": "UMF"},
        version=None,
        name="重建 staging 隔离",
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
    )

    assert succeeded is False
    assert evidence_file.read_bytes() == evidence_before
    assert _inventory_ledger_snapshot() == ledger_before


def test_legacy_task_without_v6_snapshot_requires_rebuild(kpi_v6_seed) -> None:
    with session_factory() as session:
        session.query(TaskKpiScopeSnapshot).filter(TaskKpiScopeSnapshot.task_id == kpi_v6_seed.umf.task_id).delete()
        session.commit()

    client = TestClient(app)
    response = client.get(f"/api/v6/kpi/tasks/{kpi_v6_seed.umf.task_id}/summary")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "task_result_requires_rebuild"


def test_full_rebuild_package_missing_keeps_existing_output_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    task_dir = output / task_id
    output_before = _tree_digest(task_dir)

    with pytest.raises(TaskRebuildError) as exc_info:
        task_service.rebuild(
            task_id,
            RebuildRequest(mode=RebuildMode.FULL, confirmed=True),
        )

    assert exc_info.value.code == "package_missing"
    assert exc_info.value.status_code == 409
    assert _tree_digest(task_dir) == output_before


def test_full_rebuild_after_scene_cleanup_returns_scene_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    shutil.rmtree(output / task_id)

    with pytest.raises(TaskRebuildError) as exc_info:
        task_service.rebuild(
            task_id,
            RebuildRequest(mode=RebuildMode.FULL, confirmed=True),
        )

    assert exc_info.value.code == "scene_cleaned"
    assert exc_info.value.status_code == 410
    assert not (output / task_id).exists()


def test_failed_full_rebuild_preserves_original_package_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, task_id = _setup_task(tmp_path, monkeypatch)
    task_dir = output / task_id
    output_before = _tree_digest(task_dir)
    package_before = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()

    broken_package = tmp_path / "broken-rebuild.zip"
    broken_package.write_bytes(b"not a zip archive")
    _assign("kpi.measurement_units", ["CSP"])

    succeeded = task_service._execute_rebuild(
        task_id,
        RebuildPlan(mode=RebuildMode.FULL, trigger_source="ui"),
        package=broken_package,
        customer={"product": "UMF"},
        version=None,
        name="失败重建保留原包",
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
    )

    assert succeeded is False
    assert _tree_digest(task_dir) == output_before
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == package_before
    assert hashlib.sha256(broken_package.read_bytes()).hexdigest() == hashlib.sha256(b"not a zip archive").hexdigest()
