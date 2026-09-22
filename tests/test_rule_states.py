"""规则启停状态服务契约测试。"""

from pathlib import Path

import pytest
import yaml

from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry, registry
from app.models.db import RuleState, session_factory
from app.models.schemas import Priority, RuleCategory, Severity
from app.services.rule_states import (
    RuleStateError,
    ensure_rule_states,
    get_enabled_rule_codes,
    list_rule_states,
    update_rule_state,
)


def _write_scan_config(path: Path, disabled_rules: list[str] | object) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "groups": {"test": {"source_patterns": [r"test/.*"]}},
                "disabled_rules": disabled_rules,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _local_registry(codes: list[str]) -> RuleRegistry:
    target = RuleRegistry()
    for code in codes:
        target.register(
            Inspector(
                code=code,
                name=code,
                category=RuleCategory.OTHER,
                severity=Severity.LOW,
                priority=Priority.P1,
                rule_version="1.0.0",
                description="测试规则",
                recommendation="测试规则",
                source_patterns=[r"test/.*"],
                run=lambda _ctx: None,
            )
        )
    return target


def test_ensure_imports_configured_disabled_rules_once() -> None:
    ensure_rule_states()

    with session_factory() as session:
        states = {item.rule_code: item.enabled for item in session.query(RuleState).all()}

    assert "log.ccc_service" in states
    assert states["log.ccc_service"] is False
    assert "log.error_density" in states
    assert states["log.error_density"] is True


def test_existing_states_are_not_overwritten_by_reinitialization() -> None:
    ensure_rule_states()
    update_rule_state("log.ccc_service", True)
    ensure_rule_states()

    assert update_rule_state("log.ccc_service", True).enabled is True


def test_update_persists_state_and_timestamp() -> None:
    ensure_rule_states()
    first = update_rule_state("log.error_density", False)
    second = update_rule_state("log.error_density", False)

    assert first.enabled is False
    assert second.updated_at == first.updated_at
    assert "log.error_density" not in get_enabled_rule_codes()


def test_enabled_codes_match_persisted_states() -> None:
    ensure_rule_states()
    update_rule_state("log.error_density", False)

    enabled = get_enabled_rule_codes()
    assert "log.error_density" not in enabled
    assert "config.check" in enabled


def test_ten_sequential_toggles_keep_final_state() -> None:
    ensure_rule_states()
    for enabled in [False, True] * 5:
        state = update_rule_state("log.error_density", enabled)
        assert state.enabled is enabled

    states = {item.code: item.enabled for item in list_rule_states(page=1, page_size=100).items}
    assert states["log.error_density"] is True


def test_unknown_rule_returns_not_found() -> None:
    ensure_rule_states()
    with pytest.raises(RuleStateError) as exc_info:
        update_rule_state("rule.not_registered", False)
    assert exc_info.value.code == "not_found"
    assert exc_info.value.status_code == 404


def test_hidden_rule_is_not_manageable() -> None:
    ensure_rule_states()
    with pytest.raises(RuleStateError) as exc_info:
        update_rule_state("pkg.extract.main", False)
    assert exc_info.value.code == "rule_not_manageable"
    assert exc_info.value.status_code == 409


def test_local_registry_initializes_missing_rules_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scan_rules = tmp_path / "scan_rules.yaml"
    _write_scan_config(scan_rules, ["test.disabled"])
    monkeypatch.setattr("app.services.rule_states.settings.config_dir", tmp_path)

    target = _local_registry(["test.enabled", "test.disabled"])
    ensure_rule_states(target)

    states = {
        item.code: item.enabled for item in list_rule_states(page=1, page_size=10, registry_override=target).items
    }
    assert states == {"test.enabled": True, "test.disabled": False}


def test_local_registry_new_rule_defaults_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scan_rules = tmp_path / "scan_rules.yaml"
    _write_scan_config(scan_rules, [])
    monkeypatch.setattr("app.services.rule_states.settings.config_dir", tmp_path)

    target = _local_registry(["test.first"])
    ensure_rule_states(target)
    target.register(
        Inspector(
            code="test.second",
            name="test.second",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="测试规则",
            recommendation="测试规则",
            source_patterns=[r"test/.*"],
            run=lambda _ctx: None,
        )
    )
    ensure_rule_states(target)

    assert get_enabled_rule_codes(registry_override=target) == {"test.first", "test.second"}


def test_unknown_configured_rule_blocks_initialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scan_rules = tmp_path / "scan_rules.yaml"
    _write_scan_config(scan_rules, ["test.missing"])
    monkeypatch.setattr("app.services.rule_states.settings.config_dir", tmp_path)

    with pytest.raises(ValueError, match="禁用规则未注册"):
        ensure_rule_states(_local_registry(["test.enabled"]))


def test_invalid_config_format_blocks_initialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scan_rules = tmp_path / "scan_rules.yaml"
    scan_rules.write_text("version: []\n", encoding="utf-8")
    monkeypatch.setattr("app.services.rule_states.settings.config_dir", tmp_path)

    with pytest.raises(ValueError, match="扫描配置"):
        ensure_rule_states(_local_registry(["test.enabled"]))


def test_registry_keeps_disabled_rules_loaded_for_ui_and_rerun() -> None:
    registry.load_all()

    assert "log.ccc_service" in registry.codes()
    assert registry.get("log.ccc_service").hidden is False
