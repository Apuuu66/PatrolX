"""规则执行器：优先级顺序 + 源文件显式匹配 + 结果契约校验。"""

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.metrics import RULES_TOTAL
from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry
from app.models.schemas import RuleResult, RuleStatus

LogFn = Callable[[str, str, dict], None]


class RuleContext:
    """单条规则的运行上下文；files 是 source_patterns 匹配到的任务内相对路径。"""

    def __init__(
        self,
        task_id: str,
        data_dir: Path,
        log: LogFn,
        package_path: Path | None = None,
        result_dir: Path | None = None,
    ) -> None:
        self.task_id = task_id
        self.data_dir = data_dir
        self._log = log
        self.package_path = package_path
        self.result_dir = result_dir
        self.files: list[Path] = []

    def log(self, level: str, message: str, **detail: object) -> None:
        self._log(level, message, detail)

    def resolved_files(self) -> list[Path]:
        """将相对匹配路径解析为任务现场中的实际文件。"""
        return [ctx_file if ctx_file.is_absolute() else self.data_dir / ctx_file for ctx_file in self.files]


class Executor:
    def __init__(self, registry: RuleRegistry) -> None:
        self.registry = registry
        self.collected: dict[str, RuleResult] = {}

    def plan(self) -> list[str]:
        """全量执行计划：P0 基础设施先执行，普通规则按优先级与注册码排序。"""
        by_priority: dict[int, list[str]] = {}
        for code in self.registry.codes():
            by_priority.setdefault(self.registry.get(code).priority.value, []).append(code)
        order: list[str] = []
        for priority in sorted(by_priority):
            codes = sorted(by_priority[priority])
            if priority == 0:
                codes = sorted(
                    codes,
                    key=lambda code: (
                        0 if code == "pkg.extract.main" else 1,
                        self.registry.get(code).hidden is False,
                        code,
                    ),
                )
            order.extend(codes)
        return order

    def assign_order(self, results: dict[str, RuleResult]) -> None:
        for index, code in enumerate(self.plan()):
            if code in results:
                results[code].execution_order = index

    def _matched_files(self, rule: Inspector, ctx: RuleContext) -> list[Path]:
        if not rule.source_patterns:
            return []
        candidates = [p.relative_to(ctx.data_dir) for p in ctx.data_dir.rglob("*") if p.is_file()]
        matched: list[Path] = []
        for candidate in candidates:
            relative = Path(candidate).as_posix()
            if any(re.fullmatch(pattern, relative) for pattern in rule.source_patterns):
                matched.append(Path(relative))
        return sorted(set(matched), key=lambda p: p.as_posix())

    @staticmethod
    def _validate_metrics(rule: Inspector, result: RuleResult) -> str | None:
        if result.status not in (RuleStatus.PASS, RuleStatus.WARN, RuleStatus.FAIL):
            return None
        declared = {
            (m.get("key") if isinstance(m, dict) else m.key): (m.get("unit") if isinstance(m, dict) else m.unit)
            for m in rule.outputs_metrics
        }
        actual = {metric.key: metric.unit for metric in result.metrics}
        if actual != declared:
            return f"metrics 契约不一致: 声明 {declared}, 实际 {actual}"
        return None

    def run_one(self, code: str, ctx: RuleContext) -> RuleResult:
        rule = self.registry.get(code)
        if self._reuse_existing(rule, ctx):
            RULES_TOTAL.labels(rule=code, status=self.collected[code].status.value).inc()
            return self.collected[code]
        ctx.files = self._matched_files(rule, ctx)
        ctx.log(
            "info",
            f"执行规则 {code}",
            priority=rule.priority.value,
            version=rule.rule_version,
            matched_files=[p.as_posix() for p in ctx.files],
        )
        started = time.monotonic()
        if rule.source_patterns and not ctx.files:
            result = self._result(
                rule,
                status=RuleStatus.SKIP,
                summary="未发现匹配源文件",
                skip_reason=f"source_patterns 未匹配到文件: {', '.join(rule.source_patterns)}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            self.collected[code] = result
            RULES_TOTAL.labels(rule=code, status=result.status.value).inc()
            return result
        try:
            result = rule.run(ctx)
            if not isinstance(result, RuleResult):
                raise TypeError(f"规则 {code} 未返回 RuleResult")
            contract_error = self._validate_metrics(rule, result)
            if contract_error:
                ctx.log("error", f"规则 {code} 输出契约校验失败", error=contract_error)
                result = self._result(
                    rule,
                    status=RuleStatus.ERROR,
                    summary="规则输出契约校验失败",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    metadata={"error": contract_error},
                )
            else:
                result.executed_at = datetime.now(UTC)
                result.duration_ms = int((time.monotonic() - started) * 1000)
            self.collected[code] = result
            RULES_TOTAL.labels(rule=code, status=result.status.value).inc()
            return result
        except Exception as exc:  # noqa: BLE001 - 规则异常统一记为 error
            ctx.log("error", f"规则 {code} 执行异常", error=str(exc))
            result = self._result(
                rule,
                status=RuleStatus.ERROR,
                summary="规则执行异常",
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"error": str(exc)},
            )
            self.collected[code] = result
            RULES_TOTAL.labels(rule=code, status=result.status.value).inc()
            return result

    def _reuse_existing(self, rule: Inspector, ctx: RuleContext) -> bool:
        """单规则重跑基线不启用全量复用；保留 result_dir 供测试场景使用。"""
        del rule, ctx
        return False

    def run_all(self, ctx: RuleContext) -> dict[str, RuleResult]:
        results: dict[str, RuleResult] = {}
        for code in self.plan():
            results[code] = self.run_one(code, ctx)
        return results

    def run_rule(self, code: str, ctx: RuleContext) -> RuleResult:
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
            execution_order=0,
            status=status,
            severity=rule.severity,
            summary=summary,
            skip_reason=skip_reason,
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
        execution_order=0,
        status=status,
        severity=rule.severity,
        summary=summary,
        executed_at=datetime.now(UTC),
        **kw,
    )
