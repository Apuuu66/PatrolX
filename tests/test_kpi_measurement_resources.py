"""测量单元资源目录服务测试。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.models.db import KpiMeasurementResource, init_db, session_factory
from app.services.kpi_measurement_units import (
    KpiMeasurementError,
    filename_fragment,
    import_resource_csv,
    list_measurement_resources,
    list_measurement_units,
    resource_kind,
    set_measurement_unit_enabled,
    update_manual_metric,
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


def test_import_fills_missing_defaults_without_overwriting_existing_policy(tmp_path: Path) -> None:
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求,Call Requests\n")
    )
    update_manual_metric(
        "ME_CALL",
        direction="higher_better",
        importance="P0",
        metric_group="业务质量",
        warning_threshold=90,
        critical_threshold=70,
    )
    result = import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述,所属测量单元id,显示顺序,指标分组,方向,重要级别,预警阈值,失败阈值\n"
            "ME_CALL,呼叫请求,Call Requests,MU_CALL,9,标准分组,lower_better,P2,10,20\n"
        )
    )
    assert result["errors"] == []
    metric = list_measurement_resources(kind="me", search="呼叫请求")["items"][0]
    assert metric["direction"] == "higher_better"
    assert metric["importance"] == "P0"
    assert metric["metric_group"] == "业务质量"
    assert metric["warning_threshold"] == 90
    assert metric["critical_threshold"] == 70


def test_discovered_metric_defaults_and_manual_policy_update(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import discover_measurement_bindings

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100\n",
        encoding="utf-8",
    )
    discover_measurement_bindings("task-discovery", [(path.name, path)])
    metric = list_measurement_resources(kind="me", search="呼叫请求次数")["items"][0]
    assert metric["source"] == "discovered"
    assert metric["origin_task_id"] == "task-discovery"
    assert metric["origin_file"] == path.name
    assert metric["display_order"] == 1
    assert metric["direction"] == "neutral"
    assert metric["importance"] == "normal"
    assert metric["metric_group"] == "未分组"
    assert metric["warning_threshold"] is None
    assert metric["critical_threshold"] is None

    updated = update_manual_metric(
        metric["resource_id"],
        name_zh="呼叫请求次数",
        direction="higher_better",
        warning_threshold=80,
        critical_threshold=50,
        importance="P1",
        metric_group="容量",
    )
    assert updated["direction"] == "higher_better"
    assert updated["warning_threshold"] == 80
    assert updated["critical_threshold"] == 50
    assert updated["importance"] == "P1"


def test_update_metric_rejects_invalid_threshold_policy() -> None:
    import_resource_csv(resource_csv(("ME_CALL", "呼叫请求", "Call Requests")))
    with pytest.raises(KpiMeasurementError) as exc:
        update_manual_metric("ME_CALL", direction="higher_better", warning_threshold=50, critical_threshold=80)
    assert exc.value.code == "kpi_metric_threshold_conflict"


def test_resource_list_searches_id_and_paginates() -> None:
    import_resource_csv(
        resource_csv(
            ("ME_CALL", "呼叫请求", "Call Requests"),
            ("ME_LOST", "丢失请求", "Lost Requests"),
        )
    )
    result = list_measurement_resources(kind="me", search="ME_CALL", page=1, page_size=10)
    assert result["total"] == 1
    assert result["items"][0]["resource_id"] == "ME_CALL"
