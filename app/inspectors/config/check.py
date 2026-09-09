"""config.check（P1）：基础配置完整性检查。"""

import sys
from configparser import ConfigParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

REQUIRED_KEYS = {"app": ["name", "log_level"]}

inspector = Inspector(
    code="config.check",
    name="配置完整性检查",
    category=RuleCategory.CONFIG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="检查基础配置文件与关键配置项是否存在",
    recommendation="缺失配置项可能导致功能异常，需补齐默认值",
    outputs_metrics=[
        {"key": "files", "label": "配置文件数", "unit": "个"},
        {"key": "missing", "label": "缺失配置项", "unit": "项"},
    ],
    params=[{"key": "required_keys", "label": "必填配置项", "default": "app.name/app.log_level"}],
)


def _run(ctx: RuleContext) -> object:
    root = ctx.data_dir / RuleCategory.CONFIG.value
    files = [p for p in sorted(root.rglob("*")) if p.is_file()]
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现配置类文件",
            skip_reason="未发现配置类文件",
        )
    missing: list[str] = []
    for path in files:
        parser = ConfigParser()
        try:
            parser.read(path, encoding="utf-8")
        except OSError:
            continue
        for section, keys in REQUIRED_KEYS.items():
            for key in keys:
                if not parser.has_option(section, key):
                    missing.append(f"{path.name}:{section}.{key}")
    findings = (
        [
            Finding(
                finding_id=f"{inspector.code}-missing",
                title="关键配置项缺失",
                severity=Severity.MEDIUM,
                source_file=missing[0],
                evidence="缺失项：" + "、".join(missing),
                recommendation=inspector.recommendation,
            )
        ]
        if missing
        else []
    )
    status = RuleStatus.WARN if missing else RuleStatus.PASS
    summary = (
        f"配置检查完成：{len(files)} 个文件，缺失 {len(missing)} 项"
        if missing
        else f"配置检查完成：{len(files)} 个文件均完整"
    )
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "files", "label": "配置文件数", "value": len(files), "unit": "个"},
            {"key": "missing", "label": "缺失配置项", "value": len(missing), "unit": "项"},
        ],
        findings=findings,
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
