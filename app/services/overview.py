"""全局巡检概览统计。"""

import json

from app.core.config import settings
from app.inspectors.registry import registry
from app.models.schemas import OverviewSummary, Summary


def build_overview() -> OverviewSummary:
    """汇总任务、注册规则、规则结果、发现问题与状态分布。"""
    registry.load_all()
    task_count = 0
    rule_result_count = 0
    finding_count = 0
    counts = {key: 0 for key in ("pass", "warn", "fail", "error", "skip")}

    for path in settings.output.glob("*/task.json"):
        task = json.loads(path.read_text(encoding="utf-8"))
        task_count += 1
        stats = task.get("stats", {})
        rule_result_count += int(stats.get("total", 0))
        for key in counts:
            counts[key] += int(stats.get(key, 0))
        system = task.get("system") or {}
        for rule in system.get("rules") or []:
            finding_count += len(rule.get("findings") or [])

    return OverviewSummary(
        task_count=task_count,
        registered_rule_count=len(registry.all(include_hidden=True)),
        rule_result_count=rule_result_count,
        finding_count=finding_count,
        status_counts=Summary(
            total=rule_result_count,
            **counts,
        ),
    )
