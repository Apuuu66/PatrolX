"""规则执行器：优先级顺序 + 源文件显式匹配 + 结果契约校验。"""

import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.archive import ArchiveError
from app.core.checksum import sha256_file
from app.core.metrics import RULES_TOTAL
from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry
from app.models.schemas import RuleResult, RuleStatus
from app.services import extraction
from app.services.prepare import marker_path, rule_file_sha256
from app.services.scanning import TaskFileCatalog, validate_patterns

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
        prepared_dir: Path | None = None,
    ) -> None:
        self.task_id = task_id
        self.data_dir = data_dir
        self._log = log
        self.package_path = package_path
        self.result_dir = result_dir
        self.prepared_dir = prepared_dir or data_dir / "prepared"
        self.files: list[Path] = []
        self.catalog: TaskFileCatalog | None = None
        self.prepare_states: dict[str, str] = {}

    def log(self, level: str, message: str, **detail: object) -> None:
        self._log(level, message, detail)

    def ensure_catalog(self) -> TaskFileCatalog:
        """确保解压终态后的任务文件清单只构建一次。"""
        if self.catalog is None:
            self.catalog = TaskFileCatalog.build(self.data_dir)
        return self.catalog

    def resolved_files(self) -> list[Path]:
        """将相对匹配路径解析为任务现场中的实际文件。"""
        if self.catalog is not None:
            return [self.catalog.resolve(ctx_file) for ctx_file in self.files]
        return [ctx_file if ctx_file.is_absolute() else self.data_dir / ctx_file for ctx_file in self.files]


class Executor:
    def __init__(self, registry: RuleRegistry) -> None:
        self.registry = registry
        self.collected: dict[str, RuleResult] = {}

    def extract_plan(self) -> list[str]:
        """解压阶段计划：主包最先，其余 pkg.extract.* 按 code 排序。"""
        extract_codes = [code for code in self.registry.codes() if code.startswith("pkg.extract.")]
        return sorted(
            extract_codes,
            key=lambda code: (0 if code == "pkg.extract.main" else 1, code),
        )

    def prepare_plan(self) -> list[str]:
        """prepare 阶段计划：owner priority → owner code → prepare code。"""
        return [prepare.code for _owner, prepare in self.registry.prepares()]

    def inspect_plan(self) -> list[str]:
        """普通规则 inspect 计划：priority → code。"""
        return [rule.code for rule in self.registry.all() if not rule.hidden]

    def plan(self) -> list[str]:
        """兼容旧调用：返回 extract + inspect 的完整规则序列。"""
        return self.extract_plan() + self.inspect_plan()

    def assign_order(self, results: dict[str, RuleResult]) -> None:
        for index, code in enumerate(self.plan()):
            if code in results:
                results[code].execution_order = index

    def _matched_files(self, rule: Inspector, ctx: RuleContext) -> list[Path]:
        if not rule.source_patterns:
            return []
        catalog = ctx.ensure_catalog()
        for pattern in rule.source_patterns:
            try:
                validate_patterns([pattern])
            except ValueError as exc:
                ctx.log(
                    "error",
                    "pattern_rejected",
                    task_id=ctx.task_id,
                    rule_code=rule.code,
                    pattern=pattern,
                    error=str(exc),
                )
                raise
        return catalog.match(rule.source_patterns)

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

    def _run_prepare(self, owner: Inspector, prepare, ctx: RuleContext) -> str:
        """执行或复用 owner 私有 prepare；状态不进入公共 RuleResult。"""
        owner_dir = ctx.prepared_dir / owner.code
        marker = marker_path(ctx, owner.code)
        try:
            matched = self._matched_files(owner, ctx)
        except ValueError:
            ctx.prepare_states[owner.code] = "FAILED"
            return "FAILED"
        if not matched:
            ctx.prepare_states[owner.code] = "SKIP"
            ctx.log(
                "info",
                "prepare_skip",
                task_id=ctx.task_id,
                rule_code=owner.code,
                prepare_code=prepare.code,
                reason="未发现匹配源文件",
                prepare_state="SKIP",
            )
            return "SKIP"
        expected_sha256 = rule_file_sha256(owner)
        if marker.exists() and marker.read_text(encoding="utf-8") == expected_sha256:
            ctx.prepare_states[owner.code] = "HIT"
            ctx.files = matched
            ctx.log(
                "info",
                "prepare_cache_hit",
                task_id=ctx.task_id,
                rule_code=owner.code,
                prepare_code=prepare.code,
                prepare_state="HIT",
            )
            return "HIT"

        shutil.rmtree(owner_dir, ignore_errors=True)
        owner_dir.mkdir(parents=True, exist_ok=True)
        ctx.files = matched
        try:
            prepare.run(ctx)
            marker.write_text(expected_sha256, encoding="utf-8")
            ctx.prepare_states[owner.code] = "REBUILT"
            ctx.log(
                "info",
                "prepare_cache_rebuild",
                task_id=ctx.task_id,
                rule_code=owner.code,
                prepare_code=prepare.code,
                prepare_state="REBUILT",
            )
            return "REBUILT"
        except Exception as exc:  # noqa: BLE001 - prepare 失败必须隔离为 owner skip
            ctx.prepare_states[owner.code] = "FAILED"
            ctx.log(
                "error",
                "prepare_error",
                task_id=ctx.task_id,
                rule_code=owner.code,
                prepare_code=prepare.code,
                error=str(exc),
                prepare_state="FAILED",
            )
            return "FAILED"

    def run_one(self, code: str, ctx: RuleContext) -> RuleResult:
        rule = self.registry.get(code)
        if self._reuse_existing(rule, ctx):
            RULES_TOTAL.labels(rule=code, status=self.collected[code].status.value).inc()
            return self.collected[code]
        prepare_state = ctx.prepare_states.get(rule.code) if rule.prepare is not None else None
        if prepare_state in {"SKIP", "FAILED"}:
            started = time.monotonic()
            skip_reason = "预处理未就绪" if prepare_state == "FAILED" else "未发现匹配源文件"
            result = self._result(
                rule,
                status=RuleStatus.SKIP,
                summary="预处理未就绪" if prepare_state == "FAILED" else "未发现匹配源文件",
                skip_reason=skip_reason,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            if prepare_state == "FAILED":
                ctx.log(
                    "info",
                    "inspect_skip_prepare_not_ready",
                    task_id=ctx.task_id,
                    rule_code=rule.code,
                    prepare_state=prepare_state,
                )
            self.collected[rule.code] = result
            RULES_TOTAL.labels(rule=rule.code, status=result.status.value).inc()
            return result
        started = time.monotonic()
        try:
            ctx.files = self._matched_files(rule, ctx)
        except ValueError as exc:
            result = self._result(
                rule,
                status=RuleStatus.ERROR,
                summary="source_patterns 执行异常",
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"error": str(exc)},
            )
            self.collected[code] = result
            RULES_TOTAL.labels(rule=code, status=result.status.value).inc()
            return result
        ctx.log(
            "info",
            f"执行规则 {code}",
            priority=rule.priority.value,
            version=rule.rule_version,
            matched_files=[p.as_posix() for p in ctx.files],
        )
        if rule.source_patterns and not ctx.files:
            result = self._result(
                rule,
                status=RuleStatus.SKIP,
                summary="未发现匹配源文件",
                skip_reason=f"source_patterns 未匹配到文件: {', '.join(rule.source_patterns)}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            ctx.log(
                "info",
                "inspect_skip_no_match",
                task_id=ctx.task_id,
                rule_code=rule.code,
                source_patterns=rule.source_patterns,
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
                ctx.log(
                    "error",
                    f"规则 {code} 输出契约校验失败",
                    task_id=ctx.task_id,
                    rule_code=code,
                    error=contract_error,
                )
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
            ctx.log(
                "error",
                f"规则 {code} 执行异常",
                task_id=ctx.task_id,
                rule_code=code,
                error=str(exc),
            )
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
        """按 EXTRACT → PREPARE → INSPECT 固定屏障执行任务。"""
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

        try:
            ctx.ensure_catalog()
        except Exception as exc:  # noqa: BLE001 - 构建清单异常必须保留原因并继续传播
            ctx.log("error", "catalog_error", task_id=ctx.task_id, error=str(exc))
            raise

        for owner, prepare in self.registry.prepares():
            self._run_prepare(owner, prepare, ctx)

        for code in self.inspect_plan():
            results[code] = self.run_one(code, ctx)
        return results

    def _ensure_extraction_site(self, ctx: RuleContext) -> None:
        """单规则重跑前确保主包解压现场与 manifest 可复用。"""
        if ctx.package_path is None or not ctx.package_path.exists():
            return
        checksum = sha256_file(ctx.package_path)
        if extraction.reusable_manifest(ctx.data_dir, checksum) is not None:
            return
        try:
            extraction.extract_main_site(ctx.package_path, ctx.data_dir, checksum, log=ctx.log)
        except ArchiveError as exc:
            raise ValueError(f"单规则重跑前主包解压失败: {exc}") from exc

    def run_rule_with_deps(self, code: str, ctx: RuleContext) -> RuleResult:
        """单规则重跑：先保证解压现场与 owner prepare 就绪，再只执行目标 inspect。"""
        rule = self.registry.get(code)
        self._ensure_extraction_site(ctx)
        ctx.ensure_catalog()
        if rule.prepare is not None:
            self._run_prepare(rule, rule.prepare, ctx)
        return self.run_one(code, ctx)

    def run_rule(self, code: str, ctx: RuleContext) -> RuleResult:
        return self.run_rule_with_deps(code, ctx)

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
