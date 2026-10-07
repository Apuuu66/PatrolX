"""执行器阶段内并行：等价性、阶段屏障、并行度、日志完整性与可观测（US1）。"""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from app.models.schemas import RuleStatus
from tests.parallel_helpers import (
    ALPHA,
    BETA,
    DELTA,
    GAMMA,
    RULES_ENV,
    TRACE_DIR_ENV,
    build_registry,
    log_messages,
    make_context,
    make_executor,
    max_overlap,
    read_log,
    read_traces,
    stage_entries,
    write_logs,
)

VOLATILE_FIELDS = {"executed_at", "duration_ms"}
CODES = [ALPHA, BETA, GAMMA, DELTA]
LOG_FILES = ["alpha-01.log", "beta-01.log", "gamma-01.log"]


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    parallel: bool,
    task_id: str,
    codes: list[str] | None = None,
) -> tuple[dict[str, object], list[dict], list[dict]]:
    """跑一次完整巡检，返回结果、execution.log 条目与执行追踪。"""
    monkeypatch.setenv(RULES_ENV, ",".join(codes or CODES))
    trace_root = tmp_path / f"trace-{task_id}"
    monkeypatch.setenv(TRACE_DIR_ENV, str(trace_root))
    ctx = make_context(tmp_path, task_id=task_id)
    write_logs(ctx, LOG_FILES)
    executor = make_executor(build_registry(), parallel=parallel)
    results = executor.run_all(ctx)
    return results, read_log(ctx.data_dir / "execution.log"), read_traces(trace_root)


def test_serial_baseline_stays_serial_and_spawns_no_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """串行基线：结果齐全、阶段事件为 serial、执行后无子进程。"""
    results, entries, traces = _run(tmp_path, monkeypatch, parallel=False, task_id="baseline")

    assert set(results) == {*CODES, "pkg.extract.main"}
    stages = stage_entries(entries, "stage_parallel_done")
    assert {entry["stage"]: entry["mode"] for entry in stages} == {"PREPARE": "serial", "INSPECT": "serial"}
    assert all(entry["reason"] == "policy_disabled" for entry in stages)
    assert all(entry["workers"] == 0 for entry in stages)
    assert all(entry["children_peak_rss_bytes"] == 0 for entry in stages)
    assert multiprocessing.active_children() == []
    assert {record["pid"] for record in traces} == {os.getpid()}


def test_parallel_results_match_serial_field_by_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一现场串行与并行执行，除时间字段外逐字段一致。"""
    serial, serial_log, _ = _run(tmp_path, monkeypatch, parallel=False, task_id="serial")
    parallel, parallel_log, _ = _run(tmp_path, monkeypatch, parallel=True, task_id="parallel")

    assert set(serial) == set(parallel)
    for code, expected in serial.items():
        actual = parallel[code]
        assert actual.model_dump(exclude=VOLATILE_FIELDS) == expected.model_dump(exclude=VOLATILE_FIELDS), code
        assert actual.status == expected.status

    assert {entry["stage"]: entry["mode"] for entry in stage_entries(parallel_log, "stage_parallel_done")} == {
        "PREPARE": "parallel",
        "INSPECT": "parallel",
    }
    assert {entry["stage"]: entry["mode"] for entry in stage_entries(serial_log, "stage_parallel_done")} == {
        "PREPARE": "serial",
        "INSPECT": "serial",
    }


def test_stage_barrier_holds_between_extract_prepare_and_inspect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阶段屏障：prepare 全部结束才进入 inspect，且均晚于解压。"""
    _, entries, traces = _run(tmp_path, monkeypatch, parallel=True, task_id="barrier")
    messages = log_messages(entries)

    extract_index = messages.index("fake_extract_done")
    prepare_indices = [index for index, item in enumerate(messages) if item.startswith("prepare_")]
    inspect_indices = [index for index, item in enumerate(messages) if item in {f"执行规则 {code}" for code in CODES}]
    assert prepare_indices and inspect_indices
    assert extract_index < min(prepare_indices)
    assert max(prepare_indices) < min(inspect_indices)

    prepare_finished = max(float(record["finished"]) for record in traces if str(record["unit"]).startswith("prepare:"))
    inspect_started = min(
        float(record["started"]) for record in traces if str(record["unit"]) in {ALPHA, BETA, GAMMA, DELTA}
    )
    assert prepare_finished <= inspect_started


def test_stage_parallelism_uses_multiple_workers_within_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """并行度：inspect 阶段同时活跃单元 >1，worker 进程数不超过固定上限 4。"""
    _, entries, traces = _run(tmp_path, monkeypatch, parallel=True, task_id="workers")
    inspect_records = [record for record in traces if record["unit"] in {ALPHA, BETA, GAMMA, DELTA}]
    pids = {record["pid"] for record in inspect_records}

    assert len(pids) > 1
    assert len(pids) <= 4
    assert max_overlap(inspect_records) > 1

    inspect_stage = [entry for entry in stage_entries(entries, "stage_parallel_done") if entry["stage"] == "INSPECT"][0]
    assert inspect_stage["workers"] == 4
    assert inspect_stage["pending_units"] == len(CODES)


def test_execution_log_keeps_complete_json_lines_and_plan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """日志完整性：每行完整 JSON，单元日志块按计划序写入且块内顺序稳定。"""
    ctx = make_context(tmp_path, task_id="logging")
    write_logs(ctx, LOG_FILES)
    monkeypatch.setenv(RULES_ENV, ",".join(CODES))
    monkeypatch.setenv(TRACE_DIR_ENV, str(tmp_path / "trace-logging"))

    executor = make_executor(build_registry(), parallel=True)
    planned = list(executor.inspect_plan())
    results = executor.run_all(ctx)
    raw_lines = (ctx.data_dir / "execution.log").read_text(encoding="utf-8").splitlines()
    assert raw_lines
    entries = [json.loads(line) for line in raw_lines]
    assert all(isinstance(entry, dict) and "message" in entry for entry in entries)

    messages = log_messages(entries)
    starts = {code: messages.index(f"执行规则 {code}") for code in planned}
    assert list(starts) == sorted(starts, key=lambda code: starts[code])
    for code in planned:
        assert starts[code] < messages.index(f"{code}_done")
    assert set(planned) == set(CODES)
    assert all(results[code].status in {RuleStatus.PASS, RuleStatus.WARN} for code in CODES)


def test_stage_events_expose_parallel_observability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """阶段可观测：mode/reason/workers/pending/matched/wall/RSS 全部落进阶段事件。"""
    _, entries, _ = _run(tmp_path, monkeypatch, parallel=True, task_id="observability")
    inspect_stage = [entry for entry in stage_entries(entries, "stage_parallel_done") if entry["stage"] == "INSPECT"][0]

    assert inspect_stage["mode"] == "parallel"
    assert inspect_stage["reason"] == "eligible"
    assert inspect_stage["workers"] == 4
    assert inspect_stage["pending_units"] == len(CODES)
    assert inspect_stage["matched_bytes"] > 0
    assert inspect_stage["wall_ms"] >= 0
    assert inspect_stage["slowest_unit_ms"] > 0
    assert inspect_stage["parent_peak_rss_bytes"] > 0
    assert inspect_stage["children_peak_rss_bytes"] > 0
    assert len(stage_entries(entries, "stage_parallel_start")) == len(stage_entries(entries, "stage_parallel_done"))
