"""安全解压资源预算与路径安全测试。"""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError, UnpackLimit, unpack_tar, unpack_zip


def limit() -> UnpackLimit:
    value = UnpackLimit()
    value.max_files = 2
    value.max_single_file = 16
    value.max_depth = 2
    return value


def make_zip(path: Path, names: list[str], content: str = "x") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, content)


@pytest.mark.parametrize("writer", [unpack_zip, unpack_tar])
def test_file_count_budget(tmp_path: Path, writer) -> None:
    archive = tmp_path / ("archive.zip" if writer is unpack_zip else "archive.tar.gz")
    if writer is unpack_zip:
        make_zip(archive, ["a.txt", "b.txt", "c.txt"])
    else:
        with tarfile.open(archive, "w:gz") as tf:
            for name in ["a.txt", "b.txt", "c.txt"]:
                data = (tmp_path / name).resolve()
                data.write_text("x")
                tf.add(data, arcname=name)
    with pytest.raises(ArchiveError, match="文件数超限"):
        writer(archive, tmp_path / "out", limit())


@pytest.mark.parametrize("writer", [unpack_zip, unpack_tar])
def test_single_file_budget(tmp_path: Path, writer) -> None:
    archive = tmp_path / ("big.zip" if writer is unpack_zip else "big.tar.gz")
    payload = "0" * 17
    if writer is unpack_zip:
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("big.txt", payload)
    else:
        payload_path = tmp_path / "big.txt"
        payload_path.write_text(payload)
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(payload_path, arcname="big.txt")
    with pytest.raises(ArchiveError, match="单文件超限"):
        writer(archive, tmp_path / "out", limit())


@pytest.mark.parametrize("writer", [unpack_zip, unpack_tar])
def test_total_budget(tmp_path: Path, writer) -> None:
    archive = tmp_path / ("bomb.zip" if writer is unpack_zip else "bomb.tar.gz")
    if writer is unpack_zip:
        make_zip(archive, ["zeros.bin"], "0" * 4096)
    else:
        payload = tmp_path / "zeros.bin"
        payload.write_bytes(b"0" * 4096)
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(payload, arcname="zeros.bin")
    value = limit()
    value.max_files = 100
    value.max_single_file = 100_000
    value.expansion_ratio = 0.5
    with pytest.raises(ArchiveError, match="总量超限"):
        writer(archive, tmp_path / "out", value)


@pytest.mark.parametrize("writer", [unpack_zip, unpack_tar])
def test_path_traversal_rejected(tmp_path: Path, writer) -> None:
    archive = tmp_path / ("evil.zip" if writer is unpack_zip else "evil.tar.gz")
    if writer is unpack_zip:
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape.txt", "boom")
    else:
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("../escape.txt")
            data = b"boom"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    with pytest.raises(ArchiveError, match="路径穿越"):
        writer(archive, tmp_path / "out", limit())


def test_symlink_rejected(tmp_path: Path) -> None:
    zip_path = tmp_path / "link.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("link.txt")
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "target.txt")
    with pytest.raises(ArchiveError, match="链接"):
        unpack_zip(zip_path, tmp_path / "out", limit())

    tar_path = tmp_path / "link.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        info = tarfile.TarInfo("link.txt")
        info.type = tarfile.SYMTYPE
        info.linkname = "target.txt"
        tf.addfile(info)
    with pytest.raises(ArchiveError, match="链接"):
        unpack_tar(tar_path, tmp_path / "out", limit())


@pytest.mark.parametrize("writer", [unpack_zip, unpack_tar])
def test_nested_depth_budget(tmp_path: Path, writer) -> None:
    archive = tmp_path / ("deep.zip" if writer is unpack_zip else "deep.tar.gz")
    name = "a/b/c/d/deep.txt"
    if writer is unpack_zip:
        make_zip(archive, [name])
    else:
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo(name)
            data = b"x"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    with pytest.raises(ArchiveError, match="嵌套深度超限"):
        writer(archive, tmp_path / "out", limit())
