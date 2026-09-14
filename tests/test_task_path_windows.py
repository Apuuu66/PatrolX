"""任务删除的 Windows 长路径兼容测试。"""

from pathlib import Path

from app.services.tasks import _extended_windows_path


def test_windows_extended_path_prefixes_absolute_windows_paths(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tasks.os.name", "nt")
    assert _extended_windows_path(Path("C:/repo/output/task")) == r"\\?\C:\repo\output\task"
    assert _extended_windows_path(Path("//server/share/task")) == r"\\?\UNC\server\share\task"
    assert _extended_windows_path(Path(r"\\?\C:\already\extended")) == r"\\?\C:\already\extended"


def test_windows_extended_path_keeps_posix_paths(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tasks.os.name", "posix")
    assert _extended_windows_path(Path("/tmp/task")) == "/tmp/task"
