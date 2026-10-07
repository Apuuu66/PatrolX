"""执行器阶段内并行：单单元故障隔离与资源回收（US2）。

三类故障注入（prepare 失败、规则异常、worker 非正常退出）都只允许影响自身单元：
其余规则结果必须与无故障基线逐字段一致，任务结束后不得残留子进程。
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest

from app.inspectors.base import Inspector
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import Executor
from app.services.parallel import ParallelPolicy
from app.services.prepare import marker_path
from tests.parallel_helpers import (
    ALPHA,
    BETA,
    CRASH,
    DELTA,
    EXTRACT_CODE,
    GAMMA,
    INSPECT_FAIL,
    PREPARE_FAIL,
    RULES_ENV,
    TRACE_DIR_ENV,
    build_registry,
    make_context,
    make_executor,
    read_log,
    read_traces,
    stage_entries,
    write_logs,
)

VOLATILE_FIELDS = {"executed_at", "duration_ms"}
LOG_FILES = ["alpha-01.log", "beta-01.log", "gamma-01.log"]
DEGRADED_UNIT_ERROR = "worker 非正常退出"


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    codes: list[str],
    task_id: str,
    parallel: bool,
) -> tuple[object, dict[str, object], list[dict], list[dict]]:
    """跑一次完整巡检；返回任务现场、结果、执行日志与追踪。"""
    monkeypatch.setenv(RULES_ENV, ",".join(codes))
    trace_root = tmp_path / f"trace-{task_id}"
    monkeypatch.setenv(TRACE_DIR_ENV, str(trace_root))
    ctx = make_context(tmp_path, task_id=task_id)
    write_logs(ctx, LOG_FILES)
    executor = make_executor(build_registry(), parallel=parallel)
    results = executor.run_all(ctx)
    return ctx, results, read_log(ctx.data_dir / "execution.log"), read_traces(trace_root)


def _assert_same_results(expected: dict[str, object], actual: dict[str, object], codes: list[str]) -> None:
    """除时间字段外逐字段一致。"""
    for code in codes:
        assert actual[code].model_dump(exclude=VOLATILE_FIELDS) == expected[code].model_dump(exclude=VOLATILE_FIELDS), (
            code
        )


def test_prepare_failure_only_skips_owner_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """prepare 失败：owner 规则 skip 且写明原因，marker 不写，其他单元与串行基线一致（FR-005）。"""
    codes = [BETA, PREPARE_FAIL, DELTA]
    _, baseline, _, _ = _run(tmp_path, monkeypatch, codes=codes, task_id="fault-prepare-serial", parallel=False)
    ctx, results, entries, _ = _run(tmp_path, monkeypatch, codes=codes, task_id="fault-prepare-parallel", parallel=True)

    owner = results[PREPARE_FAIL]
    assert owner.status == RuleStatus.SKIP
    assert owner.skip_reason == "预处理未就绪"
    assert not marker_path(ctx, PREPARE_FAIL).exists()

    messages = [entry.get("message") for entry in entries]
    assert "prepare_error" in messages
    prepare_error = next(entry for entry in entries if entry.get("message") == "prepare_error")
    assert prepare_error["prepare_code"] == f"{PREPARE_FAIL}.prepare"
    assert prepare_error["prepare_state"] == "FAILED"
    assert "注入的 prepare 失败" in str(prepare_error["error"])
    assert "inspect_skip_prepare_not_ready" in messages

    # prepare 失败路径与串行基线逐字段一致：故障语义不因并行而改变。
    _assert_same_results(baseline, results, codes)
    assert multiprocessing.active_children() == []


def test_rule_exception_is_isolated_to_that_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """规则异常：该规则 error 且带错误摘要，其余单元继续完成（FR-006）。"""
    codes = [BETA, INSPECT_FAIL, DELTA]
    _, baseline, _, _ = _run(tmp_path, monkeypatch, codes=codes, task_id="fault-inspect-serial", parallel=False)
    _, results, entries, _ = _run(tmp_path, monkeypatch, codes=codes, task_id="fault-inspect-parallel", parallel=True)

    failed = results[INSPECT_FAIL]
    assert failed.status == RuleStatus.ERROR
    assert failed.summary == "规则执行异常"
    assert "注入的规则异常" in str(failed.metadata["error"])
    assert failed.duration_ms >= 0

    _assert_same_results(baseline, results, [BETA, DELTA])
    assert results[BETA].status == baseline[BETA].status
    assert results[DELTA].status == baseline[DELTA].status

    messages = [entry.get("message") for entry in entries]
    assert f"规则 {INSPECT_FAIL} 执行异常" in messages
    assert multiprocessing.active_children() == []


def test_worker_crash_degrades_and_keeps_other_units_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """worker 非正常退出：崩溃规则 error，其余规则降级串行补跑且结果与基线一致（FR-006、契约 C5）。"""
    baseline_codes = [GAMMA, DELTA]
    _, baseline, _, _ = _run(
        tmp_path,
        monkeypatch,
        codes=baseline_codes,
        task_id="fault-crash-serial",
        parallel=False,
    )
    _, results, entries, _ = _run(
        tmp_path,
        monkeypatch,
        codes=[GAMMA, CRASH, DELTA],
        task_id="fault-crash-parallel",
        parallel=True,
    )

    crashed = results[CRASH]
    assert crashed.status == RuleStatus.ERROR
    assert crashed.summary == "规则执行异常"
    assert crashed.metadata["error"] == DEGRADED_UNIT_ERROR

    degraded = stage_entries(entries, "parallel_degraded")
    assert len(degraded) == 1
    assert degraded[0]["stage"] == "INSPECT"
    assert degraded[0]["reason"] == "broker_broken"
    assert degraded[0]["affected_units"] >= 1
    assert degraded[0]["errored_units"] == 1

    inspect_stage = [entry for entry in stage_entries(entries, "stage_parallel_done") if entry["stage"] == "INSPECT"]
    assert inspect_stage[0]["mode"] == "degraded"

    _assert_same_results(baseline, results, baseline_codes)
    assert results[GAMMA].status == RuleStatus.PASS
    assert results[DELTA].status == RuleStatus.PASS
    assert multiprocessing.active_children() == []


def _failing_extract_run(ctx: object) -> object:
    """主包解压失败注入：worker 不在该路径上，直接在父进程串行抛出。"""
    raise RuntimeError("注入的主包解压失败")


def test_resources_are_reclaimed_on_success_failure_and_main_extract_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """资源回收：成功、异常与主包失败三条路径结束后都没有残留子进程（FR-013、SC-006）。"""
    _, results, entries, traces = _run(
        tmp_path,
        monkeypatch,
        codes=[ALPHA, BETA, DELTA],
        task_id="reclaim-success",
        parallel=True,
    )
    assert results[ALPHA].status in {RuleStatus.PASS, RuleStatus.WARN}
    assert len(stage_entries(entries, "stage_parallel_done")) == 2
    assert any(record["pid"] != os.getpid() for record in traces)
    assert multiprocessing.active_children() == []

    _, fault_results, fault_entries, _ = _run(
        tmp_path,
        monkeypatch,
        codes=[GAMMA, INSPECT_FAIL, CRASH, DELTA],
        task_id="reclaim-fault",
        parallel=True,
    )
    assert fault_results[INSPECT_FAIL].status == RuleStatus.ERROR
    assert fault_results[CRASH].status == RuleStatus.ERROR
    assert stage_entries(fault_entries, "parallel_degraded")
    assert multiprocessing.active_children() == []

    monkeypatch.setenv(RULES_ENV, "")
    ctx = make_context(tmp_path, task_id="reclaim-extract-failure")
    write_logs(ctx, LOG_FILES)
    registry = build_registry(with_extract=False)
    registry.register(
        Inspector(
            code=EXTRACT_CODE,
            name="失败的主包解压",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P0,
            rule_version="1.0.0",
            description="测试主包解压失败",
            recommendation="测试主包解压失败",
            hidden=True,
            run=_failing_extract_run,
        )
    )
    executor = Executor(registry, None, policy=ParallelPolicy(enabled=True, min_units=0, min_matched_bytes=0))
    results = executor.run_all(ctx)
    entries = read_log(ctx.data_dir / "execution.log")

    assert set(results) == {EXTRACT_CODE}
    assert results[EXTRACT_CODE].status == RuleStatus.ERROR
    assert f"规则 {EXTRACT_CODE} 执行异常" in [entry.get("message") for entry in entries]
    assert stage_entries(entries, "stage_parallel_start") == []
    assert multiprocessing.active_children() == []
