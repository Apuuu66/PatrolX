"""解压服务的包形态、幂等、损坏重建与局部失败测试。"""

import gzip
import zipfile
from pathlib import Path

import pytest

from app.core.archive import ArchiveError
from app.core.checksum import sha256_file
from app.services import extraction
from app.services.scanning import TaskFileCatalog
from tests.baseline_helpers import Env, setup_env


def _zip(path: Path, files: dict[str, str | bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def _gz_bytes(content: str) -> bytes:
    return gzip.compress(content.encode("utf-8"))


def _nested_package(env: Env) -> Path:
    kpi_zip = env.uploads / "_build/kpi_data.zip"
    _zip(kpi_zip, {"kpi/inner.csv": "metric,value\nsuccess,99\n"})
    log_zip = env.uploads / "_build/ServiceLog_inner.zip"
    _zip(log_zip, {"InnerService/logs/node/error.log": "ERROR inner\n"})
    package = env.uploads / "nested-package.zip"
    _zip(
        package,
        {
            "kpi_outer.zip": kpi_zip.read_bytes(),
            "ServiceLog_inner.zip": log_zip.read_bytes(),
            "config/system.ini": "[app]\nname=app\n",
        },
    )
    return package


def test_large_main_package_expands_nested_log_and_kpi(tmp_path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _nested_package(env)
    data_dir = env.task_dir("task-large")

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))
    catalog = TaskFileCatalog.build(data_dir)

    assert manifest["main"]["count"] == 3
    assert any(item["category"] == "kpi" for item in manifest["subpackages"])
    assert (data_dir / ".main/kpi_outer.zip").is_file()
    assert (data_dir / "kpi/kpi_outer/kpi/inner.csv").is_file()
    assert (data_dir / "logs/ServiceLog_inner/InnerService/logs/node/error.log").is_file()
    assert {path.as_posix() for path in catalog.paths()} >= {
        "config/system.ini",
        "kpi/kpi_outer/kpi/inner.csv",
        "logs/ServiceLog_inner/InnerService/logs/node/error.log",
    }


def test_small_single_category_package_expands_directly(tmp_path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "kpi-only.zip"
    _zip(package, {"kpi/kpi-api-5.csv": "metric,value\nsuccess,99\n"})
    data_dir = env.task_dir("task-small")

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))
    catalog = TaskFileCatalog.build(data_dir)

    assert manifest["main"]["count"] == 1
    assert [path.as_posix() for path in catalog.paths()] == ["kpi/kpi-api-5.csv"]


def test_repeat_extraction_reuses_manifest_and_site(tmp_path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _nested_package(env)
    checksum = sha256_file(package)
    data_dir = env.task_dir("task-repeat")
    before = {path.relative_to(data_dir).as_posix() for path in data_dir.rglob("*")}

    first = extraction.extract_main_site(package, data_dir, checksum)
    first_snapshot = {path.relative_to(data_dir).as_posix() for path in data_dir.rglob("*")}
    first_manifest = (data_dir / extraction.MANIFEST_NAME).read_text(encoding="utf-8")
    messages: list[str] = []

    second = extraction.extract_main_site(
        package,
        data_dir,
        checksum,
        log=lambda _level, message, **_detail: messages.append(message),
    )
    after = {path.relative_to(data_dir).as_posix() for path in data_dir.rglob("*")}

    assert first["main"]["reused"] is False
    assert second["main"]["reused"] is True
    assert messages == ["解压现场复用"]
    assert (data_dir / extraction.MANIFEST_NAME).read_text(encoding="utf-8") == first_manifest
    assert after == first_snapshot
    del before


def test_corrupt_manifest_is_rebuilt_with_same_evidence(tmp_path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = _nested_package(env)
    checksum = sha256_file(package)
    data_dir = env.task_dir("task-corrupt")
    extraction.extract_main_site(package, data_dir, checksum)
    evidence = {path.name for path in (data_dir / ".main").iterdir()}
    manifest_path = data_dir / extraction.MANIFEST_NAME
    manifest_path.write_text("{broken", encoding="utf-8")

    manifest = extraction.extract_main_site(package, data_dir, checksum)

    assert manifest["main"]["reused"] is False
    assert {path.name for path in (data_dir / ".main").iterdir()} == evidence
    assert extraction.reusable_manifest(data_dir, checksum) is not None


def test_failed_main_package_is_blocked(tmp_path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "bad-main.zip"
    package.write_text("not archive", encoding="utf-8")
    data_dir = env.task_dir("task-failed")

    with pytest.raises(ArchiveError, match="压缩包读取失败"):
        extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert not (data_dir / extraction.MANIFEST_NAME).exists()
    assert not (data_dir / ".main").exists()


def test_nested_and_gzip_local_failures_continue(tmp_path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "partial-failures.zip"
    _zip(
        package,
        {
            "ServiceLog_bad.zip": b"not archive",
            "logs/node/bad.log.gz": b"not gzip",
            "config/system.ini": "[app]\nname=app\n",
        },
    )
    data_dir = env.task_dir("task-partial")

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert (data_dir / "config/system.ini").is_file()
    assert any(item["status"] == "failed" for item in manifest["subpackages"])
    assert any(item["status"] == "failed" for item in manifest["log_gz"])
    assert extraction.category_failures(manifest, "logs")
    assert TaskFileCatalog.build(data_dir).paths() == [Path("config/system.ini")]
