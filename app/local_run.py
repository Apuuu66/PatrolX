"""本地调试运行入口：执行 local_run/ 目录下的全部数据包。"""

from app.cli import find_packages, run_task
from app.core.config import settings
from app.models.schemas import TaskMode, TaskTrigger


def run_local_packages() -> int:
    """运行 local_run/ 下所有压缩包；每个包仍是独立任务。"""
    packages = find_packages(settings.local_run)
    if not packages:
        print("未找到数据包：请将 zip/tar.gz 放入 local_run/ 目录")
        return 1

    for package in packages:
        run_task(package, mode=TaskMode.LOCAL, trigger=TaskTrigger.CLI)
    return 0
