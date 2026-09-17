"""真实样例包规则覆盖看护：防止规则因真实数据缺失被静默跳过。"""

from app.inspectors.registry import registry
from app.services.executor import Executor
from tests.baseline_helpers import setup_env
from tests.fixtures.make_real_package import build_real_package

CALL_KPI_RULES = {"kpi.call"}
EXPECTED_SKIPS = {
    "kpi.api",
    "kpi.media",
    "log.ccc_service",
    "log.ddd_service",
    "traffic.stat",
}


def test_real_package_covers_app_scene_rules(tmp_path, monkeypatch) -> None:
    """真实包必须覆盖告警、配置、呼叫 KPI、容器资源和 UMF 日志规则。"""
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    registry.load_all()
    expected_codes = set(Executor(registry).inspect_plan())
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
