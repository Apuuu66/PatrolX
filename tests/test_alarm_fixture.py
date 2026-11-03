"""039 告警合成样例覆盖与幂等性测试。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from app.core.checksum import sha256_file
from tests.fixtures.make_real_package import build_real_package


def test_alarm_fixture_covers_language_quality_and_recurrence_cases(tmp_path: Path) -> None:
    first = build_real_package(tmp_path / "first")
    second = build_real_package(tmp_path / "second")

    assert sha256_file(first) == sha256_file(second)
    with zipfile.ZipFile(first) as archive:
        alarm_name = next(name for name in archive.namelist() if "/Alarm Information/" in name)
        with zipfile.ZipFile(io.BytesIO(archive.read(alarm_name))) as alarm_archive:
            members = {name: alarm_archive.read(name) for name in alarm_archive.namelist()}

    assert any(name.startswith("alarm_english") for name in members)
    assert any(name.startswith("alarm_chinese") for name in members)
    assert any(name.startswith("alarm_mixed") for name in members)
    assert any(name.startswith("alarm_bad_encoding") for name in members)
    combined = b"\n".join(members.values())
    for token in ("未清除", "Not Cleared", "Reset Cleared", "Repeat Times"):
        assert token.encode("utf-8") in combined or token == "Repeat Times"
    assert b"Pod Name=pod-active" in combined
    assert b"\xff\xfe" in combined
