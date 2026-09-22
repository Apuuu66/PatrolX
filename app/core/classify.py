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


def _match_pattern(name: str, pattern: str) -> bool:
    """同时兼容通配符与正则；非法正则按未命中处理。"""
    if fnmatch.fnmatch(name.lower(), pattern.lower()):
        return True
    try:
        return re.search(pattern, name, re.IGNORECASE) is not None
    except re.error:
        return False


def _match_name(name: str, rules: dict) -> RuleCategory | None:
    # 先按名称规律匹配，再按扩展名兜底；避免 alarm_*.csv 被通用 .csv 规则抢先分类。
    for cat in RuleCategory:
        if cat == RuleCategory.OTHER:
            continue
        spec = rules.get("category", {}).get(cat.value, {})
        if any(_match_pattern(name, str(pattern)) for pattern in spec.get("patterns", [])):
            return cat
    for cat in RuleCategory:
        if cat == RuleCategory.OTHER:
            continue
        spec = rules.get("category", {}).get(cat.value, {})
        if any(name.lower().endswith(ext) for ext in spec.get("extensions", [])):
            return cat
    return None


def classify_member(archive_name: str | None) -> RuleCategory | None:
    """按父压缩包归组规则识别成员类别；未配置归组时返回 None。"""
    if not archive_name:
        return None
    for rule in _load_rules().get("archive_members", []):
        pattern = str(rule.get("archive") or "")
        category_name = str(rule.get("category") or "")
        try:
            category = RuleCategory(category_name)
        except ValueError:
            continue
        if pattern and _match_pattern(archive_name, pattern):
            return category
    return None


def classify_name(name: str) -> RuleCategory | None:
    """按名称/扩展名分类（不修改文件名，保留原始包名用于追溯）。"""
    return _match_name(name, _load_rules())


def classify_content(path: Path) -> RuleCategory | None:
    """按内容嗅探分类；压缩包只查看内部成员文件名。"""
    if path.suffix.lower() in {".zip", ".tar", ".gz", ".tgz", ".tar.gz"}:
        members = peek_members(path, limit=20)
        for member in members:
            category = classify_name(Path(member).name)
            if category:
                return category
    return None
