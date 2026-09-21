"""成功率派生指标测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.db import init_db
from app.services.kpi_measurement_units import (
    create_measurement_derived,
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    io,
    list_measurement_bindings,
    set_measurement_binding_status,
)

HEADER = "container,测量开始时间,测量结束时间,周期(分钟),成功请求次数(次),呼叫请求次数(次)\n"


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


def _prepare() -> None:
    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU__CALL,呼叫统计,Call Statistics\n"
            "ME_SUCCESS,成功请求次数,Success Requests\n"
            "ME_TOTAL,呼叫请求次数,Call Requests\n"
            "ME_RATE,呼叫成功率,Call Success Rate\n"
        )
    )


def _confirmed_files(tmp_path: Path, body: str) -> list[tuple[str, Path]]:
    path = tmp_path / "ne333_Call_Statistics_15_0_202609020000.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    files = [("ne333_Call_Statistics_15_0_202609020000.csv", path)]
    discover_measurement_bindings("task-1", files)
    for binding in list_measurement_bindings()["items"]:
        set_measurement_binding_status(binding["id"], "confirmed")
    return files


def test_success_rate_computed_per_object(tmp_path: Path) -> None:
    _prepare()
    files = _confirmed_files(
        tmp_path,
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,9876,10000\n"
        "pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,90,100\n",
    )
    create_measurement_derived("MU__CALL", "ME_RATE", "ME_SUCCESS", "ME_TOTAL")
    result = inspect_measurement_files("task-1", files)
    derived = result["measurement_units"][0]["derived_metrics"][0]
    values = {item["object_key"]: item["value"] for item in derived["observations"]}
    assert values == {"pod-a": 98.76, "pod-b": 90.0}


def test_zero_denominator_is_not_failure(tmp_path: Path) -> None:
    _prepare()
    files = _confirmed_files(
        tmp_path,
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,0,0\n",
    )
    create_measurement_derived("MU__CALL", "ME_RATE", "ME_SUCCESS", "ME_TOTAL")
    result = inspect_measurement_files("task-1", files)
    derived = result["measurement_units"][0]["derived_metrics"][0]["observations"][0]
    assert derived["status"] == "pass"
    assert derived["message"] == "疑似业务未触发"


def test_missing_derived_dependency_fails(tmp_path: Path) -> None:
    _prepare()
    files = _confirmed_files(
        tmp_path,
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1,1\n",
    )
    create_measurement_derived("MU__CALL", "ME_RATE", "ME_SUCCESS", "ME_TOTAL")
    path = files[0][1]
    path.write_text(
        "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"
        "pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,1\n",
        encoding="utf-8",
    )
    result = inspect_measurement_files("task-1", files)
    derived = result["measurement_units"][0]["derived_metrics"][0]
    assert derived["status"] == "fail"
    assert "依赖指标缺失" in derived["message"]
