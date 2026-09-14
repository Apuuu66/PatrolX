"""真实样例包规则覆盖看护：防止新增或存量规则因数据缺失被跳过。"""

from pathlib import Path

import pytest

from app.inspectors.registry import registry
from app.services.executor import Executor
from tests.baseline_helpers import setup_env

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_PACKAGES = (
    REPO_ROOT / "uploads" / "CCC_DDD_sample_20260914.zip",
    REPO_ROOT / "uploads" / "ZZapp01BCN_app_Problem_scene_333_full.zip",
)
KPI_RULES = {"kpi.api", "kpi.call", "kpi.media"}


@pytest.mark.parametrize("package", GUARD_PACKAGES, ids=lambda package: package.name)
def test_sample_package_covers_all_normal_rules(package: Path, tmp_path, monkeypatch) -> None:
    """样例包必须让全部普通规则获得结果，且 KPI 三类规则不被跳过。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    registry.load_all()
    expected_codes = set(Executor(registry).inspect_plan())
    assert expected_codes, "普通规则计划不能为空"
    assert KPI_RULES <= expected_codes

    task = run_task(package, name=package.stem)
    actual_results = {result.code: result for result in task.system.rules}

    assert task.status == "completed"
    assert set(actual_results) == expected_codes
    assert task.stats.skip == 0
    skipped = {code for code, result in actual_results.items() if result.status == "skip"}
    assert not skipped, f"样例包存在跳过规则: {sorted(skipped)}"
    assert not ({"kpi.api", "kpi.call", "kpi.media"} - set(actual_results))
