"""规则执行器：优先级分级 + 消费即依赖 + 单规则重跑 + 产物版本校验。"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.metrics import RULES_TOTAL
from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry
from app.models.schemas import RuleResult, RuleStatus
from app.services.artifacts import Artifact, ArtifactStore

LogFn = Callable[[str, str, dict], None]


class RuleContext:
    def __init__(
        self,
        task_id: str,
        system_id: str,
        data_dir: Path,
        artifacts: ArtifactStore,
        log: LogFn,
        package_path: Path | None = None,
        result_dir: Path | None = None,
    ) -> None:
        self.task_id = task_id
        self.system_id = system_id
        self.data_dir = data_dir
        self.artifacts = artifacts
        self.artifacts_dir = artifacts.root
        self._log = log
        self.inputs: dict[str, Artifact] = {}
        self.package_path = package_path
        self.result_dir = result_dir

    def log(self, level: str, message: str, **detail: object) -> None:
        self._log(level, message, detail)

    def rule_artifact_path(self, rule_code: str, key: str) -> Path:
        """规则产出产物的约定路径：artifacts/<rule_code>/<key>。"""
        return self.artifacts_dir / rule_code / key


class Executor:
    def __init__(self, registry: RuleRegistry) -> None:
        self.registry = registry
        self.collected: dict[str, RuleResult] = {}

    def producer_of(self, key: str) -> str | None:
        return self.registry.producers.get(key)

    def validate_dependencies(self) -> None:
        producers = self.registry.producers
        for rule in self.registry.all(include_hidden=True):
            for key in rule.inputs:
                producer_code = producers.get(key)
                if producer_code is None:
                    raise ValueError(f"规则 {rule.code} 消费未声明的产物: {key}")
                producer = self.registry.get(producer_code)
                if producer.priority > rule.priority:
                    raise ValueError(
                        f"规则 {rule.code} 依赖 {producer_code} 未指向更高优先级"
                        f"（P{producer.priority} -> P{rule.priority}）"
                    )
                if producer.priority == rule.priority and not self._is_extract_rule(producer):
                    raise ValueError(f"规则 {rule.code} 同优先级依赖 {producer_code}：仅允许依赖解压基础设施规则")

    @staticmethod
    def _is_extract_rule(rule: Inspector) -> bool:
        return rule.hidden and rule.code.startswith("pkg.extract.")

    def plan(self) -> list[str]:
        """全量执行计划：按优先级分组升序，组内按依赖拓扑排序（生产者先于消费者）。"""
        self.validate_dependencies()
        producers = self.registry.producers
        by_priority: dict[int, list[str]] = {}
        for code in self.registry.codes():
            by_priority.setdefault(self.registry.get(code).priority.value, []).append(code)
        visited: set[str] = set()
        order: list[str] = []

        def visit(code: str) -> None:
            if code in visited:
                return
            visited.add(code)
            rule = self.registry.get(code)
            for key in rule.inputs:
                producer_code = producers.get(key)
                if (
                    producer_code
                    and producer_code != code
                    and self.registry.get(producer_code).priority == rule.priority
                ):
                    visit(producer_code)
            order.append(code)

        for priority in sorted(by_priority):
            codes = sorted(by_priority[priority])
            # 解压基础设施规则在同优先级内先执行，保证数据就绪
            extract_first = [c for c in codes if c.startswith("pkg.extract.")]
            rest = [c for c in codes if not c.startswith("pkg.extract.")]
            for code in extract_first + rest:
                visit(code)
        return order

    def assign_order(self, results: dict[str, RuleResult]) -> None:
        for index, code in enumerate(self.plan()):
            if code in results:
                results[code].execution_order = index

    def _ensure_dependency(self, rule: Inspector, ctx: RuleContext) -> list[str]:
        """确保规则消费的产物可用（缺失/版本过期则补跑生产者），返回缺失的产物 key。"""
        missing: list[str] = []
        for key in rule.inputs:
            producer_code = self.producer_of(key)
            producer = self.registry.get(producer_code)
            artifact = ctx.artifacts.valid(key, producer)
            if artifact is None:
                self.run_one(producer_code, ctx)
                artifact = ctx.artifacts.valid(key, producer)
            if artifact is None:
                missing.append(key)
            else:
                ctx.inputs[key] = artifact
        return missing

    def run_one(self, code: str, ctx: RuleContext) -> RuleResult:
        rule = self.registry.get(code)
        if self._reuse_existing(rule, ctx):
            RULES_TOTAL.labels(rule=code, status=self.collected[code].status.value).inc()
            return self.collected[code]
        ctx.log("info", f"执行规则 {code}", priority=rule.priority.value, version=rule.rule_version)
        started = time.monotonic()
        ctx.inputs = {}
        missing = self._ensure_dependency(rule, ctx)
        if missing:
            result = self._result(
                rule,
                status=RuleStatus.SKIP,
                summary="数据未准备",
                skip_reason=(f"数据未准备：依赖产物 {', '.join(missing)} 缺失。请先执行全量巡检生成数据"),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            self.collected[code] = result
            RULES_TOTAL.labels(rule=code, status=result.status.value).inc()
            return result
        try:
            result = rule.run(ctx)
            if not isinstance(result, RuleResult):
                raise TypeError(f"规则 {code} 未返回 RuleResult")
            result.executed_at = datetime.now(UTC)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            if result.status in (RuleStatus.PASS, RuleStatus.WARN, RuleStatus.FAIL):
                self._persist_outputs(rule, ctx)
            self.collected[code] = result
            RULES_TOTAL.labels(rule=code, status=result.status.value).inc()
            return result
        except Exception as exc:  # noqa: BLE001 - 规则异常统一记为 error
            ctx.log("error", f"规则 {code} 执行异常", error=str(exc))
            result = self._result(
                rule,
                status=RuleStatus.ERROR,
                summary="规则执行异常",
                skip_reason=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"error": str(exc)},
            )
            self.collected[code] = result
            RULES_TOTAL.labels(rule=code, status=result.status.value).inc()
            return result

    def _reuse_existing(self, rule: Inspector, ctx: RuleContext) -> bool:
        """产物全部有效（存在且 rule_version 一致）且旧结果存在时复用，避免重复解析。"""
        if not rule.outputs_artifacts:
            return False
        if not all(ctx.artifacts.valid(key, rule) for key in rule.outputs_artifacts):
            return False
        if ctx.result_dir is None:
            return False
        result_path = ctx.result_dir / f"{rule.code}.json"
        if not result_path.exists():
            return False
        import json

        from app.models.schemas import RuleResult

        result = RuleResult.model_validate(json.loads(result_path.read_text(encoding="utf-8")))
        ctx.log("info", f"复用规则产物 {rule.code}", version=rule.rule_version)
        self.collected[rule.code] = result
        return True

    def _persist_outputs(self, rule: Inspector, ctx: RuleContext) -> None:
        for key in rule.outputs_artifacts:
            path = ctx.rule_artifact_path(rule.code, key)
            if not path.exists():
                ctx.log("warn", f"规则 {rule.code} 声明产物 {key} 但未生成文件")
                continue
            ctx.artifacts.save(key, rule, path)

    def run_all(self, ctx: RuleContext) -> dict[str, RuleResult]:
        self.validate_dependencies()
        results: dict[str, RuleResult] = {}
        for code in self.plan():
            results[code] = self.run_one(code, ctx)
        return results

    def run_rule_with_deps(self, code: str, ctx: RuleContext) -> RuleResult:
        self.validate_dependencies()
        return self.run_one(code, ctx)

    @staticmethod
    def _result(
        rule: Inspector,
        *,
        status: RuleStatus,
        summary: str | None,
        skip_reason: str | None = None,
        duration_ms: int,
        metadata: dict | None = None,
    ) -> RuleResult:
        return RuleResult(
            code=rule.code,
            name=rule.name,
            category=rule.category,
            priority=rule.priority,
            inputs=list(rule.inputs),
            execution_order=0,
            status=status,
            severity=rule.severity,
            summary=summary,
            skip_reason=skip_reason,
            executed_at=datetime.now(UTC),
            duration_ms=duration_ms,
            metadata=metadata or {},
        )


def make_result(rule: Inspector, *, status: RuleStatus, summary: str, **kw) -> RuleResult:
    """规则 run 内构建结果的辅助函数。"""
    return RuleResult(
        code=rule.code,
        name=rule.name,
        category=rule.category,
        priority=rule.priority,
        inputs=list(rule.inputs),
        execution_order=0,
        status=status,
        severity=rule.severity,
        summary=summary,
        executed_at=datetime.now(UTC),
        **kw,
    )
