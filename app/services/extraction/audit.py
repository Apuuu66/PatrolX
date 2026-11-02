"""分类审计记录、稳定消歧、汇总与 canonical JSON 序列化。"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

PRODUCTS = frozenset({"UMF", "CSP"})
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
LANDED_ACTIONS = ACTIONS - {"ignore"}
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
ERROR_CODES = frozenset(
    {
        "archive_depth_exceeded",
        "member_path_depth_exceeded",
        "file_count_exceeded",
        "task_file_count_exceeded",
        "file_too_large",
        "total_bytes_exceeded",
        "archive_corrupt",
        "unsafe_path",
        "link_rejected",
        "duplicate_member",
        "target_conflict",
        "invalid_classification_config",
    }
)
_ROUTE_ID_PATTERN = re.compile(r"[a-z0-9._-]+")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{12}")


@dataclass(frozen=True, slots=True)
class LandedEntry:
    """成功落位文件的审计记录。"""

    source_relative: str
    member_relative: str | None
    route_id: str
    product: str | None
    category: str
    original_target: str
    target: str
    action: str
    status: str
    reason: str | None
    error_code: None
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class IgnoredRecord:
    """明确忽略文件或成员的审计记录。"""

    source_relative: str
    member_relative: str | None
    route_id: str | None
    product: str | None
    category: str | None
    original_target: str | None
    target: str | None
    action: str
    status: str
    reason: str
    error_code: None


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    """目标重名且已稳定消歧的审计记录。"""

    source_relative: str
    member_relative: str | None
    original_target: str
    target: str
    digest: str
    status: str

    def __post_init__(self) -> None:
        """拒绝直接构造的伪造或未消歧冲突记录。"""
        _validate_relative_path(self.source_relative, "source_relative")
        _validate_optional_member(self.member_relative)
        original_target = _validate_target(self.original_target)
        target = _validate_target(self.target)
        if self.status != "resolved":
            raise ValueError("status 必须固定为 resolved")
        if not isinstance(self.digest, str) or _DIGEST_PATTERN.fullmatch(self.digest) is None:
            raise ValueError("摘要必须为 12 位小写十六进制摘要")
        if not _conflict_target_is_valid(original_target, target, self.digest):
            raise ValueError("冲突 target 必须不同于 original_target 且包含对应摘要")


@dataclass(frozen=True, slots=True)
class FailureRecord:
    """单文件或单个归档成员失败的审计记录。"""

    source_relative: str
    member_relative: str | None
    route_id: str
    category: str | None
    action: str | None
    error_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class SummaryCounts:
    """分类摘要计数。"""

    landed: int
    ignored: int
    conflicts: int
    failures: int
    catalog: int


@dataclass(frozen=True, slots=True)
class Summary:
    """路由、分类、动作和状态汇总。"""

    counts: SummaryCounts
    by_route: dict[str, int]
    by_category: dict[str, int]
    by_action: dict[str, int]
    by_status: dict[str, int]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_route_id(route_id: object, *, required: bool) -> str | None:
    if route_id is None:
        if required:
            raise ValueError("route_id 必须是非空字符串")
        return None
    if not isinstance(route_id, str) or len(route_id) > 128 or _ROUTE_ID_PATTERN.fullmatch(route_id) is None:
        raise ValueError("route_id 非法")
    return route_id


def _validate_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}必须是非空字符串")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise ValueError(f"{label}不得是绝对路径、包含反斜杠或 NUL")
    segments = value.split("/")
    if any(segment == "" or segment in {".", ".."} for segment in segments):
        raise ValueError(f"{label}不得包含空段、. 或 ..")
    return value


def _validate_optional_member(value: object) -> str | None:
    if value is None:
        return None
    return _validate_relative_path(value, "member_relative")


def _validate_target(value: object) -> str:
    target = _validate_relative_path(value, "target")
    first_segment = target.split("/", 1)[0]
    if first_segment == ".main":
        raise ValueError("target 不得指向内部保留路径 .main")
    if first_segment not in TARGET_ROOTS:
        raise ValueError(f"target 首段不在允许范围内: {first_segment}")
    return target


def _validate_optional_target(value: object) -> str | None:
    if value is None:
        return None
    return _validate_target(value)


def _validate_product(product: object) -> str | None:
    if product is None:
        return None
    if not isinstance(product, str) or product not in PRODUCTS:
        raise ValueError("product 必须是 UMF、CSP 或 null")
    return product


def _validate_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("sha256 必须是 64 位小写十六进制摘要")
    return value


def _validate_reason(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("reason 必须是非空字符串")
    return value


def make_landed_entry(
    *,
    source_relative: str,
    route_id: str,
    product: str | None,
    category: str,
    original_target: str,
    target: str,
    action: str,
    sha256: str,
    size: int,
    member_relative: str | None = None,
    reason: str | None = None,
) -> LandedEntry:
    """构造并校验成功落位记录。"""
    source = _validate_relative_path(source_relative, "source_relative")
    checked_route_id = _validate_route_id(route_id, required=True)
    checked_product = _validate_product(product)
    if category not in CATEGORIES:
        raise ValueError("category 非法")
    checked_original_target = _validate_target(original_target)
    checked_target = _validate_target(target)
    if action not in LANDED_ACTIONS:
        raise ValueError("action 非法")
    checked_member = _validate_optional_member(member_relative)
    checked_reason = _validate_reason(reason)
    checked_sha = _validate_sha256(sha256)
    if not _is_int(size) or size < 0:
        raise ValueError("size 必须是非负整数")

    return LandedEntry(
        source_relative=source,
        member_relative=checked_member,
        route_id=checked_route_id,
        product=checked_product,
        category=category,
        original_target=checked_original_target,
        target=checked_target,
        action=action,
        status="landed",
        reason=checked_reason,
        error_code=None,
        sha256=checked_sha,
        size=size,
    )


def make_ignored_record(
    *,
    source_relative: str,
    route_id: str | None,
    action: str,
    reason: str,
    product: str | None,
    member_relative: str | None = None,
    category: str | None = None,
    original_target: str | None = None,
    target: str | None = None,
) -> IgnoredRecord:
    """构造并校验忽略记录。"""
    checked_source = _validate_relative_path(source_relative, "source_relative")
    checked_route_id = _validate_route_id(route_id, required=False)
    if action not in ACTIONS:
        raise ValueError("action 非法")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason 必须是非空字符串")
    checked_product = _validate_product(product)
    if category is not None and category not in CATEGORIES:
        raise ValueError("category 非法")
    checked_member = _validate_optional_member(member_relative)
    checked_original_target = _validate_optional_target(original_target)
    checked_target = _validate_optional_target(target)

    return IgnoredRecord(
        source_relative=checked_source,
        member_relative=checked_member,
        route_id=checked_route_id,
        product=checked_product,
        category=category,
        original_target=checked_original_target,
        target=checked_target,
        action=action,
        status="ignored",
        reason=reason,
        error_code=None,
    )


def make_failure_record(
    *,
    source_relative: str,
    route_id: str,
    category: str | None,
    action: str | None,
    error_code: str,
    reason: str,
    member_relative: str | None = None,
) -> FailureRecord:
    """构造并校验局部失败记录。"""
    checked_source = _validate_relative_path(source_relative, "source_relative")
    checked_member = _validate_optional_member(member_relative)
    checked_route_id = _validate_route_id(route_id, required=True)
    if category is not None and category not in CATEGORIES:
        raise ValueError("category 非法")
    if action is not None and action not in ACTIONS:
        raise ValueError("action 非法")
    if error_code not in ERROR_CODES:
        raise ValueError("error_code 必须来自稳定错误码集合")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason 必须是非空字符串")

    return FailureRecord(
        source_relative=checked_source,
        member_relative=checked_member,
        route_id=checked_route_id,
        category=category,
        action=action,
        error_code=error_code,
        reason=reason,
    )


def make_conflict_record(entry: LandedEntry, digest: str) -> ConflictRecord:
    """根据成功 entry 构造已解决冲突记录。"""
    if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
        raise ValueError("摘要必须为 12 位小写十六进制摘要")
    expected = conflict_digest(entry.product, entry.source_relative, entry.member_relative or "")
    if digest != expected:
        raise ValueError("摘要与 product/source/member 重算结果不一致")
    return ConflictRecord(
        source_relative=entry.source_relative,
        member_relative=entry.member_relative,
        original_target=entry.original_target,
        target=entry.target,
        digest=digest,
        status="resolved",
    )


def conflict_digest(
    product: str | None,
    source_relative: str,
    member_relative: str,
) -> str:
    """计算稳定消歧摘要的前 12 位。"""
    if product is not None and product not in PRODUCTS:
        raise ValueError("product 必须是 UMF、CSP 或 null")
    _validate_relative_path(source_relative, "source_relative")
    if not isinstance(member_relative, str):
        raise ValueError("member_relative 必须是字符串")
    identity = b"\x00".join(
        (
            (product or "").encode("utf-8"),
            source_relative.encode("utf-8"),
            member_relative.encode("utf-8"),
        )
    )
    return hashlib.sha256(identity).hexdigest()[:12]


def _disambiguated_target(original_target: str, digest: str, suffix: int | None = None) -> str:
    directory, separator, filename = original_target.rpartition("/")
    marker = f"__{digest}" if suffix is None else f"__{digest}-{suffix}"
    dot_index = filename.find(".")
    if dot_index < 0:
        new_filename = f"{filename}{marker}"
    else:
        new_filename = f"{filename[:dot_index]}{marker}{filename[dot_index:]}"
    if directory:
        return f"{directory}{separator}{new_filename}"
    return new_filename


def _conflict_target_is_valid(original_target: str, target: str, digest: str) -> bool:
    """确认 target 是由 original_target 与指定摘要生成的唯一消歧路径。"""
    original_directory, _, original_filename = original_target.rpartition("/")
    target_directory, _, target_filename = target.rpartition("/")
    if original_directory != target_directory or original_target == target:
        return False
    dot_index = original_filename.find(".")
    if dot_index < 0:
        stem = original_filename
        extension = ""
    else:
        stem = original_filename[:dot_index]
        extension = original_filename[dot_index:]
    pattern = re.compile(re.escape(stem) + rf"__{re.escape(digest)}(?:-[2-9]\d*)?" + re.escape(extension))
    return pattern.fullmatch(target_filename) is not None


def _disambiguation_slot_count(original_target: str, used_targets: set[str]) -> int:
    directory, _, filename = original_target.rpartition("/")
    dot_index = filename.find(".")
    if dot_index < 0:
        stem = filename
        extension = ""
    else:
        stem = filename[:dot_index]
        extension = re.escape(filename[dot_index:])
    pattern = re.compile(re.escape(stem) + r"__[0-9a-f]{12}(?:-\d+)?" + extension)
    count = 0
    for target in used_targets:
        target_directory, _, target_filename = target.rpartition("/")
        if target_directory == directory and pattern.fullmatch(target_filename):
            count += 1
    return count


def resolve_target(
    *,
    original_target: str,
    product: str | None,
    source_relative: str,
    member_relative: str,
    used_targets: set[str],
) -> tuple[str, str]:
    """在不覆盖既有目标的前提下，返回稳定消歧后的目标路径。"""
    checked_original = _validate_target(original_target)
    digest = conflict_digest(product, source_relative, member_relative)
    if checked_original not in used_targets:
        return checked_original, digest

    slot_count = _disambiguation_slot_count(checked_original, used_targets)
    if slot_count == 0:
        candidate = _disambiguated_target(checked_original, digest)
        if candidate not in used_targets:
            return candidate, digest
        suffix = 2
    else:
        suffix = slot_count + 1

    while True:
        candidate = _disambiguated_target(checked_original, digest, suffix)
        if candidate not in used_targets:
            return candidate, digest
        suffix += 1


def _increase(mapping: dict[str, int], key: str | None) -> None:
    if key is not None:
        mapping[key] = mapping.get(key, 0) + 1


def build_summary(
    *,
    entries: list[LandedEntry],
    ignored: list[IgnoredRecord],
    conflicts_count: int,
    failures: list[FailureRecord],
    catalog_count: int,
) -> Summary:
    """根据审计数组构造严格摘要。"""
    if not _is_int(conflicts_count) or conflicts_count < 0:
        raise ValueError("conflicts_count 必须是非负整数")
    if not _is_int(catalog_count) or catalog_count < 0:
        raise ValueError("catalog_count 必须是非负整数")

    by_route: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_action: dict[str, int] = {}

    for entry in entries:
        _increase(by_route, entry.route_id)
        _increase(by_category, entry.category)
        _increase(by_action, entry.action)
    for record in ignored:
        _increase(by_route, record.route_id)
        if record.category is not None:
            _increase(by_category, record.category)
        _increase(by_action, record.action)
    for failure in failures:
        _increase(by_route, failure.route_id)
        if failure.action is not None:
            _increase(by_action, failure.action)

    counts = SummaryCounts(
        landed=len(entries),
        ignored=len(ignored),
        conflicts=conflicts_count,
        failures=len(failures),
        catalog=catalog_count,
    )
    return Summary(
        counts=counts,
        by_route=dict(sorted(by_route.items())),
        by_category=dict(sorted(by_category.items())),
        by_action=dict(sorted(by_action.items())),
        by_status={"failed": len(failures), "ignored": len(ignored), "landed": len(entries)},
    )


def canonical_json(payload: Any) -> bytes:
    """将对象序列化为紧凑、键排序且保留 UTF-8 的 canonical JSON。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
