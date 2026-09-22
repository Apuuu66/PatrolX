"""分类规则表测试（名称规律 + 内容嗅探）。"""

from app.core.classify import classify_member, classify_name
from app.models.schemas import RuleCategory


def test_classify_by_pattern() -> None:
    assert classify_name("AAAService.zip") == RuleCategory.LOG
    assert classify_name("ServiceLog.zip") == RuleCategory.LOG
    assert classify_name("kpi_export.csv") == RuleCategory.KPI
    assert classify_name("kpi-api-5.csv") == RuleCategory.KPI
    assert classify_name("kpi-media-60.csv") == RuleCategory.KPI
    assert classify_name("ne333_Call_Session_API_Statistics_15_0_202609020000.csv") == RuleCategory.KPI
    assert classify_name("alarm_export.txt") == RuleCategory.ALARM
    assert classify_name("alarm_history.csv") == RuleCategory.ALARM
    assert classify_name("alarm_summary.json") == RuleCategory.ALARM
    assert classify_name("app.conf") == RuleCategory.CONFIG
    assert classify_name("pod_cpu.txt") == RuleCategory.RESOURCE
    assert classify_name("ne333_Call_Session_API_Statistics_5_0_202609020000.csv") == RuleCategory.KPI
    assert classify_name("ne333_Container_Metric_Unit_5_0_202609020000.csv") == RuleCategory.RESOURCE
    assert classify_name("unknown.dat") is None


def test_archive_member_lock_overrides_member_name() -> None:
    assert (
        classify_member(
            "ne333_Container_Metric_Unit_5_0.csv",
            "PerfResult_202609010101137101.zip",
        )
        == RuleCategory.KPI
    )
    assert classify_member("unknown.csv", "unknown.zip") is None
    assert classify_member("unknown.csv", "*invalid-[.zip") is None
