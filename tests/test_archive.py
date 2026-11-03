"""安全解压基础行为与资源上限测试。"""

import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError, UnpackLimit, is_archive, unpack_tar, unpack_zip


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
