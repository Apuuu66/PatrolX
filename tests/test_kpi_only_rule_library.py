"""KPI-only 规则库的核心验收用例。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.checksum import sha256_file
from app.services.executor import Executor
from app.services.rule_states import get_enabled_rule_codes
from tests.baseline_helpers import SAMPLE, load_rule, setup_env
from tests.fixtures.make_real_package import build_real_package, isolate_umf_scene

ACTIVE_RULES = {"alarm.active_state", "alarm.recurrence", "kpi.measurement_units"}
ACTIVE_RULE_CODES = ["alarm.active_state", "alarm.recurrence", "kpi.measurement_units"]


def test_sample_task_runs_only_kpi_and_preserves_package(tmp_path: Path, monkeypatch) -> None:
    from app.cli import run_task
    from app.inspectors.registry import registry

    env = setup_env(tmp_path, monkeypatch)
    checksum = sha256_file(SAMPLE)
    registry.load_all()
    expected = set(Executor(registry, get_enabled_rule_codes()).inspect_plan())

    task = run_task(
        SAMPLE,
        task_id="task-kpi-only",
        customer={"province": "北京", "operator": "移动", "product": "UMF"},
    )

    assert expected == ACTIVE_RULES
    assert [rule.code for rule in task.system.rules] == ACTIVE_RULE_CODES
    result = load_rule(env, task.task_id, "kpi.measurement_units")
    assert result["code"] == "kpi.measurement_units"
    assert result["status"] == "skip"
    assert result["skip_reason"] == "KPI CSV 未匹配到任何已启用测量单元"
    assert "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv" in result["metadata"]["files"]
    assert not (env.rules_dir(task.task_id) / "log.error_density.json").exists()
    manifest = json.loads((env.task_dir(task.task_id) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 5
    assert any(item["path"].startswith("kpi/") for item in manifest["catalog"])
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
    assert task.inventory.status.value == "not_archived"
    assert task.inventory.not_archived_reason == "source_file_missing"
    assert task.inventory.network_element_type_filter is not None
    assert task.inventory.network_element_type_filter.normalized == "CSP"
    assert task.inventory.network_element_type_filter.matched_count == 0
    assert [rule.code for rule in task.system.rules] == ACTIVE_RULE_CODES
    result = load_rule(env, task.task_id, "kpi.measurement_units")
    assert result["status"] == "skip"
    assert result["skip_reason"]
    manifest = json.loads((env.task_dir(task.task_id) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 5
    catalog_paths = {item["path"] for item in manifest["catalog"]}
    assert catalog_paths
    assert all(path.startswith("alarm/") for path in catalog_paths)
    assert not any(path.startswith(("kpi/", "basic/", "logs/")) for path in catalog_paths)
    assert manifest["summary"]["counts"]["ignored"] > 0
    assert any(item["error_code"] == "archive_corrupt" for item in manifest["failures"])
    rule_files = {path.stem for path in env.rules_dir(task.task_id).glob("*.json")}
    assert "kpi.measurement_units" in rule_files
    assert not any(name.startswith(("log.", "traffic.", "resource.")) for name in rule_files)
    assert sha256_file(package) == checksum


def test_real_structure_umf_package_runs_kpi_from_scene(tmp_path: Path, monkeypatch) -> None:
    """真实 UMF 场景中的 KPI 可被分类，并且只执行既有 KPI 普通规则。"""
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
    package = isolate_umf_scene(build_real_package(env.uploads), env.uploads / "umf-scene-focused.zip")
    checksum = sha256_file(package)

    task = run_task(
        package,
        task_id="task-kpi-real",
        customer={"province": "江苏", "operator": "移动", "product": "umf"},
    )

    assert task.status.value == "completed"
    assert [rule.code for rule in task.system.rules] == ACTIVE_RULE_CODES
    result = load_rule(env, task.task_id, "kpi.measurement_units")
    assert result["status"] == "pass"
    raw_metric_names = {
        metric["raw_source_name"] for unit in result["metadata"]["measurement_units"] for metric in unit["metrics"]
    }
    assert {"呼叫请求次数", "Call Requests"} <= raw_metric_names
    rate_metric_names = {
        "Media Resource Creation Success Rate(%)",
        "DC Resource Update Success Rate(%)",
        "Media Resource Creation Requests Success Rate(%)",
        "Data Channel Resource Update Requests Success Rate(%)",
    }
    rate_metrics = [
        metric
        for unit in result["metadata"]["measurement_units"]
        for metric in unit["metrics"]
        if metric["raw_source_name"] in rate_metric_names
    ]
    assert {metric["raw_source_name"] for metric in rate_metrics} == rate_metric_names
    for metric in rate_metrics:
        observations = metric["observations"]
        assert sum(observation["not_applicable_count"] for observation in observations) == 2
        assert sum(observation["valid_count"] for observation in observations) == 1
        assert all(observation["null_count"] == 0 for observation in observations)
    manifest = json.loads((env.task_dir(task.task_id) / "manifest.json").read_text(encoding="utf-8"))
    assert len([item for item in manifest["catalog"] if item["path"].startswith("kpi/")]) == 74
    assert sha256_file(package) == checksum


def test_us3_log_and_chr_categories_do_not_restore_non_kpi_rules(tmp_path: Path) -> None:
    """新增业务日志/CHR/主机分类只服务落位，不得恢复已下线普通规则。"""
    from app.core.archive import unpack
    from app.inspectors.registry import registry
    from app.services.extraction.classification import classify_main_evidence

    package = build_real_package(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)

    base = "Outer Device/Problem 038/wrapper/UMF Problem Scene"
    data_dir = tmp_path / "task"
    evidence_root = data_dir / ".main"
    shutil.copytree(extracted / base, evidence_root / base)
    run = classify_main_evidence(data_dir, product="UMF")

    assert {"umf.service-logs", "umf.chr", "umf.host-debug", "umf.host-system"} <= {
        entry.route_id for entry in run.entries
    }
    registry.load_all()
    assert {rule.code for rule in registry.all()} == ACTIVE_RULES
    assert {rule.code for rule in registry.all(include_hidden=True)} == {
        *ACTIVE_RULES,
        "pkg.extract.main",
        "pkg.extract.classification",
    }
