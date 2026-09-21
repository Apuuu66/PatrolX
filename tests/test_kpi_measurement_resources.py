"""测量单元资源目录服务测试。"""

from __future__ import annotations

import io

import pytest

from app.models.db import init_db
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
    assert resource_kind("MU__CALL") == "mu"
    assert resource_kind("ME_CALL") == "me"
    assert resource_kind("UNIT_COUNT") == "unit"
    assert filename_fragment("Call Session API Statistics") == "Call_Session_API_Statistics"


def test_import_resource_csv_adds_and_upserts() -> None:
    first = import_resource_csv(
        resource_csv(("MU__CALL", "呼叫统计", "Call Statistics"), ("ME_CALL", "呼叫请求", "Call Requests"))
    )
    assert first["added"] == {"mu": 1, "me": 1, "unit": 0}
    assert first["errors"] == []
    second = import_resource_csv(resource_csv(("MU__CALL", "呼叫统计新", "Call Statistics New")))
    assert second["added"] == {"mu": 0, "me": 0, "unit": 0}
    assert second["updated"] == {"mu": 1, "me": 0, "unit": 0}
    units = list_measurement_units()
    assert units["items"][0]["name_zh"] == "呼叫统计新"
    assert units["items"][0]["name_en"] == "Call Statistics New"


def test_import_keeps_existing_resources_absent_from_csv() -> None:
    import_resource_csv(
        resource_csv(
            ("MU__CALL", "呼叫统计", "Call Statistics"),
            ("ME_CALL", "呼叫请求", "Call Requests"),
            ("UNIT_COUNT", "次", "Count"),
        )
    )
    import_resource_csv(resource_csv(("MU__CALL", "呼叫统计", "Call Statistics")))
    units = list_measurement_units()
    assert units["total"] == 1
    assert units["items"][0]["metric_count"] == 1
    assert units["items"][0]["unit_count"] == 1


def test_import_rejects_unknown_prefix_and_requires_mu_fields() -> None:
    result = import_resource_csv(
        resource_csv(("BAD_CALL", "非法", "Bad"), ("ME_ORPHAN", "孤立", ""), ("ME_VALID", "有效", "Valid"))
    )
    assert result["added"] == {"mu": 0, "me": 1, "unit": 0}
    assert len(result["errors"]) == 2
    assert result["errors"][0]["resource_id"] == "BAD_CALL"


def test_enable_toggle_only_affects_mu() -> None:
    import_resource_csv(resource_csv(("MU__CALL", "呼叫统计", "Call Statistics")))
    set_measurement_unit_enabled("MU__CALL", False)
    assert list_measurement_units()["items"][0]["enabled"] is False
    with pytest.raises(KpiMeasurementError):
        set_measurement_unit_enabled("ME_CALL", False)
