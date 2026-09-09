"""安全解压测试：路径穿越拒绝、正常解压。"""

import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError, unpack_zip


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
