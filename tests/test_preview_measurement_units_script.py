"""测量单元资源 CSV 预览脚本测试。"""

from __future__ import annotations

from pathlib import Path

from tools.preview_measurement_units import DEFAULT_RESOURCE_DIR, preview_directory, preview_file


def test_preview_resource_csv_reports_kinds_without_import(tmp_path: Path) -> None:
    path = tmp_path / "resources.csv"
    path.write_text(
        " 资源id , 中文描述 , 英文描述 \n"
        "MU__CALL,呼叫统计,Call Statistics\n"
        "ME_CALL,呼叫请求,Call Requests\n"
        "BAD_CALL,非法资源,Bad Resource\n",
        encoding="utf-8",
    )

    result = preview_file(path)

    assert result["valid"] is True
    assert result["total_rows"] == 3
    assert result["kinds"] == {"mu": 1, "me": 1}
    assert result["statuses"] == {"importable": 2, "unsupported_prefix": 1}
    assert result["rows"][0]["status"] == "importable"
    assert result["rows"][-1]["status"] == "unsupported_prefix"


def test_preview_directory_processes_all_root_level_csv_files(tmp_path: Path) -> None:
    (tmp_path / "b-call.csv").write_text(
        "资源id,中文描述,英文描述\nMU__CALL,呼叫统计,Call Statistics\n",
        encoding="utf-8",
    )
    (tmp_path / "A-UNIT.CSV").write_text(
        "资源id,中文描述,英文描述\nUNIT_CALL,呼叫,Call\nME_CALL,呼叫请求,Call Requests\n",
        encoding="gb18030",
    )
    (tmp_path / "ignored.txt").write_text("not csv", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "nested.csv").write_text(
        "资源id,中文描述,英文描述\nUNIT_NESTED,嵌套,Nested\n",
        encoding="utf-8",
    )

    result = preview_directory(tmp_path)

    assert result["directory"] == str(tmp_path)
    assert result["file_count"] == 2
    assert result["total_rows"] == 3
    assert result["kinds"] == {"mu": 1, "me": 1, "unit": 1}
    assert result["statuses"] == {"importable": 3}
    assert [Path(item["file"]).name for item in result["files"]] == ["A-UNIT.CSV", "b-call.csv"]
    assert all(item["valid"] for item in result["files"])


def test_preview_directory_continues_after_invalid_header(tmp_path: Path) -> None:
    (tmp_path / "bad.csv").write_text("resource_id,name_zh,name_en\n", encoding="utf-8")
    (tmp_path / "good.csv").write_text(
        "资源id,中文描述,英文描述\nMU__CALL,呼叫统计,Call Statistics\n",
        encoding="utf-8",
    )

    result = preview_directory(tmp_path)

    assert result["file_count"] == 2
    assert result["total_rows"] == 1
    assert result["statuses"] == {"importable": 1}
    assert result["files"][0]["valid"] is False
    assert result["files"][0]["reason"] == "表头必须是资源id/中文描述/英文描述"
    assert result["files"][1]["valid"] is True


def test_preview_directory_reports_empty_directory(tmp_path: Path) -> None:
    result = preview_directory(tmp_path)

    assert result["valid"] is True
    assert result["file_count"] == 0
    assert result["total_rows"] == 0
    assert result["files"] == []


def test_default_resource_directory_is_fixed() -> None:
    assert DEFAULT_RESOURCE_DIR == Path(__file__).resolve().parents[1] / "local_run" / "resource_metrics"
