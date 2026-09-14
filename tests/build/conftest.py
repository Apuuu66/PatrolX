"""构建器测试共享替身。"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("_patrolx_build", PROJECT_ROOT / "build.py")
_build_module = importlib.util.module_from_spec(_spec)
sys.modules["_patrolx_build"] = _build_module
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_build_module)
build = _build_module


@dataclass
class RunnerCall:
    command: list[str]
    cwd: Path | None = None


@dataclass
class FakeRunner:
    result: int = 0
    calls: list[RunnerCall] = field(default_factory=list)
    callback: Callable[[list[str], Path | None], int | None] | None = None

    def __call__(self, command: list[str], cwd: Path | None = None) -> int:
        call = RunnerCall([str(item) for item in command], cwd)
        self.calls.append(call)
        if self.callback is not None:
            value = self.callback(call.command, call.cwd)
            return self.result if value is None else value
        return self.result

    def commands(self) -> list[list[str]]:
        return [call.command for call in self.calls]


def make_context(tmp_path: Path, runner: FakeRunner | None = None) -> build.BuildContext:
    context = build.BuildContext(root=tmp_path, runner=runner or FakeRunner())
    context.venv_python(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    context.venv_python(tmp_path).touch()
    return context
