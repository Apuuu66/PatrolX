"""source_patterns 匹配器契约测试。"""

from pathlib import Path

import pytest

from app.services.scanning import match_paths, validate_patterns


def test_match_uses_fullmatch_not_substring() -> None:
    paths = [Path("logs/app.log"), Path("logs/app.log.old")]

    matched = match_paths(paths, [r"logs/.*\.log"])

    assert matched == [Path("logs/app.log")]


def test_match_unions_patterns_deduplicates_and_sorts() -> None:
    paths = [
        Path("kpi/b.csv"),
        Path("logs/a.log"),
        Path("logs/a.log"),
        Path("config/a.conf"),
    ]

    matched = match_paths(paths, [r"logs/.*", r"kpi/.*", r"logs/a\.log"])

    assert [path.as_posix() for path in matched] == ["kpi/b.csv", "logs/a.log"]


@pytest.mark.parametrize(
    "patterns",
    [
        [""],
        [" logs/.*"],
        ["logs/.* "],
        ["/logs/.*"],
        ["\\logs"],
        ["~/logs/.*"],
        ["../logs/.*"],
        [r"logs\..\other"],
        ["C:/logs/.*"],
        ["C:\\logs"],
        ["logs/("],
    ],
)
def test_match_rejects_unsafe_or_invalid_patterns(patterns: list[str]) -> None:
    with pytest.raises(ValueError, match="source_patterns"):
        match_paths([Path("logs/a.log")], patterns)


@pytest.mark.parametrize(
    "pattern",
    ["", " logs/.*", "/logs/.*", "~/logs/.*", "../logs/.*", "C:\\logs", "logs/("],
)
def test_validate_rejects_unsafe_or_invalid_patterns(pattern: str) -> None:
    with pytest.raises(ValueError, match="source_patterns"):
        validate_patterns([pattern])


def test_match_rejects_absolute_and_traversal_paths() -> None:
    with pytest.raises(ValueError, match="匹配路径越界"):
        match_paths([Path("/logs/a.log")], [r"logs/.*"])
    with pytest.raises(ValueError, match="匹配路径越界"):
        match_paths([Path("../logs/a.log")], [r"logs/.*"])
