"""并行执行测试助手：可被 spawn 序列化的假规则、任务现场与父子进程追踪。

规则函数必须是模块级可 pickle 对象：并行路径在 `spawn` 子进程内执行，
因此假规则的行为由测试进程环境变量选择，父进程与 worker 用同一份构造逻辑。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.inspectors.registry import registry as runtime_registry
from app.models.schemas import Finding, Metric, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import Executor, RuleContext
from app.services.parallel import ParallelPolicy

TRACE_DIR_ENV = "PATROLX_TEST_TRACE_DIR"
RULES_ENV = "PATROLX_TEST_FAKE_RULES"
SLEEP_ENV = "PATROLX_TEST_SLEEP_S"

DEFAULT_SLEEP_S = 0.35
EXTRACT_CODE = "pkg.extract.main"
ALPHA = "test.parallel.alpha"
BETA = "test.parallel.beta"
GAMMA = "test.parallel.gamma"
DELTA = "test.parallel.delta"
PREPARE_FAIL = "test.parallel.prepare_fail"
INSPECT_FAIL = "test.parallel.inspect_fail"
CRASH = "test.parallel.crash"
ALL_LOGS = r"^logs/.*\.log$"
DEFAULT_CODES = [ALPHA, BETA, GAMMA, DELTA]


@dataclass(frozen=True, slots=True)
class FakeSpec:
    """一份假规则规格：父进程注册表与 worker 注册表共用。"""

    code: str
    priority: Priority
    severity: Severity
    patterns: tuple[str, ...] | None
    run: Any
    hidden: bool = False
    metrics: tuple[dict[str, str], ...] = ()
    prepare_code: str | None = None
    prepare_run: Any = None


def _sleep_seconds() -> float:
    raw = os.environ.get(SLEEP_ENV)
    return float(raw) if raw else DEFAULT_SLEEP_S


def trace(unit: str, *, started: float, finished: float | None = None, **detail: Any) -> None:
    """把单元执行区间写入任务外的追踪目录；未配置追踪目录时静默跳过。"""
    root = os.environ.get(TRACE_DIR_ENV)
    if not root:
        return
    record = {
        "unit": unit,
        "pid": os.getpid(),
        "started": started,
        "finished": finished if finished is not None else time.time(),
        **detail,
    }
    path = Path(root) / "traces.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def make_fake_result(
    code: str,
    *,
    status: RuleStatus,
    summary: str | None,
    skip_reason: str | None = None,
    metrics: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """构造与假规则元数据一致的 RuleResult，串并行两路共用。"""
    from app.models.schemas import RuleResult

    spec = SPECS[code]
    return RuleResult(
        code=code,
        name=f"假规则 {code}",
        category=RuleCategory.LOG,
        priority=spec.priority,
        execution_order=0,
        status=status,
        severity=spec.severity,
        summary=summary,
        skip_reason=skip_reason,
        metrics=[Metric(**item) for item in (metrics or [])],
        findings=[Finding(**item) for item in (findings or [])],
        metadata=metadata or {},
    )


def _read_index(ctx: RuleContext) -> dict[str, int]:
    """读取 owner 私有 prepared 索引；缺失说明 prepare 未按屏障先跑。"""
    index_path = ctx.prepared_dir / ALPHA / "index.json"
    if not index_path.exists():
        return {}
    return json.loads(index_path.read_text(encoding="utf-8"))


def _run_extract(ctx: RuleContext) -> Any:
    started = time.time()
    trace("pkg.extract.main", started=started, task_id=ctx.task_id)
    ctx.log("info", "fake_extract_done", task_id=ctx.task_id, pid=os.getpid())
    return make_fake_result(EXTRACT_CODE, status=RuleStatus.PASS, summary="测试解压完成")


def _prepare_alpha(ctx: RuleContext) -> None:
    started = time.time()
    index = {path.name: path.stat().st_size for path in ctx.resolved_files()}
    target = ctx.prepared_dir / ALPHA
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.json").write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
    trace("prepare:alpha", started=started, files=len(index))


def _prepare_fail(ctx: RuleContext) -> None:
    started = time.time()
    trace("prepare:fail", started=started)
    raise RuntimeError("注入的 prepare 失败")


def _run_alpha(ctx: RuleContext) -> Any:
    started = time.time()
    index = _read_index(ctx)
    trace(ALPHA, started=started, files=len(index))
    ctx.log("info", f"{ALPHA}_done", task_id=ctx.task_id, pid=os.getpid(), files=len(index))
    return make_fake_result(
        ALPHA,
        status=RuleStatus.PASS,
        summary=f"私有 prepare 索引 {len(index)} 个文件",
        metrics=[{"key": "alpha_files", "label": "日志文件数", "unit": "个", "value": len(index)}],
        metadata={"prepared_files": sorted(index)},
    )


def _run_beta(ctx: RuleContext) -> Any:
    started = time.time()
    files = [path for path in ctx.resolved_files()]
    trace(BETA, started=started, files=len(files))
    ctx.log("info", f"{BETA}_done", task_id=ctx.task_id, pid=os.getpid(), files=len(files))
    return make_fake_result(
        BETA,
        status=RuleStatus.WARN,
        summary="发现可疑日志行",
        findings=[
            {
                "finding_id": "test-parallel-beta-001",
                "title": "可疑日志行",
                "severity": Severity.LOW,
                "source_file": files[0].relative_to(ctx.data_dir).as_posix() if files else "logs/unknown.log",
                "evidence": "注入证据",
            }
        ],
        metadata={"matched_files": len(files)},
    )


def _sleep_unit(ctx: RuleContext, code: str) -> None:
    started = time.time()
    time.sleep(_sleep_seconds())
    trace(code, started=started, files=0)
    ctx.log("info", f"{code}_done", task_id=ctx.task_id, pid=os.getpid())


def _run_gamma(ctx: RuleContext) -> Any:
    _sleep_unit(ctx, GAMMA)
    return make_fake_result(GAMMA, status=RuleStatus.PASS, summary="gamma 完成")


def _run_delta(ctx: RuleContext) -> Any:
    _sleep_unit(ctx, DELTA)
    return make_fake_result(DELTA, status=RuleStatus.PASS, summary="delta 完成")


def _run_inspect_fail(ctx: RuleContext) -> Any:
    started = time.time()
    trace(INSPECT_FAIL, started=started)
    raise RuntimeError("注入的规则异常")


def _run_crash(ctx: RuleContext) -> Any:
    trace(CRASH, started=time.time(), crashing=True)
    os._exit(1)


SPECS: dict[str, FakeSpec] = {
    EXTRACT_CODE: FakeSpec(
        code=EXTRACT_CODE,
        priority=Priority.P0,
        severity=Severity.LOW,
        patterns=None,
        run=_run_extract,
        hidden=True,
    ),
    ALPHA: FakeSpec(
        code=ALPHA,
        priority=Priority.P1,
        severity=Severity.LOW,
        patterns=(r"^logs/alpha-.*\.log$",),
        run=_run_alpha,
        metrics=({"key": "alpha_files", "label": "日志文件数", "unit": "个"},),
        prepare_code=f"{ALPHA}.prepare",
        prepare_run=_prepare_alpha,
    ),
    BETA: FakeSpec(
        code=BETA,
        priority=Priority.P1,
        severity=Severity.LOW,
        patterns=(r"^logs/beta-.*\.log$",),
        run=_run_beta,
    ),
    GAMMA: FakeSpec(
        code=GAMMA,
        priority=Priority.P1,
        severity=Severity.LOW,
        patterns=(ALL_LOGS,),
        run=_run_gamma,
    ),
    DELTA: FakeSpec(
        code=DELTA,
        priority=Priority.P1,
        severity=Severity.LOW,
        patterns=(ALL_LOGS,),
        run=_run_delta,
    ),
    PREPARE_FAIL: FakeSpec(
        code=PREPARE_FAIL,
        priority=Priority.P2,
        severity=Severity.MEDIUM,
        patterns=(ALL_LOGS,),
        run=_run_beta,
        prepare_code=f"{PREPARE_FAIL}.prepare",
        prepare_run=_prepare_fail,
    ),
    INSPECT_FAIL: FakeSpec(
        code=INSPECT_FAIL,
        priority=Priority.P2,
        severity=Severity.MEDIUM,
        patterns=(ALL_LOGS,),
        run=_run_inspect_fail,
    ),
    CRASH: FakeSpec(
        code=CRASH,
        priority=Priority.P2,
        severity=Severity.MEDIUM,
        patterns=(ALL_LOGS,),
        run=_run_crash,
    ),
}


def selected_codes() -> list[str]:
    """由环境变量选择的假规则集合；未设置时返回默认 4 条正常规则。"""
    raw = os.environ.get(RULES_ENV)
    if raw is None:
        return list(DEFAULT_CODES)
    return [item for item in (part.strip() for part in raw.split(",")) if item]


def build_inspector(code: str) -> Inspector:
    """按规格构造假规则；prepare 继承 owner 的 source_patterns。"""
    spec = SPECS[code]
    prepare = None
    if spec.prepare_code is not None:
        prepare = PrepareSpec(
            code=spec.prepare_code,
            owner_code=code,
            run=spec.prepare_run,
        )
    return Inspector(
        code=code,
        name=f"假规则 {code}",
        category=RuleCategory.LOG,
        severity=spec.severity,
        priority=spec.priority,
        rule_version="1.0.0",
        description="并行测试假规则",
        recommendation="并行测试假规则",
        hidden=spec.hidden,
        source_patterns=list(spec.patterns) if spec.patterns is not None else None,
        outputs_metrics=[dict(item) for item in spec.metrics],
        run=spec.run,
        prepare=prepare,
    )


def install_fake_rules(target: RuleRegistry) -> None:
    """把当前选择的假规则装入指定注册表。"""
    for code in selected_codes():
        target.register(build_inspector(code))


def worker_setup() -> None:
    """worker initializer：在子进程内装入同一批假规则（spawn 可 pickle）。"""
    install_fake_rules(runtime_registry)


def build_registry(*, with_extract: bool = True) -> RuleRegistry:
    """父进程规划用注册表：可选假解压规则 + 当前选择的假规则。"""
    registry = RuleRegistry()
    if with_extract:
        registry.register(build_inspector(EXTRACT_CODE))
    install_fake_rules(registry)
    return registry


def make_context(tmp_path: Path, *, task_id: str = "task-parallel") -> RuleContext:
    """构造任务现场：日志文件、execution.log 写入器与 owner 私有 prepared 目录。"""
    data_dir = tmp_path / task_id
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "execution.log"

    def log(level: str, message: str, detail: dict | None = None) -> None:
        entry = {"ts": time.time(), "level": level, "message": message, **(detail or {})}
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return RuleContext(
        task_id=task_id,
        data_dir=data_dir,
        log=log,
        package_path=data_dir / "package.zip",
        result_dir=data_dir / "rules",
        prepared_dir=data_dir / "prepared",
    )


def write_logs(ctx: RuleContext, names: list[str], *, lines: int = 3) -> None:
    """在任务现场写入可被 `logs/**/*.log` 匹配的日志文件。"""
    for name in names:
        path = ctx.data_dir / "logs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(
            f"2026-10-08T10:00:0{index}.000Z INFO 测试日志行 {index} name={name}\n" for index in range(lines)
        )
        path.write_text(body, encoding="utf-8")


def make_executor(
    registry: RuleRegistry,
    *,
    parallel: bool = True,
    max_workers: int = 4,
    min_units: int = 0,
    min_matched_bytes: int = 0,
) -> Executor:
    """构造强制走并行（或串行基线）的执行器；阈值默认放开以便小样本触发并行。"""
    policy = ParallelPolicy(
        max_workers=max_workers,
        min_units=min_units,
        min_matched_bytes=min_matched_bytes,
        enabled=parallel,
    )
    return Executor(registry, None, policy=policy, worker_setup=worker_setup)


def read_log(path: Path) -> list[dict[str, Any]]:
    """读取 execution.log，每行必须是完整 JSON。"""
    if not path.exists():
        return []
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


def log_messages(entries: list[dict[str, Any]]) -> list[str]:
    return [str(entry["message"]) for entry in entries]


def read_traces(root: Path) -> list[dict[str, Any]]:
    """读取追踪目录下的执行区间记录。"""
    path = root / "traces.jsonl"
    if not path.exists():
        return []
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


def max_overlap(records: list[dict[str, Any]]) -> int:
    """按追踪记录计算同时活跃的单元数上限。"""
    events: list[tuple[float, int]] = []
    for record in records:
        events.append((float(record["started"]), 1))
        events.append((float(record["finished"]), -1))
    active = 0
    peak = 0
    for _, delta in sorted(events, key=lambda item: (item[0], -item[1])):
        active += delta
        peak = max(peak, active)
    return peak


def stage_entries(entries: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("message") == message]
