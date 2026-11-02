"""压缩包安全解压的健壮性测试。"""

import io
import stat
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.core.archive import (
    ArchiveError,
    UnpackLimit,
    unpack_gzip,
    unpack_tar,
    unpack_zip,
)


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


def _set_zip_declared_size(path: Path, size: int) -> None:
    """直接写入 ZIP 本地和中央目录字段，构造展开前可见的声明大小。"""
    payload = bytearray(path.read_bytes())
    local_pos = payload.rindex(b"PK\x03\x04")
    central_pos = payload.rindex(b"PK\x01\x02")
    struct.pack_into("<I", payload, local_pos + 22, size)
    struct.pack_into("<I", payload, central_pos + 24, size)
    path.write_bytes(payload)


def _write_raw_nul_zip(path: Path) -> None:
    """用等长占位符保留 ZIP 原始成员名中的 NUL 字节。"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("DIRXNAME.TXT", b"x")
    payload = path.read_bytes().replace(b"DIRXNAME.TXT", b"dir\x00name.txt")
    path.write_bytes(payload)


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
    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(archive, tmp_path / "out")
    assert exc_info.value.error_code == "unsafe_path"


@pytest.mark.parametrize("member_name", ["/etc/escape.txt", r"C:\escape.txt", "C:/escape.txt"])
def test_tar_absolute_paths_are_rejected(tmp_path: Path, member_name: str) -> None:
    archive = tmp_path / "absolute.tar.gz"
    _write_tar(archive, [(_tar_info(member_name, 4), b"boom")])
    with pytest.raises(ArchiveError) as exc_info:
        unpack_tar(archive, tmp_path / "out")
    assert exc_info.value.error_code == "unsafe_path"


@pytest.mark.parametrize("extension,writer", [("zip", unpack_zip), ("tar.gz", unpack_tar)])
def test_deep_paths_are_rejected(tmp_path: Path, extension: str, writer) -> None:
    archive = tmp_path / f"deep.{extension}"
    name = "/".join(f"level-{index}" for index in range(13))
    if extension == "zip":
        _write_zip(archive, [_zip_info(name, b"x")])
    else:
        _write_tar(archive, [(_tar_info(name, 1), b"x")])
    with pytest.raises(ArchiveError) as exc_info:
        writer(archive, tmp_path / "out")
    assert exc_info.value.error_code == "member_path_depth_exceeded"
    assert exc_info.value.details["depth"] == 13


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
    with pytest.raises(ArchiveError) as exc_info:
        unpack_tar(archive, tmp_path / "out")
    assert exc_info.value.error_code == "unsafe_path"


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


# v5 稳定错误码与固定预算边界测试
ARCHIVE_DEPTH_LIMIT = 8
MEMBER_PATH_DEPTH_LIMIT = 12
ARCHIVE_FILE_LIMIT = 100_000
TASK_FILE_LIMIT = 200_000
FILE_BYTE_LIMIT = 2 * 1024 * 1024 * 1024
TOTAL_BYTE_LIMIT = 3 * 1024 * 1024 * 1024


def test_unpack_limit_uses_v5_fixed_defaults() -> None:
    """核心归档预算必须固定为 v5 冻结值，不提供任务级覆盖。"""
    limit = UnpackLimit()

    assert limit.max_depth == ARCHIVE_DEPTH_LIMIT
    assert limit.max_member_path_depth == MEMBER_PATH_DEPTH_LIMIT
    assert limit.max_files == ARCHIVE_FILE_LIMIT
    assert limit.max_single_file == FILE_BYTE_LIMIT
    assert limit.max_total_bytes == TOTAL_BYTE_LIMIT


@pytest.mark.parametrize(
    "member_name",
    [
        "../escape.txt",
        "/etc/escape.txt",
        r"C:\escape.txt",
        "C:/escape.txt",
        "C:relative.txt",
        "dir\x00name.txt",
        r"foo\..\bar.txt",
    ],
)
def test_unsafe_member_paths_raise_stable_code(tmp_path: Path, member_name: str) -> None:
    """绝对路径、穿越、NUL 和危险反斜杠路径必须返回 unsafe_path。"""
    archive = tmp_path / "unsafe.zip"
    if member_name == "dir\x00name.txt":
        _write_raw_nul_zip(archive)
    else:
        _write_zip(archive, [_zip_info(member_name, b"x")])

    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(archive, tmp_path / "out")

    assert exc_info.value.error_code == "unsafe_path"


@pytest.mark.parametrize("extension", ["zip", "tar.gz"])
def test_member_error_is_recorded_and_safe_members_continue(
    tmp_path: Path,
    extension: str,
) -> None:
    """单个不安全成员必须记录稳定错误码，同归档的安全成员继续落位。"""
    archive = tmp_path / f"partial.{extension}"
    member_errors: list[ArchiveError] = []
    if extension == "zip":
        _write_zip(
            archive,
            [
                _zip_info("../evil.txt", b"evil"),
                _zip_info("ok.txt", b"ok"),
            ],
        )
        writer = unpack_zip
    else:
        _write_tar(
            archive,
            [
                (_tar_info("../evil.txt", 4), b"evil"),
                (_tar_info("ok.txt", 2), b"ok"),
            ],
        )
        writer = unpack_tar

    count = writer(
        archive,
        tmp_path / "out",
        on_member_error=member_errors.append,
    )

    assert count == 1
    assert (tmp_path / "out/ok.txt").is_file()
    assert not (tmp_path.parent / "evil.txt").exists()
    assert len(member_errors) == 1
    assert member_errors[0].error_code == "unsafe_path"


@pytest.mark.parametrize(
    "members",
    [
        [
            _zip_info("dir/file.txt", b"first"),
            _zip_info("DIR/FILE.TXT", b"second"),
        ],
        [
            _zip_info("dir/file.txt", b"first"),
            _zip_info(r"dir\file.txt", b"second"),
        ],
    ],
)
def test_zip_duplicate_members_are_case_and_separator_normalized(
    tmp_path: Path,
    members: list[tuple[zipfile.ZipInfo, bytes]],
) -> None:
    """大小写或分隔符归一后重复的成员必须返回 duplicate_member。"""
    archive = tmp_path / "duplicate.zip"
    _write_zip(archive, members)

    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(archive, tmp_path / "out")

    assert exc_info.value.error_code == "duplicate_member"


def test_tar_duplicate_members_are_casefold_normalized(tmp_path: Path) -> None:
    """TAR 成员大小写归一后重复时必须返回 duplicate_member。"""
    archive = tmp_path / "duplicate.tar.gz"
    _write_tar(
        archive,
        [
            (_tar_info("dir/file.txt", 1), b"a"),
            (_tar_info("DIR/FILE.TXT", 1), b"b"),
        ],
    )

    with pytest.raises(ArchiveError) as exc_info:
        unpack_tar(archive, tmp_path / "out")

    assert exc_info.value.error_code == "duplicate_member"


@pytest.mark.parametrize("depth", [MEMBER_PATH_DEPTH_LIMIT, MEMBER_PATH_DEPTH_LIMIT + 1])
def test_member_path_depth_boundary(tmp_path: Path, depth: int) -> None:
    """成员路径等于 12 段允许，第 13 段拒绝并返回稳定错误码。"""
    name = "/".join(f"level-{index}" for index in range(depth))
    archive_name = f"member-depth-{depth}.zip"
    output = tmp_path / "out"
    full_archive = tmp_path / archive_name
    _write_zip(full_archive, [_zip_info(name, b"x")])

    if depth == MEMBER_PATH_DEPTH_LIMIT:
        assert unpack_zip(full_archive, output) == 1
    else:
        with pytest.raises(ArchiveError) as exc_info:
            unpack_zip(full_archive, output)
        assert exc_info.value.error_code == "member_path_depth_exceeded"


def test_archive_file_count_boundary(tmp_path: Path) -> None:
    """单归档等于 100,000 文件允许，第 100,001 个文件拒绝。"""
    allowed = tmp_path / "allowed.zip"
    with zipfile.ZipFile(allowed, "w", compression=zipfile.ZIP_STORED) as zf:
        for index in range(ARCHIVE_FILE_LIMIT):
            zf.writestr(f"file-{index:06d}.txt", b"")

    assert unpack_zip(allowed, tmp_path / "allowed-out") == ARCHIVE_FILE_LIMIT

    rejected = tmp_path / "rejected.zip"
    with zipfile.ZipFile(rejected, "w", compression=zipfile.ZIP_STORED) as zf:
        for index in range(ARCHIVE_FILE_LIMIT + 1):
            zf.writestr(f"file-{index:06d}.txt", b"")

    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(rejected, tmp_path / "rejected-out")

    assert exc_info.value.error_code == "file_count_exceeded"


def test_task_file_count_boundary(tmp_path: Path) -> None:
    """任务累计等于 200,000 文件允许，第 200,001 个文件拒绝。"""
    from app.services.extraction.budget import ExtractionBudget

    marker = tmp_path / "marker.txt"
    marker.write_text("x", encoding="utf-8")
    budget = ExtractionBudget()
    budget.files = TASK_FILE_LIMIT - 1

    assert budget.charge_file(marker) == 1

    with pytest.raises(ArchiveError) as exc_info:
        budget.charge_file(marker)

    assert exc_info.value.error_code == "task_file_count_exceeded"


@pytest.mark.parametrize(
    "size",
    [FILE_BYTE_LIMIT, FILE_BYTE_LIMIT + 1],
)
def test_single_file_size_boundary_using_zip_metadata(
    tmp_path: Path,
    size: int,
) -> None:
    """ZIP 元数据等于 2 GiB 允许，超过 2 GiB 在展开前拒绝。"""
    info = zipfile.ZipInfo("large.bin")
    info.file_size = size
    archive = tmp_path / f"large-{size}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, b"")
    _set_zip_declared_size(archive, size)

    if size == FILE_BYTE_LIMIT:
        assert unpack_zip(archive, tmp_path / "out") == 1
    else:
        with pytest.raises(ArchiveError) as exc_info:
            unpack_zip(archive, tmp_path / "out")
        assert exc_info.value.error_code == "file_too_large"


def test_total_bytes_boundary() -> None:
    """累计解压字节等于 3 GiB 允许，超过 3 GiB 拒绝。"""
    from app.services.extraction.budget import ExtractionBudget

    budget = ExtractionBudget()
    budget.bytes = TOTAL_BYTE_LIMIT - 1
    budget.charge_gzip_chunk(1)

    with pytest.raises(ArchiveError) as exc_info:
        budget.charge_gzip_chunk(1)

    assert exc_info.value.error_code == "total_bytes_exceeded"


def test_gzip_target_symlink_is_rejected(tmp_path: Path) -> None:
    """gzip 输出目标本身是符号链接时必须拒绝，不能跟随写入。"""
    import gzip

    archive = tmp_path / "input.log.gz"
    archive.write_bytes(gzip.compress(b"abc"))
    through_link = tmp_path / "through-link.txt"
    target = tmp_path / "linked.txt"
    target.symlink_to(through_link)

    with pytest.raises(ArchiveError) as exc_info:
        unpack_gzip(archive, target)

    assert exc_info.value.error_code == "link_rejected"
    assert not through_link.exists()


def test_corrupt_archive_uses_stable_code(tmp_path: Path) -> None:
    """无法读取的 ZIP 必须返回 archive_corrupt。"""
    archive = tmp_path / "corrupt.zip"
    archive.write_bytes(b"not a zip")

    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(archive, tmp_path / "out")

    assert exc_info.value.error_code == "archive_corrupt"


def test_target_out_of_bounds_uses_stable_code(tmp_path: Path) -> None:
    """目标路径越出任务根必须返回 unsafe_path。"""
    from app.services.extraction.layout import _safe_destination

    with pytest.raises(ArchiveError) as exc_info:
        _safe_destination(tmp_path / "data", Path("../escape.txt"))

    assert exc_info.value.error_code == "unsafe_path"


def test_zip_file_count_includes_rejected_non_directory_members(tmp_path: Path) -> None:
    """文件数先按全部非目录成员统计，非法路径成员也不能绕过单归档预算。"""
    archive = tmp_path / "count-invalid.zip"
    _write_zip(
        archive,
        [
            _zip_info("../rejected.txt", b"x"),
            _zip_info("safe.txt", b"x"),
        ],
    )
    limit = UnpackLimit()
    limit.max_files = 1

    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(archive, tmp_path / "out", limit=limit)

    assert exc_info.value.error_code == "file_count_exceeded"


def test_tar_file_count_includes_rejected_non_directory_members(tmp_path: Path) -> None:
    """TAR 也必须先统计全部非目录成员，非法路径成员不能绕过预算。"""
    archive = tmp_path / "count-invalid.tar.gz"
    _write_tar(
        archive,
        [
            (_tar_info("../rejected.txt", 1), b"x"),
            (_tar_info("safe.txt", 1), b"x"),
        ],
    )
    limit = UnpackLimit()
    limit.max_files = 1

    with pytest.raises(ArchiveError) as exc_info:
        unpack_tar(archive, tmp_path / "out", limit=limit)

    assert exc_info.value.error_code == "file_count_exceeded"


def test_unix_zip_directory_without_trailing_slash_is_not_a_file(tmp_path: Path) -> None:
    """Unix ZIP 目录成员即使名称无结尾斜杠也不计文件数且深度受限。"""
    archive = tmp_path / "unix-directory.zip"
    directory = zipfile.ZipInfo("directory")
    directory.create_system = 3
    directory.external_attr = (stat.S_IFDIR | 0o755) << 16
    _write_zip(archive, [(directory, b""), _zip_info("safe.txt", b"x")])
    limit = UnpackLimit()
    limit.max_files = 1

    assert unpack_zip(archive, tmp_path / "out", limit=limit) == 1
    assert (tmp_path / "out/safe.txt").is_file()


def test_unix_zip_directory_member_path_depth_is_checked(tmp_path: Path) -> None:
    """目录成员同样适用 12 段成员路径深度限制。"""
    archive = tmp_path / "deep-directory.zip"
    directory = zipfile.ZipInfo("/".join(f"level-{index}" for index in range(13)))
    directory.create_system = 3
    directory.external_attr = (stat.S_IFDIR | 0o755) << 16
    _write_zip(archive, [(directory, b"")])

    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(archive, tmp_path / "out")

    assert exc_info.value.error_code == "member_path_depth_exceeded"


@pytest.mark.parametrize("extension", ["zip", "tar.gz"])
def test_archive_member_parent_symlink_is_rejected(tmp_path: Path, extension: str) -> None:
    """成员目标已有父目录链接时必须拒绝，不能跟随到任务根之外。"""
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "dir").symlink_to(outside, target_is_directory=True)
    archive = tmp_path / f"parent-link.{extension}"
    if extension == "zip":
        _write_zip(archive, [_zip_info("dir/file.txt", b"x")])
        writer = unpack_zip
    else:
        _write_tar(archive, [(_tar_info("dir/file.txt", 1), b"x")])
        writer = unpack_tar

    with pytest.raises(ArchiveError) as exc_info:
        writer(archive, output)

    assert exc_info.value.error_code == "link_rejected"
    assert not (outside / "file.txt").exists()


@pytest.mark.parametrize("extension", ["zip", "tar.gz"])
def test_archive_root_symlink_is_rejected(tmp_path: Path, extension: str) -> None:
    """归档输出根自身是链接时不得在解析后跟随到任务现场外。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "out"
    output.symlink_to(outside, target_is_directory=True)
    archive = tmp_path / f"root-link.{extension}"
    if extension == "zip":
        _write_zip(archive, [_zip_info("safe.txt", b"x")])
        writer = unpack_zip
    else:
        _write_tar(archive, [(_tar_info("safe.txt", 1), b"x")])
        writer = unpack_tar

    with pytest.raises(ArchiveError) as exc_info:
        writer(archive, output)

    assert exc_info.value.error_code == "link_rejected"
    assert not (outside / "safe.txt").exists()


def test_safe_destination_rejects_symlinked_task_root(tmp_path: Path) -> None:
    """任务根本身为链接时，_safe_destination 必须在 resolve 前拒绝。"""
    from app.services.extraction.layout import _safe_destination

    outside = tmp_path / "outside"
    outside.mkdir()
    data_dir = tmp_path / "data"
    data_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArchiveError) as exc_info:
        _safe_destination(data_dir, Path("safe.txt"))

    assert exc_info.value.error_code == "link_rejected"
    assert not (outside / "safe.txt").exists()


def test_gzip_target_parent_symlink_is_rejected(tmp_path: Path) -> None:
    """gzip 目标父目录是链接时必须在解析前拒绝。"""
    import gzip

    archive = tmp_path / "input.log.gz"
    archive.write_bytes(gzip.compress(b"abc"))
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArchiveError) as exc_info:
        unpack_gzip(archive, linked_parent / "output.log")

    assert exc_info.value.error_code == "link_rejected"
    assert not (outside / "output.log").exists()


def test_gzip_allows_link_above_target_parent(tmp_path: Path) -> None:
    """目标父目录之上的平台级祖先后缀链接不应被误判为 gzip 链接逃逸。"""
    import gzip

    archive = tmp_path / "input.log.gz"
    archive.write_bytes(gzip.compress(b"abc"))
    real_parent = tmp_path / "real-platform-parent"
    real_task = real_parent / "task"
    real_task.mkdir(parents=True)
    platform_link = tmp_path / "platform-link"
    platform_link.symlink_to(real_parent, target_is_directory=True)
    target = platform_link / "task" / "output.log"

    written = unpack_gzip(archive, target)

    assert written == 3
    assert (real_task / "output.log").read_bytes() == b"abc"


@pytest.mark.parametrize("exception_type", [RuntimeError, NotImplementedError, struct.error, EOFError])
def test_zip_runtime_style_archive_failures_map_to_archive_corrupt(
    tmp_path: Path,
    monkeypatch,
    exception_type,
) -> None:
    """加密、不支持压缩方法、结构错误和截断读取都稳定映射为 archive_corrupt。"""
    import app.core.archive as archive_module

    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"placeholder")

    def raising(_archive: Path) -> None:
        raise exception_type("failed")

    monkeypatch.setattr(archive_module, "_reject_unsafe_zip_raw_names", raising)

    with pytest.raises(ArchiveError) as exc_info:
        unpack_zip(archive, tmp_path / "out")

    assert exc_info.value.error_code == "archive_corrupt"
