"""在线启动脚本的跨平台命令测试。"""

from pathlib import Path

import run_online
from run_online import backend_command, select_port, web_command


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


def test_web_command_uses_npm_vite_arguments() -> None:
    command = web_command(npm="npm.cmd", host="0.0.0.0", port=5174)
    assert command == [
        "npm.cmd",
        "run",
        "dev",
        "--",
        "--host",
        "0.0.0.0",
        "--port",
        "5174",
    ]


def test_select_port_returns_free_preferred_port() -> None:
    with run_online.socket.socket(run_online.socket.AF_INET, run_online.socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]
        with run_online.socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
            if free == occupied:
                free += 1

    assert select_port("127.0.0.1", free) == free


def test_select_port_skips_occupied_port() -> None:
    with run_online.socket.socket(run_online.socket.AF_INET, run_online.socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]
        selected = select_port("127.0.0.1", occupied)

    assert selected != occupied
    assert selected > occupied


def test_main_starts_on_next_available_ports(monkeypatch, capsys) -> None:
    selected: list[int] = []

    def fake_select_port(host: str, preferred: int) -> int:
        selected.append(preferred + 10)
        return preferred + 10

    commands: list[list[str]] = []

    class FakeProcess:
        def poll(self) -> int | None:
            return 0

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float) -> int:
            return 0

    def fake_popen(command: list[str], cwd: str | Path) -> FakeProcess:
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(run_online, "select_port", fake_select_port)
    monkeypatch.setattr(run_online, "_find_npm", lambda: "npm")
    monkeypatch.setattr(run_online, "_prepare_python", lambda root: Path("python"))
    monkeypatch.setattr(run_online, "_prepare_web", lambda root, npm: None)
    monkeypatch.setattr(run_online, "_wait_any", lambda processes: 0)
    monkeypatch.setattr(run_online.subprocess, "Popen", fake_popen)

    assert run_online.main([]) == 0
    assert selected == [8010, 5183]
    assert "--port" in commands[0]
    assert str(8010) in commands[0]
    assert "--port" in commands[1]
    assert str(5183) in commands[1]
    output = capsys.readouterr().out
    assert "默认后端端口 8000 已被占用，自动使用 8010" in output
    assert "默认前端端口 5173 已被占用，自动使用 5183" in output
