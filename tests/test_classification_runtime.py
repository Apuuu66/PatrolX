"""分类审计记录、稳定消歧、汇总与 canonical JSON 测试。"""

import pytest

from app.services.extraction.audit import (
    LandedEntry,
    build_summary,
    canonical_json,
    conflict_digest,
    make_failure_record,
    make_ignored_record,
    make_landed_entry,
    resolve_target,
)

SHA256_A = "a" * 64
SHA256_B = "b" * 64


def test_landed_entry_has_strict_fields_and_fixed_status() -> None:
    """成功记录必须严格符合冻结字段、枚举和 checksum/size 类型。"""
    entry = make_landed_entry(
        source_relative="dir/file.txt",
        route_id="route.a",
        product="UMF",
        category="config",
        original_target="basic/file.txt",
        target="basic/file.txt",
        action="copy",
        sha256=SHA256_A,
        size=12,
    )

    assert isinstance(entry, LandedEntry)
    assert set(entry.__dataclass_fields__) == {
        "source_relative",
        "member_relative",
        "route_id",
        "product",
        "category",
        "original_target",
        "target",
        "action",
        "status",
        "reason",
        "error_code",
        "sha256",
        "size",
    }
    assert entry.status == "landed"
    assert entry.error_code is None
    assert entry.member_relative is None


def test_ignored_record_has_strict_fields_and_nonempty_reason() -> None:
    """忽略记录必须严格符合字段集合，且不得携带错误码或创建目标。"""
    record = make_ignored_record(
        source_relative="dir/skip.txt",
        route_id="route.ignore",
        action="ignore",
        reason="route_ignored",
        product="CSP",
    )

    assert set(record.__dataclass_fields__) == {
        "source_relative",
        "member_relative",
        "route_id",
        "product",
        "category",
        "original_target",
        "target",
        "action",
        "status",
        "reason",
        "error_code",
    }
    assert record.status == "ignored"
    assert record.error_code is None
    assert record.target is None
    assert record.category is None


def test_failure_record_validates_stable_error_code() -> None:
    """失败记录必须使用稳定错误码和非空中文原因。"""
    failure = make_failure_record(
        source_relative="bad.zip",
        member_relative="inner.txt",
        route_id="route.expand",
        category="kpi",
        action="expand",
        error_code="archive_corrupt",
        reason="压缩包已损坏",
    )

    assert set(failure.__dataclass_fields__) == {
        "source_relative",
        "member_relative",
        "route_id",
        "category",
        "action",
        "error_code",
        "reason",
    }
    assert failure.error_code == "archive_corrupt"
    assert failure.reason == "压缩包已损坏"


def test_conflict_digest_uses_stable_null_separated_identity() -> None:
    """消歧摘要必须来自 product、source 与 member 的固定 NUL 拼接。"""
    import hashlib

    expected = hashlib.sha256(b"UMF\x00dir/file.txt\x00inner/member.txt").hexdigest()[:12]

    assert conflict_digest("UMF", "dir/file.txt", "inner/member.txt") == expected


def test_resolve_target_inserts_digest_before_first_extension() -> None:
    """目标冲突时必须在首个扩展名前插入 12 位摘要，不覆盖原文件。"""
    target, digest = resolve_target(
        original_target="basic/file.txt",
        product="UMF",
        source_relative="dir/file.txt",
        member_relative="",
        used_targets={"basic/file.txt"},
    )

    assert target == f"basic/file__{digest}.txt"
    assert len(digest) == 12


def test_resolve_target_appends_suffix_when_disambiguated_target_is_used() -> None:
    """消歧目标仍冲突时必须稳定追加 -2、-3。"""
    first_target, digest = resolve_target(
        original_target="basic/file.txt",
        product="UMF",
        source_relative="dir/file.txt",
        member_relative="",
        used_targets={"basic/file.txt"},
    )

    second_target, second_digest = resolve_target(
        original_target="basic/file.txt",
        product="UMF",
        source_relative="other/file.txt",
        member_relative="",
        used_targets={"basic/file.txt", first_target},
    )

    assert second_digest != digest
    assert second_target == f"basic/file__{second_digest}-2.txt"


def test_resolve_target_without_extension_appends_digest() -> None:
    """无扩展名文件应直接追加摘要。"""
    target, digest = resolve_target(
        original_target="basic/LICENSE",
        product=None,
        source_relative="LICENSE",
        member_relative="",
        used_targets={"basic/LICENSE"},
    )

    assert target == f"basic/LICENSE__{digest}"


def test_build_summary_counts_and_groups_records() -> None:
    """摘要必须严格计数，并按 route/category/action/status 汇总。"""
    landed = make_landed_entry(
        source_relative="config.txt",
        route_id="route.a",
        product="UMF",
        category="config",
        original_target="config/file.txt",
        target="config/file.txt",
        action="copy",
        sha256=SHA256_A,
        size=1,
    )
    ignored = make_ignored_record(
        source_relative="skip.txt",
        route_id="route.b",
        action="ignore",
        reason="route_ignored",
        product="CSP",
    )
    failure = make_failure_record(
        source_relative="bad.zip",
        route_id="route.a",
        category="config",
        action="expand",
        error_code="archive_corrupt",
        reason="压缩包已损坏",
    )

    summary = build_summary(
        entries=[landed],
        ignored=[ignored],
        conflicts_count=1,
        failures=[failure],
    )

    assert set(summary.__dataclass_fields__) == {
        "counts",
        "by_route",
        "by_category",
        "by_action",
        "by_status",
    }
    assert set(summary.counts.__dataclass_fields__) == {
        "landed",
        "ignored",
        "conflicts",
        "failures",
        "catalog",
    }
    assert summary.counts.landed == 1
    assert summary.counts.ignored == 1
    assert summary.counts.conflicts == 1
    assert summary.counts.failures == 1
    assert summary.counts.catalog == 1
    assert summary.by_route == {"route.a": 2, "route.b": 1}
    assert summary.by_category == {"config": 1}
    assert summary.by_action == {"copy": 1, "expand": 1, "ignore": 1}
    assert summary.by_status == {"failed": 1, "ignored": 1, "landed": 1}


def test_canonical_json_sorts_keys_compactly() -> None:
    """canonical JSON 必须按键排序、紧凑分隔并保留 UTF-8。"""
    payload = {"b": 1, "a": {"中文": "值", "数组": [2, 1]}}

    assert canonical_json(payload) == '{"a":{"中文":"值","数组":[2,1]},"b":1}'.encode()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "sniff"},
        {"category": "network"},
        {"product": "UNKNOWN"},
        {"sha256": "not-sha256"},
        {"size": -1},
        {"target": "../escape.txt"},
        {"target": ".main/secret.txt"},
    ],
)
def test_landed_entry_rejects_invalid_values(kwargs: dict[str, str | int]) -> None:
    """非法枚举、checksum、大小或越界目标必须使记录构造失败。"""
    defaults = {
        "source_relative": "dir/file.txt",
        "route_id": "route.a",
        "product": "UMF",
        "category": "config",
        "original_target": "basic/file.txt",
        "target": "basic/file.txt",
        "action": "copy",
        "sha256": SHA256_A,
        "size": 1,
    }
    defaults.update(kwargs)

    with pytest.raises(ValueError, match="非法|必须|不得|摘要"):
        make_landed_entry(**defaults)


def test_conflict_record_rejects_short_digest() -> None:
    """冲突记录必须拒绝非 12 位摘要。"""
    from app.services.extraction.audit import make_conflict_record

    entry = make_landed_entry(
        source_relative="dir/file.txt",
        route_id="route.a",
        product="UMF",
        category="config",
        original_target="basic/file.txt",
        target="basic/file__abc.txt",
        action="copy",
        sha256=SHA256_B,
        size=2,
    )

    with pytest.raises(ValueError, match="摘要必须为 12"):
        make_conflict_record(entry, "abc")
