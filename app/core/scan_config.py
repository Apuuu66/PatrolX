"""扫描组配置加载与校验。

扫描组是命名后的 `source_patterns` 集合；规则只引用稳定组名，运行时仍展开为既有
`source_patterns` 契约。所有路径 pattern 必须面向 POSIX 相对路径，避免 Windows
反斜杠分隔符在运行环境间产生歧义。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from app.services.scanning import validate_patterns

_GROUP_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def validate_scan_groups(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    """校验扫描组配置并返回展开后的运行时 patterns。"""
    if not isinstance(payload, Mapping):
        raise ValueError("扫描配置必须是 YAML 对象")
    if set(payload) != {"version", "groups"}:
        raise ValueError("扫描配置只允许 version/groups 字段")
    if payload["version"] != 1:
        raise ValueError("扫描配置 version 必须为 1")
    groups = payload["groups"]
    if not isinstance(groups, Mapping):
        raise ValueError("扫描配置 groups 必须是对象")

    resolved: dict[str, list[str]] = {}
    for name, spec in groups.items():
        if not isinstance(name, str) or not _GROUP_NAME_RE.fullmatch(name):
            raise ValueError(f"扫描配置组名非法: {name!r}")
        if not isinstance(spec, Mapping):
            raise ValueError(f"扫描配置组 {name} 必须是对象")
        if set(spec) - {"description", "source_patterns"}:
            raise ValueError(f"扫描配置组 {name} 只允许 description/source_patterns")
        patterns = spec.get("source_patterns")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(f"扫描配置组 {name} 必须声明非空 source_patterns")
        if len(patterns) != len(set(patterns)):
            raise ValueError(f"扫描配置组 {name} 存在重复 source_patterns")
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise ValueError(f"扫描配置组 {name} 的 source_patterns 必须是字符串")
            if "\\\\" in pattern:
                raise ValueError(f"扫描配置组 {name} 的 source_patterns 必须使用 POSIX / 分隔符: {pattern}")
        try:
            validate_patterns([str(pattern) for pattern in patterns])
        except ValueError as exc:
            raise ValueError(f"扫描配置组 {name} 无效: {exc}") from exc
        resolved[name] = [str(pattern) for pattern in patterns]
    return resolved


def load_scan_groups(path: Path) -> dict[str, list[str]]:
    """读取并校验扫描组 YAML。"""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取扫描配置: {path}: {exc}") from exc
    try:
        return validate_scan_groups(payload)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
