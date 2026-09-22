"""测量单元资源目录服务测试。"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from app.models.db import KpiMeasurementResource, init_db, session_factory
from app.services.kpi_measurement_units import (
    KpiMeasurementError,
    filename_fragment,
    import_resource_csv,
    list_measurement_units,
    resource_kind,
    set_measurement_unit_enabled,
)


def resource_csv(*rows: tuple[str, str, str]) -> io.StringIO:
    text = "资源id,中文描述,英文描述\n" + "".join(",".join(row) + "\n" for row in rows)
    return io.StringIO(text)


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


def test_resource_kind_and_filename_fragment() -> None:
    assert resource_kind("MU_CALL") == "mu"
    assert resource_kind("ME_CALL") == "me"
    assert resource_kind("UNIT_COUNT") == "unit"
    assert resource_kind("mu__call") == "mu"
    assert resource_kind("Mu__Call") == "mu"
    assert resource_kind("me_call") == "me"
    assert resource_kind("unit_count") == "unit"
    assert filename_fragment("Call Session API Statistics") == "Call_Session_API_Statistics"


def test_import_resource_csv_adds_and_upserts() -> None:
    first = import_resource_csv(
        resource_csv(("MU_CALL", "呼叫统计", "Call Statistics"), ("ME_CALL", "呼叫请求", "Call Requests"))
    )
    assert first["added"] == {"mu": 1, "me": 1, "unit": 0}
    assert first["errors"] == []
    second = import_resource_csv(resource_csv(("MU_CALL", "呼叫统计", "Call Statistics New")))
    assert second["added"] == {"mu": 0, "me": 0, "unit": 0}
    assert second["updated"] == {"mu": 1, "me": 0, "unit": 0}
    units = list_measurement_units()
    assert units["items"][0]["name_zh"] == "呼叫统计"
    assert units["items"][0]["name_en"] == "Call Statistics New"


def test_import_keeps_existing_resources_absent_from_csv() -> None:
    import_resource_csv(
        resource_csv(
            ("MU_CALL", "呼叫统计", "Call Statistics"),
            ("ME_CALL", "呼叫请求", "Call Requests"),
            ("UNIT_COUNT", "次", "Count"),
        )
    )
    import_resource_csv(resource_csv(("MU_CALL", "呼叫统计", "Call Statistics")))
    units = list_measurement_units()
    assert units["total"] == 1
    assert units["items"][0]["metric_count"] == 1
    assert units["items"][0]["unit_count"] == 1


def test_import_ignores_unknown_prefix_and_requires_mu_fields() -> None:
    result = import_resource_csv(
        resource_csv(("BAD_CALL", "非法", "Bad"), ("ME_ORPHAN", "孤立", ""), ("ME_VALID", "有效", "Valid"))
    )
    assert result["added"] == {"mu": 0, "me": 1, "unit": 0}
    assert result["errors"] == [
        {
            "resource_id": "ME_ORPHAN",
            "line_number": 3,
            "reason": "invalid_resource",
        }
    ]
    assert result["skipped"] == [
        {
            "resource_id": "BAD_CALL",
            "line_number": 2,
            "reason": "unsupported_resource_prefix",
        }
    ]


def test_enable_toggle_only_affects_mu() -> None:
    import_resource_csv(resource_csv(("MU_CALL", "呼叫统计", "Call Statistics")))
    set_measurement_unit_enabled("MU_CALL", False)
    assert list_measurement_units()["items"][0]["enabled"] is False
    with pytest.raises(KpiMeasurementError):
        set_measurement_unit_enabled("ME_CALL", False)


def test_import_updates_english_for_same_chinese_name() -> None:
    first = import_resource_csv(resource_csv(("ME_CALL", "呼叫请求", "Call Requests")))
    assert first["added"] == {"mu": 0, "me": 1, "unit": 0}

    second = import_resource_csv(resource_csv(("ME_CALL", "呼叫请求", "Call Request Count")))
    assert second["updated"] == {"mu": 0, "me": 1, "unit": 0}
    assert second["errors"] == []


def test_import_same_id_with_different_chinese_uses_conflict_key() -> None:
    import_resource_csv(resource_csv(("ME_CALL", "呼叫请求", "Call Requests")))
    result = import_resource_csv(resource_csv(("ME_CALL", "呼叫请求总数", "Call Request Total")))

    assert result["added"] == {"mu": 0, "me": 1, "unit": 0}
    assert result["updated"] == {"mu": 0, "me": 0, "unit": 0}
    assert result["errors"] == []

    repeat = import_resource_csv(resource_csv(("ME_CALL", "呼叫请求总数", "Call Request Total")))
    assert repeat["added"] == {"mu": 0, "me": 0, "unit": 0}
    assert repeat["updated"] == {"mu": 0, "me": 0, "unit": 0}
    assert repeat["errors"] == []

    with session_factory() as session:
        names = {
            item.name_zh: item.resource_id
            for item in session.query(KpiMeasurementResource).filter(KpiMeasurementResource.kind == "me")
        }
    assert set(names) == {"呼叫请求", "呼叫请求总数"}
    assert names["呼叫请求总数"].startswith("ME_CALL__CONFLICT_")


def test_import_merges_by_chinese_name_not_resource_id() -> None:
    first = import_resource_csv(resource_csv(("ME_CALL", "呼叫请求", "Call Requests")))
    assert first["added"] == {"mu": 0, "me": 1, "unit": 0}

    second = import_resource_csv(resource_csv(("ME_REQUEST", "呼叫请求", "Call Request Count")))
    assert second["added"] == {"mu": 0, "me": 0, "unit": 0}
    assert second["updated"] == {"mu": 0, "me": 1, "unit": 0}
    assert second["errors"] == []


def test_import_merges_same_chinese_name_with_different_ids_in_one_csv() -> None:
    result = import_resource_csv(
        resource_csv(("ME_CALL", "呼叫请求", "Call Requests"), ("ME_REQUEST", "呼叫请求", "Call Requests"))
    )

    assert result["added"] == {"mu": 0, "me": 1, "unit": 0}
    assert result["updated"] == {"mu": 0, "me": 0, "unit": 0}
    assert result["skipped"] == [{"resource_id": "ME_CALL", "reason": "unchanged"}]
    assert result["errors"] == []


def test_import_resource_csv_supports_gbk() -> None:
    content = "资源id,中文描述,英文描述\nME_CALL,呼叫请求,Call Requests\n".encode("gb18030")
    result = import_resource_csv(io.BytesIO(content))

    assert result["added"] == {"mu": 0, "me": 1, "unit": 0}
    assert result["errors"] == []


def test_import_resource_csv_supports_header_whitespace() -> None:
    result = import_resource_csv(io.StringIO(" 资源id , 中文描述 , 英文描述 \nME_CALL,呼叫请求,Call Requests\n"))

    assert result["added"] == {"mu": 0, "me": 1, "unit": 0}
    assert result["errors"] == []


def test_register_manual_metric_uses_readable_id(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import (
        discover_measurement_bindings,
        list_measurement_bindings,
        register_metric_for_binding,
    )

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),人工列(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-readable", [(path.name, path)])
    binding_id = list_measurement_bindings()["items"][0]["id"]

    _, metric = register_metric_for_binding(binding_id, name_zh="人工呼叫请求", name_en="Call Requests")

    assert re.fullmatch(r"ME__MANUAL_CALL_REQUESTS_[0-9A-F]{6}", metric["resource_id"])


def test_register_manual_metric_creates_candidate_binding(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import (
        discover_measurement_bindings,
        inspect_measurement_files,
        list_measurement_bindings,
        register_metric_for_binding,
    )

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-manual", [(path.name, path)])
    binding = list_measurement_bindings()["items"][0]
    assert binding["metric_resource_id"] is None

    binding, metric = register_metric_for_binding(binding["id"], name_zh="呼叫请求次数", name_en="Call Requests")
    assert metric["resource_id"].startswith("ME__MANUAL_")
    assert metric["is_manual"] is True
    assert binding["metric_resource_id"] == metric["resource_id"]
    assert binding["metric_is_manual"] is True
    assert binding["status"] == "candidate"
    inspected = inspect_measurement_files("task-manual", [(path.name, path)])
    assert inspected["measurement_units"][0]["status"] == "skip"


def test_register_metric_rejects_conflict_and_binds_existing(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import (
        discover_measurement_bindings,
        list_measurement_bindings,
        register_metric_for_binding,
    )

    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,已有指标,Existing Metric\n")
    )
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),新列(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-conflict", [(path.name, path)])
    binding = list_measurement_bindings()["items"][0]
    with pytest.raises(KpiMeasurementError) as conflict:
        register_metric_for_binding(binding["id"], name_zh="已有指标")
    assert conflict.value.code == "kpi_metric_name_conflict"
    assert conflict.value.detail == {"existing_resource_id": "ME_CALL"}

    result, metric = register_metric_for_binding(
        binding["id"], name_zh=None, name_en=None, bind_existing_resource_id="ME_CALL"
    )
    assert result["metric_resource_id"] == "ME_CALL"
    assert result["status"] == "candidate"
    assert metric["resource_id"] == "ME_CALL"
    assert metric["is_manual"] is False


def test_update_manual_metric_and_resource_list(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import (
        discover_measurement_bindings,
        list_measurement_bindings,
        list_measurement_resources,
        register_metric_for_binding,
        update_manual_metric,
    )

    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,导入指标,Imported Metric\n")
    )
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),人工列(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-update", [(path.name, path)])
    binding_id = list_measurement_bindings()["items"][0]["id"]
    _, metric = register_metric_for_binding(binding_id, name_zh="人工指标", name_en="Manual Metric")

    updated = update_manual_metric(
        metric["resource_id"], name_zh="人工指标更新", name_en="Updated Metric", enabled=False
    )
    assert updated["resource_id"] == metric["resource_id"]
    assert updated["name_zh"] == "人工指标更新"
    assert updated["enabled"] is False
    assert list_measurement_bindings()["items"][0]["status"] == "candidate"

    with pytest.raises(KpiMeasurementError) as not_manual:
        update_manual_metric("ME_CALL", name_zh="导入指标更新")
    assert not_manual.value.code == "kpi_metric_not_manual"

    with pytest.raises(KpiMeasurementError) as conflict:
        update_manual_metric(metric["resource_id"], name_zh="导入指标")
    assert conflict.value.code == "kpi_metric_name_conflict"

    listed = list_measurement_resources(kind="me", search="metric", page=1, page_size=10)
    assert listed["total"] == 2
    assert {item["is_manual"] for item in listed["items"]} == {True, False}


def test_register_manual_metric_handles_empty_and_long_english(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import (
        discover_measurement_bindings,
        list_measurement_bindings,
        register_metric_for_binding,
    )

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),空英文列(次),长英文列(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1,2\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-id-boundary", [(path.name, path)])
    bindings = list_measurement_bindings()["items"]
    empty_english = next(item for item in bindings if item["base_source_name"] == "空英文列")
    long_english = next(item for item in bindings if item["base_source_name"] == "长英文列")

    _, empty_metric = register_metric_for_binding(empty_english["id"], name_zh="空英文指标", name_en="全中文名称")
    _, long_metric = register_metric_for_binding(long_english["id"], name_zh="长英文指标", name_en="X" * 256)

    assert re.fullmatch(r"ME__MANUAL_UNNAMED_[0-9A-F]{6}", empty_metric["resource_id"])
    assert len(long_metric["resource_id"]) <= 128
    assert re.fullmatch(r"ME__MANUAL_X+_[0-9A-F]{6}", long_metric["resource_id"])


def test_register_manual_metric_rejects_registered_and_ignored_binding(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import (
        discover_measurement_bindings,
        list_measurement_bindings,
        register_metric_for_binding,
        set_measurement_binding_status,
    )

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),已注册列(次),忽略列(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1,2\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-register-invalid", [(path.name, path)])
    bindings = list_measurement_bindings()["items"]
    registered_binding = next(item for item in bindings if item["base_source_name"] == "已注册列")
    ignored_binding = next(item for item in bindings if item["base_source_name"] == "忽略列")

    register_metric_for_binding(registered_binding["id"], name_zh="已注册指标", name_en="Registered")
    set_measurement_binding_status(ignored_binding["id"], "ignored")

    with pytest.raises(KpiMeasurementError) as already_registered:
        register_metric_for_binding(registered_binding["id"], name_zh="重复注册")
    assert already_registered.value.code == "kpi_binding_already_registered"
    with pytest.raises(KpiMeasurementError) as not_candidate:
        register_metric_for_binding(ignored_binding["id"], name_zh="忽略后注册")
    assert not_candidate.value.code == "kpi_binding_not_unregistered"


def test_register_metric_keeps_other_candidates_unchanged(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import (
        discover_measurement_bindings,
        list_measurement_bindings,
        register_metric_for_binding,
    )

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),保持列(次),注册列(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1,2\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-other-binding", [(path.name, path)])
    before = {item["base_source_name"]: item for item in list_measurement_bindings()["items"]}

    _, metric = register_metric_for_binding(before["注册列"]["id"], name_zh="注册列指标", name_en="Registered")

    after = {item["base_source_name"]: item for item in list_measurement_bindings()["items"]}
    assert after["注册列"]["metric_resource_id"] == metric["resource_id"]
    assert after["保持列"]["metric_resource_id"] is None
    assert after["保持列"]["status"] == "candidate"
