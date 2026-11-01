"""预制数据字典加载测试。"""

import re

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
