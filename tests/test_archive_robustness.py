"""压缩包安全解压的健壮性测试。"""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError, UnpackLimit, unpack_tar, unpack_zip


def _zip_info(name: str, content: bytes, *, external_attr: int | None = None) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    if external_attr is not None:
        info.create_system = 3
        info.external_attr = external_attr
    return info, content


def _write_zip(path: Path, members: list[tuple[zipfile.ZipInfo, bytes]]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for info, content in members:
            zf.writestr(info, content)


def _tar_info(name: str, size: int, *, linkname: str | None = None, link: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    if link:
        info.type = tarfile.SYMTYPE if linkname is not None and linkname.startswith("/") else tarfile.LNKTYPE
        info.linkname = linkname or ""
    return info


def _write_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for info, content in members:
            tf.addfile(info, io.BytesIO(content))


def test_zip_symlink_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    mode = 0o120777 << 16
    _write_zip(archive, [_zip_info("link.txt", b"/etc/passwd", external_attr=mode)])
    with pytest.raises(ArchiveError, match="链接文件被拒绝"):
        unpack_zip(archive, tmp_path / "out")


def test_tar_symlink_and_hardlink_members_are_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "links.tar.gz"
    _write_tar(
        archive,
        [
            (_tar_info("symlink.txt", 0, linkname="/etc/passwd", link=True), b""),
            (_tar_info("hardlink.txt", 0, linkname="payload.txt"), b""),
        ],
    )
    with pytest.raises(ArchiveError, match="链接文件被拒绝"):
        unpack_tar(archive, tmp_path / "out")


@pytest.mark.parametrize("member_name", ["/etc/escape.txt", r"C:\escape.txt", "C:/escape.txt"])
def test_zip_absolute_paths_are_rejected(tmp_path: Path, member_name: str) -> None:
    archive = tmp_path / "absolute.zip"
    _write_zip(archive, [_zip_info(member_name, b"boom")])
    with pytest.raises(ArchiveError, match="路径穿越被拒绝"):
        unpack_zip(archive, tmp_path / "out")


@pytest.mark.parametrize("member_name", ["/etc/escape.txt", r"C:\escape.txt", "C:/escape.txt"])
def test_tar_absolute_paths_are_rejected(tmp_path: Path, member_name: str) -> None:
    archive = tmp_path / "absolute.tar.gz"
    _write_tar(archive, [(_tar_info(member_name, 4), b"boom")])
    with pytest.raises(ArchiveError, match="路径穿越被拒绝"):
        unpack_tar(archive, tmp_path / "out")


@pytest.mark.parametrize("extension,writer", [("zip", unpack_zip), ("tar.gz", unpack_tar)])
def test_deep_paths_are_rejected(tmp_path: Path, extension: str, writer) -> None:
    archive = tmp_path / f"deep.{extension}"
    name = "/".join(f"level-{index}" for index in range(13))
    if extension == "zip":
        _write_zip(archive, [_zip_info(name, b"x")])
    else:
        _write_tar(archive, [(_tar_info(name, 1), b"x")])
    limit = UnpackLimit()
    limit.max_depth = 12
    with pytest.raises(ArchiveError, match="嵌套深度超限"):
        writer(archive, tmp_path / "out", limit)


@pytest.mark.parametrize("extension,writer", [("zip", unpack_zip), ("tar.gz", unpack_tar)])
def test_file_count_limit_is_rejected(tmp_path: Path, extension: str, writer) -> None:
    archive = tmp_path / f"many.{extension}"
    if extension == "zip":
        _write_zip(archive, [_zip_info("first.txt", b"1"), _zip_info("second.txt", b"2")])
    else:
        _write_tar(archive, [(_tar_info("first.txt", 1), b"1"), (_tar_info("second.txt", 1), b"2")])
    limit = UnpackLimit()
    limit.max_files = 1
    with pytest.raises(ArchiveError, match="文件数超限"):
        writer(archive, tmp_path / "out", limit)


@pytest.mark.parametrize("extension,writer", [("zip", unpack_zip), ("tar.gz", unpack_tar)])
def test_single_file_limit_is_rejected(tmp_path: Path, extension: str, writer) -> None:
    archive = tmp_path / f"large.{extension}"
    if extension == "zip":
        _write_zip(archive, [_zip_info("large.bin", b"12345")])
    else:
        _write_tar(archive, [(_tar_info("large.bin", 5), b"12345")])
    limit = UnpackLimit()
    limit.max_single_file = 1
    with pytest.raises(ArchiveError, match="单文件超限"):
        writer(archive, tmp_path / "out", limit)


def test_duplicate_zip_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.zip"
    _write_zip(archive, [_zip_info("same.txt", b"first"), _zip_info("same.txt", b"second")])
    with pytest.raises(ArchiveError, match="重复路径被拒绝"):
        unpack_zip(archive, tmp_path / "out")


def test_conflicting_tar_member_paths_are_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "conflict.tar.gz"
    _write_tar(archive, [(_tar_info("logs", 4), b"file"), (_tar_info("logs/item.txt", 1), b"x")])
    with pytest.raises(ArchiveError, match="压缩包读取失败|路径冲突"):
        unpack_tar(archive, tmp_path / "out")


@pytest.mark.parametrize("extension", ["zip", "tar.gz"])
def test_empty_and_corrupt_archives_are_rejected(tmp_path: Path, extension: str) -> None:
    empty = tmp_path / f"empty.{extension}"
    empty.write_bytes(b"")
    corrupt = tmp_path / f"corrupt.{extension}"
    corrupt.write_bytes(b"not-an-archive")
    with pytest.raises(ArchiveError, match="压缩包读取失败"):
        (unpack_zip if extension == "zip" else unpack_tar)(empty, tmp_path / "empty-out")
    with pytest.raises(ArchiveError, match="压缩包读取失败"):
        (unpack_zip if extension == "zip" else unpack_tar)(corrupt, tmp_path / "corrupt-out")
