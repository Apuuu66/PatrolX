"""本地全流程集成测试（样例包 → 解压 → 规则 → 契约落盘）。"""

import json
from pathlib import Path

from app.cli import clean_system_id, run_task
from app.core.config import settings

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"


def test_clean_system_id() -> None:
    assert clean_system_id("ALL120231311231.zip") == "all120231311231"
    assert clean_system_id("客户-包.tar.gz") == "system"


def test_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    assert SAMPLE.exists(), "请先运行 tests/fixtures/make_sample.py"
    out = tmp_path / "out"
    monkeypatch.setattr(settings, "output_dir", out)
    task = run_task(SAMPLE, name="样例任务")
    assert task.task_id == "task-sample"
    assert task.stats.pass_ >= 2
    assert task.stats.warn >= 3
    assert task.stats.fail >= 1
    assert task.stats.error == 0
    assert task.stats.skip == 0

    sys_dir = out / task.task_id / clean_system_id(SAMPLE.name)
    for code in (
        "log.error_density",
        "log.filter",
        "kpi.threshold",
        "traffic.stat",
        "alarm.stat",
        "config.check",
        "resource.check",
    ):
        assert (sys_dir / "rules" / f"{code}.json").exists(), f"缺少规则结果 {code}"
    assert (sys_dir / "artifacts" / "log.filter" / "log.filter.artifacts.filtered_logs").exists()
    system = json.loads((sys_dir / "system.json").read_text(encoding="utf-8"))
    assert "pass" in system["summary"]
    report = out / task.task_id / "report.html"
    assert report.exists() and "PatrolX" in report.read_text(encoding="utf-8")


def test_local_task_id_is_fixed_for_same_package(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setattr(settings, "output_dir", out)
    first = run_task(SAMPLE)
    second = run_task(SAMPLE)
    assert first.task_id == second.task_id == "task-sample"
    sys_dir = out / first.task_id / clean_system_id(SAMPLE.name)
    assert (sys_dir / "rules" / "log.filter.json").exists()
    assert (sys_dir / "artifacts" / "log.filter" / "log.filter.artifacts.filtered_logs").exists()
