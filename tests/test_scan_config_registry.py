"""注册表启动时加载扫描配置的契约测试。"""

from pathlib import Path

import yaml

from app.core.config import settings
from app.inspectors.registry import registry
from app.services.scanning import match_paths

ACTIVE_RULES = {"alarm.active_state", "alarm.recurrence", "kpi.measurement_units"}
HIDDEN_RULES = {
    "pkg.extract.main",
    "pkg.extract.classification",
}


def test_load_all_resolves_declared_source_refs() -> None:
    registry.load_all()
    rules = {rule.code: rule for rule in registry.all()}

    assert set(rules) == ACTIVE_RULES
    for code in ("alarm.active_state", "alarm.recurrence"):
        assert rules[code].source_refs == ["alarm_all"]
        assert rules[code].scan_refs_resolved
        assert rules[code].source_patterns == [r"^alarm/[^/]+\.csv$"]
    kpi = rules["kpi.measurement_units"]
    assert kpi.source_refs == ["kpi_all"]
    assert kpi.scan_refs_resolved
    assert kpi.source_patterns == [r"^kpi/.*\.csv$", r"^traffic/.*\.csv$"]
    assert kpi.rule_version == "3.3.3"

    assert (settings.config / "scan_rules.yaml").is_file()


def test_load_all_keeps_alarm_and_kpi_active_and_extraction_hidden() -> None:
    """活动普通规则含告警与 KPI；解压基础设施保持 hidden。"""
    from app.services.executor import Executor
    from app.services.rule_states import get_enabled_rule_codes

    registry.load_all()
    hidden = {rule.code for rule in registry.all(include_hidden=True) if rule.hidden}
    assert hidden == HIDDEN_RULES
    assert all(code.startswith("pkg.extract.") for code in hidden)
    versions = {rule.code: rule.rule_version for rule in registry.all(include_hidden=True) if rule.hidden}
    assert versions == {
        "pkg.extract.main": "4.0.0",
        "pkg.extract.classification": "1.0.0",
    }
    assert get_enabled_rule_codes() == ACTIVE_RULES

    assert Executor(registry, get_enabled_rule_codes()).inspect_plan() == [
        "alarm.active_state",
        "alarm.recurrence",
        "kpi.measurement_units",
    ]


def test_scan_config_declares_direct_alarm_csv_group() -> None:
    payload = yaml.safe_load(pathlib_path(settings.config / "scan_rules.yaml").read_text(encoding="utf-8"))
    assert payload["groups"].keys() == {"alarm_all", "kpi_all"}
    assert payload["groups"]["alarm_all"] == {
        "description": "告警目录直属 CSV",
        "source_patterns": [r"^alarm/[^/]+\.csv$"],
    }
    assert payload["disabled_rules"] == []

    pattern = payload["groups"]["alarm_all"]["source_patterns"]
    matched = match_paths(
        [
            Path("alarm/alarm_history_001.csv"),
            Path("alarm/nested/alarm_history_002.csv"),
            Path("alarm/alarm_history_001.json"),
            Path("operation-log/alarm_history_001.csv"),
        ],
        pattern,
    )
    assert [path.as_posix() for path in matched] == ["alarm/alarm_history_001.csv"]


def pathlib_path(value: object) -> Path:
    """让 YAML 配置断言在不同 Path 实现下保持类型明确。"""
    return Path(value)
