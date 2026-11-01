"""注册表启动时加载扫描配置的契约测试。"""

from pathlib import Path

from app.core.config import settings
from app.inspectors.registry import registry

ACTIVE_RULES = {"kpi.measurement_units"}
HIDDEN_RULES = {
    "pkg.extract.main",
    "pkg.extract.logs",
    "pkg.extract.kpi",
    "pkg.extract.traffic",
    "pkg.extract.alarm",
    "pkg.extract.config",
    "pkg.extract.resource",
    "pkg.extract.other",
}


def test_load_all_resolves_declared_source_refs() -> None:
    registry.load_all()
    rules = {rule.code: rule for rule in registry.all()}

    assert set(rules) == ACTIVE_RULES
    kpi = rules["kpi.measurement_units"]
    assert kpi.source_refs == ["kpi_all"]
    assert kpi.scan_refs_resolved
    assert kpi.source_patterns == [r"^kpi/.*\.csv$", r"^traffic/.*\.csv$"]
    assert kpi.rule_version == "3.3.0"

    assert (settings.config / "scan_rules.yaml").is_file()


def test_load_all_keeps_only_kpi_active_and_extraction_hidden() -> None:
    """活动普通规则只含 KPI；解压基础设施保持 hidden。"""
    from app.services.executor import Executor
    from app.services.rule_states import get_enabled_rule_codes

    registry.load_all()
    hidden = {rule.code for rule in registry.all(include_hidden=True) if rule.hidden}
    assert hidden == HIDDEN_RULES
    assert all(code.startswith("pkg.extract.") for code in hidden)
    assert get_enabled_rule_codes() == ACTIVE_RULES

    assert Executor(registry, get_enabled_rule_codes()).inspect_plan() == ["kpi.measurement_units"]


def test_scan_config_contains_only_kpi_group() -> None:
    import yaml

    payload = yaml.safe_load(pathlib_path(settings.config / "scan_rules.yaml").read_text(encoding="utf-8"))
    assert payload["groups"].keys() == {"kpi_all"}
    assert payload["disabled_rules"] == []


def pathlib_path(value: object) -> Path:
    """让 YAML 配置断言在不同 Path 实现下保持类型明确。"""
    return Path(value)
