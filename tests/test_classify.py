"""分类规则表测试（名称规律 + 内容嗅探）。"""

from app.core.classify import classify_name
from app.models.schemas import RuleCategory


def test_classify_by_pattern() -> None:
    assert classify_name("AAAService.zip") == RuleCategory.LOG
    assert classify_name("ServiceLog.zip") == RuleCategory.LOG
    assert classify_name("kpi_export.csv") == RuleCategory.KPI
    assert classify_name("alarm_export.txt") == RuleCategory.ALARM
    assert classify_name("app.conf") == RuleCategory.CONFIG
    assert classify_name("pod_cpu.txt") == RuleCategory.RESOURCE
    assert classify_name("unknown.dat") is None
