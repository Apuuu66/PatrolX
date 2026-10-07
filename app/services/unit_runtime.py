"""执行单元运行时：串并行共用的上下文、载荷、结果产出与 worker 入口。"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import RuleRegistry
from app.inspectors.registry import registry as runtime_registry
from app.models.schemas import RuleResult, RuleStatus
from app.services.scanning import TaskFileCatalog

LogFn = Callable[..., None]

UNIT_STATUS_OK = "OK"
UNIT_STATUS_CRASHED = "CRASHED"

PREPARE_REBUILT = "REBUILT"
PREPARE_FAILED = "FAILED"
PREPARE_HIT = "HIT"
PREPARE_SKIP = "SKIP"


class RuleContext:
    """单条规则的运行上下文；files 是 source_patterns 匹配到的任务内相对路径。"""

    def __init__(
        self,
        task_id: str,
        data_dir: Path,
        log: LogFn,
        package_path: Path | None = None,
        package_checksum: str | None = None,
        result_dir: Path | None = None,
        prepared_dir: Path | None = None,
    ) -> None:
        self.task_id = task_id
        self.data_dir = data_dir
        self._log = log
        self.package_path = package_path
        self.package_checksum = package_checksum
        self.result_dir = result_dir
        self.prepared_dir = prepared_dir or data_dir / "prepared"
        self.files: list[Path] = []
        self.catalog: TaskFileCatalog | None = None
        self.prepare_states: dict[str, str] = {}

    def log(self, level: str, message: str, **detail: object) -> None:
        self._log(level, message, detail)

    def ensure_package_checksum(self) -> str:
        """确保同一运行上下文内的主包 checksum 只计算一次。"""
        if self.package_path is None:
            raise ValueError("当前上下文未绑定数据包")
        if self.package_checksum is None:
            from app.core.checksum import sha256_file

            self.package_checksum = sha256_file(self.package_path)
        return self.package_checksum

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


def make_result(rule: Inspector, *, status: RuleStatus, summary: str, **kw: object) -> RuleResult:
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


class UnitKind(StrEnum):
    """可独立调度的最小执行单元类型。"""

    PREPARE = "prepare"
    INSPECT = "inspect"


@dataclass(frozen=True, slots=True)
class UnitRequest:
    """父进程 → 执行单元的最小载荷；只传值，可被 spawn 序列化。"""

    unit_kind: UnitKind
    code: str
    owner_code: str
    task_id: str
    data_dir: str
    prepared_dir: str
    files: tuple[str, ...] = ()
    prepare_state: str | None = None


@dataclass(frozen=True, slots=True)
class UnitOutcome:
    """执行单元 → 父进程的返回值；结果与日志落盘只由父进程完成。"""

    unit_kind: UnitKind
    code: str
    status: str
    duration_ms: int
    worker_peak_rss_bytes: int
    result: RuleResult | None = None
    prepare_state: str | None = None
    logs: tuple[dict[str, Any], ...] = ()
    error: str | None = None


def elapsed_ms(started: float) -> int:
    """自 started（time.monotonic）以来的毫秒数。"""
    return int((time.monotonic() - started) * 1000)


def peak_rss_bytes() -> int:
    """当前进程峰值 RSS，统一换算为字节（Linux ru_maxrss 为 KB）。"""
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows 无 resource 模块
        return 0
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform.startswith("linux") else value


def validate_request(request: UnitRequest) -> None:
    """校验载荷路径：必须绝对目录 + 任务内相对文件，非法载荷直接拒绝。"""
    if not Path(request.data_dir).is_absolute():
        raise ValueError(f"data_dir 必须是绝对路径: {request.data_dir}")
    if not Path(request.prepared_dir).is_absolute():
        raise ValueError(f"prepared_dir 必须是绝对路径: {request.prepared_dir}")
    for item in request.files:
        candidate = Path(item)
        if candidate.is_absolute() or item.startswith("~") or ".." in candidate.parts:
            raise ValueError(f"files 必须是任务内相对路径: {item}")


def load_registry_once() -> None:
    """worker 初始化：装载注册表（幂等，每个子进程只生效一次）。"""
    runtime_registry.load_all()


def initialize_worker(worker_setup: Callable[[], None] | None = None) -> None:
    """ProcessPoolExecutor initializer：调用可注入的规则装载入口。"""
    if worker_setup is None:
        load_registry_once()
        return
    worker_setup()


def build_result(
    rule: Inspector,
    *,
    status: RuleStatus,
    summary: str | None,
    duration_ms: int,
    skip_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RuleResult:
    """按规则元数据构建结果；父进程与 worker 共用这一份实现。"""
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


def validate_metrics(rule: Inspector, result: RuleResult) -> str | None:
    """校验规则输出指标与声明契约是否一致。"""
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


def log_entry(level: str, message: str, detail: dict[str, Any]) -> dict[str, Any]:
    """构造可序列化的日志条目；父进程按计划序 flush 到 execution.log。"""
    return {"level": level, "message": message, "detail": detail}


def flush_logs(ctx: RuleContext, logs: Sequence[dict[str, Any]]) -> None:
    """把收集到的单元日志按原顺序写入执行日志（父进程唯一写入者）。"""
    for record in logs:
        ctx.log(record.get("level", "info"), record.get("message", ""), **dict(record.get("detail") or {}))


def run_prepare_call(prepare: PrepareSpec, ctx: RuleContext, logs: list[dict[str, Any]]) -> str:
    """执行 prepare 函数；异常隔离为 FAILED 并留下可解释日志。"""
    try:
        prepare.run(ctx)
    except Exception as exc:  # noqa: BLE001 - prepare 失败必须隔离为 owner skip
        logs.append(
            log_entry(
                "error",
                "prepare_error",
                {
                    "task_id": ctx.task_id,
                    "rule_code": prepare.owner_code,
                    "prepare_code": prepare.code,
                    "error": str(exc),
                    "prepare_state": PREPARE_FAILED,
                },
            )
        )
        return PREPARE_FAILED
    return PREPARE_REBUILT


def run_inspect_call(
    rule: Inspector,
    ctx: RuleContext,
    logs: list[dict[str, Any]],
    started: float,
) -> RuleResult:
    """调用规则并返回契约化结果；异常与契约问题都转为 error 结果。"""
    try:
        result = rule.run(ctx)
        if not isinstance(result, RuleResult):
            raise TypeError(f"规则 {rule.code} 未返回 RuleResult")
        contract_error = validate_metrics(rule, result)
        if contract_error:
            logs.append(
                log_entry(
                    "error",
                    f"规则 {rule.code} 输出契约校验失败",
                    {"task_id": ctx.task_id, "rule_code": rule.code, "error": contract_error},
                )
            )
            return build_result(
                rule,
                status=RuleStatus.ERROR,
                summary="规则输出契约校验失败",
                duration_ms=elapsed_ms(started),
                metadata={"error": contract_error},
            )
        result.executed_at = datetime.now(UTC)
        result.duration_ms = elapsed_ms(started)
        return result
    except Exception as exc:  # noqa: BLE001 - 规则异常统一记为 error
        logs.append(
            log_entry(
                "error",
                f"规则 {rule.code} 执行异常",
                {"task_id": ctx.task_id, "rule_code": rule.code, "error": str(exc)},
            )
        )
        return build_result(
            rule,
            status=RuleStatus.ERROR,
            summary="规则执行异常",
            duration_ms=elapsed_ms(started),
            metadata={"error": str(exc)},
        )


def execute_unit(request: UnitRequest, registry: RuleRegistry | None = None) -> UnitOutcome:
    """执行单个单元；worker 内只回传结果与日志，不写任何任务产物。

    registry 为空时使用 worker 进程中已装载的全局注册表；父进程串行执行时显式传入。
    """
    validate_request(request)
    active_registry = registry if registry is not None else runtime_registry
    logs: list[dict[str, Any]] = []
    ctx = _build_context(request, logs)
    started = time.monotonic()
    if request.unit_kind == UnitKind.PREPARE:
        state = run_prepare_call(active_registry.prepare(request.code), ctx, logs)
        return _finish_outcome(request, logs, started, prepare_state=state)
    result = run_inspect_call(active_registry.get(request.code), ctx, logs, started)
    return _finish_outcome(request, logs, started, result=result)


def _build_context(request: UnitRequest, logs: list[dict[str, Any]]) -> RuleContext:
    """按载荷构造最小上下文：不携带注册表、日志函数与主包路径。"""

    def collect(level: str, message: str, detail: dict | None = None) -> None:
        logs.append(log_entry(level, message, dict(detail or {})))

    ctx = RuleContext(
        task_id=request.task_id,
        data_dir=Path(request.data_dir),
        log=collect,
        prepared_dir=Path(request.prepared_dir),
    )
    ctx.files = [Path(item) for item in request.files]
    if request.prepare_state is not None:
        ctx.prepare_states = {request.owner_code: request.prepare_state}
    return ctx


def _finish_outcome(
    request: UnitRequest,
    logs: list[dict[str, Any]],
    started: float,
    *,
    result: RuleResult | None = None,
    prepare_state: str | None = None,
) -> UnitOutcome:
    return UnitOutcome(
        unit_kind=request.unit_kind,
        code=request.code,
        status=UNIT_STATUS_OK,
        duration_ms=elapsed_ms(started),
        worker_peak_rss_bytes=peak_rss_bytes(),
        result=result,
        prepare_state=prepare_state,
        logs=tuple(logs),
    )
