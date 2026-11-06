"""预制数据字典加载与维护。"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings
from app.models.schemas import DictItem, DictsResponse, Product


def _dict_path() -> Path:
    return settings.config / "dicts.yaml"


@lru_cache(maxsize=8)
def _parse_dicts(text: str) -> dict[str, Any]:
    """按原文缓存字典 YAML 解析结果，文件内容变化时自然失效。"""
    payload = yaml.safe_load(text)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("字典配置必须是 YAML 对象")
    return payload


def load_dicts() -> DictsResponse:
    raw = _parse_dicts(_dict_path().read_text(encoding="utf-8"))
    return DictsResponse(
        **{
            name: [DictItem(**item) for item in raw.get(name, []) or []]
            for name in ("province", "operator", "product", "version")
        }
    )


def match_product(value: str | None) -> DictItem | None:
    """按 trim + upper 语义匹配产品字典；非法值返回 None。"""
    if value is None:
        return None
    try:
        canonical = Product(value)
    except ValueError:
        return None
    return next((item for item in load_dicts().product if item.code == canonical.value), None)
