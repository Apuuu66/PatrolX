"""PatrolX 在线服务启动器。

用法：

    python run_online.py

脚本会启动 FastAPI 后端和 Vite 前端，并统一处理 Ctrl+C 停止；也可通过
`--host`、`--port`、`--web-host`、`--web-port` 覆盖默认地址。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"


def venv_python(root: Path = ROOT) -> Path:
    """返回当前平台对应的虚拟环境 Python 路径。"""
    suffix = "Scripts/python.exe" if IS_WINDOWS else "bin/python"
    return root / ".venv" / suffix


def backend_command(*, python: Path, host: str, port: int, reload: bool) -> list[str]:
    """构造后端启动命令。"""
    command = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        command.append("--reload")
    return command


def web_command(*, npm: str, host: str, port: int) -> list[str]:
    """构造前端启动命令。"""
    return [npm, "run", "dev", "--", "--host", host, "--port", str(port)]


def _prepare_python(root: Path) -> Path:
    python = venv_python(root)
    if python.exists():
        return python

    print("[PatrolX] 初始化 Python 虚拟环境...")
    subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], cwd=root, check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=root, check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-e", ".[dev]"], cwd=root, check=True)
    return python


def _find_npm() -> str:
    if IS_WINDOWS:
        return shutil.which("npm.cmd") or shutil.which("npm") or ""
    return shutil.which("npm") or ""


def _prepare_web(root: Path, npm: str) -> None:
    web_dir = root / "web"
    if (web_dir / "node_modules").exists():
        return
    print("[PatrolX] 安装前端依赖...")
    subprocess.run([npm, "install"], cwd=web_dir, check=True)


def _stop(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _wait_any(processes: list[subprocess.Popen[bytes]]) -> int:
    while True:
        for index, process in enumerate(processes):
            code = process.poll()
            if code is not None:
                if index == 0:
                    print("[PatrolX] 后端已退出")
                else:
                    print("[PatrolX] 前端已退出")
                return code or 1
        time.sleep(0.2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 PatrolX 在线服务（API + Web）")
    parser.add_argument("--host", default="127.0.0.1", help="后端 API 地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="后端 API 端口，默认 8000")
    parser.add_argument("--web-host", default="127.0.0.1", help="前端页面地址，默认 127.0.0.1")
    parser.add_argument("--web-port", type=int, default=5173, help="前端页面端口，默认 5173")
    parser.add_argument("--no-reload", action="store_true", help="关闭后端自动重载")
    args = parser.parse_args(argv)

    npm = _find_npm()
    if not npm:
        print("[PatrolX] 未找到 npm，请先安装 Node.js 18+", file=sys.stderr)
        return 1

    python = _prepare_python(ROOT)
    _prepare_web(ROOT, npm)

    backend = subprocess.Popen(
        backend_command(
            python=python,
            host=args.host,
            port=args.port,
            reload=not args.no_reload,
        ),
        cwd=ROOT,
    )
    frontend = subprocess.Popen(
        web_command(npm=npm, host=args.web_host, port=args.web_port),
        cwd=ROOT / "web",
    )
    processes = [backend, frontend]

    print("[PatrolX] 在线服务启动中...")
    print(f"[PatrolX] 后端 API：http://{args.host}:{args.port}")
    print(f"[PatrolX] 前端页面：http://{args.web_host}:{args.web_port}")
    print("[PatrolX] 停止服务：按 Ctrl+C")

    exit_code = 0
    try:
        exit_code = _wait_any(processes)
    except KeyboardInterrupt:
        print("\n[PatrolX] 正在停止服务...")
    finally:
        _stop(processes)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
