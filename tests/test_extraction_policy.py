"""manifest 策略契约与解压现场幂等复用测试。"""

import json
import shutil
import zipfile
from pathlib import Path

import pytest
import yaml

from app.core.checksum import sha256_file
from app.services.extraction import (
    extract_main_site,
    policy_skipped_summary,
    read_manifest,
    sync_policy_counters,
    validate_manifest,
    write_manifest,
)


def _policy_zip(path: Path, files: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def _configure_policy(tmp_path: Path, monkeypatch, data: dict) -> None:
    from app.core.config import settings

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "deploy/config/classify_rules.yaml",
        config_dir / "classify_rules.yaml",
    )
    (config_dir / "extract_policy.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "config_dir", config_dir)


def _setup_policy_env(tmp_path: Path, monkeypatch, data: dict):
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    _configure_policy(tmp_path, monkeypatch, data)
    return env


def _extract_policy_site(tmp_path, monkeypatch, files: dict[str, str]):
    """创建策略包并返回首次解压 manifest，便于直接校验契约。"""
    from app.cli import run_task

    _setup_policy_env(
        tmp_path,
        monkeypatch,
        {
            "nested": {"skip_paths": ["/0/"]},
            "whitelist": {"paths": ["/0/keep/"], "name_keywords": ["alarm"]},
        },
    )
    package = tmp_path / "uploads/policy.zip"
    _policy_zip(package, files)
    task = run_task(package, task_id="policy-contract")
    return task.task_id, read_manifest(tmp_path / "output" / task.task_id)


def test_old_manifest_without_policy_is_reusable(tmp_path, monkeypatch) -> None:
    """007 旧 manifest 没有 policy 节时仍可复用有效现场。"""
    from app.cli import run_task

    _setup_policy_env(tmp_path, monkeypatch, {"nested": {"skip_paths": ["/0/"]}, "whitelist": {"name_keywords": []}})
    package = tmp_path / "uploads/old.zip"
    _policy_zip(package, {"0/a.zip": _policy_zip(tmp_path / "_build/a.zip", {"a": "a"}).read_bytes()})
    task = run_task(package, task_id="old-manifest")
    data_dir = tmp_path / "output" / task.task_id
    checksum = sha256_file(package)

    manifest = read_manifest(data_dir)
    assert validate_manifest(manifest, require_policy=True)
    del manifest["policy"]
    assert validate_manifest(manifest, require_policy=False)
    (data_dir / ".patrolx-extracted.json").write_text(json.dumps(manifest), encoding="utf-8")

    reused = extract_main_site(package, data_dir, checksum)
    assert reused["main"]["reused"] is True
    assert "policy" not in reused


def test_new_manifest_requires_valid_policy() -> None:
    manifest = {
        "version": 3,
        "main": {"checksum": "a", "count": 0, "evidence_path": ".main", "reused": False},
        "subpackages": [],
        "log_gz": [],
        "rejected": [],
    }
    with pytest.raises(ValueError, match="策略快照"):
        write_manifest(Path("/tmp/unused-policy-manifest"), manifest)


def test_skipped_status_contract_and_counters(tmp_path, monkeypatch) -> None:
    """skipped 只表示成功保留，counters 与条目状态一致。"""
    _, manifest = _extract_policy_site(
        tmp_path,
        monkeypatch,
        {
            "0/a.zip": _policy_zip(tmp_path / "_build/a.zip", {"a": "a"}).read_bytes(),
            "0/b.log.gz": __import__("gzip").compress(b"log"),
            "0/keep/keep.zip": _policy_zip(tmp_path / "_build/keep.zip", {"keep": "keep"}).read_bytes(),
            "0/alarm.zip": _policy_zip(tmp_path / "_build/alarm.zip", {"alarm": "alarm"}).read_bytes(),
            "0/alarm.txt": "alarm",
        },
    )

    assert validate_manifest(manifest, require_policy=True)
    assert manifest["policy"]["counters"] == {
        "skipped_subpackages": 1,
        "skipped_log_gz": 1,
        "whitelisted_subpackages": 2,
        "whitelisted_log_gz": 0,
        "whitelisted_files": 1,
    }
    assert sync_policy_counters(manifest) == manifest["policy"]["counters"]
    assert manifest["subpackages"][0]["status"] == "skipped"
    assert manifest["subpackages"][0]["target"]
    assert manifest["subpackages"][0]["error"] is None

    failed = dict(manifest["subpackages"][0])
    failed.update({"status": "failed", "error": "目标文件已存在，未覆盖"})
    manifest["subpackages"] = [failed]
    assert validate_manifest(manifest)
    for invalid in (
        {**failed, "status": "skipped"},
        {**failed, "status": "skipped", "error": None, "target": ""},
    ):
        manifest["subpackages"] = [invalid]
        assert not validate_manifest(manifest)
    manifest["subpackages"] = [failed]

    manifest["log_gz"] = [
        {
            "source_evidence": ".main/0/b.log.gz",
            "source_relative_path": "0/b.log.gz",
            "target": "logs/0/b.log",
            "depth": 1,
            "status": "skipped",
            "error": None,
            "policy": {"action": "skip", "reason": "skip_path", "scope": "0/", "keyword": None},
        }
    ]
    assert validate_manifest(manifest)


def test_policy_summary_returns_category_skipped_items(tmp_path, monkeypatch) -> None:
    _, manifest = _extract_policy_site(
        tmp_path,
        monkeypatch,
        {
            "0/a.zip": _policy_zip(tmp_path / "_build/a.zip", {"a": "a"}).read_bytes(),
            "0/b.log.gz": __import__("gzip").compress(b"log"),
        },
    )
    summary = policy_skipped_summary(manifest, "other")
    assert [item["name"] for item in summary] == ["a.zip"]
    assert [item["source"] for item in summary] == [".main/0/a.zip"]
    assert [item["target"] for item in summary] == ["other/0/a.zip"]
    assert summary[0]["reason"] == "skip_path"
    assert policy_skipped_summary(manifest, "logs")[0]["name"] == "b.log.gz"


def test_idempotent_reuse_and_policy_change_does_not_rebuild_old_site(tmp_path, monkeypatch) -> None:
    """有效现场按原 manifest 复用；现场缺失时才按当前策略重建。"""
    from app.cli import run_task

    _setup_policy_env(tmp_path, monkeypatch, {"nested": {"skip_paths": ["/0/"]}, "whitelist": {"name_keywords": []}})
    package = tmp_path / "uploads/reuse.zip"
    _policy_zip(package, {"0/a.zip": _policy_zip(tmp_path / "_build/a.zip", {"a": "a"}).read_bytes()})
    task_id = run_task(package, task_id="reuse").task_id
    data_dir = tmp_path / "output" / task_id
    old_manifest = read_manifest(data_dir)
    old_fingerprint = old_manifest["policy"]["fingerprint"]

    _configure_policy(tmp_path, monkeypatch, {"whitelist": {"paths": ["/0/"]}})
    run_task(package, task_id=task_id)
    reused = read_manifest(data_dir)
    assert reused["policy"]["fingerprint"] == old_fingerprint
    assert (data_dir / "other/0/a.zip").is_file()
    assert not (data_dir / "other/a").exists()

    shutil.rmtree(data_dir / ".main")
    run_task(package, task_id=task_id)
    rebuilt = read_manifest(data_dir)
    assert rebuilt["policy"]["fingerprint"] != old_fingerprint
    assert (data_dir / "other/a").is_file()


def test_conflict_duplicate_and_skipped_are_recorded(tmp_path, monkeypatch) -> None:
    """目标冲突、相同 checksum 和策略保留分别记录为 conflict/duplicate/skipped。"""
    from app.core.checksum import sha256_file
    from app.services import extraction

    _setup_policy_env(tmp_path, monkeypatch, {"nested": {"skip_paths": ["/skip/"]}, "whitelist": {"name_keywords": []}})
    source_zip = _policy_zip(tmp_path / "_build/source.zip", {"data.txt": "data"})
    conflict_zip = _policy_zip(tmp_path / "_build/conflict.zip", {"same.txt": "first"})
    duplicate_zip = _policy_zip(tmp_path / "_build/duplicate.zip", {"same.txt": "first"})
    package = tmp_path / "uploads/states.zip"
    _policy_zip(
        package,
        {
            "skip/retained.zip": source_zip.read_bytes(),
            "first.zip": conflict_zip.read_bytes(),
            "second.zip": _policy_zip(tmp_path / "_build/conflict2.zip", {"same.txt": "second"}).read_bytes(),
            "third.zip": duplicate_zip.read_bytes(),
        },
    )
    data_dir = tmp_path / "output/state-task"

    manifest = extraction.extract_main_site(package, data_dir, sha256_file(package))

    states = [item["status"] for item in manifest["subpackages"]]
    assert states.count("skipped") == 1
    assert states.count("extracted") == 2
    assert states.count("duplicate") == 1
    conflicts = [item for item in manifest["files"] if item["target"] == "other/same.txt"]
    assert [item["status"] for item in conflicts] == ["extracted", "conflict"]
    assert (data_dir / "other/same.txt").read_text() == "first"
