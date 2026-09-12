"""HTML 报告渲染（Jinja2 模板）。"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.schemas import SystemInspection


def render_report(output: Path, task_id: str, system: SystemInspection, completed_at=None) -> Path:
    template_dir = Path(__file__).resolve().parents[1] / "reports" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html.j2").render(
        task_id=task_id,
        system=system,
        completed_at=completed_at,
    )
    path = output / task_id / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
