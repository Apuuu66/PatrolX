"""KPI-only 规则库的核心验收用例。"""

from __future__ import annotations

from pathlib import Path

from app.core.checksum import sha256_file
from app.services.executor import Executor
from app.services.rule_states import get_enabled_rule_codes
from tests.baseline_helpers import SAMPLE, load_rule, setup_env
from tests.fixtures.make_real_package import build_real_package


def test_sample_task_runs_only_kpi_and_preserves_package(tmp_path: Path, monkeypatch) -> None:
    from app.cli import run_task
    from app.inspectors.registry import registry

    env = setup_env(tmp_path, monkeypatch)
    checksum = sha256_file(SAMPLE)
    registry.load_all()
    expected = set(Executor(registry, get_enabled_rule_codes()).inspect_plan())

    task = run_task(SAMPLE, task_id="task-kpi-only")

    assert expected == {"kpi.measurement_units"}
    assert [rule.code for rule in task.system.rules] == ["kpi.measurement_units"]
    assert load_rule(env, task.task_id, "kpi.measurement_units")["code"] == "kpi.measurement_units"
    assert not (env.rules_dir(task.task_id) / "log.error_density.json").exists()
    for category in ("logs", "kpi", "traffic", "alarm", "config", "resource", "other"):
        assert (env.task_dir(task.task_id) / category).is_dir()
    assert sha256_file(SAMPLE) == checksum


def test_task_without_kpi_returns_skip_and_preserves_non_kpi_files(tmp_path: Path, monkeypatch) -> None:
    from app.cli import run_task

    env = setup_env(tmp_path, monkeypatch)
    package = build_real_package(tmp_path / "boundary", include_kpi=False)
    checksum = sha256_file(package)

    task = run_task(
        package,
        task_id="task-kpi-skip",
        customer={"province": "北京", "operator": "移动", "product": "CSP"},
    )

    assert task.status.value == "completed"
    assert task.inventory is not None
    assert task.inventory.status.value == "archived"
    assert task.inventory.network_element_type_filter is not None
    assert task.inventory.network_element_type_filter.matched_count == 3
    assert [rule.code for rule in task.system.rules] == ["kpi.measurement_units"]
    result = load_rule(env, task.task_id, "kpi.measurement_units")
    assert result["status"] == "skip"
    assert result["skip_reason"]
    for category in ("alarm", "config", "logs"):
        files = [path for path in (env.task_dir(task.task_id) / category).rglob("*") if path.is_file()]
        assert files, f"{category} 分类文件应被保留"
    rule_files = {path.stem for path in env.rules_dir(task.task_id).glob("*.json")}
    assert "kpi.measurement_units" in rule_files
    assert all(name.startswith(("kpi.", "pkg.extract.")) for name in rule_files)
    assert sha256_file(package) == checksum


def test_real_structure_package_runs_kpi_and_archives_inventory(tmp_path: Path, monkeypatch) -> None:
    """含 KPI 与台账的真实结构包只执行 KPI，并完整归档匹配网元的台账。"""
    from app.cli import run_task

    env = setup_env(tmp_path, monkeypatch)
    from app.services.kpi_measurement_units import import_resource_csv, io

    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫会话统计,Call Session API Statistics\n"
            "MU_CONTAINER,容器指标单元,Container Metric Unit\n"
        )
    )
    package = build_real_package(env.uploads)
    checksum = sha256_file(package)

    task = run_task(
        package,
        task_id="task-kpi-real",
        customer={"province": "江苏", "operator": "移动", "product": "csp"},
    )

    assert task.status.value == "completed"
    assert task.inventory is not None
    assert task.inventory.status.value == "archived"
    assert task.inventory.network_element_type_filter is not None
    assert task.inventory.network_element_type_filter.normalized == "CSP"
    assert task.inventory.network_element_type_filter.matched_count == 3
    assert [rule.code for rule in task.system.rules] == ["kpi.measurement_units"]
    assert load_rule(env, task.task_id, "kpi.measurement_units")["status"] != "skip"
    assert sha256_file(package) == checksum
