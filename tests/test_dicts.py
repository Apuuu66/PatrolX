"""预制数据字典加载测试。"""

import re

from app.core.dicts import load_dicts


def test_dicts_loaded() -> None:
    dicts = load_dicts()
    for name in ("province", "operator", "product", "version"):
        items = getattr(dicts, name)
        assert items, f"字典 {name} 为空"


def test_dict_codes_safe() -> None:
    dicts = load_dicts()
    pattern = re.compile(r"^[a-z0-9_]+$")
    for name in ("province", "operator", "product", "version"):
        for item in getattr(dicts, name):
            assert pattern.match(item.code), f"{name}.{item.code} 不符合目录安全编码"
