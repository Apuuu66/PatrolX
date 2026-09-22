"""测量单元指标绑定发现与确认测试。"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.models.db import init_db
from app.services.kpi_measurement_units import (
    KpiMeasurementError,
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    io,
    list_measurement_bindings,
    set_measurement_binding_status,
)

CSV_TEXT = """container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)
pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100
pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,0
"""


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


@pytest.fixture
def call_file(tmp_path: Path) -> tuple[str, Path]:
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return "ne333_Call_Statistics_15_0_202609020000.csv", path


def _import_call_resources() -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )


def test_discover_binding_strips_display_unit(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    result = discover_measurement_bindings("task-1", [call_file])
    assert result["files"][0]["binding_candidates"] == 1
    bindings = list_measurement_bindings()["items"]
    assert bindings[0]["status"] == "candidate"
    assert bindings[0]["raw_source_name"] == "呼叫请求次数(次)"
    assert bindings[0]["base_source_name"] == "呼叫请求次数"
    assert bindings[0]["display_unit"] == "次"
    assert bindings[0]["metric_resource_id"] == "ME_CALL"
    assert bindings[0]["measurement_unit_id"] == "MU_CALL"


def test_unconfirmed_binding_is_not_inspected(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    discover_measurement_bindings("task-1", [call_file])
    result = inspect_measurement_files("task-1", [call_file])
    assert result["measurement_units"][0]["status"] == "skip"
    assert "未配置已确认指标绑定" in result["measurement_units"][0]["reason"]


def test_confirm_binding_enables_inspection(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    discover_measurement_bindings("task-1", [call_file])
    binding_id = list_measurement_bindings()["items"][0]["id"]
    set_measurement_binding_status(binding_id, "confirmed")
    result = inspect_measurement_files("task-1", [call_file])
    assert result["measurement_units"][0]["status"] == "pass"
    assert result["measurement_units"][0]["metric_coverage"] == "1/1"


def test_conflicting_metric_binding_is_not_auto_rebound(call_file: tuple[str, Path]) -> None:
    _import_call_resources()
    discover_measurement_bindings("task-1", [call_file])
    first_id = list_measurement_bindings()["items"][0]["id"]
    set_measurement_binding_status(first_id, "confirmed")
    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_OTHER,其他统计,Other Statistics\n"))
    other_path = call_file[1].with_name("ne333_Other_Statistics_15_0_202609020000.csv")
    other_path.write_text(CSV_TEXT, encoding="utf-8")
    discover_measurement_bindings("task-2", [("ne333_Other_Statistics_15_0_202609020000.csv", other_path)])
    second = next(item for item in list_measurement_bindings()["items"] if item["measurement_unit_id"] == "MU_OTHER")
    assert second["status"] == "conflict"
    with pytest.raises(KpiMeasurementError):
        set_measurement_binding_status(second["id"], "confirmed")


def test_unknown_column_is_reported(tmp_path: Path) -> None:
    _import_call_resources()
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),未注册指标(个)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    result = discover_measurement_bindings("task-1", [("ne333_Call_Statistics_15_0_202609020000.csv", path)])
    assert result["files"][0]["unknown_columns"] == ["未注册指标(个)"]
    assert list_measurement_bindings()["items"][0]["metric_resource_id"] is None


def test_binding_search_matches_keywords_fuzzily() -> None:
    """绑定搜索匹配指标 ID 和基础列名；不匹配原始列名中的展示单位。"""
    matched = _create_binding(metric_resource_id="ME_CALL", base_source_name="呼叫请求次数")
    unmatched = _create_binding(
        metric_resource_id="ME_CPU",
        measurement_unit_id="MU_CPU",
        base_source_name="容器CPU使用率",
    )

    result = list_measurement_bindings(search="请求")

    assert result["total"] == 1
    assert result["items"][0]["id"] == matched
    assert result["items"][0]["base_source_name"] == "呼叫请求次数"

    raw_search = list_measurement_bindings(search="呼叫请求次数(次)")
    assert raw_search["total"] == 0
    assert all(item["id"] not in {matched, unmatched} for item in raw_search["items"])


def _create_binding(
    *,
    metric_resource_id: str | None,
    measurement_unit_id: str = "MU_CALL",
    status: str = "candidate",
    base_source_name: str = "呼叫请求次数",
) -> int:
    """为批量确认测试创建受控绑定行。"""
    from datetime import UTC, datetime

    from app.models.db import KpiMeasurementBinding, session_factory

    now = datetime.now(UTC)
    row = KpiMeasurementBinding(
        metric_resource_id=metric_resource_id,
        measurement_unit_id=measurement_unit_id,
        base_source_name=base_source_name,
        raw_source_name=f"{base_source_name}(次)-{uuid.uuid4().hex}",
        display_unit="次",
        status=status,
        enabled=True,
        task_id=f"task-{measurement_unit_id}-{status}",
        source_file="ne333_Call_Statistics_15_0_202609020000.csv",
        created_at=now,
        updated_at=now,
    )
    with session_factory() as session:
        session.add(row)
        session.commit()
        return row.id


def _get_binding(binding_id: int) -> dict[str, object]:
    from app.models.db import KpiMeasurementBinding, session_factory
    from app.services.kpi_measurement_units import _binding_dict

    with session_factory() as session:
        row = session.get(KpiMeasurementBinding, binding_id)
        assert row is not None
        session.refresh(row)
        result = _binding_dict(row)
        result["updated_at"] = row.updated_at
        return result


def test_batch_confirm_updates_selected_candidates_and_is_idempotent() -> None:
    from app.services.kpi_measurement_units import batch_confirm_measurement_bindings

    first = _create_binding(metric_resource_id="ME_CALL")
    second = _create_binding(metric_resource_id="ME_CALL")
    confirmed = _create_binding(metric_resource_id="ME_CALL", status="confirmed")
    unselected = _create_binding(metric_resource_id="ME_OTHER")

    confirmed_before = _get_binding(confirmed)
    result = batch_confirm_measurement_bindings([first, second, confirmed, first])

    assert result["total"] == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert [item["binding_id"] for item in result["items"]] == [first, second, confirmed]
    assert [item["outcome"] for item in result["items"]] == ["confirmed", "confirmed", "already_confirmed"]
    assert _get_binding(first)["status"] == "confirmed"
    assert _get_binding(second)["status"] == "confirmed"
    assert _get_binding(confirmed)["status"] == "confirmed"
    assert _get_binding(confirmed)["updated_at"] == confirmed_before["updated_at"]
    assert _get_binding(unselected)["status"] == "candidate"


def test_batch_confirm_returns_item_failures_without_blocking_others() -> None:
    from app.services.kpi_measurement_units import batch_confirm_measurement_bindings

    valid = _create_binding(metric_resource_id="ME_CALL")
    missing_metric = _create_binding(metric_resource_id=None)
    ignored = _create_binding(metric_resource_id="ME_CALL", status="ignored")
    missing = 999999

    result = batch_confirm_measurement_bindings([valid, missing_metric, missing, ignored])

    assert result["total"] == 4
    assert result["succeeded"] == 1
    assert result["failed"] == 3
    by_id = {item["binding_id"]: item for item in result["items"]}
    assert by_id[valid]["outcome"] == "confirmed"
    assert by_id[missing_metric]["outcome"] == "failed"
    assert by_id[missing_metric]["error_code"] == "kpi_binding_metric_missing"
    assert by_id[missing]["error_code"] == "kpi_binding_not_found"
    assert by_id[ignored]["error_code"] == "kpi_binding_status_not_confirmable"
    assert _get_binding(missing_metric)["status"] == "candidate"
    assert _get_binding(ignored)["status"] == "ignored"


def test_batch_confirm_rejects_more_than_two_hundred_unique_bindings() -> None:
    from app.services.kpi_measurement_units import batch_confirm_measurement_bindings

    binding_ids = list(range(1, 202))

    with pytest.raises(KpiMeasurementError) as exc_info:
        batch_confirm_measurement_bindings(binding_ids)

    assert exc_info.value.code == "kpi_binding_batch_too_large"


def test_batch_confirm_is_serialized_for_metric_conflicts() -> None:
    """并发确认同一指标时，后提交方必须重新读取最终状态。"""
    from app.services.kpi_measurement_units import batch_confirm_measurement_bindings

    first = _create_binding(metric_resource_id="ME_CALL", measurement_unit_id="MU_CALL")
    second = _create_binding(metric_resource_id="ME_CALL", measurement_unit_id="MU_OTHER")
    selected_threads: set[int] = set()
    condition = threading.Condition()

    def _wait_for_stale_reads(_conn, _cursor, statement, *_args, **_kwargs) -> None:
        normalized = " ".join(statement.lower().split())
        if "from kpi_measurement_bindings" not in normalized:
            return
        thread_id = threading.get_ident()
        with condition:
            if thread_id in selected_threads:
                return
            selected_threads.add(thread_id)
            if len(selected_threads) < 2:
                # BEGIN IMMEDIATE serializes the second reader; do not deadlock while
                # waiting for a read that can only happen after the first commit.
                condition.wait(0.2)

    event.listen(Engine, "before_cursor_execute", _wait_for_stale_reads)
    try:
        results: dict[str, object] = {}

        def _confirm(key: str, binding_id: int) -> None:
            results[key] = batch_confirm_measurement_bindings([binding_id])

        threads = [
            threading.Thread(target=_confirm, args=("first", first)),
            threading.Thread(target=_confirm, args=("second", second)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        first_result = results["first"]
        second_result = results["second"]
        assert isinstance(first_result, dict)
        assert isinstance(second_result, dict)
        outcomes = (("first", first_result), ("second", second_result))
        succeeded_keys = [key for key, result in outcomes if result["succeeded"]]
        failed_keys = [key for key, result in outcomes if result["failed"]]
        assert len(succeeded_keys) == 1
        assert len(failed_keys) == 1
        failed_result = second_result if failed_keys == ["second"] else first_result
        assert failed_result["items"][0]["error_code"] == "kpi_binding_conflict"
        assert [_get_binding(first)["status"], _get_binding(second)["status"]].count("confirmed") == 1
        assert [_get_binding(first)["status"], _get_binding(second)["status"]].count("candidate") == 1
    finally:
        event.remove(Engine, "before_cursor_execute", _wait_for_stale_reads)


def test_batch_confirm_blocks_cross_unit_metric_conflicts() -> None:
    from app.services.kpi_measurement_units import batch_confirm_measurement_bindings

    call = _create_binding(metric_resource_id="ME_CALL", measurement_unit_id="MU_CALL")
    other = _create_binding(metric_resource_id="ME_CALL", measurement_unit_id="MU_OTHER")

    result = batch_confirm_measurement_bindings([call, other])

    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert all(item["outcome"] == "failed" for item in result["items"])
    assert all(item["error_code"] == "kpi_binding_conflict" for item in result["items"])
    assert _get_binding(call)["status"] == "candidate"
    assert _get_binding(other)["status"] == "candidate"


def test_batch_confirm_respects_existing_confirmed_metric_in_other_unit() -> None:
    from app.services.kpi_measurement_units import batch_confirm_measurement_bindings

    call = _create_binding(metric_resource_id="ME_CALL", measurement_unit_id="MU_CALL")
    other = _create_binding(
        metric_resource_id="ME_CALL",
        measurement_unit_id="MU_OTHER",
        status="confirmed",
    )

    result = batch_confirm_measurement_bindings([call, other])

    assert result["succeeded"] == 1
    assert result["failed"] == 1
    by_id = {item["binding_id"]: item for item in result["items"]}
    assert by_id[other]["outcome"] == "already_confirmed"
    assert by_id[call]["outcome"] == "failed"
    assert by_id[call]["error_code"] == "kpi_binding_conflict"
    assert _get_binding(call)["status"] == "candidate"
