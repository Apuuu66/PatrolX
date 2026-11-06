"""日志补充包规则适用网元类型与任务范围集成测试（041 T065 / T076）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.inspectors.registry import registry
from app.main import app
from app.models.db import InventoryObservation, session_factory
from tests.baseline_helpers import assign_rules_to_network_element, setup_env, wait_for_task
from tests.fixtures.inventory.builder import make_log_supplement_zip

client = TestClient(app)


def _business_rule_codes() -> list[str]:
    registry.load_all()
    return [rule.code for rule in registry.all() if not rule.hidden]


def _post(
    package: Path,
    *,
    upload_name: str,
    package_kind: str,
    name: str,
    fields: dict[str, str] | None = None,
) -> object:
    data = {"package_kind": package_kind, "name": name, **(fields or {})}
    with package.open("rb") as fh:
        return client.post(
            "/api/v3/tasks",
            files={"package_file": (upload_name, fh, "application/zip")},
            data=data,
        )


def _post_log(
    package: Path,
    *,
    upload_name: str = "log-scope.zip",
    name: str = "日志范围",
    rule_network_element_type: str | None = None,
) -> object:
    fields = {}
    if rule_network_element_type is not None:
        fields["rule_network_element_type"] = rule_network_element_type
    return _post(
        package,
        upload_name=upload_name,
        package_kind="log_supplement",
        name=name,
        fields=fields,
    )


def _inventory_observation_count() -> int:
    with session_factory() as session:
        return int(session.query(InventoryObservation).count())


def _wait_for_summary(task_id: str) -> dict[str, object]:
    """等待任务终态后读取列表摘要，验证持久化元数据。"""
    wait_for_task(client, task_id)
    items = client.get("/api/v2/tasks").json()["items"]
    return next(item for item in items if item["task_id"] == task_id)


def test_log_supplement_selected_type_only_freezes_matching_rules_and_never_kpi_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UMF 日志包只冻结 UMF 规则；KPI、product 与台账均保持不适用。"""
    env = setup_env(tmp_path, monkeypatch)
    umf_rule, csp_rule = _business_rule_codes()[:2]
    assign_rules_to_network_element([umf_rule], "UMF")
    assign_rules_to_network_element([csp_rule], "CSP")
    package = make_log_supplement_zip(tmp_path / "log-scope.zip")

    response = _post_log(package, rule_network_element_type="UMF")
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    task = _wait_for_summary(task_id)

    assert task["status"] == "completed"
    assert task["package_kind"] == "log_supplement"
    assert task["customer_product"] is None
    assert task["rule_network_element_type"] == "UMF"

    manifest = json.loads((env.task_dir(task_id) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["classification"]["profile"] == "GENERIC"
    assert _inventory_observation_count() == 0

    from app.services import task_db

    rule_snapshot = task_db.get_rule_scope_snapshot(task_id, network_element_type="UMF")
    assert rule_snapshot is not None
    assert [item.rule_code for item in rule_snapshot.items] == [umf_rule]
    kpi_snapshot = task_db.get_kpi_scope_snapshot(task_id, network_element_type=None)
    assert kpi_snapshot is not None
    assert kpi_snapshot.network_element_type is None
    assert kpi_snapshot.items == ()

    assert (env.rules_dir(task_id) / "pkg.extract.main.json").is_file()
    assert (env.rules_dir(task_id) / "pkg.extract.classification.json").is_file()
    assert not (env.rules_dir(task_id) / f"{csp_rule}.json").exists()

    log_rows = [
        json.loads(line)
        for line in (env.task_dir(task_id) / "execution.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert not any(row.get("rule_code") == csp_rule for row in log_rows), "未归属当前类型的规则不得生成 skip 或执行日志"


@pytest.mark.parametrize("raw_type", [" umf ", "csp"])
def test_log_supplement_rule_type_is_trimmed_and_uppercased(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_type: str,
) -> None:
    setup_env(tmp_path, monkeypatch)
    package = make_log_supplement_zip(tmp_path / "normalize-log.zip")

    response = _post_log(package, rule_network_element_type=raw_type)
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    task = _wait_for_summary(task_id)
    normalized = raw_type.strip().upper()

    assert task["rule_network_element_type"] == normalized
    from app.services import task_db

    snapshot = task_db.get_rule_scope_snapshot(task_id, network_element_type=normalized)
    assert snapshot is not None
    assert snapshot.network_element_type == normalized


@pytest.mark.parametrize("raw_type", [None, "", "   "])
def test_log_supplement_without_rule_type_runs_only_hidden_technical_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_type: str | None,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    package = make_log_supplement_zip(tmp_path / "unscoped-log.zip")

    response = _post_log(package, rule_network_element_type=raw_type)
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    task = _wait_for_summary(task_id)

    assert task["status"] == "completed"
    assert task["rule_network_element_type"] is None
    from app.services import task_db

    rule_snapshot = task_db.get_rule_scope_snapshot(task_id, network_element_type=None)
    assert rule_snapshot is not None
    assert rule_snapshot.network_element_type is None
    assert rule_snapshot.items == ()
    kpi_snapshot = task_db.get_kpi_scope_snapshot(task_id, network_element_type=None)
    assert kpi_snapshot is not None
    assert kpi_snapshot.network_element_type is None
    assert kpi_snapshot.items == ()
    assert (env.rules_dir(task_id) / "pkg.extract.main.json").is_file()
    assert (env.rules_dir(task_id) / "pkg.extract.classification.json").is_file()


def test_inspection_rejects_rule_network_element_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_env(tmp_path, monkeypatch)
    package = make_log_supplement_zip(tmp_path / "inspection-with-rule-type.zip")

    response = _post(
        package,
        upload_name="inspection-with-rule-type.zip",
        package_kind="inspection",
        name="巡检包误带规则类型",
        fields={"province": "北京", "operator": "移动", "product": "UMF", "rule_network_element_type": "UMF"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "metadata_not_applicable"


@pytest.mark.parametrize("raw_type", ["*", "COMMON", "PUBLIC", "GENERIC", "UNKNOWN"])
def test_log_supplement_rejects_invalid_or_public_rule_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_type: str,
) -> None:
    setup_env(tmp_path, monkeypatch)
    package = make_log_supplement_zip(tmp_path / "invalid-log-scope.zip")

    response = _post_log(package, rule_network_element_type=raw_type)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_rule_network_element_type"


def test_existing_task_checksum_conflict_precedes_metadata_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_env(tmp_path, monkeypatch)
    first_package = tmp_path / "first" / "same-name.zip"
    first_package.parent.mkdir(parents=True, exist_ok=True)
    make_log_supplement_zip(first_package)
    created = _post_log(first_package, upload_name="same-name.zip", rule_network_element_type="UMF")
    assert created.status_code == 202, created.text

    changed_package = tmp_path / "changed" / "same-name.zip"
    changed_package.parent.mkdir(parents=True, exist_ok=True)
    make_log_supplement_zip(changed_package, content=b"changed")
    conflict = _post(
        changed_package,
        upload_name="same-name.zip",
        package_kind="inspection",
        name="冲突",
        fields={"rule_network_element_type": "UMF"},
    )

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "package_checksum_conflict"


def test_existing_package_kind_conflict_precedes_log_metadata_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_env(tmp_path, monkeypatch)
    package = make_log_supplement_zip(tmp_path / "kind-order.zip")
    created = _post(
        package,
        upload_name="kind-order.zip",
        package_kind="inspection",
        name="先创建巡检包",
        fields={"province": "北京", "operator": "移动", "product": "UMF"},
    )
    assert created.status_code == 202, created.text

    conflict = _post(
        package,
        upload_name="kind-order.zip",
        package_kind="log_supplement",
        name="类型冲突",
        fields={"province": "北京"},
    )

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "package_kind_conflict"


def test_existing_log_supplement_rule_type_conflict_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_env(tmp_path, monkeypatch)
    package = make_log_supplement_zip(tmp_path / "rule-type-conflict.zip")
    created = _post_log(package, upload_name="rule-type-conflict.zip", rule_network_element_type="UMF")
    assert created.status_code == 202, created.text

    conflict = _post_log(package, upload_name="rule-type-conflict.zip", rule_network_element_type="CSP")

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "package_rule_network_element_type_conflict"


def test_existing_inspection_product_conflict_is_rejected_before_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    package = make_log_supplement_zip(tmp_path / "product-conflict.zip")
    created = _post(
        package,
        upload_name="product-conflict.zip",
        package_kind="inspection",
        name="产品冲突",
        fields={"province": "北京", "operator": "移动", "product": "UMF"},
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    conflict = _post(
        package,
        upload_name="product-conflict.zip",
        package_kind="inspection",
        name="产品冲突",
        fields={"province": "北京", "operator": "移动", "product": "CSP"},
    )

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "package_product_conflict"
    assert (env.uploads / task_id / "product-conflict.zip").is_file()
