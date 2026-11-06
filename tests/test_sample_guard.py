"""真实样例包规则覆盖看护：防止规则因真实数据缺失被静默跳过。"""

from app.inspectors.registry import registry
from app.services.kpi_measurement_units import import_resource_csv, io
from tests.baseline_helpers import load_rule, setup_env
from tests.fixtures.make_real_package import build_real_package

ACTIVE_RULES = {"alarm.active_state", "alarm.recurrence", "kpi.measurement_units"}


def test_real_package_covers_app_scene_rules(tmp_path, monkeypatch) -> None:
    """真实包触发当前活动的告警与 KPI 普通规则，并保留其他证据分类。"""
    env = setup_env(tmp_path, monkeypatch, assign_rules_to="UMF")
    from app.cli import run_task

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫会话统计,Call Session API Statistics\n"))
    registry.load_all()
    expected_codes = set(registry.inspect_plan())
    assert expected_codes, "普通规则计划不能为空"
    assert ACTIVE_RULES == expected_codes

    package = build_real_package(env.uploads)
    task = run_task(package, name=package.stem, customer={"product": "UMF"})
    actual_results = {result.code: result for result in task.system.rules}
    assert task.status.value == "completed"
    assert set(actual_results) == expected_codes
    assert actual_results["kpi.measurement_units"].status.value != "skip"
    active_rule = load_rule(env, task.task_id, "alarm.active_state")
    recurrence_rule = load_rule(env, task.task_id, "alarm.recurrence")
    active_metadata = active_rule["metadata"]["alarm_active"]
    recurrence_metadata = recurrence_rule["metadata"]["alarm_recurrence"]
    assert active_rule["status"] == "fail"
    assert recurrence_rule["status"] == "fail"
    assert active_metadata["coverage"]["end_at"] == "2026-09-18T09:01:00+00:00"
    assert active_metadata["coverage"]["end_basis"] == "max_valid_alarm_timestamp"
    assert active_metadata["totals"]["failed_files"] == 1
    assert active_metadata["totals"]["active_records"] == 5
    assert active_metadata["active_summary"]["raw_repeat_times_total"] == 28
    assert active_metadata["active_summary"]["estimated_report_total"] == 33
    assert recurrence_metadata["coverage"]["end_at"] == "2026-09-18T09:01:00+00:00"
    assert recurrence_metadata["coverage"]["end_basis"] == "max_valid_alarm_timestamp"
    assert recurrence_metadata["totals"]["failed_files"] == 1
    assert recurrence_metadata["totals"]["valid_records"] == 21
    assert recurrence_metadata["totals"]["alarm_types"] == 18
    assert recurrence_metadata["totals"]["repeat_reporting_types"] == 15
    assert recurrence_metadata["totals"]["rapid_recurrence_types"] == 1
    assert recurrence_metadata["totals"]["reset_cleared_records"] == 2
    for category in (
        "basic",
        "chr",
        "host-debug",
        "host-system",
        "kpi",
        "logs",
        "mml",
        "other",
        "status",
    ):
        assert (env.task_dir(task.task_id) / category).is_dir(), category
    assert not (env.rules_dir(task.task_id) / "alarm.flapping.json").exists()
    assert load_rule(env, task.task_id, "kpi.measurement_units")["code"] == "kpi.measurement_units"
