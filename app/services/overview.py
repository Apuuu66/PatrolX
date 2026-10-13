"""全局巡检概览统计：数据全部来自 SQLite。"""

from app.inspectors.registry import registry
from app.models.schemas import OverviewSummary, Summary
from app.services import task_db


def build_overview() -> OverviewSummary:
    """汇总任务、注册规则、规则结果、发现问题与状态分布。

    展示口径（任务数、可见规则结果数、发现数、状态分布）全部由任务行与规则结果行聚合，
    不扫描 ``output/``；隐藏规则与既有口径一致地不计入。
    """
    registry.load_all()
    counts = task_db.overview_counts()
    return OverviewSummary(
        task_count=counts.task_count,
        registered_rule_count=len(registry.all(include_hidden=True)),
        rule_result_count=counts.rule_result_count,
        finding_count=counts.finding_count,
        status_counts=Summary(
            total=counts.rule_result_count,
            **counts.status_counts,
        ),
    )
