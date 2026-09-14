"""压缩项解压跳过与白名单策略的加载、校验和判定。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings


class ExtractPolicyError(Exception):
    """解压策略配置无效时抛出的统一业务错误。"""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """单个来源文件的策略判定结果。"""

    action: str
    reason: str
    scope: str | None = None
    keyword: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractPolicyConfig:
    """项目级解压策略配置。"""

    version: int = 1
    skip_all: bool = False
    skip_paths: tuple[str, ...] = ()
    whitelist_paths: tuple[str, ...] = ()
    whitelist_keywords: tuple[str, ...] = ()
    fingerprint: str = field(
        default_factory=lambda: policy_fingerprint(
            skip_all=False,
            skip_paths=(),
            whitelist_paths=(),
            whitelist_keywords=(),
        )
    )

    @property
    def snapshot(self) -> dict[str, object]:
        """生成写入 manifest 的策略快照。"""
        return {
            "fingerprint": self.fingerprint,
            "skip_all": self.skip_all,
            "skip_paths": list(self.skip_paths),
            "whitelist_paths": list(self.whitelist_paths),
            "whitelist_keywords": list(self.whitelist_keywords),
            "counters": {
                "skipped_subpackages": 0,
                "skipped_log_gz": 0,
                "whitelisted_subpackages": 0,
                "whitelisted_log_gz": 0,
                "whitelisted_files": 0,
            },
        }


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ExtractPolicyError(f"解压策略配置读取失败: {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExtractPolicyError("解压策略配置必须是对象")
    return value


def _only_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ExtractPolicyError(f"{label}包含未知键: {', '.join(unknown)}")


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExtractPolicyError(f"{label}必须是字符串数组")
    return value


def normalize_policy_path(value: str, label: str = "策略路径") -> str:
    """把 `/0/`、`0/`、`/0` 统一为 `0/` 并拒绝越界或歧义路径。"""
    if not isinstance(value, str) or not value:
        raise ExtractPolicyError(f"{label}不能为空")
    if "\x00" in value or "\\" in value:
        raise ExtractPolicyError(f"{label}包含非法字符: {value}")
    relative = value[1:] if value.startswith("/") else value
    if relative.endswith("/"):
        relative = relative[:-1]
    if not relative:
        raise ExtractPolicyError(f"{label}不能是根目录")
    segments = relative.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ExtractPolicyError(f"{label}包含空段或越界段: {value}")
    return "/".join(segments) + "/"


def policy_fingerprint(
    *,
    skip_all: bool,
    skip_paths: tuple[str, ...] | list[str],
    whitelist_paths: tuple[str, ...] | list[str],
    whitelist_keywords: tuple[str, ...] | list[str],
) -> str:
    """只按归一化策略字段计算稳定 SHA-256。"""
    payload = {
        "skip_all": skip_all,
        "skip_paths": list(skip_paths),
        "whitelist_paths": list(whitelist_paths),
        "whitelist_keywords": list(whitelist_keywords),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def load_extract_policy(path: Path | None = None) -> ExtractPolicyConfig:
    """加载项目级静态策略；缺失或空文件等价于 007 基线。"""
    config_path = path or settings.config / "extract_policy.yaml"
    raw = _load_mapping(config_path)
    _only_keys(raw, {"version", "nested", "whitelist"}, "解压策略配置")
    version = raw.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ExtractPolicyError(f"解压策略版本不支持: {version}")

    nested_raw = raw.get("nested", {})
    if not isinstance(nested_raw, dict):
        raise ExtractPolicyError("nested 必须是对象")
    _only_keys(nested_raw, {"skip_all", "skip_paths"}, "nested")
    skip_all = nested_raw.get("skip_all", False)
    if not isinstance(skip_all, bool):
        raise ExtractPolicyError("nested.skip_all 必须是布尔值")
    skip_path_items = _string_list(nested_raw.get("skip_paths", []), "nested.skip_paths")
    skip_paths = tuple(normalize_policy_path(item, "nested.skip_paths") for item in skip_path_items)

    whitelist_raw = raw.get("whitelist", {})
    if not isinstance(whitelist_raw, dict):
        raise ExtractPolicyError("whitelist 必须是对象")
    _only_keys(whitelist_raw, {"paths", "name_keywords"}, "whitelist")
    whitelist_path_items = _string_list(whitelist_raw.get("paths", []), "whitelist.paths")
    whitelist_paths = tuple(normalize_policy_path(item, "whitelist.paths") for item in whitelist_path_items)
    whitelist_keywords = tuple(
        item for item in _string_list(whitelist_raw.get("name_keywords", []), "whitelist.name_keywords")
    )
    if any(not item.strip() for item in whitelist_keywords):
        raise ExtractPolicyError("whitelist.name_keywords 不能为空")

    unique_scopes = (
        (skip_paths, "nested.skip_paths"),
        (whitelist_paths, "whitelist.paths"),
        (whitelist_keywords, "whitelist.name_keywords"),
    )
    for values, label in unique_scopes:
        if len(values) != len(set(values)):
            raise ExtractPolicyError(f"{label}存在重复值")
    duplicated_scopes = set(skip_paths) & set(whitelist_paths)
    if duplicated_scopes:
        raise ExtractPolicyError(f"跳过与白名单路径存在重复作用域: {', '.join(sorted(duplicated_scopes))}")

    fingerprint = policy_fingerprint(
        skip_all=skip_all,
        skip_paths=skip_paths,
        whitelist_paths=whitelist_paths,
        whitelist_keywords=whitelist_keywords,
    )
    return ExtractPolicyConfig(
        version=version,
        skip_all=skip_all,
        skip_paths=skip_paths,
        whitelist_paths=whitelist_paths,
        whitelist_keywords=whitelist_keywords,
        fingerprint=fingerprint,
    )


def evaluate_extract_policy(
    policy: ExtractPolicyConfig,
    source_relative: str,
    *,
    is_compressed: bool = False,
) -> PolicyDecision | None:
    """按白名单优先原则判定主包内来源文件。"""
    normalized = source_relative.strip("/")
    for scope in policy.whitelist_paths:
        if normalized.startswith(scope):
            return PolicyDecision("whitelist", "whitelist_path", scope=scope)
    segments = normalized.split("/")
    for keyword in policy.whitelist_keywords:
        if any(keyword.lower() in segment.lower() for segment in segments):
            return PolicyDecision("whitelist", "whitelist_keyword", keyword=keyword)
    if not is_compressed:
        return None
    if policy.skip_all:
        return PolicyDecision("skip", "global_retain")
    for scope in policy.skip_paths:
        scope_segments = scope.rstrip("/").split("/")
        path_segments = normalized.split("/")
        for i in range(len(path_segments) - len(scope_segments) + 1):
            if path_segments[i : i + len(scope_segments)] == scope_segments:
                return PolicyDecision("skip", "skip_path", scope=scope)
    return None


def policy_manifest_snapshot(policy: ExtractPolicyConfig) -> dict[str, object]:
    """返回 manifest 使用的完整策略节。"""
    return policy.snapshot
