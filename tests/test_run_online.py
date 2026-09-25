"""在线启动脚本的跨平台命令测试。"""

from pathlib import Path

from run_online import backend_command, web_command


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
