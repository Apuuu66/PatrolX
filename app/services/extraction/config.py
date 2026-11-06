"""分类配置读取、严格校验、规范化与语义指纹。"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings

CLASSIFICATION_CONFIG_CODE = "invalid_classification_config"
CONFIG_VERSION = 1
PROFILE_KEYS = frozenset({"UMF", "CSP", "GENERIC"})
PHASES = frozenset({"alarm", "precise", "ignore", "fallback"})
ACTIONS = frozenset(
    {
        "copy",
        "expand",
        "decompress",
        "expand_recursive",
        "select_and_decompress",
        "ignore",
        "fallback",
    }
)
CATEGORIES = frozenset({"config", "status", "operation", "kpi", "alarm", "log", "chr", "other"})
TARGET_ROOTS = frozenset(
    {
        "alarm",
        "basic",
        "chr",
        "config",
        "debug",
        "host-debug",
        "host-system",
        "kpi",
        "logs",
        "mml",
        "operation-log",
        "other",
        "resource",
        "status",
        "traffic",
    }
)
EXPAND_ACTIONS = frozenset({"expand", "expand_recursive"})
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1


class ClassificationConfigError(ValueError):
    """分类配置错误；code/path/route_id 是稳定错误契约。"""

    code = CLASSIFICATION_CONFIG_CODE

    def __init__(
        self,
        message: str,
        path: str = "",
        route_id: str | None = None,
        *,
        conflict_routes: tuple[str, str] | None = None,
        phase: str | None = None,
        priority: int | None = None,
        profile_intersection: tuple[str, ...] | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.route_id = route_id
        self.conflict_routes = conflict_routes
        self.phase = phase
        self.priority = priority
        self.profile_intersection = profile_intersection
        super().__init__(message)

    def to_detail(self) -> dict[str, Any]:
        """返回可写入任务错误详情的结构化对象。"""
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "route_id": self.route_id,
            "conflict_routes": self.conflict_routes,
            "phase": self.phase,
            "priority": self.priority,
            "profile_intersection": self.profile_intersection,
        }


@dataclass(frozen=True, slots=True)
class Profile:
    """场景 anchor 配置；保留配置原始大小写用于发布记录。"""

    key: str
    scene_anchors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourcePattern:
    """route 的来源范围、目录和文件模式。"""

    scope: str
    directory: str
    file: str
    capture_root: str | None


@dataclass(frozen=True, slots=True)
class SelectionInclude:
    """归档成员选择 include 规则。"""

    pattern: str
    service: str | None


@dataclass(frozen=True, slots=True)
class SelectionExclude:
    """归档成员选择 exclude 规则。"""

    pattern: str
    reason: str


@dataclass(frozen=True, slots=True)
class Selection:
    """归档成员选择规则集合。"""

    include: tuple[SelectionInclude, ...]
    exclude: tuple[SelectionExclude, ...]


@dataclass(frozen=True, slots=True)
class Route:
    """一条从来源模式到目标模板的分类路线。"""

    id: str
    phase: str
    priority: int
    profiles: tuple[str, ...]
    source: SourcePattern
    action: str
    category: str | None
    target: str | None
    selection: Selection | None
    member_decompress: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassificationConfig:
    """完整且已通过校验的分类配置。"""

    version: int
    profiles: dict[str, Profile]
    routes: tuple[Route, ...]
    fingerprint: str


class _UniqueKeyLoader(yaml.SafeLoader):
    """拒绝嵌套 mapping 中重复 key 的 YAML loader。"""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    *,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "YAML mapping key 必须是字符串",
                key_node.start_mark,
            )
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"发现重复 YAML key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(_value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _config_error(
    message: str,
    path: str = "",
    route_id: str | None = None,
    **detail: object,
) -> ClassificationConfigError:
    return ClassificationConfigError(message, path, route_id, **detail)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _normalized_enum(value: object) -> str | None:
    """把字符串 enum 规范化为小写；非字符串返回 None。"""
    if not isinstance(value, str):
        return None
    return value.strip().lower()


def _reject_forbidden_chars(value: str, *, wildcard: bool = False) -> None:
    if "\x00" in value or "\\" in value:
        raise ValueError("路径包含 NUL 或反斜杠")
    if wildcard and "/" in value:
        raise ValueError("文件名不能包含 /")


def validate_literal_segment(segment: str) -> str:
    """校验单个 literal 目录段并返回 strip 后的值。"""
    value = segment.strip()
    if not value or value in {".", ".."}:
        raise ValueError("目录段为空或是保留段")
    forbidden = {"/", "*", "?", "\x00", "\\"}
    if any(char in value for char in forbidden):
        raise ValueError("目录段包含通配符或非法字符")
    return value


def validate_glob_file_name(value: object) -> str:
    """校验单个文件名 glob。"""
    if not isinstance(value, str):
        raise ValueError("文件名 glob 必须是字符串")
    text = value.strip()
    if not text or text in {".", ".."} or "/" in text:
        raise ValueError("文件名不能为空、保留段或包含 /")
    if any(char in text for char in ("\x00", "\\")):
        raise ValueError("文件名包含 NUL 或反斜杠")
    return text


def validate_directory_pattern(value: object) -> tuple[str, tuple[str, ...]]:
    """校验目录模式，返回原始 strip 值和规范化段。"""
    if not isinstance(value, str):
        raise ValueError("directory 必须是字符串")
    text = value.strip()
    if not text:
        raise ValueError("directory 不能为空")
    if text.startswith("/") or text.endswith("/"):
        raise ValueError("directory 不得以 / 开头或结尾")
    if "\x00" in text or "\\" in text:
        raise ValueError("directory 包含 NUL 或反斜杠")
    segments = tuple(segment.strip() for segment in text.split("/"))
    if any(not segment for segment in segments):
        raise ValueError("directory 包含空段")
    for segment in segments:
        if segment in {".", ".."}:
            raise ValueError("directory 包含保留段")
        if segment != "**" and any(char in segment for char in ("*", "?")):
            raise ValueError("通配符只能使用完整目录段 **")
    return text, tuple(segment.upper() for segment in segments)


def validate_member_pattern(value: object) -> tuple[str, tuple[str, ...]]:
    """校验归档成员 glob，允许完整段 ** 和最后一段文件 glob。"""
    if not isinstance(value, str):
        raise ValueError("成员 pattern 必须是字符串")
    text = value.strip()
    if not text or text.startswith("/") or text.endswith("/"):
        raise ValueError("成员 pattern 不能为空或以 / 开头/结尾")
    if "\x00" in text or "\\" in text:
        raise ValueError("成员 pattern 包含 NUL 或反斜杠")
    raw_segments = [segment.strip() for segment in text.split("/")]
    if any(not segment or segment in {".", ".."} for segment in raw_segments):
        raise ValueError("成员 pattern 包含空段或保留段")
    for segment in raw_segments[:-1]:
        if segment != "**":
            validate_literal_segment(segment)
    validate_glob_file_name(raw_segments[-1])
    return text, tuple(segment.upper() for segment in raw_segments)


def _parse_source(payload: object, route_path: str, route_id: str) -> SourcePattern:
    if not isinstance(payload, Mapping):
        raise _config_error("source 必须是对象", f"{route_path}.source", route_id)
    allowed = {"scope", "directory", "file", "capture_root"}
    unknown = set(payload) - allowed
    if unknown:
        raise _config_error(
            f"source 存在未知字段: {sorted(unknown)}",
            f"{route_path}.source",
            route_id,
        )
    missing = {"scope", "directory", "file"} - set(payload)
    if missing:
        raise _config_error(
            f"source 缺少字段: {sorted(missing)}",
            f"{route_path}.source",
            route_id,
        )
    scope = _normalized_enum(payload["scope"])
    if scope not in {"scene", "evidence"}:
        raise _config_error("未知 scope", f"{route_path}.source.scope", route_id)
    try:
        directory, _segments = validate_directory_pattern(payload["directory"])
    except ValueError as exc:
        raise _config_error(str(exc), f"{route_path}.source.directory", route_id) from exc
    try:
        file_name = validate_glob_file_name(payload["file"])
    except ValueError as exc:
        raise _config_error(str(exc), f"{route_path}.source.file", route_id) from exc
    capture_root = payload.get("capture_root")
    if capture_root is not None:
        if not isinstance(capture_root, str):
            raise _config_error("capture_root 必须是字符串", f"{route_path}.source.capture_root", route_id)
        try:
            capture_root = validate_literal_segment(capture_root)
        except ValueError as exc:
            raise _config_error(str(exc), f"{route_path}.source.capture_root", route_id) from exc
    return SourcePattern(
        scope=str(scope),
        directory=directory,
        file=file_name,
        capture_root=capture_root,
    )


def _parse_selection(
    payload: object,
    route_path: str,
    target: str | None,
    route_id: str | None,
) -> Selection:
    if not isinstance(payload, Mapping):
        raise _config_error("selection 必须是对象", f"{route_path}.selection", route_id)
    allowed = {"include", "exclude"}
    if set(payload) != allowed:
        raise _config_error("selection 键必须严格为 include/exclude", f"{route_path}.selection", route_id)
    includes = payload["include"]
    excludes = payload.get("exclude", [])
    if not isinstance(includes, list) or not includes:
        raise _config_error(
            "selection.include 必须是非空列表",
            f"{route_path}.selection.include",
            route_id,
        )
    if not isinstance(excludes, list):
        raise _config_error("selection.exclude 必须是列表", f"{route_path}.selection.exclude", route_id)

    parsed_include: list[SelectionInclude] = []
    for index, item in enumerate(includes):
        if not isinstance(item, Mapping):
            raise _config_error(
                "include 项必须是对象",
                f"{route_path}.selection.include[{index}]",
                route_id,
            )
        if set(item) - {"pattern", "service"} or "pattern" not in item:
            raise _config_error(
                "include 项键必须严格为 pattern/service",
                f"{route_path}.selection.include[{index}]",
                route_id,
            )
        try:
            pattern, _segments = validate_member_pattern(item["pattern"])
        except ValueError as exc:
            raise _config_error(
                str(exc),
                f"{route_path}.selection.include[{index}].pattern",
                route_id,
            ) from exc
        service = item.get("service")
        if service is not None:
            if not isinstance(service, str) or not service.strip():
                raise _config_error(
                    "service 必须是非空字符串",
                    f"{route_path}.selection.include[{index}].service",
                    route_id,
                )
            service = service.strip().upper()
        parsed_include.append(SelectionInclude(pattern=pattern, service=service))

    parsed_exclude: list[SelectionExclude] = []
    for index, item in enumerate(excludes):
        if not isinstance(item, Mapping):
            raise _config_error(
                "exclude 项必须是对象",
                f"{route_path}.selection.exclude[{index}]",
                route_id,
            )
        if set(item) != {"pattern", "reason"}:
            raise _config_error(
                "exclude 项键必须严格为 pattern/reason",
                f"{route_path}.selection.exclude[{index}]",
                route_id,
            )
        try:
            pattern, _segments = validate_member_pattern(item["pattern"])
        except ValueError as exc:
            raise _config_error(
                str(exc),
                f"{route_path}.selection.exclude[{index}].pattern",
                route_id,
            ) from exc
        reason = item["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise _config_error(
                "reason 必须是非空字符串",
                f"{route_path}.selection.exclude[{index}].reason",
                route_id,
            )
        parsed_exclude.append(SelectionExclude(pattern=pattern, reason=reason.strip()))

    _validate_selection_services(parsed_include, route_path, route_id)

    if target is not None and "{service}" in target and any(item.service is None for item in parsed_include):
        raise _config_error(
            "include 未声明 service 时 target 不能使用 {service}",
            f"{route_path}.target",
            route_id,
        )
    return Selection(include=tuple(parsed_include), exclude=tuple(parsed_exclude))


def _target_variables(target: str) -> set[str]:
    variables: set[str] = set()
    cursor = 0
    while cursor < len(target):
        char = target[cursor]
        if char == "}":
            raise ValueError("目标变量存在多余 }")
        if char != "{":
            cursor += 1
            continue
        end = target.find("}", cursor + 1)
        if end < 0:
            raise ValueError("目标变量未闭合")
        name = target[cursor + 1 : end]
        if not name:
            raise ValueError("目标变量为空")
        if "{" in name:
            raise ValueError("目标变量不得嵌套")
        variables.add(name)
        cursor = end + 1
    return variables


def _validate_target_template(
    target: object,
    action: str,
    route_path: str,
    route_id: str,
) -> str:
    def target_error(message: str, path: str) -> ClassificationConfigError:
        return _config_error(message, path, route_id)

    if not isinstance(target, str):
        raise target_error("target 必须是字符串", f"{route_path}.target")
    value = target.strip()
    if not value or value.startswith("/"):
        raise target_error("目标路径不能为空或是绝对路径", f"{route_path}.target")
    if "\x00" in value or "\\" in value:
        raise target_error("目标路径包含 NUL 或反斜杠", f"{route_path}.target")
    segments = value.split("/")
    if any(segment == "" or segment in {".", ".."} for segment in segments):
        raise target_error("目标路径非法：包含空段、. 或 ..", f"{route_path}.target")
    try:
        variables = _target_variables(value)
    except ValueError as exc:
        raise target_error(str(exc), f"{route_path}.target") from exc
    unknown = variables - {
        "suffix",
        "member",
        "archive_stem",
        "service",
        "node_path",
        "name_without_gz",
    }
    if unknown:
        raise target_error(f"未知目标变量: {sorted(unknown)}", f"{route_path}.target")

    first_segment = segments[0]
    if "{" in first_segment or first_segment not in TARGET_ROOTS:
        raise target_error(
            f"目标首段不在 allowlist: {first_segment}",
            f"{route_path}.target",
        )

    allowed_by_action: dict[str, set[str]] = {
        "copy": {"suffix"},
        "fallback": {"suffix"},
        "decompress": {"suffix", "name_without_gz"},
        "expand": {"member", "archive_stem"},
        "expand_recursive": {"member", "archive_stem"},
        "select_and_decompress": {
            "member",
            "service",
            "node_path",
            "name_without_gz",
        },
    }
    unsupported = variables - allowed_by_action[action]
    if unsupported:
        raise target_error(
            f"动作 {action} 不支持目标变量: {sorted(unsupported)}",
            f"{route_path}.target",
        )
    return value


def _directory_segments(directory: str) -> tuple[str, ...]:
    """返回已 strip 并大写的目录段。"""
    return tuple(segment.strip().upper() for segment in directory.strip().split("/"))


def _is_catch_all_file_pattern(pattern: str) -> bool:
    """判断文件名 glob 是否覆盖所有非空文件名。"""
    normalized = pattern.strip()
    return (
        bool(normalized)
        and all(char in {"*", "?"} for char in normalized)
        and "*" in normalized
        and normalized.count("?") <= 1
    )


def _is_catch_all_source(source: SourcePattern) -> bool:
    """判断 source 是否无前置条件地覆盖 scope 内全部普通文件。"""
    segments = _directory_segments(source.directory)
    return (
        source.capture_root is None
        and bool(segments)
        and all(segment == "**" for segment in segments)
        and _is_catch_all_file_pattern(source.file)
    )


def _parse_route(payload: object, index: int) -> Route:
    route_path = f"routes[{index}]"
    if not isinstance(payload, Mapping):
        raise _config_error("route 必须是对象", route_path)

    preliminary_id = payload.get("id")
    detail_route_id = preliminary_id if isinstance(preliminary_id, str) else None
    base_keys = {
        "id",
        "phase",
        "priority",
        "profiles",
        "source",
        "action",
        "category",
        "target",
    }
    missing = base_keys - set(payload)
    if missing:
        raise _config_error(f"route 缺少基础字段: {sorted(missing)}", route_path, detail_route_id)
    action = _normalized_enum(payload.get("action"))
    if action not in ACTIONS:
        raise _config_error(
            f"未知动作: {action}",
            f"{route_path}.action",
            detail_route_id,
        )

    allowed = set(base_keys)
    if action in EXPAND_ACTIONS:
        allowed.add("member_decompress")
    if action == "select_and_decompress":
        allowed.add("selection")
    unknown = set(payload) - allowed
    if unknown:
        raise _config_error(f"route 存在未知字段: {sorted(unknown)}", route_path, detail_route_id)

    route_id = payload.get("id")
    if (
        not isinstance(route_id, str)
        or not route_id
        or len(route_id) > 128
        or not all(char.isascii() and (char.islower() or char.isdigit() or char in "._-") for char in route_id)
    ):
        raise _config_error("route id 非法", f"{route_path}.id")
    phase = _normalized_enum(payload.get("phase"))
    if phase not in PHASES:
        raise _config_error(f"未知 phase: {phase}", f"{route_path}.phase", route_id)
    priority = payload.get("priority")
    if not _is_int(priority) or not INT32_MIN <= int(priority) <= INT32_MAX:
        raise _config_error("priority 必须是 32 位有符号整数", f"{route_path}.priority", route_id)
    profiles_payload = payload.get("profiles")
    if not isinstance(profiles_payload, list) or not profiles_payload:
        raise _config_error("profiles 必须是非空列表", f"{route_path}.profiles", route_id)
    profiles: set[str] = set()
    for profile_index, item in enumerate(profiles_payload):
        if not isinstance(item, str) or item.strip().upper() not in PROFILE_KEYS:
            raise _config_error(
                f"未知 profile: {item}",
                f"{route_path}.profiles[{profile_index}]",
                route_id,
            )
        profiles.add(item.strip().upper())
    if "GENERIC" in profiles and (profiles & {"UMF", "CSP"}):
        raise _config_error("GENERIC 不得与 UMF/CSP 混用", f"{route_path}.profiles", route_id)
    if phase == "alarm" and profiles != {"UMF", "CSP"}:
        raise _config_error("告警 route 的 profiles 必须为 [UMF, CSP]", f"{route_path}.profiles", route_id)

    source = _parse_source(payload.get("source"), route_path, route_id)
    category_payload = payload["category"]
    if category_payload is not None and not isinstance(category_payload, str):
        raise _config_error("category 必须是字符串或 null", f"{route_path}.category", route_id)
    category = _normalized_enum(category_payload)
    target = payload.get("target")
    if action == "ignore":
        if category is not None:
            raise _config_error("ignore route 的 category 必须为 null", f"{route_path}.category", route_id)
        if target is not None:
            raise _config_error("ignore route 的 target 必须为 null", f"{route_path}.target", route_id)
        target_value = None
    else:
        if category not in CATEGORIES:
            raise _config_error(f"非法业务分类: {category}", f"{route_path}.category", route_id)
        target_value = _validate_target_template(target, action, route_path, route_id)
    if action == "fallback" and not _is_catch_all_source(source):
        raise _config_error(
            "fallback route 必须覆盖全部路径且不得声明 capture_root",
            f"{route_path}.source",
            route_id,
        )
    if phase == "alarm":
        if action != "expand_recursive":
            raise _config_error("告警 route 必须使用 expand_recursive", f"{route_path}.action", route_id)
        if source.capture_root not in {"Alarm Information", "Alarm Data"}:
            raise _config_error("告警 route 的 capture_root 非法", f"{route_path}.source.capture_root", route_id)
        if source.capture_root.upper() not in {segment.upper() for segment in source.directory.split("/") if segment}:
            raise _config_error(
                "告警 capture_root 必须位于 directory pattern",
                f"{route_path}.source.directory",
                route_id,
            )

    selection = None
    if action == "select_and_decompress":
        if "selection" not in payload:
            raise _config_error("select_and_decompress 必须声明 selection", f"{route_path}.selection", route_id)
        selection = _parse_selection(payload["selection"], route_path, target_value, route_id)

    member_decompress: tuple[str, ...] = ()
    if action in EXPAND_ACTIONS and "member_decompress" in payload:
        value = payload["member_decompress"]
        if not isinstance(value, list):
            raise _config_error("member_decompress 必须是列表", f"{route_path}.member_decompress", route_id)
        patterns: dict[str, str] = {}
        for item in value:
            try:
                pattern, _segments = validate_member_pattern(item)
            except ValueError as exc:
                raise _config_error(str(exc), f"{route_path}.member_decompress", route_id) from exc
            patterns.setdefault(pattern.upper(), pattern)
        member_decompress = tuple(sorted(patterns.values()))

    return Route(
        id=route_id,
        phase=str(phase),
        priority=int(priority),
        profiles=tuple(sorted(profiles)),
        source=source,
        action=str(action),
        category=None if category is None else str(category),
        target=target_value,
        selection=selection,
        member_decompress=member_decompress,
    )


def _validate_profiles(payload: object) -> dict[str, Profile]:
    if not isinstance(payload, Mapping):
        raise _config_error("profiles 必须是对象", "profiles")
    normalized_keys: dict[str, str] = {}
    for key in payload:
        if not isinstance(key, str):
            raise _config_error("profile key 必须是字符串", "profiles")
        normalized = key.strip().upper()
        if normalized in normalized_keys:
            raise _config_error("profile key 重复", "profiles")
        normalized_keys[normalized] = key
    missing = PROFILE_KEYS - set(normalized_keys)
    unknown = set(normalized_keys) - PROFILE_KEYS
    if missing or unknown:
        raise _config_error(
            f"profile 必须严格声明 {sorted(PROFILE_KEYS)}",
            "profiles",
        )
    result: dict[str, Profile] = {}
    for normalized_key, original_key in normalized_keys.items():
        item = payload[original_key]
        if not isinstance(item, Mapping) or set(item) != {"scene_anchors"}:
            raise _config_error(
                "profile 对象键必须严格为 scene_anchors",
                f"profiles.{normalized_key}",
            )
        anchors_payload = item["scene_anchors"]
        if not isinstance(anchors_payload, list):
            raise _config_error("scene_anchors 必须是列表", f"profiles.{normalized_key}")
        if normalized_key != "GENERIC" and not anchors_payload:
            raise _config_error("scene_anchors 必须是非空列表", f"profiles.{normalized_key}")
        anchors: set[str] = set()
        for anchor in anchors_payload:
            if not isinstance(anchor, str):
                raise _config_error("anchor 必须是字符串", f"profiles.{normalized_key}")
            try:
                value = validate_literal_segment(anchor)
            except ValueError as exc:
                raise _config_error(str(exc), f"profiles.{normalized_key}") from exc
            anchors.add(value)
        result[normalized_key] = Profile(
            key=normalized_key,
            scene_anchors=tuple(sorted(anchors)),
        )
    return result


def _validate_reachable_defaults(profiles: dict[str, Profile], routes: tuple[Route, ...]) -> None:
    """确认每个 profile 存在可覆盖全部路径的 fallback 或 catch-all ignore。"""
    covered: set[str] = set()
    for route in routes:
        if route.phase not in {"ignore", "fallback"}:
            continue
        if not _is_catch_all_source(route.source):
            continue
        if route.action == "ignore":
            covered.update(route.profiles)
        elif route.phase == "fallback" and route.action in {"fallback", "copy"}:
            covered.update(route.profiles)
    for profile in profiles:
        if profile not in covered:
            raise _config_error(
                f"profile {profile} 默认行为不可达",
                f"profiles.{profile}",
            )


@dataclass(frozen=True, slots=True)
class _Symbol:
    """ε-NFA 输入符号；kind 区分目录段与文件字符。"""

    kind: str
    value: str


@dataclass(slots=True)
class _PatternNFA:
    """目录段与文件 glob 共用的 ε-NFA。"""

    start: int
    accept: int
    epsilon: list[set[int]] = field(default_factory=list)
    transitions: list[dict[_Symbol, set[int]]] = field(default_factory=list)

    def state(self) -> int:
        """分配一个 NFA 状态。"""
        state = len(self.epsilon)
        self.epsilon.append(set())
        self.transitions.append({})
        return state

    def add_epsilon(self, source: int, target: int) -> None:
        """添加 ε 边。"""
        self.epsilon[source].add(target)

    def add_symbol(self, source: int, symbol: _Symbol, target: int) -> None:
        """添加普通符号边。"""
        self.transitions[source].setdefault(symbol, set()).add(target)


def _directory_symbols(routes: tuple[Route, ...]) -> set[_Symbol]:
    """收集全部目录 literal scalar；OTHER 在校验时单独补入。"""
    symbols: set[_Symbol] = set()
    for route in routes:
        for segment in _directory_segments(route.source.directory):
            if segment != "**":
                symbols.add(_Symbol("directory", segment))
    return symbols


def _file_symbols(routes: tuple[Route, ...]) -> set[_Symbol]:
    """收集全部文件 literal scalar；通配符可匹配这些字符与 OTHER。"""
    symbols: set[_Symbol] = set()
    for route in routes:
        for char in route.source.file.strip().upper():
            if char not in {"*", "?"}:
                symbols.add(_Symbol("file", char))
    return symbols


def _append_double_star(
    nfa: _PatternNFA,
    cursor: int,
    symbols: set[_Symbol],
) -> int:
    """编译目录段 `**`：匹配零到任意多个完整目录段。"""
    after = nfa.state()
    loop = nfa.state()
    nfa.add_epsilon(cursor, after)
    nfa.add_epsilon(cursor, loop)
    for symbol in symbols:
        nfa.add_symbol(loop, symbol, loop)
    nfa.add_epsilon(loop, after)
    return after


def _append_file_pattern(
    nfa: _PatternNFA,
    cursor: int,
    pattern: str,
    symbols: set[_Symbol],
) -> int:
    """编译单文件 glob；`*` 不跨越目录段，`?` 匹配一个字符。"""
    for char in pattern:
        if char == "*":
            after = nfa.state()
            loop = nfa.state()
            nfa.add_epsilon(cursor, after)
            nfa.add_epsilon(cursor, loop)
            for symbol in symbols:
                nfa.add_symbol(loop, symbol, loop)
            nfa.add_epsilon(loop, after)
            cursor = after
        else:
            target = nfa.state()
            if char == "?":
                for symbol in symbols:
                    nfa.add_symbol(cursor, symbol, target)
            else:
                nfa.add_symbol(cursor, _Symbol("file", char), target)
            cursor = target
    return cursor


def _compile_route_pattern(
    route: Route,
    directory_symbols: set[_Symbol],
    file_symbols: set[_Symbol],
) -> _PatternNFA:
    """将一条 route 的 source pattern 编译到同一个 ε-NFA。"""
    nfa = _PatternNFA(start=0, accept=0)
    nfa.state()
    cursor = nfa.start
    segments = [segment.strip().upper() for segment in route.source.directory.strip().split("/")]
    if route.source.scope == "scene":
        cursor = _append_double_star(nfa, cursor, directory_symbols)
    for segment in segments:
        if segment == "**":
            cursor = _append_double_star(nfa, cursor, directory_symbols)
        else:
            target = nfa.state()
            nfa.add_symbol(cursor, _Symbol("directory", segment), target)
            cursor = target
    cursor = _append_file_pattern(
        nfa,
        cursor,
        route.source.file.strip().upper(),
        file_symbols,
    )
    nfa.accept = cursor
    return nfa


def _epsilon_closure(nfa: _PatternNFA, states: frozenset[int]) -> frozenset[int]:
    """计算一组状态的 ε-closure。"""
    result = set(states)
    stack = list(states)
    while stack:
        state = stack.pop()
        for target in nfa.epsilon[state]:
            if target not in result:
                result.add(target)
                stack.append(target)
    return frozenset(result)


def _member_pattern_symbols(patterns: tuple[str, ...]) -> tuple[set[_Symbol], set[_Symbol]]:
    """收集成员路径中的目录与文件字符符号，并补充 OTHER 等价类。"""
    directory_symbols: set[_Symbol] = {_Symbol("directory", "OTHER")}
    file_symbols: set[_Symbol] = {_Symbol("file", "OTHER")}
    for pattern in patterns:
        segments = [segment.strip().upper() for segment in pattern.strip().split("/")]
        for segment in segments[:-1]:
            if segment != "**":
                directory_symbols.add(_Symbol("directory", segment))
        for char in segments[-1]:
            if char not in {"*", "?"}:
                file_symbols.add(_Symbol("file", char))
    return directory_symbols, file_symbols


def _compile_member_pattern(
    pattern: str,
    directory_symbols: set[_Symbol],
    file_symbols: set[_Symbol],
) -> _PatternNFA:
    """将归档成员完整路径 pattern 编译为 ε-NFA。"""
    nfa = _PatternNFA(start=0, accept=0)
    nfa.state()
    cursor = nfa.start
    segments = [segment.strip().upper() for segment in pattern.strip().split("/")]
    for segment in segments[:-1]:
        if segment == "**":
            cursor = _append_double_star(nfa, cursor, directory_symbols)
        else:
            target = nfa.state()
            nfa.add_symbol(cursor, _Symbol("directory", segment), target)
            cursor = target
    nfa.accept = _append_file_pattern(nfa, cursor, segments[-1], file_symbols)
    return nfa


def _product_nfa_overlap(left_nfa: _PatternNFA, right_nfa: _PatternNFA) -> bool:
    """对两份 ε-NFA 的 closure 状态对做广度优先乘积搜索。"""
    left_start = _epsilon_closure(left_nfa, frozenset({left_nfa.start}))
    right_start = _epsilon_closure(right_nfa, frozenset({right_nfa.start}))
    pending = {(left_start, right_start)}
    visited: set[tuple[frozenset[int], frozenset[int]]] = set()

    while pending:
        left_states, right_states = pending.pop()
        if left_nfa.accept in left_states and right_nfa.accept in right_states:
            return True
        visited.add((left_states, right_states))
        symbols: set[_Symbol] = set()
        for state in left_states:
            symbols.update(left_nfa.transitions[state])
        for state in right_states:
            symbols.update(right_nfa.transitions[state])

        for symbol in symbols:
            next_left: set[int] = set()
            next_right: set[int] = set()
            for state in left_states:
                next_left.update(left_nfa.transitions[state].get(symbol, set()))
            for state in right_states:
                next_right.update(right_nfa.transitions[state].get(symbol, set()))
            if not next_left or not next_right:
                continue
            candidate = (
                _epsilon_closure(left_nfa, frozenset(next_left)),
                _epsilon_closure(right_nfa, frozenset(next_right)),
            )
            if candidate not in visited:
                pending.add(candidate)
    return False


def _selection_patterns_overlap(left_pattern: str, right_pattern: str) -> bool:
    """判断两个归档成员 include pattern 是否存在共同成员。"""
    directory_symbols, file_symbols = _member_pattern_symbols((left_pattern, right_pattern))
    left_nfa = _compile_member_pattern(left_pattern, directory_symbols, file_symbols)
    right_nfa = _compile_member_pattern(right_pattern, directory_symbols, file_symbols)
    return _product_nfa_overlap(left_nfa, right_nfa)


def _validate_selection_services(
    includes: list[SelectionInclude],
    route_path: str,
    route_id: str | None,
) -> None:
    """不同 service 的 include 若可命中同一成员，则配置整体失败。"""
    for left_index, left in enumerate(includes):
        for right in includes[left_index + 1 :]:
            if (
                left.service is not None
                and right.service is not None
                and left.service != right.service
                and _selection_patterns_overlap(left.pattern, right.pattern)
            ):
                raise _config_error(
                    f"selection include 同时命中不同 service: {left.service} <-> {right.service}",
                    f"{route_path}.selection.include",
                    route_id,
                )


def _patterns_overlap(left: Route, right: Route) -> bool:
    """对两份 route pattern 的 ε-NFA 做状态乘积重叠判断。"""
    directory_symbols = _directory_symbols((left, right))
    directory_symbols.add(_Symbol("directory", "OTHER"))
    file_symbols = _file_symbols((left, right))
    file_symbols.add(_Symbol("file", "OTHER"))
    left_nfa = _compile_route_pattern(left, directory_symbols, file_symbols)
    right_nfa = _compile_route_pattern(right, directory_symbols, file_symbols)
    return _product_nfa_overlap(left_nfa, right_nfa)


def _validate_route_overlaps(routes: tuple[Route, ...]) -> None:
    """同 phase、同 priority、profile 有交集且 pattern 重叠时整体失败。"""
    ordered = sorted(routes, key=lambda route: route.id)
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            if left.phase != right.phase or left.priority != right.priority:
                continue
            profile_intersection = tuple(sorted(set(left.profiles) & set(right.profiles)))
            if not profile_intersection or not _patterns_overlap(left, right):
                continue
            raise _config_error(
                f"route pattern 重叠: {left.id} <-> {right.id}",
                "routes",
                left.id,
                conflict_routes=(left.id, right.id),
                phase=left.phase,
                priority=left.priority,
                profile_intersection=profile_intersection,
            )


def _normalized_path_pattern(pattern: str) -> str:
    """返回按 `/` 分段去空白并大写的 canonical pattern。"""
    return "/".join(_directory_segments(pattern))


def _normalized_source(source: SourcePattern) -> dict[str, object]:
    return {
        "scope": source.scope,
        "directory": _normalized_path_pattern(source.directory),
        "file": source.file.upper(),
        "capture_root": None if source.capture_root is None else source.capture_root.upper(),
    }


def _normalized_selection(selection: Selection | None) -> dict[str, object] | None:
    if selection is None:
        return None
    include_values = {
        (_normalized_path_pattern(item.pattern), None if item.service is None else item.service.strip().upper())
        for item in selection.include
    }
    exclude_values = {(_normalized_path_pattern(item.pattern), item.reason.strip()) for item in selection.exclude}
    include = [{"pattern": pattern, "service": service} for pattern, service in include_values]
    exclude = [{"pattern": pattern, "reason": reason} for pattern, reason in exclude_values]
    include.sort(key=lambda item: (item["pattern"], item["service"] or ""))
    exclude.sort(key=lambda item: (item["pattern"], item["reason"]))
    return {"include": include, "exclude": exclude}


def _fingerprint_data(
    profiles: dict[str, Profile],
    routes: tuple[Route, ...],
) -> dict[str, object]:
    normalized_routes = []
    for route in sorted(routes, key=lambda item: item.id):
        normalized_routes.append(
            {
                "id": route.id,
                "phase": route.phase,
                "priority": route.priority,
                "profiles": list(route.profiles),
                "source": _normalized_source(route.source),
                "action": route.action,
                "category": route.category,
                "target": route.target,
                "selection": _normalized_selection(route.selection),
                "member_decompress": sorted({_normalized_path_pattern(pattern) for pattern in route.member_decompress}),
            }
        )
    normalized_profiles = {
        key: sorted({anchor.upper() for anchor in profile.scene_anchors}) for key, profile in profiles.items()
    }
    return {
        "version": CONFIG_VERSION,
        "profiles": normalized_profiles,
        "routes": normalized_routes,
    }


def _calculate_fingerprint(
    profiles: dict[str, Profile],
    routes: tuple[Route, ...],
) -> str:
    payload = _fingerprint_data(profiles, routes)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_classification_config(payload: object) -> ClassificationConfig:
    """校验内存中的分类配置对象。"""
    if not isinstance(payload, Mapping):
        raise _config_error("根节点必须是 YAML 对象")
    allowed = {"version", "profiles", "routes"}
    unknown = set(payload) - allowed
    if unknown:
        raise _config_error(f"未知顶层字段: {sorted(unknown)}")
    missing = allowed - set(payload)
    if missing:
        raise _config_error(f"缺少顶层字段: {sorted(missing)}")
    if not _is_int(payload["version"]) or int(payload["version"]) != CONFIG_VERSION:
        raise _config_error("version 必须为 1", "version")
    profiles = _validate_profiles(payload["profiles"])
    routes_payload = payload["routes"]
    if not isinstance(routes_payload, list):
        raise _config_error("routes 必须是列表", "routes")

    route_ids: set[str] = set()
    parsed_routes: list[Route] = []
    for index, item in enumerate(routes_payload):
        route = _parse_route(item, index)
        if route.id in route_ids:
            raise _config_error("route id 重复", f"routes[{index}].id", route.id)
        route_ids.add(route.id)
        parsed_routes.append(route)
    routes = tuple(parsed_routes)
    _validate_reachable_defaults(profiles, routes)
    _validate_route_overlaps(routes)
    fingerprint = _calculate_fingerprint(profiles, routes)
    return ClassificationConfig(
        version=CONFIG_VERSION,
        profiles=profiles,
        routes=routes,
        fingerprint=fingerprint,
    )


@lru_cache(maxsize=8)
def loads_classification_config(text: str) -> ClassificationConfig:
    """从 YAML 字符串读取并严格校验分类配置。"""
    try:
        payload = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506
    except (yaml.YAMLError, TypeError, ValueError, AttributeError) as exc:
        raise _config_error(f"YAML 解析失败：{exc}") from exc
    return parse_classification_config(payload)


def load_classification_config(path: Path | str | None = None) -> ClassificationConfig:
    """从 classify_rules.yaml 读取并严格校验分类配置。"""
    config_path = Path(path) if path is not None else settings.config_dir / "classify_rules.yaml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _config_error(f"无法读取分类配置: {exc}") from exc
    return loads_classification_config(text)
