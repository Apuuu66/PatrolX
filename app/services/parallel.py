"""阶段内并行运行时：固定并行度、计划序收集、失败降级与阶段统计。"""

from __future__ import annotations

import multiprocessing
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any

from app.inspectors.registry import RuleRegistry
from app.models.schemas import RuleResult, RuleStatus
from app.services.unit_runtime import (
    PREPARE_FAILED,
    UNIT_STATUS_CRASHED,
    RuleContext,
    UnitKind,
    UnitOutcome,
    UnitRequest,
    build_result,
    execute_unit,
    flush_logs,
    initialize_worker,
    log_entry,
    peak_rss_bytes,
)

LogEntry = dict[str, Any]

DEFAULT_MAX_WORKERS = 4
DEFAULT_MIN_UNITS = 3
DEFAULT_MIN_MATCHED_BYTES = 8 * 1024 * 1024

STAGE_PREPARE = "PREPARE"
STAGE_INSPECT = "INSPECT"

MODE_SERIAL = "serial"
MODE_PARALLEL = "parallel"
MODE_DEGRADED = "degraded"

REASON_ELIGIBLE = "eligible"
REASON_NO_PENDING_UNITS = "no_pending_units"
REASON_DISABLED = "policy_disabled"
REASON_BROKER_BROKEN = "broker_broken"

WORKER_CRASH_ERROR = "worker 非正常退出"


@dataclass(frozen=True, slots=True)
class ParallelPolicy:
    """阶段并行策略；只作为 Executor 构造参数注入，不进入 CLI、环境变量与 API。"""

    max_workers: int = DEFAULT_MAX_WORKERS
    min_units: int = DEFAULT_MIN_UNITS
    min_matched_bytes: int = DEFAULT_MIN_MATCHED_BYTES
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.max_workers <= 0:
            raise ValueError(f"max_workers 必须为正整数: {self.max_workers}")
        if self.min_units < 0:
            raise ValueError(f"min_units 不能为负数: {self.min_units}")
        if self.min_matched_bytes < 0:
            raise ValueError(f"min_matched_bytes 不能为负数: {self.min_matched_bytes}")

    def decide(self, *, pending_units: int, matched_bytes: int) -> tuple[bool, str]:
        """返回（是否并行，直通原因）；原因只用于阶段事件，不参与调度。"""
        if not self.enabled:
            return False, REASON_DISABLED
        if pending_units < self.min_units:
            return False, f"units<{self.min_units}"
        if matched_bytes < self.min_matched_bytes:
            return False, f"matched_bytes<{self.min_matched_bytes // (1024 * 1024)}MB"
        return True, REASON_ELIGIBLE

    def workers_for(self, pending_units: int) -> int:
        """实际池大小：min(max_workers, 待执行单元数)。"""
        return min(self.max_workers, max(pending_units, 0))


@dataclass(slots=True)
class UnitPlan:
    """父进程规划结果：要么短路产出结果，要么把执行交给运行时。"""

    unit_kind: UnitKind
    code: str
    owner_code: str
    request: UnitRequest | None = None
    matched_bytes: int = 0
    prepare_state: str | None = None
    short_circuit: RuleResult | None = None
    logs: list[LogEntry] = field(default_factory=list)

    @property
    def needs_worker(self) -> bool:
        return self.request is not None


UnitOutcomeHook = Callable[[UnitPlan, UnitOutcome], None]


@dataclass(frozen=True, slots=True)
class StageStats:
    """阶段可观测数据；写入 stage_parallel_done 事件。"""

    stage: str
    mode: str
    reason: str
    workers: int
    pending_units: int
    matched_bytes: int
    wall_ms: int
    parent_peak_rss_bytes: int
    children_peak_rss_bytes: int
    slowest_unit_ms: int

    def as_detail(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "mode": self.mode,
            "reason": self.reason,
            "workers": self.workers,
            "pending_units": self.pending_units,
            "matched_bytes": self.matched_bytes,
            "wall_ms": self.wall_ms,
            "parent_peak_rss_bytes": self.parent_peak_rss_bytes,
            "children_peak_rss_bytes": self.children_peak_rss_bytes,
            "slowest_unit_ms": self.slowest_unit_ms,
        }


class StageRunner:
    """单任务内的阶段运行时：惰性建池、跨阶段复用、降级与按计划序落日志。"""

    def __init__(
        self,
        *,
        registry: RuleRegistry,
        policy: ParallelPolicy | None = None,
        worker_setup: Callable[[], None] | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or ParallelPolicy()
        self._worker_setup = worker_setup
        self._pool: ProcessPoolExecutor | None = None
        self._broken = False

    def close(self) -> None:
        """任务结束（含异常路径）回收进程池，不留下残留子进程。"""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    def run_single(
        self,
        plan: UnitPlan,
        ctx: RuleContext,
        *,
        on_outcome: UnitOutcomeHook | None = None,
    ) -> UnitOutcome | None:
        """父进程串行执行单个计划项（单规则重跑路径，永不建池）。"""
        outcome = self._execute_plan(plan, ctx)
        self._flush_unit(ctx, plan, outcome, on_outcome)
        return outcome

    def run_stage(
        self,
        stage: str,
        plans: Sequence[UnitPlan],
        ctx: RuleContext,
        *,
        on_outcome: UnitOutcomeHook | None = None,
    ) -> list[UnitOutcome | None]:
        """执行一个阶段的全部计划项，并按计划序落日志、返回对齐的结果序列。"""
        if not plans:
            return []
        wall_started = time.monotonic()
        pending = [(index, plan) for index, plan in enumerate(plans) if plan.needs_worker]
        matched_bytes = sum(plan.matched_bytes for plan in plans)
        parallel, reason = self.policy.decide(pending_units=len(pending), matched_bytes=matched_bytes)
        if not pending:
            parallel, reason = False, REASON_NO_PENDING_UNITS
        elif parallel and self._broken:
            parallel, reason = False, REASON_BROKER_BROKEN
        workers = self.policy.workers_for(len(pending)) if parallel else 0
        mode = MODE_PARALLEL if parallel else MODE_SERIAL
        ctx.log(
            "info",
            "stage_parallel_start",
            task_id=ctx.task_id,
            stage=stage,
            mode=mode,
            reason=reason,
            workers=workers,
            pending_units=len(pending),
            matched_bytes=matched_bytes,
        )

        measured: dict[int, UnitOutcome] = {}
        children_peak_rss_bytes = 0
        if parallel:
            measured, unsettled, degraded = self._run_parallel(pending)
            children_peak_rss_bytes = sum(outcome.worker_peak_rss_bytes for outcome in measured.values())
            if degraded:
                mode = MODE_DEGRADED
                reason = REASON_BROKER_BROKEN
                recovered = self._recover_units(unsettled)
                ctx.log(
                    "warn",
                    "parallel_degraded",
                    task_id=ctx.task_id,
                    stage=stage,
                    reason=REASON_BROKER_BROKEN,
                    affected_units=len(unsettled),
                    errored_units=sum(1 for outcome in recovered.values() if outcome.status == UNIT_STATUS_CRASHED),
                )
                children_peak_rss_bytes += sum(outcome.worker_peak_rss_bytes for outcome in recovered.values())
                measured.update(recovered)
        else:
            for index, plan in pending:
                measured[index] = self._execute_plan(plan, ctx)

        outcomes: list[UnitOutcome | None] = []
        for index, plan in enumerate(plans):
            outcome = measured.get(index)
            self._flush_unit(ctx, plan, outcome, on_outcome)
            outcomes.append(outcome)

        stats = StageStats(
            stage=stage,
            mode=mode,
            reason=reason,
            workers=workers,
            pending_units=len(pending),
            matched_bytes=matched_bytes,
            wall_ms=int((time.monotonic() - wall_started) * 1000),
            parent_peak_rss_bytes=peak_rss_bytes(),
            children_peak_rss_bytes=children_peak_rss_bytes,
            slowest_unit_ms=max((outcome.duration_ms for outcome in measured.values()), default=0),
        )
        ctx.log("info", "stage_parallel_done", task_id=ctx.task_id, **stats.as_detail())
        return outcomes

    def _run_parallel(
        self,
        pending: Sequence[tuple[int, UnitPlan]],
    ) -> tuple[dict[int, UnitOutcome], list[tuple[int, UnitPlan]], bool]:
        """有界窗口并行执行；池失效时返回剩余未提交单元交给父进程串行补跑。"""
        measured: dict[int, UnitOutcome] = {}
        pool = self._ensure_pool()
        queue: deque[tuple[int, UnitPlan]] = deque(pending)
        window = self.policy.workers_for(len(pending))
        in_flight: dict[Future[UnitOutcome], tuple[int, UnitPlan]] = {}
        crashed: dict[int, UnitPlan] = {}
        degraded = False
        while queue or in_flight:
            while queue and len(in_flight) < window and not self._broken:
                index, plan = queue.popleft()
                try:
                    future = pool.submit(execute_unit, plan.request)
                except BrokenProcessPool:
                    self._broken = True
                    degraded = True
                    queue.appendleft((index, plan))
                    break
                in_flight[future] = (index, plan)
            if not in_flight:
                break
            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                index, plan = in_flight.pop(future)
                outcome = self._settle(future)
                if outcome is None:
                    self._broken = True
                    degraded = True
                    crashed[index] = plan
                    continue
                measured[index] = outcome
            if self._broken:
                for future in list(in_flight):
                    index, plan = in_flight.pop(future)
                    outcome = self._settle(future)
                    if outcome is None:
                        crashed[index] = plan
                        continue
                    measured[index] = outcome
                unsettled = [(index, plan) for index, plan in crashed.items() if index not in measured]
                return measured, [*unsettled, *queue], degraded
        return measured, list(queue), degraded

    def _recover_units(self, unsettled: Sequence[tuple[int, UnitPlan]]) -> dict[int, UnitOutcome]:
        """池失效后的降级补跑：未完成单元在独立单进程池内逐个执行。

        进程池失效会连带作废同批在飞单元的结果，无法就地判定谁是崩溃单元；
        因此未完成单元一律在新的单进程池内补跑，只有补跑仍崩溃的单元记 error 且不再重试。
        """
        recovered: dict[int, UnitOutcome] = {}
        if not unsettled:
            return recovered
        pool = self._recovery_pool()
        try:
            for index, plan in unsettled:
                outcome = self._recover_one(pool, plan)
                if outcome is not None:
                    recovered[index] = outcome
                    continue
                recovered[index] = self._crash_outcome(plan)
                pool.shutdown(wait=True, cancel_futures=True)
                pool = self._recovery_pool()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        return recovered

    def _recover_one(self, pool: ProcessPoolExecutor, plan: UnitPlan) -> UnitOutcome | None:
        """补跑单个单元；崩溃或回传失败返回 None，由调用方记 error。"""
        try:
            return pool.submit(execute_unit, plan.request).result()
        except Exception:  # noqa: BLE001 - 补跑失败只影响该单元
            return None

    def _recovery_pool(self) -> ProcessPoolExecutor:
        return ProcessPoolExecutor(
            max_workers=1,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize_worker,
            initargs=(self._worker_setup,),
        )

    def _settle(self, future: Future[UnitOutcome]) -> UnitOutcome | None:
        """结算单个 future；worker 崩溃或回传失败返回 None。"""
        try:
            outcome = future.result()
        except BrokenProcessPool:
            return None
        except Exception:  # noqa: BLE001 - 回传失败同样只影响该单元
            return None
        if outcome.status == UNIT_STATUS_CRASHED:
            return None
        return outcome

    def _execute_plan(self, plan: UnitPlan, ctx: RuleContext) -> UnitOutcome | None:
        """串行路径与降级补跑共用的单元执行实现（父进程内）。"""
        if plan.request is None:
            return None
        try:
            return execute_unit(plan.request, registry=self.registry)
        except Exception as exc:  # noqa: BLE001 - 单元执行异常只影响该单元
            ctx.log(
                "error",
                "unit_execution_error",
                task_id=ctx.task_id,
                stage=plan.unit_kind.value,
                unit_code=plan.code,
                error=str(exc),
            )
            return self._crash_outcome(plan)

    def _crash_outcome(self, plan: UnitPlan) -> UnitOutcome:
        """worker 非正常退出的补写结果；由父进程构造，不重试。"""
        if plan.unit_kind == UnitKind.PREPARE:
            return UnitOutcome(
                unit_kind=plan.unit_kind,
                code=plan.code,
                status=UNIT_STATUS_CRASHED,
                duration_ms=0,
                worker_peak_rss_bytes=0,
                prepare_state=PREPARE_FAILED,
                logs=(
                    log_entry(
                        "error",
                        "prepare_error",
                        {
                            "rule_code": plan.owner_code,
                            "prepare_code": plan.code,
                            "error": WORKER_CRASH_ERROR,
                            "prepare_state": PREPARE_FAILED,
                        },
                    ),
                ),
                error=WORKER_CRASH_ERROR,
            )
        result = build_result(
            self.registry.get(plan.code),
            status=RuleStatus.ERROR,
            summary="规则执行异常",
            duration_ms=0,
            metadata={"error": WORKER_CRASH_ERROR},
        )
        return UnitOutcome(
            unit_kind=plan.unit_kind,
            code=plan.code,
            status=UNIT_STATUS_CRASHED,
            duration_ms=0,
            worker_peak_rss_bytes=0,
            result=result,
            logs=(
                log_entry(
                    "error",
                    f"规则 {plan.code} 执行异常",
                    {"rule_code": plan.code, "error": WORKER_CRASH_ERROR},
                ),
            ),
            error=WORKER_CRASH_ERROR,
        )

    def _flush_unit(
        self,
        ctx: RuleContext,
        plan: UnitPlan,
        outcome: UnitOutcome | None,
        on_outcome: UnitOutcomeHook | None,
    ) -> None:
        """按计划序写出单元日志块：规划日志 → worker 日志 → 父进程收尾日志。"""
        flush_logs(ctx, plan.logs)
        if outcome is None:
            return
        flush_logs(ctx, outcome.logs)
        if on_outcome is not None:
            on_outcome(plan, outcome)

    def _ensure_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=self.policy.max_workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=initialize_worker,
                initargs=(self._worker_setup,),
            )
        return self._pool
