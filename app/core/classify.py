"""按可配置规则表对文件/子包分类（名称规律 → 内容嗅探兜底）。"""

import fnmatch
import re
from pathlib import Path

import yaml

from app.core.archive import peek_members
from app.core.config import settings
from app.models.schemas import RuleCategory


def _load_rules() -> dict[str, dict]:
    path = settings.config / "classify_rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _match_name(name: str, rules: dict) -> RuleCategory | None:
    for cat in RuleCategory:
        if cat == RuleCategory.OTHER:
            continue
        spec = rules.get("category", {}).get(cat.value, {})
        for pattern in spec.get("patterns", []):
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                return cat
            try:
                if re.search(pattern, name, re.IGNORECASE):
                    return cat
            except re.error:
                continue
        if any(name.lower().endswith(ext) for ext in spec.get("extensions", [])):
            return cat
    return None


def classify_name(name: str) -> RuleCategory | None:
    """按名称/扩展名分类（不修改文件名，保留原始包名用于追溯）。"""
    rules = _load_rules()
    return _match_name(name, rules)


def classify_file(path: Path) -> RuleCategory | None:
    """名称分类失败时，按内容嗅探兜底（嵌套子包查看内部文件名）。"""
    cat = classify_name(path.name)
    if cat:
        return cat
    if path.suffix.lower() in {".zip", ".tar", ".gz", ".tgz", ".tar.gz"}:
        members = peek_members(path, limit=20)
        for member in members:
            cat = classify_name(Path(member).name)
            if cat:
                return cat
    return None


def final_category(name: str, path: Path) -> RuleCategory:
    cat = classify_name(name) or classify_file(path)
    return cat or RuleCategory.OTHER
