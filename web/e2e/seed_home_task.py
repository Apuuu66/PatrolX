"""为巡检任务首页 E2E 准备失败任务样例；已完成样例由测量历史 seed 提供。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.models.db import init_db
from app.models.schemas import (
    InspectionTask,
    Priority,
    RuleCategory,
    RuleResult,
    RuleStatus,
    Severity,
    Summary,
    SystemInspection,
    TaskStats,
)
from app.services.store import save_rule_result, save_system, save_task_meta

TASK_ID = "task-home-failed"


def main() -> None:
    init_db()
    task_dir = settings.output / TASK_ID
    upload_dir = settings.uploads / TASK_ID
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "home-failed.zip").write_bytes(b"e2e")

    rule = RuleResult(
        code="log.error_density",
        name="日志错误密度",
        category=RuleCategory.LOG,
        priority=Priority.P1,
        execution_order=0,
        status=RuleStatus.ERROR,
        severity=Severity.MEDIUM,
        summary="主清单解析失败",
        executed_at=datetime(2026, 9, 22, 10, 0, 10, tzinfo=UTC),
        duration_ms=10000,
    )
    system = SystemInspection(
        package_file="home-failed.zip",
        version="v2",
        status="failed",
        summary=Summary(total=1, pass_=0, warn=0, fail=0, error=1, skip=0),
        rules=[rule],
        customer={
            "province": "js",
            "operator": "cmcc",
            "product": "router",
            "device_id": "home-device-001",
        },
    )
    save_rule_result(settings.output, TASK_ID, rule)
    save_system(settings.output, TASK_ID, system)
    save_task_meta(
        settings.output,
        InspectionTask(
            task_id=TASK_ID,
            name="首页失败任务样例",
            mode="local",
            status="failed",
            trigger="api",
            created_at=datetime(2026, 9, 22, 10, 0, tzinfo=UTC),
            completed_at=datetime(2026, 9, 22, 10, 0, 10, tzinfo=UTC),
            stats=TaskStats.model_validate(
                {"total": 1, "pass": 0, "warn": 0, "fail": 0, "error": 1, "skip": 0, "systems": 1}
            ),
            system=system,
        ),
    )
    (task_dir / "execution.log").write_text(
        json.dumps(
            {
                "ts": "2026-09-22T10:00:10Z",
                "level": "error",
                "message": "任务执行失败：解析主清单失败",
                "rule_code": "log.error_density",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
