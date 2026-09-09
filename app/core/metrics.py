"""Prometheus 指标：任务与规则执行的内部可观测（/metrics）。"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

TASKS_TOTAL = Counter("patrolx_tasks_total", "巡检任务总数（按结果与模式）", ["result", "mode"])
TASKS_DURATION = Histogram(
    "patrolx_task_duration_seconds",
    "任务执行耗时",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)
RULES_TOTAL = Counter("patrolx_rules_total", "规则执行总数（按规则与状态）", ["rule", "status"])


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
