"""注册表启动时加载扫描配置的契约测试。"""

from app.core.config import settings
from app.inspectors.registry import registry

EXPECTED_REFS = {
    "alarm.stat",
    "config.check",
    "resource.check",
    "traffic.stat",
    "log.error_density",
    "log.aaa_service",
    "log.app_service",
    "log.ccc_service",
    "log.ddd_service",
    "log.stacktrace",
    "log.filter",
    "log.repeat_error",
    "log.fault_pattern",
    "log.service_errors",
    "kpi.call",
    "kpi.api",
    "kpi.media",
}


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
