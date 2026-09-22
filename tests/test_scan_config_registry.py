"""注册表启动时加载扫描配置的契约测试。"""

from app.core.config import settings
from app.inspectors.registry import registry

EXPECTED_REFS = {
    "alarm.stat",
    "config.check",
    "resource.check",
    "traffic.stat",
    "log.error_density",
    "log.umf_service",
    "log.umf_acc",
    "log.stacktrace",
    "log.filter",
    "log.repeat_error",
    "log.fault_pattern",
    "log.service_errors",
    "kpi.measurement_units",
}
DISABLED_RULES = {"log.ccc_service", "log.ddd_service"}


def test_load_all_resolves_declared_source_refs() -> None:
    registry.load_all()
    rules = {rule.code: rule for rule in registry.all()}

    assert EXPECTED_REFS <= set(rules)
    for code in EXPECTED_REFS:
        rule = rules[code]
        assert rule.source_refs, code
        assert rule.scan_refs_resolved, code
        assert rule.source_patterns, code

    assert (settings.config / "scan_rules.yaml").is_file()


def test_load_all_retains_disabled_rules_and_their_prepares() -> None:
    """配置禁用只影响执行计划；注册表仍保留规则元数据和私有 prepare。"""
    from app.services.executor import Executor
    from app.services.rule_states import get_enabled_rule_codes

    registry.load_all()
    rules = {rule.code: rule for rule in registry.all()}
    assert DISABLED_RULES <= set(rules)
    for code in DISABLED_RULES:
        assert not rules[code].hidden

    assert DISABLED_RULES.isdisjoint(Executor(registry, get_enabled_rule_codes()).inspect_plan())
