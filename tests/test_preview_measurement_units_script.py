"""测量单元资源 CSV 预览脚本测试。"""

from __future__ import annotations

from scripts.preview_measurement_units import preview


def test_preview_resource_csv_reports_kinds_without_import(tmp_path) -> None:
    path = tmp_path / "resources.csv"
    path.write_text(
        " 资源id , 中文描述 , 英文描述 \n"
        "MU__CALL,呼叫统计,Call Statistics\n"
        "ME_CALL,呼叫请求,Call Requests\n"
        "BAD_CALL,非法资源,Bad Resource\n",
        encoding="utf-8",
    )

    result = preview(path)

    assert result["valid"] is True
    assert result["total_rows"] == 3
    assert result["kinds"] == {"mu": 1, "me": 1}
    assert result["statuses"] == {"importable": 2, "unsupported_prefix": 1}
    assert result["rows"][0]["status"] == "importable"
    assert result["rows"][-1]["status"] == "unsupported_prefix"
