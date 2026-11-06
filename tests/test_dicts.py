"""预制数据字典加载测试。"""

import re
from pathlib import Path

import pytest

import app.core.dicts as dicts_module
from app.core.config import settings
from app.core.dicts import load_dicts, match_product


def test_dicts_loaded() -> None:
    dicts = load_dicts()
    for name in ("province", "operator", "product"):
        items = getattr(dicts, name)
        assert items, f"字典 {name} 为空"


def test_version_is_not_a_seed_dict() -> None:
    dicts = load_dicts()
    assert dicts.version == []


def test_dict_codes_safe() -> None:
    dicts = load_dicts()
    pattern = re.compile(r"^[a-z0-9_]+$")
    for name in ("province", "operator"):
        for item in getattr(dicts, name):
            assert pattern.match(item.code), f"{name}.{item.code} 不符合目录安全编码"
    product_pattern = re.compile(r"^[A-Z0-9_]+$")
    for item in dicts.product:
        assert product_pattern.match(item.code), f"product.{item.code} 不符合规范大写编码"


def test_province_dict_contains_all_provincial_regions() -> None:
    dicts = load_dicts()
    provinces = dicts.province
    assert len(provinces) >= 34
    codes = {item.code for item in provinces}
    names = {item.name for item in provinces}
    assert {"gd", "js", "zj", "sd", "sc", "bj", "sh", "cq", "nx", "xj", "xg", "am", "tw"} <= codes
    assert {"北京", "上海", "重庆", "内蒙", "广西", "西藏", "新疆", "香港", "澳门", "台湾"} <= names


def test_product_dict_codes_are_canonical_and_match_case_insensitively() -> None:
    dicts = load_dicts()
    assert [item.code for item in dicts.product] == ["UMF", "CSP"]
    assert {item.name for item in dicts.product} == {"UMF", "CSP"}
    for raw in ("UMF", "umf", " umf ", "CSP", "csp", " cSp "):
        matched = match_product(raw)
        assert matched is not None, raw
        assert matched.code == raw.strip().upper()


def test_match_product_rejects_unknown_value() -> None:
    assert match_product("MME") is None


def test_unchanged_dictionary_content_is_parsed_once_and_changes_are_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """字典文件未变化时复用解析结果，内容变化时不得返回旧缓存。"""
    config_file = tmp_path / "dicts.yaml"
    config_file.write_text(
        "# cache-behavior-test\nprovince: []\noperator: []\nproduct: [{code: UMF, name: UMF}]\nversion: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "config_dir", tmp_path)

    original_safe_load = dicts_module.yaml.safe_load
    parse_calls = 0

    def counted_safe_load(text: str) -> object:
        nonlocal parse_calls
        parse_calls += 1
        return original_safe_load(text)

    monkeypatch.setattr(dicts_module.yaml, "safe_load", counted_safe_load)

    assert load_dicts() == load_dicts()
    assert parse_calls == 1

    config_file.write_text(
        "# cache-behavior-test\nprovince: []\noperator: []\nproduct: [{code: CSP, name: CSP}]\nversion: []\n",
        encoding="utf-8",
    )

    assert [item.code for item in load_dicts().product] == ["CSP"]
    assert parse_calls == 2
