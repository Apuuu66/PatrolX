"""真实样例包规则覆盖看护：防止规则因真实数据缺失被静默跳过。"""

from app.inspectors.registry import registry
from app.services.executor import Executor
from app.services.kpi_measurement_units import import_resource_csv, io
from app.services.rule_states import get_enabled_rule_codes
from tests.baseline_helpers import load_rule, setup_env
from tests.fixtures.make_real_package import build_real_package

CALL_KPI_RULES = {"kpi.measurement_units"}


def test_real_package_covers_app_scene_rules(tmp_path, monkeypatch) -> None:
    """真实包只触发 KPI 普通规则，但保留其他证据分类。"""
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫会话统计,Call Session API Statistics\n"))
    registry.load_all()
    expected_codes = set(Executor(registry, get_enabled_rule_codes()).inspect_plan())
    assert expected_codes, "普通规则计划不能为空"
    assert CALL_KPI_RULES == expected_codes

    package = build_real_package(env.uploads)
    task = run_task(package, name=package.stem)
    actual_results = {result.code: result for result in task.system.rules}
    assert task.status.value == "completed"
    assert set(actual_results) == expected_codes
    assert actual_results["kpi.measurement_units"].status.value != "skip"
    for category in ("alarm", "config", "logs", "resource", "traffic"):
        assert (env.task_dir(task.task_id) / category).is_dir()
    assert not (env.rules_dir(task.task_id) / "alarm.flapping.json").exists()
    assert load_rule(env, task.task_id, "kpi.measurement_units")["code"] == "kpi.measurement_units"
