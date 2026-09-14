"""安全解压测试：路径穿越拒绝、正常解压。"""

import gzip
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


def _policy_zip(path: Path, files: dict[str, str | bytes]) -> None:
    """创建策略集成测试使用的 zip 包。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def _configure_policy(tmp_path: Path, monkeypatch, data: dict) -> None:
    """将运行时配置目录指向临时 classify + extract policy 配置。"""
    import shutil

    from app.core.config import settings

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "deploy/config/classify_rules.yaml",
        config_dir / "classify_rules.yaml",
    )
    import yaml

    (config_dir / "extract_policy.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "config_dir", config_dir)


def _setup_policy_env(tmp_path, monkeypatch, data: dict):
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    _configure_policy(tmp_path, monkeypatch, data)
    return env


def _relative_set(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_path_skip_retains_nested_archives_and_processes_outside(tmp_path, monkeypatch) -> None:
    """跳过路径内压缩项保留为最终现场，范围外压缩项仍正常展开。"""
    from app.cli import run_task

    _setup_policy_env(
        tmp_path,
        monkeypatch,
        {"nested": {"skip_paths": ["/0/", "/xx/0/"]}, "whitelist": {"name_keywords": []}},
    )
    package = tmp_path / "uploads/path-skip.zip"
    _policy_zip(
        package,
        {
            "0/a.zip": _policy_zip(tmp_path / "_build/a.zip", {"a-inner.txt": "a"}).read_bytes(),
            "xx/0/deep.zip": _policy_zip(tmp_path / "_build/deep.zip", {"deep-inner.txt": "deep"}).read_bytes(),
            "outside.zip": _policy_zip(tmp_path / "_build/outside.zip", {"outside-inner.txt": "outside"}).read_bytes(),
        },
    )
    task = run_task(package, task_id="task-path-skip")
    task_dir = tmp_path / "output" / task.task_id
    main_files = _relative_set(task_dir / ".main")

    assert main_files == {"0/a.zip", "xx/0/deep.zip", "outside.zip"}
    assert (task_dir / "other/0/a.zip").read_bytes() == (task_dir / ".main/0/a.zip").read_bytes()
    assert (task_dir / "other/xx/0/deep.zip").read_bytes() == (task_dir / ".main/xx/0/deep.zip").read_bytes()
    assert (task_dir / "other/outside/outside-inner.txt").read_text() == "outside"
    manifest = (task_dir / ".patrolx-extracted.json").read_text(encoding="utf-8")
    assert '"status": "skipped"' in manifest
    assert "0a/file.zip" not in _relative_set(task_dir / "other")


def test_path_prefix_boundary_only_matches_exact_directory(tmp_path, monkeypatch) -> None:
    """0/ 不匹配 0a/，但 /0/ 与 0/、/xx/0/ 与 xx/0/ 等价。"""
    from app.cli import run_task

    _setup_policy_env(
        tmp_path,
        monkeypatch,
        {"nested": {"skip_paths": ["/0/", "/xx/0/"]}, "whitelist": {"name_keywords": []}},
    )
    package = tmp_path / "uploads/boundary.zip"
    _policy_zip(
        package,
        {
            "0/a.zip": _policy_zip(tmp_path / "_build/a.zip", {"a": "a"}).read_bytes(),
            "0a/b.zip": _policy_zip(tmp_path / "_build/b.zip", {"b": "b"}).read_bytes(),
            "xx/0/c.zip": _policy_zip(tmp_path / "_build/c.zip", {"c": "c"}).read_bytes(),
        },
    )
    task = run_task(package, task_id="task-boundary")
    task_dir = tmp_path / "output" / task.task_id
    final_files = _relative_set(task_dir / "other")
    assert "0/a.zip" in final_files
    assert "xx/0/c.zip" in final_files
    assert "b/b" in final_files
    assert not (task_dir / "other/0a/b.zip").exists()


def test_skipped_corrupt_archive_does_not_block_task(tmp_path, monkeypatch) -> None:
    """跳过路径内损坏压缩项不读取成员，保留后任务继续。"""
    from app.cli import run_task

    _setup_policy_env(
        tmp_path,
        monkeypatch,
        {"nested": {"skip_paths": ["/broken/"]}, "whitelist": {"name_keywords": []}},
    )
    package = tmp_path / "uploads/corrupt-skip.zip"
    _policy_zip(
        package,
        {"broken/corrupt.zip": b"not-an-archive", "ok.txt": "ok"},
    )
    task = run_task(package, task_id="task-corrupt-skip")
    task_dir = tmp_path / "output" / task.task_id
    assert (task_dir / "other/broken/corrupt.zip").read_bytes() == b"not-an-archive"
    assert (task_dir / "other/ok.txt").read_text() == "ok"
    manifest = task_dir / ".patrolx-extracted.json"
    assert '"status": "skipped"' in manifest.read_text(encoding="utf-8")


def test_whitelist_has_priority_and_restores_normal_processing(tmp_path, monkeypatch) -> None:
    """白名单路径/关键字优先于路径跳过，压缩项递归展开，普通文件正常拷贝。"""
    from app.cli import run_task

    _setup_policy_env(
        tmp_path,
        monkeypatch,
        {
            "nested": {"skip_paths": ["/skip/"]},
            "whitelist": {"paths": ["/skip/keep/"], "name_keywords": ["alarm"]},
        },
    )
    inner = _policy_zip(tmp_path / "_build/alarm-inner.zip", {"inner.txt": "alarm inner"})
    alarm_outer = _policy_zip(
        tmp_path / "_build/alarm-outer.zip",
        {"inner.zip": inner.read_bytes(), "plain.txt": "plain"},
    )
    package = tmp_path / "uploads/whitelist.zip"
    _policy_zip(
        package,
        {
            "skip/keep/keep.zip": _policy_zip(tmp_path / "_build/keep.zip", {"keep-inner.txt": "keep"}).read_bytes(),
            "skip/service_ALARM.zip": alarm_outer.read_bytes(),
            "skip/alarm.txt": "alarm text",
            "skip/normal.zip": _policy_zip(tmp_path / "_build/normal.zip", {"normal-inner.txt": "normal"}).read_bytes(),
        },
    )
    task = run_task(package, task_id="task-whitelist")
    task_dir = tmp_path / "output" / task.task_id
    all_final = _relative_set(task_dir)

    assert "other/keep/keep-inner.txt" in all_final
    assert "logs/inner/inner.txt" in all_final
    assert "alarm/skip/alarm.txt" in all_final
    assert "other/skip/normal.zip" in all_final
    assert "logs/service_ALARM/plain.txt" in all_final
    assert "logs/inner/inner.zip" not in all_final
    manifest = task_dir / ".patrolx-extracted.json"
    assert "whitelist_keyword" in manifest.read_text(encoding="utf-8")


def test_skip_all_retains_all_non_whitelisted_nested_items(tmp_path, monkeypatch) -> None:
    """全局保留仅作用于主包内嵌套压缩项，白名单项仍解压。"""
    from app.cli import run_task

    _setup_policy_env(
        tmp_path,
        monkeypatch,
        {"nested": {"skip_all": True}, "whitelist": {"name_keywords": ["alarm"]}},
    )
    package = tmp_path / "uploads/skip-all.zip"
    _policy_zip(
        package,
        {
            "a.zip": _policy_zip(tmp_path / "_build/a.zip", {"a": "a"}).read_bytes(),
            "b.tar.gz": _policy_zip(tmp_path / "_build/b.tar", {"b": "b"}).read_bytes(),
            "c.log.gz": gzip.compress(b"log"),
            "alarm.zip": _policy_zip(tmp_path / "_build/alarm.zip", {"alarm": "alarm"}).read_bytes(),
        },
    )
    task = run_task(package, task_id="task-skip-all")
    task_dir = tmp_path / "output" / task.task_id
    final_files = _relative_set(task_dir)
    assert "other/a.zip" in final_files
    assert "other/b.tar.gz" in final_files
    assert "logs/c.log.gz" in final_files
    assert "alarm/alarm/alarm" in final_files
    assert "other/a" not in final_files
    assert "other/c.log" not in final_files
