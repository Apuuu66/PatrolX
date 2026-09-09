"""巡检器注册表：启动时自动扫描 app/inspectors/** 装载全部规则。"""

import importlib
import pkgutil
import sys
from pathlib import Path

from app.inspectors.base import Inspector


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, Inspector] = {}
        self._loaded = False

    def register(self, inspector: Inspector) -> None:
        inspector.validate()
        if inspector.code in self._rules:
            raise ValueError(f"规则 code 重复: {inspector.code}")
        self._rules[inspector.code] = inspector

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

    @property
    def producers(self) -> dict[str, str]:
        """产物 key → 生产者规则 code。"""
        mapping: dict[str, str] = {}
        for code, rule in self._rules.items():
            for key in rule.outputs_artifacts:
                if key in mapping and mapping[key] != code:
                    raise ValueError(f"产物 key 被多个规则产出: {key}")
                mapping[key] = code
        return mapping

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


registry = RuleRegistry()
