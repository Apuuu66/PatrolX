"""本地调试目录入口测试：main.py 只执行 local_run/ 下的全部压缩包。"""

from pathlib import Path

from app import main as app_main
from app.core.config import settings
from app.local_run import run_local_packages
from app.models.schemas import TaskMode, TaskTrigger


def test_local_run_executes_all_packages_in_local_run_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_run_dir", tmp_path)
    packages = [tmp_path / "aaa.zip", tmp_path / "bbb.tar.gz"]
    for package in packages:
        package.touch()
    (tmp_path / "README.md").touch()

    calls: list[Path] = []

    def record_run(package: Path, **kwargs):
        calls.append(package)
        assert kwargs["mode"] == TaskMode.LOCAL
        assert kwargs["trigger"] == TaskTrigger.CLI

    monkeypatch.setattr("app.local_run.run_task", record_run)

    assert run_local_packages() == 0
    assert calls == packages


def test_local_run_returns_error_when_no_package(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_run_dir", tmp_path)
    monkeypatch.setattr(
        "app.local_run.run_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应执行任务")),
    )

    assert run_local_packages() == 1


def test_main_entry_uses_local_run(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr("app.local_run.run_local_packages", lambda: calls.append(1) or 0)

    assert app_main.main() == 0
    assert calls == [1]


def test_local_run_does_not_scan_uploads(tmp_path: Path, monkeypatch) -> None:
    local_dir = tmp_path / "local_run"
    uploads_dir = tmp_path / "uploads"
    local_dir.mkdir()
    uploads_dir.mkdir()
    monkeypatch.setattr(settings, "local_run_dir", local_dir)
    monkeypatch.setattr(settings, "uploads_dir", uploads_dir)
    local_package = local_dir / "local.zip"
    uploads_package = uploads_dir / "uploaded.zip"
    local_package.touch()
    uploads_package.touch()

    calls: list[Path] = []
    monkeypatch.setattr("app.local_run.run_task", lambda package, **_kwargs: calls.append(package))

    assert run_local_packages() == 0
    assert calls == [local_package]
