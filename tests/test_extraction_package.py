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
    assert (data_dir / "kpi/kpi/inner.csv").is_file()
    assert (data_dir / "logs/InnerService/logs/node/error.log").is_file()
    assert {path.as_posix() for path in catalog.paths()} >= {
        "config/system.ini",
        "kpi/kpi/inner.csv",
        "logs/InnerService/logs/node/error.log",
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


def test_nested_package_members_place_directly_in_category(tmp_path, monkeypatch) -> None:
    """嵌套子包成员不再保留来源包目录层。"""
    import hashlib

    from app.core.checksum import sha256_file
    from app.services import extraction

    env: Env = setup_env(tmp_path, monkeypatch)
    package = env.uploads / "kpi-nested-direct.zip"
    _zip(package, {"kpi/nested/kpi-media.csv": "metric,value\nsuccess,99\n"})
    before = package.read_bytes()
    data_dir = env.task_dir("task-kpi-direct")

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert hashlib.sha256(package.read_bytes()).hexdigest() == hashlib.sha256(before).hexdigest()
    assert (data_dir / "kpi/nested/kpi-media.csv").is_file()
    assert not (data_dir / "kpi/kpi-nested-direct").exists()
    assert any(
        item["target"] == "kpi/nested/kpi-media.csv" and item["source"] == ".main/kpi/nested/kpi-media.csv"
        for item in manifest["files"]
    )


# Manifest v5 严格契约测试
from app.services.extraction.manifest import (  # noqa: E402
    MANIFEST_VERSION,
    ManifestV5Error,
    loads_manifest,
    read_manifest,
    reusable_manifest,
    validate_manifest,
    write_manifest,
)

V5_SHA256_A = "a" * 64
V5_SHA256_B = "b" * 64
V5_PATH_LIMIT_FINGERPRINT = "9e7880498ff3f98434cb9ad1e8287dfd57e116912d277df982f93db495cf3ff9"
V5_TARGET_ROOTS = [
    "alarm",
    "basic",
    "chr",
    "debug",
    "host-debug",
    "host-system",
    "kpi",
    "logs",
    "mml",
    "operation-log",
    "other",
    "status",
]
V5_BUDGETS = {
    "max_archive_depth": 8,
    "max_member_path_depth": 12,
    "max_archive_files": 100000,
    "max_task_files": 200000,
    "max_file_bytes": 2147483648,
    "max_total_bytes": 3221225472,
}


def _v5_manifest() -> dict:
    """手工构造空 catalog 的最小有效 v5 manifest。"""
    return {
        "version": 5,
        "main": {
            "checksum": V5_SHA256_A,
            "count": 0,
            "evidence_path": ".main",
            "evidence_fingerprint": V5_SHA256_B,
            "reused": False,
        },
        "product": "UMF",
        "classification": {
            "config_fingerprint": V5_SHA256_A,
            "profile": "UMF",
            "snapshot": {
                "package_kind": "inspection",
                "product": "UMF",
                "profile": "UMF",
                "ruleset": "UMF_ARCHIVE_V1",
                "config_fingerprint": V5_SHA256_A,
                "extraction_policy_fingerprint": V5_SHA256_B,
                "path_limit_fingerprint": V5_PATH_LIMIT_FINGERPRINT,
                "scene_root": ".main",
                "target_roots": list(V5_TARGET_ROOTS),
                "budgets": dict(V5_BUDGETS),
            },
        },
        "path_limit": {
            "enabled": False,
            "limit": None,
            "fingerprint": V5_PATH_LIMIT_FINGERPRINT,
        },
        "entries": [],
        "ignored": [],
        "conflicts": [],
        "failures": [],
        "catalog": [],
        "summary": {
            "counts": {
                "landed": 0,
                "ignored": 0,
                "conflicts": 0,
                "failures": 0,
                "catalog": 0,
            },
            "by_route": {},
            "by_category": {},
            "by_action": {},
            "by_status": {"failed": 0, "ignored": 0, "landed": 0},
        },
    }


def _v5_entry() -> dict:
    """手工构造一个严格字段的成功落位记录。"""
    return {
        "source_relative": "dir/file.txt",
        "member_relative": None,
        "route_id": "route.a",
        "product": "UMF",
        "category": "config",
        "original_target": "basic/file.txt",
        "target": "basic/file.txt",
        "action": "copy",
        "status": "landed",
        "reason": None,
        "error_code": None,
        "sha256": V5_SHA256_A,
        "size": 1,
    }


def _v5_ignored() -> dict:
    """手工构造一个严格字段的忽略记录。"""
    return {
        "source_relative": "skip.txt",
        "member_relative": None,
        "route_id": "route.a",
        "product": "UMF",
        "category": None,
        "original_target": None,
        "target": None,
        "action": "ignore",
        "status": "ignored",
        "reason": "route_ignored",
        "error_code": None,
    }


def _v5_conflict() -> dict:
    """手工构造一个严格字段的冲突记录。"""
    return {
        "source_relative": "dir/file.txt",
        "member_relative": None,
        "original_target": "basic/file.txt",
        "target": "basic/file.txt",
        "digest": "0123456789ab",
        "status": "resolved",
    }


def _v5_failure() -> dict:
    """手工构造一个严格字段的失败记录。"""
    return {
        "source_relative": "bad.zip",
        "member_relative": None,
        "route_id": "route.a",
        "category": "config",
        "action": "expand",
        "error_code": "archive_corrupt",
        "reason": "压缩包已损坏",
    }


def _v5_catalog_item() -> dict:
    """手工构造一个严格字段的 catalog 记录。"""
    return {
        "path": "basic/file.txt",
        "category": "config",
        "route_id": "route.a",
        "source_relative": "dir/file.txt",
        "sha256": V5_SHA256_A,
        "size": 1,
    }


def _v5_manifest_with_records() -> dict:
    """返回包含四类审计记录且 summary 手工对齐的 v5 manifest。"""
    manifest = _v5_manifest()
    manifest["entries"] = [_v5_entry()]
    manifest["ignored"] = [_v5_ignored()]
    manifest["conflicts"] = [_v5_conflict()]
    manifest["failures"] = [_v5_failure()]
    manifest["catalog"] = [_v5_catalog_item()]
    manifest["summary"] = {
        "counts": {
            "landed": 1,
            "ignored": 1,
            "conflicts": 1,
            "failures": 1,
            "catalog": 1,
        },
        "by_route": {"route.a": 3},
        "by_category": {"config": 1},
        "by_action": {"copy": 1, "expand": 1, "ignore": 1},
        "by_status": {"failed": 1, "ignored": 1, "landed": 1},
    }
    return manifest


def test_manifest_v5_constants_and_empty_payload_are_valid() -> None:
    """v5 固定版本和 manifest.json 凭据名称必须与旧版本分离。"""
    assert MANIFEST_VERSION == 5
    assert validate_manifest(_v5_manifest())


def test_manifest_v5_can_write_and_read_strict_payload(tmp_path: Path) -> None:
    """空 catalog 的有效 v5 payload 可写入并重新读取。"""
    write_manifest(tmp_path, _v5_manifest())
    path = tmp_path / "manifest.json"

    assert path.is_file()
    assert read_manifest(tmp_path)["version"] == 5


def test_duplicate_json_key_makes_manifest_invalid() -> None:
    """JSON 重复 key 必须在解析阶段被拒绝。"""
    text = '{"version": 5, "version": 4}'

    with pytest.raises(ManifestV5Error, match="重复 JSON key"):
        loads_manifest(text)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update({"extra": True}), "未知顶层字段"),
        (lambda payload: payload.pop("product"), "缺少顶层字段"),
    ],
)
def test_manifest_v5_top_level_keys_are_strict(mutate, message: str) -> None:
    """未知或缺失顶层键必须使 manifest 无效。"""
    manifest = _v5_manifest()
    mutate(manifest)

    assert not validate_manifest(manifest)
    with pytest.raises(ManifestV5Error, match=message):
        loads_manifest(__import__("json").dumps(manifest))


@pytest.mark.parametrize(
    ("key", "item"),
    [
        ("entries", _v5_entry()),
        ("ignored", _v5_ignored()),
        ("conflicts", _v5_conflict()),
        ("failures", _v5_failure()),
        ("catalog", _v5_catalog_item()),
    ],
)
def test_manifest_v5_record_keys_are_strict(key: str, item: dict) -> None:
    """每类审计记录必须严格匹配冻结字段集合。"""
    manifest = _v5_manifest_with_records()
    manifest[key][0]["extra"] = True

    assert not validate_manifest(manifest)
    del item


def test_manifest_v5_records_with_all_strict_fields_are_valid() -> None:
    """entries/ignored/conflicts/failures/catalog 的完整字段组合必须通过。"""
    assert validate_manifest(_v5_manifest_with_records())


def test_manifest_v5_failure_route_id_must_not_be_null() -> None:
    """失败记录必须能追溯到命中的 route，不得使用 null route_id。"""
    manifest = _v5_manifest_with_records()
    manifest["failures"][0]["route_id"] = None
    manifest["summary"]["by_route"] = {"route.a": 2}

    assert not validate_manifest(manifest)


def test_manifest_v5_accepts_member_not_selected_from_select_route() -> None:
    """select_and_decompress 的未选成员必须保留 route action 并进入 ignored。"""
    manifest = _v5_manifest()
    ignored = _v5_ignored()
    ignored.update(
        {
            "source_relative": "archive.zip",
            "member_relative": "inner.txt",
            "category": "chr",
            "action": "select_and_decompress",
            "reason": "member_not_selected",
        }
    )
    manifest["ignored"] = [ignored]
    manifest["summary"] = {
        "counts": {
            "landed": 0,
            "ignored": 1,
            "conflicts": 0,
            "failures": 0,
            "catalog": 0,
        },
        "by_route": {"route.a": 1},
        "by_category": {"chr": 1},
        "by_action": {"select_and_decompress": 1},
        "by_status": {"failed": 0, "ignored": 1, "landed": 0},
    }

    assert validate_manifest(manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["summary"]["counts"].update({"landed": 2}),
        lambda manifest: manifest["summary"]["counts"].update({"catalog": 2}),
        lambda manifest: manifest["summary"]["by_status"].update({"landed": 2}),
    ],
)
def test_manifest_v5_summary_must_match_arrays(mutate) -> None:
    """summary 计数或状态计数与数组不一致时必须失败。"""
    manifest = _v5_manifest_with_records()
    mutate(manifest)

    assert not validate_manifest(manifest)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_manifest_versions_1_to_4_cannot_be_reused(tmp_path: Path, version: int) -> None:
    """旧版本 manifest 即使存在也不得复用为 v5 事实。"""
    manifest = _v5_manifest()
    manifest["version"] = version
    (tmp_path / "manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")

    assert reusable_manifest(tmp_path, V5_SHA256_A) is None
