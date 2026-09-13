"""HTML 报告渲染（Jinja2 模板）。"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.schemas import RuleResult, Severity, SystemInspection

SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def ordered_findings(system: SystemInspection) -> list[tuple[RuleResult, object]]:
    """报告展示顺序：严重度优先，同级按规则优先级和规则代码稳定排序。"""
    findings = [(rule, finding) for rule in system.rules for finding in rule.findings]
    return sorted(
        findings,
        key=lambda item: (
            SEVERITY_ORDER[item[1].severity],
            item[0].priority.value,
            item[0].code,
            item[1].finding_id,
        ),
    )


def render_report(output: Path, task_id: str, system: SystemInspection, completed_at=None) -> Path:
    template_dir = Path(__file__).resolve().parents[1] / "reports" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html.j2").render(
        task_id=task_id,
        system=system,
        findings=ordered_findings(system),
        completed_at=completed_at,
    )
    path = output / task_id / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
