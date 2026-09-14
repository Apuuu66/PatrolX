"""PatrolX 跨平台 Python 构建入口。

该文件只使用 Python 标准库，统一替代 Makefile 和 uv 的日常开发工作流。
所有子进程均通过参数列表启动，不依赖 Unix shell。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"
VENV_REL_PYTHON = "Scripts/python.exe" if IS_WINDOWS else "bin/python"
EXACT_LOCK_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+==[^\s;]+(?:\s*;\s*.+)?$")
VENV_STATE_FILE = ".patrolx-build-state.json"
PIPE_TARGETS: dict[str, tuple[str, str, str, str]] = {
    "linux": ("linux", "posix", "Linux", "x86_64"),
    "macos": ("darwin", "posix", "Darwin", "arm64"),
    "windows": ("win32", "nt", "Windows", "AMD64"),
}

Runner = Callable[[list[str], Path | None], int]

COMMANDS = OrderedDict[str, str](
    [
        ("help", "显示可用命令"),
        ("install", "创建/校验 .venv 并按精确锁安装后端依赖"),
        ("lock", "从 pyproject.toml 刷新精确依赖锁"),
        ("verify", "运行本地全流程巡检"),
        ("verify-one", "只重跑目标巡检规则"),
        ("run", "启动在线 API + Web 服务"),
        ("contract", "校验或导出 OpenAPI 契约"),
        ("gen-web-api", "生成前端 API 客户端"),
        ("test", "运行 pytest"),
        ("lint", "运行 Ruff check 和 format check"),
        ("web-install", "安装前端依赖"),
        ("web-dev", "启动前端开发服务"),
        ("web-build", "构建前端"),
        ("e2e-install", "安装 Playwright 浏览器依赖"),
        ("e2e", "运行端到端测试"),
    ]
)


class BuildError(RuntimeError):
    """构建入口前置条件或执行失败。"""


def default_runner(command: list[str], cwd: Path | None = None) -> int:
    """以参数列表执行子进程，不经过 shell。"""
    return subprocess.run(command, cwd=cwd, check=False).returncode


@dataclass
class BuildContext:
    """构建命令运行上下文，runner 可在测试中替换。"""

    root: Path = ROOT
    runner: Runner = default_runner

    def run(self, command: list[str], cwd: Path | None = None) -> int:
        return self.runner(command, cwd)

    def venv_python(self, root: Path | None = None) -> Path:
        return venv_python(root or self.root)


def python_version_ok() -> bool:
    return sys.version_info >= (3, 11)


def venv_python(root: Path) -> Path:
    """返回当前平台对应的虚拟环境解释器。"""
    suffix = "Scripts/python.exe" if IS_WINDOWS else "bin/python"
    return root / ".venv" / suffix


def lock_path(root: Path) -> Path:
    return root / "requirements-lock.txt"


def _require_host_python() -> None:
    if not python_version_ok():
        raise BuildError("需要 Python 3.11 或更高版本；请安装官方 Python 后重试。")


def _venv_state_path(root: Path) -> Path:
    """返回标准安装状态标记路径。"""
    return root / ".venv" / VENV_STATE_FILE


def _lock_fingerprint(root: Path) -> str:
    """计算当前锁文件指纹；缺锁时用空内容参与校验。"""
    path = lock_path(root)
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def _write_venv_state(root: Path) -> None:
    """标准安装成功后写入 Python 版本与锁文件指纹。"""
    state = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "lock_sha256": _lock_fingerprint(root),
    }
    _venv_state_path(root).write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")


def _validate_venv_base(root: Path) -> tuple[int, int]:
    """校验 venv 结构、Python 版本，并拒绝 uv 接管环境。"""
    config = root / ".venv" / "pyvenv.cfg"
    if not config.exists():
        raise BuildError("检测到不标准 .venv；请删除 .venv 后重新执行 python build.py install。")
    content = config.read_text(encoding="utf-8")
    if re.search(r"(?im)^uv\s*=", content):
        raise BuildError("检测到由 uv 创建的 .venv；请删除 .venv 后重新执行 python build.py install。")
    version_match = re.search(r"(?im)^version\s*=\s*(\d+)\.(\d+)", content)
    if not version_match:
        raise BuildError(".venv 缺少 Python 版本信息；请删除 .venv 后重新执行 python build.py install。")
    python_version = tuple(map(int, version_match.groups()))
    if python_version < (3, 11):
        raise BuildError(".venv Python 版本低于 3.11；请删除 .venv 后重新执行 python build.py install。")
    return python_version


def _validate_standard_venv(root: Path, *, require_lock_match: bool = True) -> None:
    """校验 venv 由标准 install 初始化；默认要求与当前锁一致。"""
    python_version = _validate_venv_base(root)
    state_path = _venv_state_path(root)
    if not state_path.exists():
        raise BuildError(".venv 缺少标准安装标记；请删除 .venv 后重新执行 python build.py install。")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        recorded_version = tuple(map(int, str(state["python"]).split(".")))
        recorded_lock = str(state["lock_sha256"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise BuildError(".venv 标准安装标记无效；请删除 .venv 后重新执行 python build.py install。") from None
    if recorded_version != python_version:
        raise BuildError(".venv 与当前 Python 版本不匹配；请删除 .venv 后重新执行 python build.py install。")
    if require_lock_match and recorded_lock != _lock_fingerprint(root):
        raise BuildError(".venv 与当前锁文件不匹配；请重新执行 python build.py install。")


def ensure_venv(context: BuildContext) -> Path:
    """确保使用官方 Python venv；已有不标准或 uv 环境必须显式重建。"""
    venv_dir = context.root / ".venv"
    python = venv_python(context.root)
    if python.exists():
        _validate_venv_base(context.root)
        return python
    _require_host_python()
    code = context.run([sys.executable, "-m", "venv", str(venv_dir)], context.root)
    if code != 0:
        raise BuildError(f"创建 .venv 失败，退出码 {code}。")
    return python


def ensure_lock(context: BuildContext) -> None:
    if not lock_path(context.root).exists():
        raise BuildError("缺少 requirements-lock.txt；无法执行精确依赖安装。")


def require_existing_venv(context: BuildContext, *, lock_match: bool = True) -> Path:
    python = venv_python(context.root)
    if not python.exists():
        raise BuildError("缺少 .venv；请先执行 python build.py install。")
    _validate_standard_venv(context.root, require_lock_match=lock_match)
    return python


def ensure_backend(context: BuildContext) -> Path:
    return require_existing_venv(context)


def _pip_command(python: Path, *arguments: str) -> list[str]:
    return [str(python), "-m", "pip", "install", "--disable-pip-version-check", *arguments]


def cmd_install(context: BuildContext) -> int:
    """创建虚拟环境并按精确锁安装，最后以 --no-deps 安装本地项目。"""
    python = ensure_venv(context)
    ensure_lock(context)
    lock_code = context.run(_pip_command(python, "-r", str(lock_path(context.root))), context.root)
    if lock_code != 0:
        raise BuildError(f"精确依赖安装失败，退出码 {lock_code}。")
    local_code = context.run(_pip_command(python, "--no-deps", "-e", "."), context.root)
    if local_code != 0:
        raise BuildError(f"本地项目安装失败，退出码 {local_code}。")
    _write_venv_state(context.root)
    print("后端环境安装完成: .venv")
    return 0


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_marker(requires_dist: list[str], target: str) -> str | None:
    """从依赖边提取平台环境标记。"""
    for requirement in requires_dist:
        match = re.match(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?[^;]+;\s*(.+)$", requirement)
        if not match:
            continue
        required_name = re.match(r"^[A-Za-z0-9_.-]+", requirement)
        if required_name and _canonical_name(required_name.group(0)) == target:
            return match.group(1).strip()
    return None


def _strip_extra_marker(marker: str) -> str:
    """去除锁标记中的 extra 条件，保留目标平台和 Python 版本条件。"""
    depth = 0
    start = 0
    clauses: list[tuple[str, str]] = []
    operator = ""
    for index, char in enumerate(marker + " "):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and char in " \t":
            word_start = index + 1
            match = re.match(r"\s*(and|or)\s*", marker[word_start:])
            if match:
                clause = marker[start:index].strip()
                if clause:
                    clauses.append((operator, clause))
                operator = match.group(1)
                start = word_start + match.end()

    tail = marker[start:].strip()
    if tail:
        clauses.append((operator, tail))

    if not clauses:
        return marker.strip()

    kept: list[str] = []
    for operator, clause in clauses:
        if "extra" in clause:
            continue
        if not kept:
            kept.append(clause)
        else:
            kept.append(f"{operator} {clause}")
    return " ".join(kept)


def _read_pip_report(path: Path) -> dict[str, tuple[str, str | None]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    items = [item.get("metadata", {}) for item in report.get("install", [])]
    incoming_markers: dict[str, tuple[bool, str | None]] = {}

    def record_marker(key: str, marker: str | None, *, has_extra: bool) -> None:
        current = incoming_markers.get(key)
        if current is None or (current[0] and not has_extra):
            incoming_markers[key] = (has_extra, marker)

    for metadata in items:
        for requirement in metadata.get("requires_dist", []):
            name_match = re.match(r"^[A-Za-z0-9_.-]+", requirement)
            marker_match = re.match(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?[^;]+;\s*(.+)$", requirement)
            if not name_match:
                continue
            key = _canonical_name(name_match.group(0))
            if not marker_match:
                record_marker(key, None, has_extra=False)
                continue
            marker = marker_match.group(1).strip()
            has_extra = re.search(r"(?:^|\s)extra\s*==", marker) is not None
            if has_extra:
                marker = _strip_extra_marker(marker) or None
            record_marker(key, marker, has_extra=has_extra)

    resolved: dict[str, tuple[str, str | None]] = {}
    for metadata in items:
        name = metadata.get("name")
        version = metadata.get("version")
        if not name or not version or _canonical_name(name) == "patrolx":
            continue
        key = _canonical_name(name)
        if key in resolved and resolved[key][0] != version:
            raise BuildError(f"平台解析结果冲突: {name} {resolved[key][0]} / {version}")
        resolved[key] = (version, incoming_markers.get(key, (False, None))[1])
    return resolved


def _project_requirements() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    requirements = list(project.get("dependencies", []))
    requirements.extend(project.get("optional-dependencies", {}).get("dev", []))
    if not requirements:
        raise BuildError("pyproject.toml 中没有可解析的后端依赖。")
    return requirements


def _generate_lock(context: BuildContext, python: Path) -> None:
    requirements = _project_requirements()
    platforms: dict[str, list[str]] = {
        "linux": [
            "--python-version",
            "3.12",
            "--implementation",
            "cp",
            "--platform",
            "manylinux2014_x86_64",
            "--only-binary=:all:",
        ],
        "macos": [
            "--python-version",
            "3.12",
            "--implementation",
            "cp",
            "--platform",
            "macosx_11_0_arm64",
            "--only-binary=:all:",
        ],
        "windows": [
            "--python-version",
            "3.12",
            "--implementation",
            "cp",
            "--platform",
            "win_amd64",
            "--only-binary=:all:",
        ],
    }
    resolved: dict[str, tuple[str, str | None]] = {}
    fd, report_name = tempfile.mkstemp(prefix="requirements-report-", suffix=".json", dir=context.root)
    report_path = Path(report_name)
    os.close(fd)
    try:
        for platform_name, platform_arguments in platforms.items():
            command = _pip_resolution_command(
                python,
                platform_name,
                "--dry-run",
                "--ignore-installed",
                "--report",
                str(report_path),
                *platform_arguments,
                *requirements,
            )
            code = context.run(command, context.root)
            if code != 0:
                raise BuildError(f"{platform_name} 平台依赖解析失败，退出码 {code}。")
            resolved.update(_read_pip_report(report_path))
    finally:
        report_path.unlink(missing_ok=True)

    lines = [
        "# 由 python build.py lock 生成；请勿手工修改精确版本。",
        "# 标准安装命令：python build.py install",
    ]
    for name in sorted(resolved):
        version, marker = resolved[name]
        suffix = f"; {marker}" if marker else ""
        lines.append(f"{name}=={version}{suffix}")
    lock_path(context.root).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pip_resolution_command(python: Path, platform_name: str, *arguments: str) -> list[str]:
    """构造按目标平台评估环境标记的 pip 解析命令。"""
    target = PIPE_TARGETS[platform_name]
    sys_platform, target_os_name, system, machine = target
    target_environment = {
        "implementation_name": "cpython",
        "implementation_version": "3.12.0",
        "os_name": target_os_name,
        "platform_machine": machine,
        "platform_release": "",
        "platform_system": system,
        "platform_version": "",
        "python_full_version": "3.12.0",
        "platform_python_implementation": "CPython",
        "python_version": "3.12",
        "sys_platform": sys_platform,
    }
    bootstrap = (
        "import pip._internal.cli.main as pip_main\n"
        "import pip._vendor.packaging.markers as markers\n"
        "import sys\n"
        f"markers.default_environment = lambda: {target_environment!r}\n"
        "sys.argv = ['pip', 'install', *sys.argv[1:]]\n"
        "raise SystemExit(pip_main.main())\n"
    )
    return [str(python), "-c", bootstrap, *arguments]


def cmd_lock(context: BuildContext, *, check: bool = False) -> int:
    """维护或校验跨平台精确依赖锁。"""
    if check:
        if not lock_path(context.root).exists():
            raise BuildError("缺少 requirements-lock.txt；请执行 python build.py lock。")
        for line_number, raw_line in enumerate(lock_path(context.root).read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if not EXACT_LOCK_PATTERN.fullmatch(line):
                raise BuildError(f"requirements-lock.txt 第 {line_number} 行不是精确版本: {line}")
        print("requirements-lock.txt 精确版本校验通过")
        return 0
    python = require_existing_venv(context, lock_match=False)
    _generate_lock(context, python)
    print("已刷新 requirements-lock.txt")
    return 0


def cmd_verify(context: BuildContext) -> int:
    python = ensure_backend(context)
    return context.run([str(python), "main.py"], context.root)


def cmd_verify_one(context: BuildContext, *, rule: str) -> int:
    python = ensure_backend(context)
    return context.run([str(python), "-m", "app.cli", "run-one", "--rule", rule], context.root)


def cmd_run(context: BuildContext, *, forward: list[str] | None = None) -> int:
    python = ensure_backend(context)
    if not find_node_tool("npm"):
        raise BuildError("未找到 npm；请先安装 Node.js 18+。")
    return context.run([str(python), "run_online.py", *(forward or [])], context.root)


def cmd_contract(context: BuildContext) -> int:
    python = ensure_backend(context)
    return context.run([str(python), "-m", "app.contract.export"], context.root)


def cmd_test(context: BuildContext) -> int:
    python = ensure_backend(context)
    return context.run([str(python), "-m", "pytest"], context.root)


def cmd_lint(context: BuildContext) -> int:
    python = ensure_backend(context)
    check_code = context.run([str(python), "-m", "ruff", "check", "app", "tests"], context.root)
    if check_code != 0:
        return check_code
    return context.run(
        [str(python), "-m", "ruff", "format", "--check", "app", "tests"],
        context.root,
    )


def find_node_tool(name: str) -> str:
    """发现 npm/npx，Windows 优先使用 .cmd 包装器。"""
    if IS_WINDOWS:
        return shutil.which(f"{name}.cmd") or shutil.which(name) or ""
    return shutil.which(name) or ""


def ensure_node_tool(name: str) -> str:
    tool = find_node_tool(name)
    if not tool:
        raise BuildError(f"未找到 {name}；请先安装 Node.js/npm。")
    return tool


def cmd_gen_web_api(context: BuildContext) -> int:
    npx = ensure_node_tool("npx")
    return context.run(
        [npx, "openapi-typescript", "../docs/api/openapi.yaml", "-o", "src/api/client.ts"],
        context.root / "web",
    )


def cmd_web_install(context: BuildContext) -> int:
    npm = ensure_node_tool("npm")
    return context.run([npm, "install"], context.root / "web")


def cmd_web_dev(context: BuildContext) -> int:
    npm = ensure_node_tool("npm")
    return context.run([npm, "run", "dev"], context.root / "web")


def cmd_web_build(context: BuildContext) -> int:
    npm = ensure_node_tool("npm")
    return context.run([npm, "run", "build"], context.root / "web")


def cmd_e2e_install(context: BuildContext) -> int:
    npm = ensure_node_tool("npm")
    npx = ensure_node_tool("npx")
    install_code = context.run([npm, "install"], context.root / "web")
    if install_code != 0:
        return install_code
    return context.run([npx, "playwright", "install", "chromium"], context.root / "web")


def cmd_e2e(context: BuildContext) -> int:
    npm = ensure_node_tool("npm")
    return context.run([npm, "run", "e2e"], context.root / "web")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python build.py",
        description="PatrolX 统一 Python 构建入口（不依赖 GNU Make 和 uv）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, description in COMMANDS.items():
        subparser = subparsers.add_parser(name, help=description, description=description)
        if name == "verify-one":
            subparser.add_argument("--rule", required=True, help="目标巡检规则代码")
        if name == "lock":
            subparser.add_argument("--check", action="store_true", help="只校验精确锁格式")
        if name == "run":
            subparser.add_argument("forward", nargs=argparse.REMAINDER, help="透传给 run_online.py 的参数")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "help":
            parser.print_help()
            return 0
        if not python_version_ok():
            print("需要 Python 3.11 或更高版本；请安装官方 Python 后重试。", file=sys.stderr)
            return 1
        context = BuildContext()
        if args.command == "install":
            return cmd_install(context)
        if args.command == "lock":
            return cmd_lock(context, check=args.check)
        if args.command == "verify":
            return cmd_verify(context)
        if args.command == "verify-one":
            return cmd_verify_one(context, rule=args.rule)
        if args.command == "run":
            return cmd_run(context, forward=args.forward)
        if args.command == "contract":
            return cmd_contract(context)
        if args.command == "gen-web-api":
            return cmd_gen_web_api(context)
        if args.command == "test":
            return cmd_test(context)
        if args.command == "lint":
            return cmd_lint(context)
        if args.command == "web-install":
            return cmd_web_install(context)
        if args.command == "web-dev":
            return cmd_web_dev(context)
        if args.command == "web-build":
            return cmd_web_build(context)
        if args.command == "e2e-install":
            return cmd_e2e_install(context)
        if args.command == "e2e":
            return cmd_e2e(context)
        parser.error(f"未知命令: {args.command}")
        return 2
    except SystemExit as exc:
        if exc.code is None:
            return 0
        return int(exc.code or 0)
    except BuildError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
