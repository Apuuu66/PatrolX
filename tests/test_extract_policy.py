"""解压策略配置、路径归一化和白名单匹配测试。"""

from pathlib import Path

import pytest
import yaml

from app.services.extraction.policy import (
    ExtractPolicyError,
    evaluate_extract_policy,
    load_extract_policy,
    normalize_policy_path,
    policy_fingerprint,
)


def _config(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "extract_policy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_missing_or_empty_config_uses_baseline(tmp_path: Path) -> None:
    missing = load_extract_policy(tmp_path / "missing.yaml")
    empty_path = _config(tmp_path, None)
    empty = load_extract_policy(empty_path)
    for policy in (missing, empty):
        assert policy.version == 1
        assert policy.skip_all is False
        assert policy.skip_paths == ()
        assert policy.whitelist_paths == ()
        assert policy.whitelist_keywords == ()


@pytest.mark.parametrize(
    "raw,expected",
    [("/0/", "0/"), ("0/", "0/"), ("/xx/0/", "xx/0/"), ("xx/0", "xx/0/")],
)
def test_policy_paths_are_normalized(raw: str, expected: str) -> None:
    assert normalize_policy_path(raw) == expected


@pytest.mark.parametrize("raw", ["", "/", ".", "..", "0//x", "0/../x", "..", "0/.."])
def test_invalid_policy_paths_are_rejected(raw: str) -> None:
    with pytest.raises(ExtractPolicyError):
        normalize_policy_path(raw)


@pytest.mark.parametrize(
    "data",
    [
        {"version": 2},
        {"unknown": True},
        {"nested": {"unknown": True}},
        {"whitelist": {"unknown": True}},
        {"nested": {"skip_paths": ["/0//"]}},
        {"whitelist": {"name_keywords": [""]}},
        {"nested": {"skip_paths": ["/0/", "0/"]}},
        {"nested": {"skip_paths": ["/0/"]}, "whitelist": {"paths": ["0/"]}},
    ],
)
def test_invalid_config_does_not_fall_back(tmp_path: Path, data: dict) -> None:
    with pytest.raises(ExtractPolicyError):
        load_extract_policy(_config(tmp_path, data))


def test_delivered_initial_policy_only_contains_alarm_keyword() -> None:
    policy = load_extract_policy()
    assert policy.skip_all is False
    assert policy.skip_paths == ("0/",)
    assert policy.whitelist_paths == ()
    assert policy.whitelist_keywords == ("alarm",)


def test_whitelist_matches_path_and_keyword_case_insensitively(tmp_path: Path) -> None:
    policy = load_extract_policy(
        _config(
            tmp_path,
            {
                "version": 1,
                "nested": {"skip_paths": ["/0/"]},
                "whitelist": {"paths": ["/safe/"], "name_keywords": ["alarm"]},
            },
        )
    )
    assert evaluate_extract_policy(policy, "0/AlarmFiles/file.txt").reason == "whitelist_keyword"
    assert evaluate_extract_policy(policy, "service_ALARM.zip", is_compressed=True).reason == "whitelist_keyword"
    assert evaluate_extract_policy(policy, "node/alarm.txt").reason == "whitelist_keyword"
    assert evaluate_extract_policy(policy, "safe/data.zip", is_compressed=True).reason == "whitelist_path"
    assert evaluate_extract_policy(policy, "0/service.zip", is_compressed=True).reason == "skip_path"
    assert evaluate_extract_policy(policy, "normal/file.txt") is None


def test_empty_keyword_list_does_not_whitelist(tmp_path: Path) -> None:
    policy = load_extract_policy(_config(tmp_path, {"whitelist": {"name_keywords": []}}))
    assert evaluate_extract_policy(policy, "alarm/file.txt") is None


def test_path_scope_boundary_is_exact_directory_prefix(tmp_path: Path) -> None:
    policy = load_extract_policy(
        _config(
            tmp_path,
            {"nested": {"skip_paths": ["/0/", "/xx/0/"]}},
        )
    )
    assert evaluate_extract_policy(policy, "0/a.zip", is_compressed=True).reason == "skip_path"
    assert evaluate_extract_policy(policy, "0a/file.zip", is_compressed=True) is None
    assert evaluate_extract_policy(policy, "xx/0/deep.zip", is_compressed=True).reason == "skip_path"


def test_fingerprint_ignores_comments_and_whitespace(tmp_path: Path) -> None:
    first_path = tmp_path / "first.yaml"
    second_path = tmp_path / "second.yaml"
    first_path.write_text(
        "# comment\nversion: 1\nnested:\n  skip_paths: [ '/0/' ]\nwhitelist:\n  name_keywords: ['alarm']\n",
        encoding="utf-8",
    )
    second_path.write_text(
        "version: 1\nnested: {skip_paths: ['0/']}\nwhitelist: {name_keywords: [alarm]}\n",
        encoding="utf-8",
    )
    first = load_extract_policy(first_path)
    second = load_extract_policy(second_path)
    assert (
        first.fingerprint
        == second.fingerprint
        == policy_fingerprint(
            skip_all=False,
            skip_paths=("0/",),
            whitelist_paths=(),
            whitelist_keywords=("alarm",),
        )
    )
