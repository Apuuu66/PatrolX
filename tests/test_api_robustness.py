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


def _upload(
    env,
    *,
    filename: str = "sample.zip",
    content: bytes | None = None,
    product: str | None = "UMF",
    **data: str,
):
    payload = {"package_kind": "inspection", **data}
    if payload["package_kind"] == "inspection":
        payload.setdefault("province", "北京")
        payload.setdefault("operator", "移动")
    if product is not None:
        payload["product"] = product
    with io.BytesIO(content) if content is not None else SAMPLE.open("rb") as package:
        return client.post(
            "/api/v3/tasks",
            files={"package_file": (filename, package, "application/zip")},
            data=payload,
        )


def _assert_error(response, *, status_code: int, code: str) -> dict:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"code", "message", "detail"}, body
    assert body["code"] == code, body
    assert body["message"], body
    return body


def test_upload_product_is_conditionally_required_and_normalized(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)

    missing = _upload(env, product=None)
    assert missing.status_code == 400, missing.text
    missing_body = missing.json()
    assert missing_body["code"] == "missing_product"
    assert missing_body["detail"]["package_kind"] == "inspection"

    blank = _upload(env, product="  ")
    assert blank.status_code == 400, blank.text
    assert blank.json()["code"] == "missing_product"

    invalid = _upload(env, product=" xyz ")
    assert invalid.status_code == 400, invalid.text
    invalid_body = invalid.json()
    assert invalid_body["code"] == "invalid_product"
    assert invalid_body["detail"] == {
        "value": " xyz ",
        "allowed": ["UMF", "CSP"],
    }

    normalized = _upload(env, product=" umf ")
    assert normalized.status_code == 202, normalized.text
    task_id = normalized.json()["task_id"]
    wait_for_task(client, task_id)

    listed = client.get("/api/v2/tasks").json()["items"]
    task = next(item for item in listed if item["task_id"] == task_id)
    assert task["customer_product"] == "UMF"
    detail = client.get(f"/api/v2/tasks/{task_id}").json()
    assert detail["system"]["customer"]["product"] == "UMF"


def test_log_supplement_rejects_inspection_metadata(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)

    for field, value in (("province", "北京"), ("operator", "移动"), ("product", " UMF ")):
        metadata: dict[str, str | None] = {"package_kind": "log_supplement", "product": None}
        metadata[field] = value
        response = _upload(env, **metadata)
        assert response.status_code == 400, (field, response.text)
        body = response.json()
        assert body["code"] == "metadata_not_applicable", (field, body)
        assert body["detail"]["fields"] == [field], (field, body)


def test_log_supplement_treats_whitespace_metadata_as_absent(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)

    response = _upload(
        env,
        filename="whitespace-log.zip",
        package_kind="log_supplement",
        province="   ",
        operator="\t",
        product="  ",
    )

    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    wait_for_task(client, task_id)
    listed = client.get("/api/v2/tasks").json()["items"]
    task = next(item for item in listed if item["task_id"] == task_id)
    assert task["package_kind"] == "log_supplement"
    assert task["customer_product"] is None


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
        'Content-Disposition: form-data; name="product"\r\n\r\nUMF\r\n'
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


def test_upload_validation_order_is_frozen_from_package_kind_through_product(tmp_path, monkeypatch) -> None:
    """组合错误必须按 package_kind → 包文件 → province → operator → product 报错。"""
    env = setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "max_upload_mb", 1)

    for package_kind in (None, "not-a-package-kind"):
        data = {} if package_kind is None else {"package_kind": package_kind}
        response = client.post(
            "/api/v3/tasks",
            files={"package_file": ("bad.zip.exe", io.BytesIO(b""), "application/zip")},
            data=data,
        )
        _assert_error(response, status_code=422, code="validation_error")

    invalid_filename = _upload(
        env,
        filename="a" * 252 + ".zip",
        content=b"",
        product=None,
        province="",
        operator="",
    )
    _assert_error(invalid_filename, status_code=400, code="invalid_filename")

    invalid_extension_missing_product = _upload(
        env,
        filename="missing-product.zip.exe",
        content=b"not-an-archive",
        product=None,
        province="",
        operator="",
    )
    _assert_error(invalid_extension_missing_product, status_code=400, code="invalid_package")

    empty_missing_product = _upload(
        env,
        filename="empty-missing-product.zip",
        content=b"",
        product=None,
        province="",
        operator="",
    )
    _assert_error(empty_missing_product, status_code=400, code="invalid_package")

    oversized_missing_product = _upload(
        env,
        filename="oversized-missing-product.zip",
        content=b"x" * (1024 * 1024 + 1),
        product=None,
        province="",
        operator="",
    )
    _assert_error(oversized_missing_product, status_code=413, code="package_too_large")

    missing_province = _upload(env, product=None, province="  ", operator="")
    _assert_error(missing_province, status_code=400, code="missing_province")

    missing_operator = _upload(env, product=None, province="北京", operator="\t")
    _assert_error(missing_operator, status_code=400, code="missing_operator")

    missing_product = _upload(env, product=None)
    _assert_error(missing_product, status_code=400, code="missing_product")

    assert not list(env.uploads.glob(".upload-*")), "所有失败路径都必须清理上传临时文件"
    assert not list(env.uploads.glob("task-*")), "元数据校验失败不得创建任务现场"


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


def test_same_name_conflicts_follow_checksum_kind_product_order(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    first = _upload(env, product="UMF")
    assert first.status_code == 202, first.text
    task_id = first.json()["task_id"]
    completed = wait_for_task(client, task_id)

    checksum_conflict = _upload(
        env,
        content=SAMPLE.read_bytes() + b"different",
        package_kind="log_supplement",
        province="",
        operator="",
        product=None,
    )
    assert checksum_conflict.status_code == 409, checksum_conflict.text
    assert checksum_conflict.json()["code"] == "package_checksum_conflict"

    kind_conflict = _upload(
        env,
        package_kind="log_supplement",
        province="",
        operator="",
        product=None,
    )
    assert kind_conflict.status_code == 409, kind_conflict.text
    assert kind_conflict.json()["code"] == "package_kind_conflict"

    product_conflict = _upload(env, product="CSP")
    assert product_conflict.status_code == 409, product_conflict.text
    assert product_conflict.json()["code"] == "package_product_conflict"

    idempotent = _upload(env, product=" umf ")
    assert idempotent.status_code == 202, idempotent.text
    assert idempotent.json()["task_id"] == task_id
    assert idempotent.headers["location"] == f"/api/v3/tasks/{task_id}"
    unchanged = client.get(f"/api/v2/tasks/{task_id}").json()
    assert unchanged["status"] == completed["status"] == "completed"
    assert unchanged["last_run_at"] == completed["last_run_at"]


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
    task_dir = env.task_dir(task_id)

    def tree_digest() -> bytes:
        digest = b""
        for path in sorted(task_dir.rglob("*")):
            digest += str(path.relative_to(task_dir)).encode()
            if path.is_file():
                digest += path.read_bytes()
        return digest

    before = tree_digest()
    response = client.post(
        f"/api/v2/tasks/{task_id}/rerun",
        json={"rule_codes": ["log.error_density"]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "unknown_rule"
    assert tree_digest() == before


def test_rerun_keeps_summary_report_and_contract_consistent(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _upload(env).json()["task_id"]
    wait_for_task(client, task_id)
    before_task = client.get(f"/api/v2/tasks/{task_id}").json()
    before_system = client.get(f"/api/v2/tasks/{task_id}/system").json()

    response = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["kpi.measurement_units"]})
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
    (env.rules_dir(task_id) / "kpi.measurement_units.json").write_text("{broken", encoding="utf-8")

    response = client.post(
        f"/api/v2/tasks/{task_id}/rerun",
        json={"rule_codes": ["kpi.measurement_units"]},
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
            json={"rule_codes": ["kpi.measurement_units"]},
        )
        for _ in range(2)
    ]
    assert [response.status_code for response in responses] == [202, 202]
    task = wait_for_task(client, task_id)
    after = client.get(f"/api/v2/tasks/{task_id}/system").json()
    assert task["status"] == "completed"
    assert after["summary"] == before["summary"]
    assert (env.task_dir(task_id) / "report.html").is_file()
