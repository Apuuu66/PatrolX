"""为告警闪断检测 E2E 准备真实样例包巡检产物。

E2E 断言的是"真实样例包执行后"的展示效果，因此这里走与线上完全一致的
执行链路（解压 → 规则执行 → 存储 → 报告），任务号固定便于前端用例直接访问。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.cli import run_task
from app.core.config import settings
from app.models.db import init_db
from tests.fixtures.make_real_package import build_real_package

TASK_ID = "task-alarm-flapping-e2e"


def main() -> None:
    init_db()
    with tempfile.TemporaryDirectory(prefix="patrolx-alarm-flapping-") as tmp:
        package = build_real_package(Path(tmp))
        upload_dir = settings.uploads / TASK_ID
        upload_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package, upload_dir / package.name)
        task = run_task(package, name="告警闪断样例任务", task_id=TASK_ID)
    if task.status.value != "completed":
        raise SystemExit(f"告警闪断 seed 任务执行失败：{task.status.value}")
    print(f"seeded {TASK_ID}: rules={task.stats.total} fail={task.stats.fail}")


if __name__ == "__main__":
    main()
