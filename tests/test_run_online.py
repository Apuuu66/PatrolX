"""在线启动脚本的跨平台命令测试。"""

from pathlib import Path

from run_online import backend_command, web_build_command, web_command


def test_backend_command_uses_venv_python_and_uvicorn() -> None:
    command = backend_command(
        python=Path(".venv/bin/python"),
        host="0.0.0.0",
        port=9000,
        reload=False,
    )
    assert command == [
        ".venv/bin/python",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
    ]


def test_web_build_command_builds_production_assets() -> None:
    command = web_build_command(npm="npm.cmd")
    assert command == ["npm.cmd", "run", "build"]


def test_web_command_defaults_to_previewing_production_assets() -> None:
    command = web_command(npm="npm.cmd", host="0.0.0.0", port=5174)
    assert command == [
        "npm.cmd",
        "run",
        "preview",
        "--",
        "--host",
        "0.0.0.0",
        "--port",
        "5174",
    ]


def test_web_command_can_explicitly_start_vite_dev_server() -> None:
    command = web_command(npm="npm.cmd", host="127.0.0.1", port=5173, dev=True)
    assert command == [
        "npm.cmd",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5173",
    ]


class _FakeProcess:
    def poll(self) -> int:
        return 0

    def terminate(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


def test_main_builds_web_before_starting_default_preview(monkeypatch) -> None:
    import run_online

    commands: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(run_online, "_find_npm", lambda: "npm")
    monkeypatch.setattr(run_online, "_prepare_python", lambda root: Path(".venv/bin/python"))
    monkeypatch.setattr(run_online, "_prepare_web", lambda root, npm: None)
    monkeypatch.setattr(
        run_online.subprocess,
        "run",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )
    monkeypatch.setattr(run_online.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess())
    monkeypatch.setattr(run_online, "_wait_any", lambda processes: 0)

    assert run_online.main(["--no-reload"]) == 0
    assert commands == [
        (
            ["npm", "run", "build"],
            {"cwd": run_online.ROOT / "web", "check": True},
        )
    ]


def test_main_skips_web_build_when_dev_server_is_explicit(monkeypatch) -> None:
    import run_online

    commands: list[list[str]] = []
    monkeypatch.setattr(run_online, "_find_npm", lambda: "npm")
    monkeypatch.setattr(run_online, "_prepare_python", lambda root: Path(".venv/bin/python"))
    monkeypatch.setattr(run_online, "_prepare_web", lambda root, npm: None)
    monkeypatch.setattr(run_online.subprocess, "run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(run_online.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess())
    monkeypatch.setattr(run_online, "_wait_any", lambda processes: 0)

    assert run_online.main(["--no-reload", "--dev-web"]) == 0
    assert commands == []
