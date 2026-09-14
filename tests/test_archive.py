"""安全解压测试：路径穿越拒绝、正常解压。"""

import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError, UnpackLimit, _expansion_budget, is_archive, unpack_tar, unpack_zip


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


def test_main_budget_uses_absolute_3gb_limit(tmp_path: Path) -> None:
    """主包解压预算只受 3GB 硬上限约束，不按压缩包大小放大。"""
    archive = tmp_path / "small.zip"
    archive.write_bytes(b"zip")

    assert _expansion_budget(UnpackLimit()) == 3 * 1024 * 1024 * 1024


def test_log_gzip_is_not_nested_archive(tmp_path: Path) -> None:
    path = tmp_path / "app_history.log.gz"
    path.write_bytes(b"plain")
    assert is_archive(path) is False


def test_zip_expansion_budget_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("zeros.bin", "0" * 4096)
    limit = UnpackLimit()
    limit.max_total_bytes = 4095

    with pytest.raises(ArchiveError, match="解压总量超限"):
        unpack_zip(archive, tmp_path / "out", limit)


def test_tar_expansion_budget_rejected(tmp_path: Path) -> None:
    import tarfile

    archive = tmp_path / "bomb.tar.gz"
    payload = tmp_path / "zeros.bin"
    payload.write_bytes(b"0" * 4096)
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(payload, arcname="zeros.bin")
    limit = UnpackLimit()
    limit.max_total_bytes = 4095

    with pytest.raises(ArchiveError, match="解压总量超限"):
        unpack_tar(archive, tmp_path / "out", limit)
