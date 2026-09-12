"""HTML 报告可审查性与契约一致性测试。"""

from pathlib import Path

from tests.baseline_helpers import SAMPLE, setup_env


def test_report_exposes_contract_results(tmp_path: Path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-sample")
    report = (tmp_path / "output" / "task-sample" / "report.html").read_text(encoding="utf-8")
    summary = task.system.summary

    for text in (
        f"总计 <b>{summary.total}</b>",
        f"通过 <b>{summary.pass_}</b>",
        f"告警 <b>{summary.warn}</b>",
        f"失败 <b>{summary.fail}</b>",
        f"异常 <b>{summary.error}</b>",
        f"跳过 <b>{summary.skip}</b>",
        "执行时间",
    ):
        assert text in report, text

    for rule in task.system.rules:
        assert rule.code in report
        if rule.status == "skip":
            assert rule.skip_reason and rule.skip_reason in report
        for finding in rule.findings:
            assert finding.title in report
            assert finding.source_file in report
            assert finding.evidence in report
            if finding.recommendation:
                assert finding.recommendation in report
