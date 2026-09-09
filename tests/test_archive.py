"""安全解压测试：路径穿越拒绝、正常解压。"""

import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError, is_archive, unpack_zip


def test_zip_slip_rejected(tmp_path: Path) -> None:
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape.txt", "boom")
    with pytest.raises(ArchiveError):
        unpack_zip(evil, tmp_path / "out")


def test_unpack_zip_ok(tmp_path: Path) -> None:
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("logs/a.log", "hello")
        zf.writestr("kpi/b.csv", "x,y\n1,2\n")
    count = unpack_zip(archive, tmp_path / "out")
    assert count == 2
    assert (tmp_path / "out" / "logs" / "a.log").read_text() == "hello"


def test_log_gzip_is_not_nested_archive(tmp_path: Path) -> None:
    path = tmp_path / "app_history.log.gz"
    path.write_bytes(b"plain")
    assert is_archive(path) is False
