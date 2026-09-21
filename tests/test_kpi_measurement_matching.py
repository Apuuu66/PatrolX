"""测量单元任务文件匹配测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.db import init_db
from app.services.kpi_measurement_units import filename_fragment, match_measurement_files


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


def test_filename_fragment_is_case_sensitive_shape() -> None:
    assert filename_fragment("Call Session API Statistics") == "Call_Session_API_Statistics"


def test_match_measurement_files_states(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import import_resource_csv, io

    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU__MATCH,呼叫统计,Call Session API Statistics\n"
            "MU__LEFT,接口左,A B\n"
            "MU__RIGHT,接口右,B C\n"
        )
    )
    files = [
        ("ne333_Call_Session_API_Statistics_15_0_202609020000.csv", tmp_path / "matched.csv"),
        ("ne333_call_session_api_statistics_15_0_202609020000.csv", tmp_path / "lower.csv"),
        ("ne333_unknown_file_15_0_202609020000.csv", tmp_path / "unknown.csv"),
        ("ne333_A_B_C_15_0_202609020000.csv", tmp_path / "ambiguous.csv"),
    ]
    for _, path in files:
        path.write_text("a,b,c\n", encoding="utf-8")
    result = match_measurement_files(files)
    by_name = {item["filename"]: item for item in result["files"]}
    assert by_name["ne333_Call_Session_API_Statistics_15_0_202609020000.csv"]["status"] == "matched"
    assert by_name["ne333_call_session_api_statistics_15_0_202609020000.csv"]["status"] == "unmatched"
    assert by_name["ne333_unknown_file_15_0_202609020000.csv"]["status"] == "unmatched"
    assert by_name["ne333_A_B_C_15_0_202609020000.csv"]["status"] == "ambiguous"


def test_disabled_measurement_unit_file_is_visible_but_skipped(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import import_resource_csv, io, set_measurement_unit_enabled

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU__CALL,呼叫统计,Call Statistics\n"))
    set_measurement_unit_enabled("MU__CALL", False)
    path = tmp_path / "disabled.csv"
    path.write_text("a,b,c\n", encoding="utf-8")
    result = match_measurement_files([("ne333_Call_Statistics_15_0_202609020000.csv", path)])
    assert result["files"][0]["status"] == "disabled"
