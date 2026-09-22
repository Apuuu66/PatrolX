"""巡检器注册表：启动时自动扫描 app/inspectors/** 装载全部规则。"""

import importlib
import pkgutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.scan_config import load_scan_config, validate_scan_groups
from app.inspectors.base import Inspector, PrepareSpec


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, Inspector] = {}
        self._prepares: dict[str, tuple[Inspector, PrepareSpec]] = {}
        self._prepare_by_owner: dict[str, PrepareSpec] = {}
        self._loaded = False
        self._scan_refs_resolved = False

    def register(self, inspector: Inspector) -> None:
        inspector.validate()
        if inspector.code in self._rules:
            raise ValueError(f"规则 code 重复: {inspector.code}")
        self._rules[inspector.code] = inspector
        if inspector.prepare is not None:
            self._register_prepare(inspector, inspector.prepare)

    def resolve_scan_refs(self, groups: Mapping[str, Any]) -> None:
        """将规则声明的 source_refs 展开为运行时 source_patterns。"""
        normalized_groups = {
            name: value if isinstance(value, Mapping) else {"source_patterns": value} for name, value in groups.items()
        }
        resolved_groups = validate_scan_groups({"version": 1, "groups": normalized_groups})
        for rule in self._rules.values():
            if rule.source_refs is None:
                continue
            unknown = [ref for ref in rule.source_refs if ref not in resolved_groups]
            if unknown:
                raise ValueError(f"规则 {rule.code} 引用未定义扫描组: {unknown[0]}")
            rule.source_patterns = [pattern for ref in rule.source_refs for pattern in resolved_groups[ref]]
            rule.scan_refs_resolved = True
            rule.validate()
        self._scan_refs_resolved = True

    def _has_unresolved_source_refs(self) -> bool:
        return any(rule.source_refs is not None for rule in self._rules.values()) and not self._scan_refs_resolved

    def _require_resolved_scan_refs(self) -> None:
        if self._has_unresolved_source_refs():
            raise ValueError("source_refs 未解析，禁止生成执行计划")

    def _register_prepare(self, owner: Inspector, prepare: PrepareSpec) -> None:
        if owner.code in self._prepare_by_owner:
            raise ValueError(f"规则 {owner.code} owner prepare 重复")
        if prepare.code in self._prepares or prepare.code in self._rules:
            raise ValueError(f"prepare code 重复: {prepare.code}")
        self._prepares[prepare.code] = (owner, prepare)
        self._prepare_by_owner[owner.code] = prepare

    def prepare_for_owner(self, owner_code: str) -> PrepareSpec | None:
        """按 owner 查询唯一私有 prepare；返回对象本身但注册表保持只读映射。"""
        return self._prepare_by_owner.get(owner_code)

    def prepare(self, code: str) -> PrepareSpec:
        try:
            return self._prepares[code][1]
        except KeyError:
            raise KeyError(f"prepare 未注册: {code}") from None

    def prepares(self) -> list[tuple[Inspector, PrepareSpec]]:
        """按 owner priority、owner code、prepare code 返回注册的 prepare。"""
        return sorted(self._prepares.values(), key=lambda item: (item[0].priority, item[0].code, item[1].code))

    def get(self, code: str) -> Inspector:
        try:
            return self._rules[code]
        except KeyError:
            raise KeyError(f"规则未注册: {code}") from None

    def all(self, include_hidden: bool = False) -> list[Inspector]:
        rules = sorted(self._rules.values(), key=lambda r: (r.priority, r.code))
        return rules if include_hidden else [r for r in rules if not r.hidden]

    def codes(self) -> list[str]:
        return sorted(self._rules)

    def inspect_plan(self) -> list[str]:
        """普通规则 inspect 计划：priority → code。"""
        self._require_resolved_scan_refs()
        return [rule.code for rule in self.all() if not rule.hidden]

    def load_all(self) -> None:
        if self._loaded:
            return
        package_dir = Path(__file__).resolve().parent
        running = None
        main_mod = sys.modules.get("__main__")
        if main_mod and getattr(main_mod, "__file__", None):
            candidate = Path(main_mod.__file__).resolve()
            if candidate.is_relative_to(package_dir):
                running = candidate
        for mod in pkgutil.walk_packages([str(package_dir)], prefix="app.inspectors."):
            if mod.name.endswith("base") or mod.name.endswith("registry"):
                continue
            if running:
                rel = mod.name[len("app.inspectors.") :].replace(".", "/") + ".py"
                if (package_dir / rel).resolve() == running:
                    continue
            importlib.import_module(mod.name)
        self._loaded = True
        if settings.scan_rules.exists():
            scan_config = load_scan_config(settings.scan_rules)
            self.resolve_scan_refs(scan_config.groups)
            self._apply_disabled_rules(scan_config.disabled_rules)

    def _apply_disabled_rules(self, disabled_rules: list[str] | tuple[str, ...]) -> None:
        """从注册表中移除禁用规则及其私有 prepare。"""
        unknown = [code for code in disabled_rules if code not in self._rules]
        if unknown:
            raise ValueError(f"禁用规则未注册: {unknown[0]}")

        for code in disabled_rules:
            rule = self._rules.pop(code, None)
            if rule is None:
                continue
            prepare = self._prepare_by_owner.pop(code, None)
            if prepare is not None:
                self._prepares.pop(prepare.code, None)


registry = RuleRegistry()
