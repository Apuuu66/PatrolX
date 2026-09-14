"""`source_patterns[]` 的运行时防御校验与完整匹配。"""

import re
from pathlib import Path

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:(?:\\|/)")


def validate_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """校验 pattern 并返回编译结果；非法输入立即拒绝。"""
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern or pattern.strip() != pattern:
            raise ValueError(f"source_patterns 存在非法正则: {pattern!r}")
        if pattern.startswith(("/", "\\")) or pattern.startswith("~") or _WINDOWS_ABSOLUTE.match(pattern):
            raise ValueError(f"source_patterns 禁止绝对路径: {pattern}")
        if ".." in pattern or r"\.\." in pattern:
            raise ValueError(f"source_patterns 禁止路径穿越: {pattern}")
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"source_patterns 存在非法正则: {pattern}") from exc
    return compiled


def match_paths(paths: list[Path] | tuple[Path, ...], patterns: list[str]) -> list[Path]:
    """对已归一化相对路径执行 `re.fullmatch()`，返回稳定排序集合。"""
    compiled = validate_patterns(patterns)
    matched: set[Path] = set()
    for relative in paths:
        posix_relative = relative.as_posix()
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"匹配路径越界: {posix_relative}")
        if any(pattern.fullmatch(posix_relative) for pattern in compiled):
            matched.add(relative)
    return sorted(matched, key=lambda path: path.as_posix())
