"""解压服务的包形态、幂等、损坏重建与局部失败测试。"""

import gzip
import json
import os
import zipfile
from dataclasses import replace
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


def test_nested_package_rejects_bad_member_and_ingests_valid_member(tmp_path, monkeypatch) -> None:
    """子包单成员穿越失败不能中断同包子包中其他合法成员的落位。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    child = env.uploads / "_build/partial-nested.zip"
    _zip(
        child,
        {
            "../evil.txt": "must not escape",
            "config/safe.ini": "[app]\nname=safe\n",
        },
    )
    package = env.uploads / "nested-member-isolation.zip"
    _zip(package, {"config/partial-nested.zip": child.read_bytes()})
    data_dir = env.task_dir("task-nested-member-isolation")

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    assert (data_dir / "config/config/safe.ini").is_file()
    assert Path("config/config/safe.ini") in TaskFileCatalog.build(data_dir).paths()
    assert any(
        item["source"] == "config/partial-nested.zip"
        and item.get("error_code") == "unsafe_path"
        and "evil.txt" in item["reason"]
        for item in manifest["rejected"]
    )
    assert not (data_dir / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()


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
import app.services.extraction.manifest as manifest_module  # noqa: E402
from app.services.extraction.audit import conflict_digest  # noqa: E402
from app.services.extraction.manifest import (  # noqa: E402
    MANIFEST_VERSION,
    ManifestReuseContext,
    ManifestV5Error,
    evidence_fingerprint,
    loads_manifest,
    read_manifest,
    reusable_manifest,
    validate_manifest,
    write_manifest,
)
from app.services.extraction.manifest import sha256_file as manifest_sha256_file  # noqa: E402

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
V5_CONFLICT_DIGEST = conflict_digest("UMF", "dir/file.txt", "")
V5_RESOLVED_TARGET = f"basic/file__{V5_CONFLICT_DIGEST}.txt"


def _v5_reuse_context(manifest: dict | None = None) -> ManifestReuseContext:
    """从 manifest 快照构造完整复用上下文。"""
    manifest = manifest or _v5_manifest()
    snapshot = manifest["classification"]["snapshot"]
    return ManifestReuseContext(
        checksum=manifest["main"]["checksum"],
        product=manifest["product"],
        package_kind=snapshot["package_kind"],
        profile=snapshot["profile"],
        config_fingerprint=snapshot["config_fingerprint"],
        extraction_policy_fingerprint=snapshot["extraction_policy_fingerprint"],
        path_limit=dict(manifest["path_limit"]),
        scene_root=snapshot["scene_root"],
        target_roots=tuple(snapshot["target_roots"]),
        budgets=dict(snapshot["budgets"]),
    )


def _materialized_v5_manifest(data_dir: Path, *, with_conflict: bool = False) -> dict:
    """构造包含真实证据与 catalog 文件的合法 v5 现场。"""
    evidence_file = data_dir / ".main/dir/file.txt"
    evidence_file.parent.mkdir(parents=True)
    evidence_file.write_text("x", encoding="utf-8")
    digest = manifest_sha256_file(evidence_file)
    count, fingerprint = evidence_fingerprint(data_dir)
    manifest = _v5_manifest()
    manifest["main"].update({"count": count, "evidence_fingerprint": fingerprint})
    entry = _v5_entry()
    entry.update({"sha256": digest, "size": 1})
    if not with_conflict:
        entry.update({"target": entry["original_target"]})
    manifest["entries"] = [entry]
    catalog = _v5_catalog_item()
    catalog.update({"path": entry["target"], "sha256": digest, "size": 1})
    manifest["catalog"] = [catalog]
    manifest["summary"] = {
        "counts": {
            "landed": 1,
            "ignored": 0,
            "conflicts": 0,
            "failures": 0,
            "catalog": 1,
        },
        "by_route": {"route.a": 1},
        "by_category": {"config": 1},
        "by_action": {"copy": 1},
        "by_status": {"failed": 0, "ignored": 0, "landed": 1},
    }
    if with_conflict:
        manifest["conflicts"] = [_v5_conflict()]
        manifest["summary"]["counts"]["conflicts"] = 1
    target = data_dir / entry["target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    write_manifest(data_dir, manifest)
    return manifest


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
        "target": V5_RESOLVED_TARGET,
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
        "target": V5_RESOLVED_TARGET,
        "digest": V5_CONFLICT_DIGEST,
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
        "path": V5_RESOLVED_TARGET,
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

    assert reusable_manifest(tmp_path, _v5_reuse_context(manifest)) is None


def test_write_manifest_uses_same_directory_atomic_replace_and_fsync(tmp_path: Path, monkeypatch) -> None:
    """发布必须同目录 staging、fsync 后原子替换，并输出键排序 JSON。"""
    staged_paths: list[Path] = []
    fsync_fds: list[int] = []
    real_replace = os.replace
    real_fsync = os.fsync

    def tracking_replace(source, destination) -> None:
        staged_paths.append(Path(source))
        assert Path(source).parent == Path(destination).parent == tmp_path
        real_replace(source, destination)

    def tracking_fsync(fd: int) -> None:
        fsync_fds.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(manifest_module.os, "replace", tracking_replace)
    monkeypatch.setattr(manifest_module.os, "fsync", tracking_fsync)

    manifest = _v5_manifest()
    write_manifest(tmp_path, manifest)

    assert len(staged_paths) == 1
    assert not staged_paths[0].exists()
    assert len(fsync_fds) >= 2
    text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert text == json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    assert list(json.loads(text)) == sorted(json.loads(text))


def test_write_manifest_rejects_manifest_symlink(tmp_path: Path) -> None:
    """manifest.json 自身是链接时不得跟随写入。"""
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "manifest.json").symlink_to(outside)

    with pytest.raises(ManifestV5Error, match="链接"):
        write_manifest(data_dir, _v5_manifest())

    assert outside.read_text(encoding="utf-8") == "keep"


def test_write_manifest_cleans_same_directory_staging_after_replace_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """原子替换失败时必须清理同目录 staging，且不发布半成品。"""
    staged_paths: list[Path] = []

    def failing_replace(source, _destination) -> None:
        staged_paths.append(Path(source))
        raise OSError("replace failed")

    monkeypatch.setattr(manifest_module.os, "replace", failing_replace)

    with pytest.raises(ManifestV5Error, match="无法原子发布"):
        write_manifest(tmp_path, _v5_manifest())

    assert staged_paths and all(not path.exists() for path in staged_paths)
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize(
    "catalog_state",
    ["missing", "wrong_digest", "wrong_size", "directory", "symlink", "parent_symlink"],
)
def test_write_manifest_verifies_catalog_before_publish(tmp_path: Path, catalog_state: str) -> None:
    """catalog 不可验证时不得发布 manifest，也不能跟随 catalog 链接。"""
    manifest = _v5_manifest_with_records()
    target = tmp_path / manifest["catalog"][0]["path"]
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_target = outside / target.name
    outside_target.write_text("outside", encoding="utf-8")

    if catalog_state in {"wrong_digest", "wrong_size"}:
        target.parent.mkdir(parents=True)
        target.write_text("x" if catalog_state == "wrong_digest" else "xx", encoding="utf-8")
    if catalog_state == "wrong_size":
        digest = manifest_sha256_file(target)
        manifest["entries"][0]["sha256"] = digest
        manifest["catalog"][0]["sha256"] = digest
    elif catalog_state == "directory":
        target.mkdir(parents=True)
    elif catalog_state == "symlink":
        target.parent.mkdir(parents=True)
        target.symlink_to(outside_target)
    elif catalog_state == "parent_symlink":
        target.parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ManifestV5Error, match="catalog"):
        write_manifest(tmp_path, manifest)

    assert not (tmp_path / "manifest.json").exists()
    assert outside_target.read_text(encoding="utf-8") == "outside"


def test_reusable_manifest_rejects_catalog_parent_symlink(tmp_path: Path) -> None:
    """catalog 任一父目录是链接时不能复用分类现场。"""
    manifest = _materialized_v5_manifest(tmp_path)
    target = tmp_path / manifest["catalog"][0]["path"]
    target.unlink()
    target.parent.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / target.name).write_text("x", encoding="utf-8")
    target.parent.symlink_to(outside, target_is_directory=True)

    assert reusable_manifest(tmp_path, _v5_reuse_context(manifest)) is None


@pytest.mark.parametrize("record_kind", ["ignored", "failures"])
def test_reusable_manifest_rejects_missing_non_entry_evidence(
    tmp_path: Path,
    record_kind: str,
) -> None:
    """ignored/failure 的来源文件也必须是 .main 内真实普通文件。"""
    manifest = _materialized_v5_manifest(tmp_path)
    if record_kind == "ignored":
        manifest["ignored"] = [_v5_ignored()]
        manifest["summary"]["counts"]["ignored"] = 1
        manifest["summary"]["by_status"]["ignored"] = 1
        manifest["summary"]["by_action"]["ignore"] = 1
    else:
        manifest["failures"] = [_v5_failure()]
        manifest["summary"]["counts"]["failures"] = 1
        manifest["summary"]["by_status"]["failed"] = 1
        manifest["summary"]["by_action"]["expand"] = 1
    manifest["summary"]["by_route"]["route.a"] = 2
    write_manifest(tmp_path, manifest)

    assert reusable_manifest(tmp_path, _v5_reuse_context(manifest)) is None


def test_reusable_manifest_rejects_missing_evidence_source(tmp_path: Path) -> None:
    """entry.source_relative 必须回溯到 .main 内真实普通文件。"""
    manifest = _v5_manifest()
    entry = _v5_entry()
    entry.update({"target": entry["original_target"]})
    catalog = _v5_catalog_item()
    catalog["path"] = entry["target"]
    manifest["entries"] = [entry]
    manifest["catalog"] = [catalog]
    manifest["summary"] = {
        "counts": {"landed": 1, "ignored": 0, "conflicts": 0, "failures": 0, "catalog": 1},
        "by_route": {"route.a": 1},
        "by_category": {"config": 1},
        "by_action": {"copy": 1},
        "by_status": {"failed": 0, "ignored": 0, "landed": 1},
    }
    target = tmp_path / entry["target"]
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    digest = manifest_sha256_file(target)
    manifest["entries"][0]["sha256"] = digest
    manifest["catalog"][0]["sha256"] = digest
    (tmp_path / ".main").mkdir()
    write_manifest(tmp_path, manifest)

    assert reusable_manifest(tmp_path, _v5_reuse_context(manifest)) is None


def test_manifest_v5_rejects_main_prefixed_landed_source() -> None:
    """entry/conflict/catalog 的来源必须是 .main 内相对路径而非 .main/ 前缀路径。"""
    manifest = _v5_manifest_with_records()
    source = ".main/dir/file.txt"
    digest = conflict_digest("UMF", source, "")
    target = f"basic/file__{digest}.txt"
    manifest["entries"][0].update({"source_relative": source, "target": target})
    manifest["conflicts"][0].update({"source_relative": source, "target": target, "digest": digest})
    manifest["catalog"][0].update({"path": target, "source_relative": source})

    assert not validate_manifest(manifest)


@pytest.mark.parametrize("record_kind", ["ignored", "failures"])
def test_manifest_v5_rejects_main_prefixed_non_landed_source(record_kind: str) -> None:
    """ignored/failure 的 source_relative 同样不得带 .main/ 前缀。"""
    manifest = _v5_manifest_with_records()
    record = manifest[record_kind][0]
    record["source_relative"] = f".main/{record['source_relative']}"

    assert not validate_manifest(manifest)


@pytest.mark.parametrize(
    "target_roots",
    [
        ["alarm", "kpi"],
        ["basic"],
    ],
)
def test_manifest_v5_accepts_nonempty_allowlisted_target_root_subset(target_roots: list[str]) -> None:
    """target_roots 必须是非空、去重、排序的固定 allowlist 子集。"""
    manifest = _v5_manifest()
    manifest["classification"]["snapshot"]["target_roots"] = target_roots

    assert validate_manifest(manifest)


@pytest.mark.parametrize(
    "target_roots",
    [
        [],
        ["prepared"],
        ["rules"],
        [".main"],
        ["config"],
        ["alarm", "alarm"],
        ["kpi", "alarm"],
    ],
)
def test_manifest_v5_rejects_reserved_unknown_duplicate_or_unsorted_target_roots(
    target_roots: list[str],
) -> None:
    """保留路径、旧分类根、重复项和未排序集合都必须拒绝。"""
    manifest = _v5_manifest()
    manifest["classification"]["snapshot"]["target_roots"] = target_roots

    assert not validate_manifest(manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["conflicts"][0].update({"digest": "0" * 12}),
        lambda manifest: manifest["conflicts"][0].update({"target": "basic/file.txt"}),
        lambda manifest: manifest["conflicts"][0].update({"target": "basic/file.txt"}),
        lambda manifest: manifest["conflicts"][0].update({"target": "basic/other.txt"}),
        lambda manifest: manifest["conflicts"].append(dict(manifest["conflicts"][0])),
    ],
)
def test_manifest_v5_conflicts_require_matching_digest_disambiguated_target_and_entry(
    mutate,
) -> None:
    """伪造摘要、未消歧目标、错误摘要后缀和重复冲突记录都必须失败。"""
    manifest = _v5_manifest_with_records()
    mutate(manifest)

    assert not validate_manifest(manifest)


def test_manifest_v5_accepts_collision_suffix_with_recomputed_digest() -> None:
    """同一摘要的第二消歧槽位允许使用 -2 后缀。"""
    manifest = _v5_manifest_with_records()
    target = f"basic/file__{V5_CONFLICT_DIGEST}-2.txt"
    manifest["entries"][0]["target"] = target
    manifest["conflicts"][0]["target"] = target
    manifest["catalog"][0]["path"] = target

    assert validate_manifest(manifest)


def test_manifest_v5_catalog_and_landed_entries_are_one_to_one() -> None:
    """catalog 不得漏项、额外项或多对一。"""
    missing = _v5_manifest_with_records()
    missing["catalog"] = []
    missing["summary"]["counts"]["catalog"] = 0
    assert not validate_manifest(missing)

    extra = _v5_manifest_with_records()
    extra["catalog"].append(dict(extra["catalog"][0]))
    extra["summary"]["counts"]["catalog"] = 2
    assert not validate_manifest(extra)

    mismatch = _v5_manifest_with_records()
    mismatch["catalog"][0]["path"] = "basic/other.txt"
    assert not validate_manifest(mismatch)


def test_manifest_v5_rejects_null_route_for_current_profiles() -> None:
    """当前 UMF/CSP/GENERIC profile 都不得产生 null route_id。"""
    manifest = _v5_manifest()
    ignored = _v5_ignored()
    ignored.update(
        {
            "route_id": None,
            "category": None,
            "original_target": None,
            "target": None,
            "action": "ignore",
            "reason": "no_route_match",
        }
    )
    manifest["ignored"] = [ignored]
    manifest["summary"] = {
        "counts": {"landed": 0, "ignored": 1, "conflicts": 0, "failures": 0, "catalog": 0},
        "by_route": {},
        "by_category": {},
        "by_action": {"ignore": 1},
        "by_status": {"failed": 0, "ignored": 1, "landed": 0},
    }
    assert not validate_manifest(manifest)


def test_manifest_v5_summary_allows_unreachable_route_zero_only() -> None:
    """by_route 可显式列出不可达 route 的 0 计数，但不得虚增非零计数。"""
    manifest = _v5_manifest_with_records()
    manifest["summary"]["by_route"]["route.unreachable"] = 0

    assert validate_manifest(manifest)

    manifest["summary"]["by_route"]["route.unreachable"] = 1
    assert not validate_manifest(manifest)


def test_reusable_manifest_requires_complete_context_and_verifies_disk(tmp_path: Path) -> None:
    """复用必须同时匹配 checksum、product、kind、配置/策略、路径与预算上下文。"""
    manifest = _materialized_v5_manifest(tmp_path)
    context = _v5_reuse_context(manifest)
    assert reusable_manifest(tmp_path, context) is not None

    variants = [
        replace(context, checksum=V5_SHA256_B),
        replace(context, product="CSP"),
        replace(context, package_kind="log_supplement"),
        replace(context, profile="CSP"),
        replace(context, config_fingerprint=V5_SHA256_B),
        replace(context, extraction_policy_fingerprint=V5_SHA256_A),
        replace(context, path_limit={**context.path_limit, "fingerprint": V5_SHA256_B}),
        replace(context, scene_root=".main/other"),
        replace(context, target_roots=("alarm", "kpi")),
        replace(context, budgets={**context.budgets, "max_archive_depth": 7}),
    ]
    assert all(reusable_manifest(tmp_path, variant) is None for variant in variants)
