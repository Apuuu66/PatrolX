"""规则私有预处理路径、缓存 marker 与 source_patterns 匹配 helper。"""

import inspect
import re
from pathlib import Path
from typing import Protocol

from app.core.checksum import sha256_file
from app.inspectors.base import Inspector


class PrepareContext(Protocol):
    """prepare helper 需要的最小任务上下文契约。"""

    task_id: str
    prepared_dir: Path


MARKER_NAME = ".prepare.sha256"


def prepared_dir(ctx: PrepareContext, owner_code: str) -> Path:
    """返回 owner 私有 prepared 目录，禁止 owner code 引入路径穿越。"""
    if not owner_code or Path(owner_code).name != owner_code or owner_code in {".", ".."}:
        raise ValueError(f"非法 prepared owner 目录: {owner_code}")
    return ctx.prepared_dir / owner_code


def marker_path(ctx: PrepareContext, owner_code: str) -> Path:
    """返回 owner 私有 prepare 的缓存 marker。"""
    return prepared_dir(ctx, owner_code) / MARKER_NAME


def rule_python_path(rule: Inspector) -> Path:
    """解析当前 owner 规则所在 Python 文件。"""
    run = rule.run
    module_file = getattr(getattr(run, "__globals__", None), "get", None)
    if module_file is not None:
        value = module_file("__file__", None)
        if value:
            return Path(value).resolve()
    try:
        return Path(inspect.getsourcefile(run) or "").resolve()
    except TypeError as exc:
        raise ValueError(f"规则 {rule.code} 无法解析 Python 文件") from exc


def rule_file_sha256(rule: Inspector) -> str:
    """计算当前规则 Python 文件的 SHA-256。"""
    return sha256_file(rule_python_path(rule))


def match_relative_files(data_dir: Path, patterns: list[str]) -> list[Path]:
    """以 re.fullmatch 匹配任务内 POSIX 相对路径，并防御路径越界。"""
    root = data_dir.resolve()
    traversal = next(
        (pattern for pattern in patterns if ".." in pattern or r"\.\." in pattern),
        None,
    )
    if traversal is not None:
        raise ValueError(f"source_patterns 禁止路径穿越: {traversal}")
    matched: set[Path] = set()
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root)
        posix_relative = relative.as_posix()
        if ".." in relative.parts:
            raise ValueError(f"匹配路径越界: {posix_relative}")
        if any(re.fullmatch(pattern, posix_relative) for pattern in patterns):
            matched.add(Path(relative))
    return sorted(matched, key=lambda path: path.as_posix())
