"""真实样例包规则覆盖看护：防止规则因真实数据缺失被静默跳过。"""

from app.inspectors.registry import registry
from app.services.executor import Executor
from app.services.rule_states import get_enabled_rule_codes
from tests.baseline_helpers import load_rule, setup_env
from tests.fixtures.make_real_package import build_real_package

CALL_KPI_RULES = {"kpi.measurement_units"}
EXPECTED_SKIPS = {
    "kpi.measurement_units",
    "traffic.stat",
}


def test_real_package_covers_app_scene_rules(tmp_path, monkeypatch) -> None:
    """真实包必须覆盖告警、配置、呼叫 KPI、容器资源和 UMF 日志规则。"""
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    registry.load_all()
    expected_codes = set(Executor(registry, get_enabled_rule_codes()).inspect_plan())
    assert expected_codes, "普通规则计划不能为空"
    assert CALL_KPI_RULES <= expected_codes

    package = build_real_package(env.uploads)
    task = run_task(package, name=package.stem)
    actual_results = {result.code: result for result in task.system.rules}
    skipped = {code for code, result in actual_results.items() if result.status.value == "skip"}

    assert task.status.value == "completed"
    assert set(actual_results) == expected_codes
    assert skipped == EXPECTED_SKIPS, f"实际跳过规则: {sorted(skipped)}"
    assert not (CALL_KPI_RULES - set(actual_results))

    # 闪断规则必须真正跑在真实样例包上，不得静默跳过（宪法 2.9.0 样例包看护）。
    flapping = actual_results["alarm.flapping"]
    assert flapping.status.value != "skip", f"alarm.flapping 不应跳过: {flapping.summary}"
    # 任务/系统索引里的 rules 是摘要（metadata 被剥离），大明细只落在 rules/<code>.json。
    detail = load_rule(env, task.task_id, "alarm.flapping")
    assert detail["metadata"]["alarm_flapping"]["totals"]["rows"] == 22
