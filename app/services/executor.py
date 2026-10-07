"""规则执行器：优先级顺序 + 源文件显式匹配 + 阶段内并行编排。

执行顺序固定为 EXTRACT → PREPARE → INSPECT → 收尾：EXTRACT 与收尾保持串行，
PREPARE / INSPECT 阶段内按 :class:`~app.services.parallel.ParallelPolicy` 决定
是否用固定并行度的进程池执行；阶段之间保留全局屏障。父进程是唯一的结果与日志写入者。
"""

import shutil
import time
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any

from app.core.archive import ArchiveError
from app.core.checksum import sha256_file
from app.core.metrics import RULES_TOTAL
from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.models.schemas import RuleCategory, RuleResult, RuleStatus
from app.services import extraction
from app.services.parallel import STAGE_INSPECT, STAGE_PREPARE, ParallelPolicy, StageRunner, UnitPlan
from app.services.prepare import marker_path, rule_file_sha256
from app.services.scanning import validate_patterns
from app.services.unit_runtime import (
    PREPARE_FAILED,
    PREPARE_HIT,
    PREPARE_REBUILT,
    PREPARE_SKIP,
    RuleContext,
    UnitKind,
    UnitOutcome,
    UnitRequest,
    build_result,
    flush_logs,
    log_entry,
    make_result,
    run_inspect_call,
)

__all__ = ["Executor", "RuleContext", "make_result"]

WORKER_RESULT_MISSING = "worker 未返回结果"


class Executor:
    def __init__(
        self,
        registry: RuleRegistry,
        enabled_rules: set[str] | None = None,
        *,
        policy: ParallelPolicy | None = None,
        worker_setup: Callable[[], None] | None = None,
    ) -> None:
        self.registry = registry
        self.enabled_rules = enabled_rules
        self.collected: dict[str, RuleResult] = {}
        self.policy = policy or ParallelPolicy()
        self._worker_setup = worker_setup

    def extract_plan(self) -> list[str]:
        """解压阶段计划：主包最先，其余 pkg.extract.* 按 code 排序。"""
        extract_codes = [code for code in self.registry.codes() if code.startswith("pkg.extract.")]
        return sorted(
            extract_codes,
            key=lambda code: (0 if code == "pkg.extract.main" else 1, code),
        )

    def _owner_enabled(self, owner_code: str) -> bool:
        return self.enabled_rules is None or owner_code in self.enabled_rules

    def prepare_plan(self) -> list[str]:
        """prepare 阶段计划：owner priority → owner code → prepare code。"""
        return [prepare.code for owner, prepare in self.registry.prepares() if self._owner_enabled(owner.code)]

    def inspect_plan(self) -> list[str]:
        """普通规则 inspect 计划：priority → code。"""
        return [rule.code for rule in self.registry.all() if not rule.hidden and self._owner_enabled(rule.code)]

    def plan(self) -> list[str]:
        """兼容旧调用：返回 extract + inspect 的完整规则序列。"""
        return self.extract_plan() + self.inspect_plan()

    def assign_order(self, results: dict[str, RuleResult]) -> None:
        for index, code in enumerate(self.plan()):
            if code in results:
                results[code].execution_order = index

    def _matched_files(
        self,
        rule: Inspector,
        ctx: RuleContext,
        *,
        sink: list[dict[str, Any]] | None = None,
    ) -> list[Path]:
        """匹配规则源文件；sink 非空时规划期日志先进缓冲，由父进程按计划序 flush。"""
        if not rule.source_patterns:
            return []

        def emit(level: str, message: str, detail: dict[str, Any]) -> None:
            if sink is None:
                ctx.log(level, message, **detail)
            else:
                sink.append(log_entry(level, message, detail))

        catalog = ctx.ensure_catalog()
        for pattern in rule.source_patterns:
            try:
                validate_patterns([pattern])
            except ValueError as exc:
                emit(
                    "error",
                    "pattern_rejected",
                    {
                        "task_id": ctx.task_id,
                        "rule_code": rule.code,
                        "pattern": pattern,
                        "error": str(exc),
                    },
                )
                raise
        return catalog.match(rule.source_patterns)

    @staticmethod
    def _matched_bytes(ctx: RuleContext, files: Sequence[Path]) -> int:
        """匹配文件字节总量；用于并行阈值判定与阶段可观测。"""
        total = 0
        for relative in files:
            try:
                total += (ctx.data_dir / relative).stat().st_size
            except OSError:
                continue
        return total

    def _no_match_reason(self, rule: Inspector, ctx: RuleContext) -> str:
        """无匹配可跳过原因；沿用现行的项目级解压策略补充说明。"""
        skip_reason = f"source_patterns 未匹配到文件: {', '.join(rule.source_patterns or [])}"
        category = "logs" if rule.category == RuleCategory.LOG else rule.category.value
        manifest = extraction.read_manifest(ctx.data_dir)
        skipped = extraction.policy_skipped_summary(manifest, category)
        if skipped:
            names = ", ".join(str(item["name"]) for item in skipped)
            skip_reason += f"；项目级解压策略保留了压缩项: {names}"
        return skip_reason

    def _plan_prepare(
        self,
        owner: Inspector,
        prepare: PrepareSpec,
        ctx: RuleContext,
        *,
        force_rebuild: bool = False,
    ) -> UnitPlan:
        """规划一个私有 prepare：匹配文件、缓存命中判定与载荷组装。"""
        plan = UnitPlan(unit_kind=UnitKind.PREPARE, code=prepare.code, owner_code=owner.code)
        try:
            matched = self._matched_files(owner, ctx, sink=plan.logs)
        except ValueError:
            plan.prepare_state = PREPARE_FAILED
            ctx.prepare_states[owner.code] = PREPARE_FAILED
            return plan
        if not matched:
            plan.prepare_state = PREPARE_SKIP
            ctx.prepare_states[owner.code] = PREPARE_SKIP
            plan.logs.append(
                log_entry(
                    "info",
                    "prepare_skip",
                    {
                        "task_id": ctx.task_id,
                        "rule_code": owner.code,
                        "prepare_code": prepare.code,
                        "reason": "未发现匹配源文件",
                        "prepare_state": PREPARE_SKIP,
                    },
                )
            )
            return plan

        plan.matched_bytes = self._matched_bytes(ctx, matched)
        marker = marker_path(ctx, owner.code)
        expected_sha256 = rule_file_sha256(owner)
        if not force_rebuild and marker.exists() and marker.read_text(encoding="utf-8") == expected_sha256:
            plan.prepare_state = PREPARE_HIT
            ctx.prepare_states[owner.code] = PREPARE_HIT
            plan.logs.append(
                log_entry(
                    "info",
                    "prepare_cache_hit",
                    {
                        "task_id": ctx.task_id,
                        "rule_code": owner.code,
                        "prepare_code": prepare.code,
                        "prepare_state": PREPARE_HIT,
                    },
                )
            )
            return plan

        owner_dir = ctx.prepared_dir / owner.code
        shutil.rmtree(owner_dir, ignore_errors=True)
        owner_dir.mkdir(parents=True, exist_ok=True)
        plan.request = UnitRequest(
            unit_kind=UnitKind.PREPARE,
            code=prepare.code,
            owner_code=owner.code,
            task_id=ctx.task_id,
            data_dir=str(ctx.data_dir),
            prepared_dir=str(ctx.prepared_dir),
            files=tuple(path.as_posix() for path in matched),
        )
        return plan

    def _finish_prepare(self, ctx: RuleContext, plan: UnitPlan, outcome: UnitOutcome) -> None:
        """prepare 结束后由父进程写缓存 marker 与状态：worker 不写任何结果产物。"""
        if outcome.prepare_state == PREPARE_REBUILT:
            owner = self.registry.get(plan.owner_code)
            marker_path(ctx, plan.owner_code).write_text(rule_file_sha256(owner), encoding="utf-8")
            ctx.prepare_states[plan.owner_code] = PREPARE_REBUILT
            ctx.log(
                "info",
                "prepare_cache_rebuild",
                task_id=ctx.task_id,
                rule_code=plan.owner_code,
                prepare_code=plan.code,
                prepare_state=PREPARE_REBUILT,
            )
            return
        ctx.prepare_states[plan.owner_code] = PREPARE_FAILED

    def _plan_inspect(self, code: str, ctx: RuleContext) -> UnitPlan:
        """规划一条规则：prepare 状态短路、源文件匹配、skip 原因与载荷组装。"""
        rule = self.registry.get(code)
        plan = UnitPlan(unit_kind=UnitKind.INSPECT, code=code, owner_code=code)
        prepare_state = ctx.prepare_states.get(rule.code) if rule.prepare is not None else None
        plan.prepare_state = prepare_state
        if prepare_state in {PREPARE_SKIP, PREPARE_FAILED}:
            summary = "预处理未就绪" if prepare_state == PREPARE_FAILED else "未发现匹配源文件"
            if prepare_state == PREPARE_FAILED:
                plan.logs.append(
                    log_entry(
                        "info",
                        "inspect_skip_prepare_not_ready",
                        {
                            "task_id": ctx.task_id,
                            "rule_code": rule.code,
                            "prepare_state": prepare_state,
                        },
                    )
                )
            plan.short_circuit = build_result(
                rule,
                status=RuleStatus.SKIP,
                summary=summary,
                skip_reason=summary,
                duration_ms=0,
            )
            return plan

        try:
            matched = self._matched_files(rule, ctx, sink=plan.logs)
        except ValueError as exc:
            plan.short_circuit = build_result(
                rule,
                status=RuleStatus.ERROR,
                summary="source_patterns 执行异常",
                duration_ms=0,
                metadata={"error": str(exc)},
            )
            return plan

        plan.matched_bytes = self._matched_bytes(ctx, matched)
        plan.logs.append(
            log_entry(
                "info",
                f"执行规则 {code}",
                {
                    "priority": rule.priority.value,
                    "version": rule.rule_version,
                    "matched_files": [path.as_posix() for path in matched],
                },
            )
        )
        if rule.source_patterns and not matched:
            plan.logs.append(
                log_entry(
                    "info",
                    "inspect_skip_no_match",
                    {
                        "task_id": ctx.task_id,
                        "rule_code": rule.code,
                        "source_patterns": rule.source_patterns,
                    },
                )
            )
            plan.short_circuit = build_result(
                rule,
                status=RuleStatus.SKIP,
                summary="未发现匹配源文件",
                skip_reason=self._no_match_reason(rule, ctx),
                duration_ms=0,
            )
            return plan

        plan.request = UnitRequest(
            unit_kind=UnitKind.INSPECT,
            code=code,
            owner_code=code,
            task_id=ctx.task_id,
            data_dir=str(ctx.data_dir),
            prepared_dir=str(ctx.prepared_dir),
            files=tuple(path.as_posix() for path in matched),
            prepare_state=prepare_state,
        )
        return plan

    def _store_result(self, result: RuleResult) -> RuleResult:
        """结果收集与 RULES_TOTAL 自增只发生在父进程。"""
        self.collected[result.code] = result
        RULES_TOTAL.labels(rule=result.code, status=result.status.value).inc()
        return result

    def run_one(self, code: str, ctx: RuleContext) -> RuleResult:
        """父进程串行执行单个规则；EXTRACT、隐藏规则与单规则重跑都走这条路径。"""
        plan = self._plan_inspect(code, ctx)
        flush_logs(ctx, plan.logs)
        if plan.short_circuit is not None:
            return self._store_result(plan.short_circuit)
        rule = self.registry.get(code)
        ctx.files = [Path(item) for item in (plan.request.files if plan.request is not None else ())]
        logs: list[dict[str, Any]] = []
        started = time.monotonic()
        result = run_inspect_call(rule, ctx, logs, started)
        flush_logs(ctx, logs)
        return self._store_result(result)

    def _stage_runner(self) -> StageRunner:
        return StageRunner(registry=self.registry, policy=self.policy, worker_setup=self._worker_setup)

    def run_all(self, ctx: RuleContext, after_extract: Callable[[], None] | None = None) -> dict[str, RuleResult]:
        """按 EXTRACT → PREPARE → INSPECT 固定屏障执行任务；阶段内最多 4 进程并行。"""
        results: dict[str, RuleResult] = {}
        for code in self.extract_plan():
            result = self.run_one(code, ctx)
            results[code] = result
            if code == "pkg.extract.main" and result.status == RuleStatus.ERROR:
                ctx.log(
                    "error",
                    "主包解压失败，阻断 prepare 和 inspect",
                    task_id=ctx.task_id,
                    rule_code=code,
                )
                return results

        if after_extract is not None:
            after_extract()

        try:
            ctx.ensure_catalog()
        except Exception as exc:  # noqa: BLE001 - 构建清单异常必须保留原因并继续传播
            ctx.log("error", "catalog_error", task_id=ctx.task_id, error=str(exc))
            raise

        runner = self._stage_runner()
        try:
            prepare_plans = [
                self._plan_prepare(owner, prepare, ctx)
                for owner, prepare in self.registry.prepares()
                if self._owner_enabled(owner.code)
            ]
            runner.run_stage(STAGE_PREPARE, prepare_plans, ctx, on_outcome=partial(self._finish_prepare, ctx))
            inspect_plans = [self._plan_inspect(code, ctx) for code in self.inspect_plan()]
            outcomes = runner.run_stage(STAGE_INSPECT, inspect_plans, ctx)
        finally:
            runner.close()

        for plan, outcome in zip(inspect_plans, outcomes, strict=True):
            result = plan.short_circuit if outcome is None else outcome.result
            if result is None:
                result = build_result(
                    self.registry.get(plan.code),
                    status=RuleStatus.ERROR,
                    summary="规则执行异常",
                    duration_ms=0,
                    metadata={"error": WORKER_RESULT_MISSING},
                )
            results[plan.code] = self._store_result(result)
        return results

    def _ensure_extraction_site(self, ctx: RuleContext) -> None:
        """单规则重跑前确保主包解压现场与 manifest 可复用。"""
        if ctx.package_path is None or not ctx.package_path.exists():
            return
        checksum = ctx.package_checksum
        if checksum is None:
            checksum = sha256_file(ctx.package_path)
            ctx.package_checksum = checksum
        if extraction.reusable_manifest(ctx.data_dir, checksum) is not None:
            return
        try:
            extraction.extract_main_site(ctx.package_path, ctx.data_dir, checksum, log=ctx.log)
        except ArchiveError as exc:
            raise ValueError(f"单规则重跑前主包解压失败: {exc}") from exc

    def run_rule_with_deps(
        self,
        code: str,
        ctx: RuleContext,
        *,
        force_prepare_rebuild: bool = False,
    ) -> RuleResult:
        """单规则重跑：先保证解压现场与 owner prepare 就绪，再只执行目标 inspect。

        该路径永不建进程池（契约 C10），只改动目标规则的产物。
        """
        rule = self.registry.get(code)
        if not rule.hidden and not self._owner_enabled(code):
            raise ValueError(f"规则已停用: {code}")
        self._ensure_extraction_site(ctx)
        ctx.ensure_catalog()
        if rule.prepare is not None:
            runner = self._stage_runner()
            try:
                plan = self._plan_prepare(rule, rule.prepare, ctx, force_rebuild=force_prepare_rebuild)
                runner.run_single(plan, ctx, on_outcome=partial(self._finish_prepare, ctx))
            finally:
                runner.close()
        return self.run_one(code, ctx)

    def run_rule(self, code: str, ctx: RuleContext) -> RuleResult:
        return self.run_rule_with_deps(code, ctx)
