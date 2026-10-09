"""执行器阶段内并行：小任务直通、重跑与日常操作语义（US3）。

并行只是执行层优化：少单元 / 小数据的任务必须走原串行路径，单规则重跑永不建池，
CLI 与 API 共用同一执行契约，删除 / BUSY / 重建语义不因并行改变。
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.services import parallel as parallel_module
from app.services.executor import Executor
from app.services.parallel import ParallelPolicy
from app.services.tasks import task_service
from tests.baseline_helpers import (
    SAMPLE,
    load_logs,
    load_rule,
    load_system,
    setup_env,
    strip_volatile,
    upload_package,
    wait_for_task,
)
from tests.parallel_helpers import (
    ALPHA,
    BETA,
    DELTA,
    GAMMA,
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

client = TestClient(app)
LOG_FILES = ["alpha-01.log", "beta-01.log", "gamma-01.log"]
ALL_CODES = [ALPHA, BETA, GAMMA, DELTA]
WALL_MS_SLACK = 50


def _stage(entries: list[dict[str, Any]], stage: str) -> dict[str, Any]:
    """取出唯一一条阶段结束事件。"""
    found = [entry for entry in stage_entries(entries, "stage_parallel_done") if entry["stage"] == stage]
    assert len(found) == 1, found
    return found[0]


def _run(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    task_id: str,
    codes: list[str],
    executor: Executor,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    monkeypatch.setenv(RULES_ENV, ",".join(codes))
    trace_root = tmp_path / f"trace-{task_id}"
    monkeypatch.setenv(TRACE_DIR_ENV, str(trace_root))
    ctx = make_context(tmp_path, task_id=task_id)
    write_logs(ctx, LOG_FILES)
    executor.run_all(ctx)
    return ctx.data_dir, ctx, read_log(ctx.data_dir / "execution.log"), read_traces(trace_root)


def test_few_execution_units_stay_serial_and_spawn_no_workers(tmp_path: Path, monkeypatch: Any) -> None:
    """单元数 < 3：默认策略直通串行，不建池、不产生子进程（FR-012）。"""
    task_id = "policy-small-units"
    monkeypatch.setenv(RULES_ENV, ",".join([GAMMA, DELTA]))
    trace_root = tmp_path / f"trace-{task_id}"
    monkeypatch.setenv(TRACE_DIR_ENV, str(trace_root))
    ctx = make_context(tmp_path, task_id=task_id)
    write_logs(ctx, LOG_FILES)

    results = Executor(build_registry(), None).run_all(ctx)
    entries = read_log(ctx.data_dir / "execution.log")
    inspect = _stage(entries, "INSPECT")

    assert set(results) == {GAMMA, DELTA, "pkg.extract.main"}
    assert inspect["mode"] == "serial"
    assert inspect["reason"] == "units<3"
    assert inspect["workers"] == 0
    assert inspect["pending_units"] == 2
    assert inspect["children_peak_rss_bytes"] == 0
    assert {record["pid"] for record in read_traces(trace_root)} == {os.getpid()}
    assert multiprocessing.active_children() == []


def test_small_payload_stays_serial_without_wall_clock_regression(tmp_path: Path, monkeypatch: Any) -> None:
    """匹配数据量 < 8MB：默认策略直通串行，且阶段墙钟相对串行基线不劣化超过 10%（SC-007）。"""
    monkeypatch.setenv(RULES_ENV, ",".join(ALL_CODES))

    default_ctx = make_context(tmp_path, task_id="policy-small-bytes-default")
    write_logs(default_ctx, LOG_FILES)
    Executor(build_registry(), None).run_all(default_ctx)
    default_stage = _stage(read_log(default_ctx.data_dir / "execution.log"), "INSPECT")

    serial_ctx = make_context(tmp_path, task_id="policy-small-bytes-baseline")
    write_logs(serial_ctx, LOG_FILES)
    make_executor(build_registry(), parallel=False).run_all(serial_ctx)
    serial_stage = _stage(read_log(serial_ctx.data_dir / "execution.log"), "INSPECT")

    assert default_stage["matched_bytes"] < 8 * 1024 * 1024
    assert default_stage["mode"] == "serial"
    assert default_stage["reason"] == "matched_bytes<8MB"
    assert serial_stage["mode"] == "serial"
    budget_ms = max(int(serial_stage["wall_ms"] * 1.10), int(serial_stage["wall_ms"]) + WALL_MS_SLACK)
    assert default_stage["wall_ms"] <= budget_ms, (default_stage["wall_ms"], serial_stage["wall_ms"])
    assert multiprocessing.active_children() == []


def test_single_rule_rerun_never_builds_pool_and_preserves_other_results(tmp_path: Path, monkeypatch: Any) -> None:
    """单规则重跑保持串行：只改动目标规则产物，其他规则 JSON 与阶段日志不变（SC-005、契约 C10）。"""
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_single_rule, run_task

    task_id = run_task(SAMPLE, task_id="task-policy-rerun").task_id
    unrelated_path = env.rules_dir(task_id) / "kpi.measurement_units.json"
    unrelated_before = unrelated_path.read_bytes()
    unrelated_mtime_before = unrelated_path.stat().st_mtime_ns
    stage_events_before = [entry for entry in load_logs(env, task_id) if entry.get("message") == "stage_parallel_start"]

    def forbidden_executor(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("单规则重跑不得创建进程池")

    monkeypatch.setattr(parallel_module, "ProcessPoolExecutor", forbidden_executor)
    run_single_rule("alarm.stat", package=SAMPLE, task_id=task_id)

    assert load_rule(env, task_id, "alarm.stat")["status"] == "fail"
    assert unrelated_path.read_bytes() == unrelated_before
    assert unrelated_path.stat().st_mtime_ns == unrelated_mtime_before

    entries = load_logs(env, task_id)
    stage_events_after = [entry for entry in entries if entry.get("message") == "stage_parallel_start"]
    assert len(stage_events_after) == len(stage_events_before)
    assert not any(entry.get("message") == "parallel_degraded" for entry in entries)
    assert multiprocessing.active_children() == []


def _forced_parallel_policy(*args: Any, **kwargs: Any) -> ParallelPolicy:
    """测试专用策略工厂：把阈值降到 0，让真实样例包也走并行路径。"""
    kwargs.setdefault("min_units", 0)
    kwargs.setdefault("min_matched_bytes", 0)
    return ParallelPolicy(*args, **kwargs)


def test_cli_and_api_share_the_parallel_execution_contract(tmp_path: Path, monkeypatch: Any) -> None:
    """CLI 与 API 双模式执行同一契约：结果逐字段一致且无残留子进程（宪法“模式同构”）。"""
    monkeypatch.setattr("app.services.executor.ParallelPolicy", _forced_parallel_policy)
    local_env = setup_env(tmp_path / "local", monkeypatch)
    from app.cli import run_task

    local_task = run_task(
        SAMPLE,
        name="并行一致性",
        customer={"province": "北京", "operator": "移动"},
    )
    local_system = load_system(local_env, local_task.task_id)
    assert local_system["rules"]
    assert multiprocessing.active_children() == []

    online_env = setup_env(tmp_path / "online", monkeypatch)
    task_id = upload_package(
        online_env,
        client,
        name="并行一致性",
        province="北京",
        operator="移动",
    )
    wait_for_task(client, task_id)

    assert task_id == local_task.task_id
    online_system = load_system(online_env, task_id)
    assert strip_volatile(online_system) == strip_volatile(local_system)
    inspect = _stage(load_logs(online_env, task_id), "INSPECT")
    assert inspect["mode"] in {"parallel", "degraded"}
    assert inspect["workers"] > 0
    assert multiprocessing.active_children() == []


def test_busy_and_rebuild_paths_are_unaffected_by_parallel(tmp_path: Path, monkeypatch: Any) -> None:
    """删除 / BUSY / 全量重建：任务运行中仍拒绝操作，重建后结果与首轮一致（边界情况）。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="并行重建")
    wait_for_task(client, task_id)

    original_active = task_service._active_task
    task_service._active_task = task_id
    try:
        assert client.delete(f"/api/v2/tasks/{task_id}").status_code == 409
        response = client.post(f"/api/v2/tasks/{task_id}/rebuild", json={"mode": "full", "confirmed": True})
        assert response.status_code == 409
        assert response.json()["code"] == "task_busy"
    finally:
        task_service._active_task = original_active

    before = load_rule(env, task_id, "alarm.stat")
    response = client.post(f"/api/v2/tasks/{task_id}/rebuild", json={"mode": "full", "confirmed": True})
    assert response.status_code == 202, response.text
    assert wait_for_task(client, task_id)["status"] == "completed"

    assert strip_volatile(load_rule(env, task_id, "alarm.stat")) == strip_volatile(before)
    assert multiprocessing.active_children() == []
