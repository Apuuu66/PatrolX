"""预制数据字典加载与维护。"""

from pathlib import Path

import yaml

from app.core.config import settings
from app.models.schemas import DictItem, DictsResponse


def _dict_path() -> Path:
    return settings.config / "dicts.yaml"


def load_dicts() -> DictsResponse:
    raw = yaml.safe_load(_dict_path().read_text(encoding="utf-8")) or {}
    return DictsResponse(
        **{
            name: [DictItem(**item) for item in raw.get(name, []) or []]
            for name in ("province", "operator", "product", "version")
        }
    )
