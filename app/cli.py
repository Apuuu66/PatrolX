"""本地开发模式 CLI：python main.py 一键离线全流程 / 单规则调试。"""

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.archive import is_archive
from app.core.checksum import sha256_file
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import TASKS_TOTAL
from app.inspectors.pkg import EXTRACT_MANIFEST
from app.inspectors.registry import registry
from app.models.db import init_db
from app.models.schemas import (
    InspectionTask,
    PackageKind,
    Product,
    RuleCategory,
    RuleStatus,
    SystemInspection,
    SystemStatus,
    TaskInventory,
    TaskMode,
    TaskStats,
    TaskStatus,
    TaskTrigger,
)
from app.services import store, task_db
from app.services.auth import AuthError, create_user, ensure_default_admin
from app.services.executor import Executor, RuleContext, RuleDependencyError
from app.services.extraction.manifest import LEGACY_TARGET_ROOTS
from app.services.extraction.manifest import read_manifest as read_manifest_v5
from app.services.inventory.ledger import archive_inventory, write_inventory_evidence
from app.services.inventory.parser import parse_inventory
from app.services.report import render_report
from app.services.rule_scope import RuleScopeError, RuleScopeResolver
from app.services.scanning import TaskFileCatalog
from app.services.task_execution_scope import TaskExecutionScope, freeze_task_execution_scope

logger = get_logger("patrolx.cli")


def _now() -> datetime:
    return datetime.now(UTC)


class CliMetadataError(ValueError):
    """CLI 任务元数据错误；携带稳定错误码与详情。"""

    def __init__(self, code: str, message: str, *, detail: dict[str, object]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def _print_cli_error(error: CliMetadataError | RuleDependencyError) -> None:
    print(f"错误 [{error.code}]: {error.message}")
    if error.detail:
        print(json.dumps(error.detail, ensure_ascii=False, sort_keys=True))


def _resolve_task_metadata(
    product: Product | str | None,
    package_kind: PackageKind | str | None,
    *,
    existing: dict | None = None,
    task_id: str | None = None,
    require_product_when_new: bool = True,
    require_product_for_existing: bool = False,
) -> tuple[Product | str | None, PackageKind]:
    """按 API 语义合并显式与持久化元数据，并拒绝同任务冲突。"""
    customer = ((existing or {}).get("system") or {}).get("customer") or {}
    persisted_product_raw = customer.get("product")
    persisted_product: Product | str | None = None
    if persisted_product_raw:
        normalized_persisted = str(persisted_product_raw).strip().upper()
        try:
            persisted_product = Product(normalized_persisted)
        except ValueError as exc:
            if normalized_persisted == "UMF2020":
                # 仅允许旧任务持久化现场恢复；CLI 新输入仍只接受 Product。
                persisted_product = normalized_persisted
            else:
                raise CliMetadataError(
                    "invalid_product",
                    "已有任务的网元类型不是受支持的历史值",
                    detail={
                        "value": str(persisted_product_raw),
                        "allowed": [Product.UMF.value, Product.CSP.value, "UMF2020"],
                    },
                ) from exc

    persisted_kind: PackageKind | None = None
    if existing is not None:
        persisted_kind_raw = existing.get("package_kind")
        try:
            persisted_kind = PackageKind(persisted_kind_raw or PackageKind.INSPECTION)
        except ValueError:
            persisted_kind = PackageKind.INSPECTION

    requested_kind = PackageKind(package_kind) if package_kind is not None else persisted_kind or PackageKind.INSPECTION
    if existing is not None and package_kind is not None and persisted_kind is not None:
        if requested_kind != persisted_kind:
            raise CliMetadataError(
                "package_kind_conflict",
                "同一任务的包类型与已有任务冲突",
                detail={
                    "task_id": task_id,
                    "existing": persisted_kind.value,
                    "requested": requested_kind.value,
                },
            )

    explicit_product: Product | None = None
    normalized_input = str(product).strip().upper() if product is not None else None
    if normalized_input:
        try:
            explicit_product = Product(normalized_input)
        except ValueError as exc:
            raise CliMetadataError(
                "invalid_product",
                "巡检包网元类型仅支持 UMF 或 CSP",
                detail={"value": str(product), "allowed": [Product.UMF.value, Product.CSP.value]},
            ) from exc

    if requested_kind == PackageKind.LOG_SUPPLEMENT:
        if explicit_product is not None:
            raise CliMetadataError(
                "metadata_not_applicable",
                "日志补充包不允许携带网元类型",
                detail={"package_kind": requested_kind.value, "fields": ["product"]},
            )
        # 日志补充包的 product 在契约中固定为 null；历史脏值不得继续传播到执行上下文。
        return None, requested_kind

    if existing is not None and explicit_product is not None and persisted_product is not None:
        if explicit_product.value != str(persisted_product):
            raise CliMetadataError(
                "package_product_conflict",
                "同一任务的网元类型与已有任务冲突",
                detail={
                    "task_id": task_id,
                    "existing": str(persisted_product),
                    "requested": explicit_product.value,
                },
            )

    resolved_product = explicit_product if explicit_product is not None else persisted_product
    product_required = (existing is None and require_product_when_new) or require_product_for_existing
    if resolved_product is None and product_required:
        raise CliMetadataError(
            "missing_product",
            "巡检包必须提供网元类型",
            detail={"package_kind": requested_kind.value, "field": "product"},
        )
    return resolved_product, requested_kind


def new_task_id() -> str:
    """任务 ID：时间戳前缀（可读、可排序）+ 随机后缀（防并发/同秒碰撞）。"""
    return f"task-{_now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def clean_task_id(package_name: str) -> str:
    """包名去扩展名 + 非法字符清洗（保证目录安全）。"""
    stem = re.sub(r"\.(zip|tar\.gz|tgz|tar)$", "", package_name.lower())
    name = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return name or "task"


def generate_task_id(package_name: str) -> str:
    """一个包名唯一派生一个任务 ID。"""
    return f"task-{clean_task_id(package_name)}"


def find_packages(root: Path | None = None) -> list[Path]:
    base = root if root is not None else settings.uploads
    base.mkdir(parents=True, exist_ok=True)
    return [p for p in sorted(base.iterdir()) if p.is_file() and is_archive(p)]


def latest_package() -> Path:
    packages = find_packages()
    if not packages:
        raise SystemExit("未找到数据包：请将 zip/tar.gz 放入 uploads/ 根目录")
    return max(packages, key=lambda p: p.stat().st_mtime)


def _make_log_fn(task_id: str, output_root: Path | None = None):
    log_path = (output_root or settings.output) / task_id / "execution.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(level: str, message: str, detail: dict | None = None) -> None:
        entry = {"ts": store.now_utc(), "level": level, "message": message, **(detail or {})}
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        suffix = f" {detail}" if detail else ""
        print(f"[{level.upper():5}] {message}{suffix}")

    return log


def _frozen_rule_scope(
    task_id: str,
    *,
    network_element_type: Product | str | None,
) -> task_db.RuleScopeSnapshotData:
    """读取既有任务冻结规则范围；旧任务不得静默采用当前配置。"""
    normalized_type = None
    if network_element_type is not None:
        normalized_type = str(getattr(network_element_type, "value", network_element_type)).strip().upper() or None
    snapshot = task_db.get_rule_scope_snapshot(
        task_id,
        network_element_type=normalized_type,
    )
    if snapshot is None:
        raise RuleScopeError(
            "task_result_requires_rebuild",
            "旧任务没有冻结规则范围，请按当前配置全量重建",
            409,
            {"task_id": task_id, "network_element_type": normalized_type},
        )
    return snapshot


def _validate_frozen_rule_scope(
    task_id: str,
    rule_codes: list[str],
    *,
    network_element_type: Product | str | None,
) -> tuple[task_db.RuleScopeSnapshotData, tuple]:
    """校验规则属于原任务快照且版本未漂移，返回冻结范围与当前实现。"""
    snapshot = _frozen_rule_scope(task_id, network_element_type=network_element_type)
    rules = RuleScopeResolver(registry).validate_frozen_rules(snapshot, rule_codes)
    return snapshot, rules


def _new_context(
    task_id: str,
    package: Path,
    package_checksum: str | None = None,
    *,
    product: Product | str | None = None,
    package_kind: PackageKind | str = PackageKind.INSPECTION,
    output_root: Path | None = None,
) -> RuleContext:
    base = output_root or settings.output
    task_dir = base / task_id
    return RuleContext(
        task_id=task_id,
        data_dir=task_dir,
        log=_make_log_fn(task_id, base),
        package_path=package,
        package_checksum=package_checksum,
        result_dir=task_dir / "rules",
        prepared_dir=task_dir / "prepared",
        product=product,
        package_kind=package_kind,
    )


def _rebuild_system(
    task_id: str,
    package_name: str,
    customer: dict,
    version: str | None,
    frozen_rule_codes: set[str] | frozenset[str] | None = None,
) -> SystemInspection:
    """单规则重跑后重建 system.json（保持摘要一致）。"""
    plan = Executor(registry, frozen_rule_codes).inspect_plan()
    results = [store.load_rule_result(settings.output, task_id, code) for code in plan]
    results = [result for result in results if result is not None and not registry.get(result.code).hidden]
    for index, result in enumerate(results):
        result.execution_order = index
    summary = store.compute_summary(results)
    return SystemInspection(
        package_file=package_name,
        status=SystemStatus.COMPLETED,
        summary=summary,
        rules=results,
        customer=customer,
        version=version,
    )


def _load_old_task(task_id: str) -> dict | None:
    path = settings.output / task_id / "task.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _publish_terminal(
    task: InspectionTask,
    publish: Callable[[InspectionTask], None] | None,
    *,
    output_root: Path | None = None,
) -> None:
    """终态发布：默认写 ``output/<task_id>/task.json``。

    在线模式由 ``TaskService`` 注入发布器，先收敛 SQLite 记录再写文件，使「文件显示终态」
    成为任务现场的最后一次写入；读方看到终态时报告、收尾日志与数据库记录均已就绪。
    """
    base = output_root or settings.output
    if publish is not None:
        publish(task)
    else:
        # 本地模式与在线模式共用同一发布语义：先提交任务行、规则结果与准备摘要，
        # 再写 task.json；KPI 镜像独立执行，不能阻塞终态可见。
        from app.services import task_db

        task_db.publish_from_scene(task, output=base, include_kpi=False)
        store.save_task_meta(base, task)
        try:
            task_db.publish_kpi_from_scene(task.task_id, output=base)
        except Exception:  # noqa: BLE001 - KPI 镜像失败不得把已完成任务改回失败
            logger.exception("task_kpi_mirror_failed", task_id=task.task_id)
        try:
            from app.services.kpi_v6_terminal_publish import publish_kpi_v6_from_scene

            publish_kpi_v6_from_scene(task, output=base)
        except Exception:  # noqa: BLE001 - v6 发布失败不得把已完成任务改回失败
            logger.exception("task_kpi_v6_publish_failed", task_id=task.task_id)
        # 本地模式与在线模式共用留存清理语义：终态发布后清理超期现场。
        from app.services import retention

        retention.cleanup_safely(output=base, uploads=settings.uploads)


def run_task(
    package: Path,
    *,
    name: str | None = None,
    customer: dict[str, str] | None = None,
    version: str | None = None,
    task_id: str | None = None,
    mode: TaskMode = TaskMode.LOCAL,
    trigger: TaskTrigger = TaskTrigger.CLI,
    created_at: datetime | None = None,
    package_kind: PackageKind = PackageKind.INSPECTION,
    rule_network_element_type: Product | str | None = None,
    publish: Callable[[InspectionTask], None] | None = None,
    output_root: Path | None = None,
    execution_scope: TaskExecutionScope | None = None,
    persist_package_checksum: bool = True,
    persist_inventory_ledger: bool = True,
) -> InspectionTask:
    init_db()
    registry.load_all()
    task_id = task_id or generate_task_id(package.name)
    run_started_at = _now()
    task_created_at = created_at or _now()
    customer_values = customer or {}
    base = output_root or settings.output
    product_value = customer_values.get("product")
    kpi_network_element_type = (
        str(product_value).strip().upper() if (package_kind == PackageKind.INSPECTION and product_value) else None
    )
    if package_kind == PackageKind.INSPECTION:
        resolved_rule_network_element_type = kpi_network_element_type
    else:
        resolved_rule_network_element_type = (
            str(getattr(rule_network_element_type, "value", rule_network_element_type)).strip().upper()
            if rule_network_element_type is not None
            else None
        ) or None
    task_db.ensure_task_execution_row(
        task_id=task_id,
        name=name or package.name,
        mode=mode,
        trigger=trigger,
        package_file=package.name,
        customer=customer_values,
        version=version,
        package_kind=package_kind,
        rule_network_element_type=resolved_rule_network_element_type,
        created_at=task_created_at,
    )
    scope = execution_scope or freeze_task_execution_scope(
        task_id=task_id,
        rule_network_element_type=resolved_rule_network_element_type,
        kpi_network_element_type=kpi_network_element_type,
        trigger=trigger.value,
        source="task_service" if mode == TaskMode.ONLINE else "cli",
        now=run_started_at,
        registry_override=registry,
    )
    if scope.rule_snapshot.task_id != task_id:
        raise ValueError("冻结规则范围与任务 ID 不一致")
    store.append_log(
        base,
        task_id,
        "info",
        "任务开始执行",
        package_file=package.name,
        name=name or package.name,
        mode=mode.value,
        trigger=trigger.value,
    )
    ctx = _new_context(
        task_id,
        package,
        product=product_value,
        package_kind=package_kind,
        output_root=base,
    )
    executor = Executor(registry, frozen_rule_codes=scope.rule_codes)
    results = executor.run_all(ctx)
    extract_errors = [
        result
        for code, result in results.items()
        if code.startswith("pkg.extract.") and result.status == RuleStatus.ERROR
    ]
    if extract_errors:
        executor.assign_order(results)
        for result in results.values():
            store.save_rule_result(base, task_id, result)
        summary = store.compute_summary([])
        system = SystemInspection(
            package_file=package.name,
            status=SystemStatus.FAILED,
            summary=summary,
            rules=[],
            customer=customer or {},
            version=version,
        )
        stats = TaskStats(total=0, pass_=0, warn=0, fail=0, error=0, skip=0)
        failed_at = _now()
        task = InspectionTask(
            task_id=task_id,
            name=name or package.name,
            mode=mode,
            status=TaskStatus.FAILED,
            trigger=trigger,
            created_at=task_created_at,
            completed_at=failed_at,
            last_run_at=run_started_at,
            duration_ms=task_db.elapsed_ms(run_started_at, failed_at),
            stats=stats,
            system=system,
            package_kind=package_kind,
        )
        store.save_system(base, task_id, system)
        store.append_log(
            base,
            task_id,
            "error",
            "解压失败，任务失败",
            failed_units=[result.code for result in extract_errors],
        )
        TASKS_TOTAL.labels(result="failed", mode=mode.value).inc()
        print(f"\n任务 {task_id} 失败：解压失败 | 日志: {base / task_id / 'execution.log'}")
        _publish_terminal(task, publish, output_root=base)
        # 首次接收的 checksum 是恢复现场与冲突判定的唯一依据，失败任务同样必须落库。
        if persist_package_checksum:
            task_db.set_package_checksum(task_id, sha256_file(package))
        return task
    executor.assign_order(results)
    ordered = [results[code] for code in executor.plan() if code in results]
    for result in ordered:
        store.save_rule_result(base, task_id, result)
    visible = [result for result in ordered if not registry.get(result.code).hidden]
    summary = store.compute_summary(visible)
    checksum = sha256_file(package)
    system = SystemInspection(
        package_file=package.name,
        package_checksum=checksum,
        status=SystemStatus.COMPLETED,
        summary=summary,
        rules=visible,
        customer=customer or {},
        version=version,
    )
    store.save_system(base, task_id, system)
    stats = TaskStats(
        total=summary.total,
        pass_=summary.pass_,
        warn=summary.warn,
        fail=summary.fail,
        error=summary.error,
        skip=summary.skip,
        systems=1,
    )
    completed_at = _now()
    task = InspectionTask(
        task_id=task_id,
        name=name or package.name,
        mode=mode,
        status=TaskStatus.COMPLETED,
        trigger=trigger,
        created_at=task_created_at,
        completed_at=completed_at,
        last_run_at=run_started_at,
        duration_ms=task_db.elapsed_ms(run_started_at, completed_at),
        stats=stats,
        system=system,
        package_kind=package_kind,
    )
    try:
        customer_values = customer or {}
        province = customer_values.get("province")
        operator = customer_values.get("operator")
        evidence = parse_inventory(
            base / task_id,
            task_id=task_id,
            province=province,
            operator=operator,
            product=customer_values.get("product"),
            package_kind=package_kind,
            completed_at=task.completed_at,
        )
        if persist_inventory_ledger:
            archive_inventory(
                evidence,
                task_id=task_id,
                package_kind=package_kind,
                completed_at=task.completed_at or _now(),
                output_root=base,
            )
        else:
            write_inventory_evidence(evidence, task_id=task_id, output_root=base)
        task = task.model_copy(update={"inventory": TaskInventory.model_validate(evidence)})
    except Exception:  # noqa: BLE001 - 台账失败不能影响巡检任务
        store.append_log(base, task_id, "error", "设备台账归档失败，任务结果不受影响")
    report = render_report(base, task_id, system, completed_at=task.completed_at)
    TASKS_TOTAL.labels(result="completed", mode=mode.value).inc()
    store.append_log(
        base,
        task_id,
        "info",
        "任务完成",
        stats=task.stats.model_dump(by_alias=True, mode="json"),
        report=str(report),
    )
    completed_summary = store.summary_task(task)
    print(
        f"\n任务 {task_id} 完成：pass={summary.pass_} warn={summary.warn} fail={summary.fail} "
        f"error={summary.error} skip={summary.skip} | 报告: {report} "
        f"| 日志: {base / task_id / 'execution.log'}"
    )
    # 终态发布是任务现场的最后一次写入：读方看到 completed 时，报告、收尾日志与台账均已就绪。
    _publish_terminal(task, publish, output_root=base)
    if persist_package_checksum:
        task_db.set_package_checksum(task_id, checksum)
    return completed_summary


def run_incremental_rebuild(
    rule_codes: list[str],
    *,
    package: Path | None = None,
    task_id: str | None = None,
    package_checksum: str | None = None,
    publish: Callable[[InspectionTask], None] | None = None,
    product: Product | str | None = None,
    package_kind: PackageKind | str | None = None,
    rule_network_element_type: Product | str | None = None,
) -> list[str]:
    """强制重建解压现场后只执行指定普通规则及其私有 prepare。"""
    if not rule_codes:
        raise ValueError("增量重建必须指定至少一条普通规则")
    run_started_at = _now()
    registry.load_all()
    package = package or latest_package()
    task_id = task_id or generate_task_id(package.name)
    existing = _load_old_task(task_id) or {}
    customer = existing.get("system", {}).get("customer") or {}
    task_product = product if product is not None else customer.get("product")
    scope_package_kind = (
        PackageKind(package_kind)
        if package_kind is not None
        else (PackageKind(existing.get("package_kind")) if existing.get("package_kind") else PackageKind.INSPECTION)
    )
    task_rule_network_element_type = (
        rule_network_element_type
        if rule_network_element_type is not None
        else (task_product if scope_package_kind == PackageKind.INSPECTION else None)
    )
    scope, _ = _validate_frozen_rule_scope(
        task_id,
        rule_codes,
        network_element_type=task_rule_network_element_type,
    )
    task_dir = settings.output / task_id

    checksum = package_checksum or sha256_file(package)
    resolved_product, resolved_package_kind = _resolve_task_metadata(
        product,
        package_kind,
        existing=_load_old_task(task_id),
        task_id=task_id,
        require_product_when_new=False,
    )
    ctx = _new_context(
        task_id,
        package,
        checksum,
        product=resolved_product,
        package_kind=resolved_package_kind,
    )
    executor = Executor(registry, frozen_rule_codes=scope.rule_codes)

    # 只删除解压 manifest 和工作分类目录；规则结果、prepared 数据与任务元数据保留。
    extraction_manifest = task_dir / EXTRACT_MANIFEST
    extraction_manifest.unlink(missing_ok=True)
    for category in LEGACY_TARGET_ROOTS:
        shutil.rmtree(task_dir / category, ignore_errors=True)

    extraction = executor.run_rule("pkg.extract.main", ctx)
    store.save_rule_result(settings.output, task_id, extraction)
    for code in rule_codes:
        try:
            old_result = store.load_rule_result(settings.output, task_id, code)
        except (json.JSONDecodeError, OSError, ValidationError):
            old_result = None
        executor.run_rule_with_deps(code, ctx, force_prepare_rebuild=True)
        result = executor.collected[code]
        if old_result is not None:
            result.execution_order = old_result.execution_order
        store.save_rule_result(settings.output, task_id, result)

    version = existing.get("system", {}).get("version")
    system = _rebuild_system(task_id, package.name, customer, version, scope.rule_codes)
    store.save_system(settings.output, task_id, system)
    completed: InspectionTask | None = None
    if existing:
        current_meta = store.load_task_meta(settings.output, task_id)
        base = current_meta or InspectionTask.model_validate(existing)
        completed_at = _now()
        completed = base.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "completed_at": completed_at,
                "last_run_at": run_started_at,
                "duration_ms": task_db.elapsed_ms(run_started_at, completed_at),
                "stats": TaskStats(
                    total=system.summary.total,
                    pass_=system.summary.pass_,
                    warn=system.summary.warn,
                    fail=system.summary.fail,
                    error=system.summary.error,
                    skip=system.summary.skip,
                    systems=1,
                ),
                "system": system,
            }
        )
    report = render_report(settings.output, task_id, system, completed_at=store.now_utc())
    store.append_log(
        settings.output,
        task_id,
        "info",
        "增量重建规则执行完成",
        operation="rebuild",
        mode="incremental",
        rule_codes=rule_codes,
        report=str(report),
    )
    if completed is not None:
        # 终态发布是任务现场的最后一次写入。
        _publish_terminal(completed, publish)
    return rule_codes


def run_single_rule(
    code: str,
    package: Path | None = None,
    task_id: str | None = None,
    package_checksum: str | None = None,
    trigger_retention: bool = True,
    *,
    product: Product | str | None = None,
    package_kind: PackageKind | str | None = None,
    rule_network_element_type: Product | str | None = None,
) -> None:
    run_started_at = _now()
    registry.load_all()
    package = package or latest_package()
    task_id = task_id or generate_task_id(package.name)
    old = _load_old_task(task_id) or {}
    customer = old.get("system", {}).get("customer") or {}
    task_product = product if product is not None else customer.get("product")
    package_kind_value = (
        PackageKind(package_kind)
        if package_kind is not None
        else (PackageKind(old.get("package_kind")) if old.get("package_kind") else PackageKind.INSPECTION)
    )
    task_rule_network_element_type = (
        rule_network_element_type
        if rule_network_element_type is not None
        else (task_product if package_kind_value == PackageKind.INSPECTION else None)
    )
    scope, _ = _validate_frozen_rule_scope(
        task_id,
        [code],
        network_element_type=task_rule_network_element_type,
    )
    task_path = settings.output / task_id / "task.json"
    resolved_product, resolved_package_kind = _resolve_task_metadata(
        product,
        package_kind,
        existing=_load_old_task(task_id),
        task_id=task_id,
        require_product_when_new=False,
    )
    ctx = _new_context(
        task_id,
        package,
        package_checksum,
        product=resolved_product,
        package_kind=resolved_package_kind,
    )
    executor = Executor(registry, frozen_rule_codes=scope.rule_codes)
    if not (settings.output / task_id / EXTRACT_MANIFEST).exists():
        extraction = executor.run_rule("pkg.extract.main", ctx)
        store.save_rule_result(settings.output, task_id, extraction)
    try:
        old_result = store.load_rule_result(settings.output, task_id, code)
    except (json.JSONDecodeError, OSError):
        # 目标历史结果损坏时按缺失处理，立即重跑可自恢复；其他规则不受影响。
        old_result = None
    executor.run_rule(code, ctx)
    for result in executor.collected.values():
        if old_result is not None:
            result.execution_order = old_result.execution_order
        store.save_rule_result(settings.output, task_id, result)
    version = old.get("system", {}).get("version")
    system = _rebuild_system(task_id, package.name, customer, version, scope.rule_codes)
    store.save_system(settings.output, task_id, system)
    if old:
        completed_at = _now()
        old["completed_at"] = completed_at.isoformat()
        old["last_run_at"] = run_started_at.isoformat()
        old["duration_ms"] = task_db.elapsed_ms(run_started_at, completed_at)
        old["stats"] = {
            "total": system.summary.total,
            "pass": system.summary.pass_,
            "warn": system.summary.warn,
            "fail": system.summary.fail,
            "error": system.summary.error,
            "skip": system.summary.skip,
            "systems": 1,
        }
        old["system"] = store.summary_system(system).model_dump(by_alias=True, mode="json")
        task_path = settings.output / task_id / "task.json"
        store.write_json_atomic(task_path, old)
    report = render_report(settings.output, task_id, system, completed_at=store.now_utc())
    result = executor.collected[code]
    print(
        f"规则 {code}: {result.status.value} | {result.summary or ''} | "
        f"耗时 {result.duration_ms}ms | 现场: output/{task_id}/ | 报告: {report}"
    )
    if trigger_retention:
        # 本地单规则重跑同样按留存策略清理；在线模式由发布回调统一触发。
        from app.services import retention

        retention.cleanup_safely(output=settings.output, uploads=settings.uploads)


def explain_match(
    code: str,
    *,
    package: Path | None = None,
    task_id: str | None = None,
    package_checksum: str | None = None,
    product: Product | str | None = None,
    package_kind: PackageKind | str | None = None,
) -> dict:
    """只读输出 v5 分类快照、任务清单和每个 pattern 的命中明细。"""
    registry.load_all()
    rule = registry.get(code)
    if rule.hidden:
        raise ValueError("隐藏解压规则不支持 explain-match")
    if not rule.source_patterns:
        raise ValueError(f"规则 {code} 没有可解释的 source_patterns")
    if task_id is None:
        package = package or latest_package()
        task_id = generate_task_id(package.name)
    task_dir = settings.output / task_id
    existing = _load_old_task(task_id)
    resolved_product, resolved_package_kind = _resolve_task_metadata(
        product,
        package_kind,
        existing=existing,
        task_id=task_id,
        require_product_when_new=False,
    )
    try:
        manifest = read_manifest_v5(task_dir)
    except Exception as exc:  # noqa: BLE001 - 统一转换为稳定诊断错误
        summary = f"分类清单无法读取或解析: {exc}"
        raise _classification_diagnostic_error(summary, exc) from exc
    snapshot = manifest["classification"]["snapshot"]
    if resolved_product is not None and str(resolved_product) != snapshot["product"]:
        raise CliMetadataError(
            "package_product_conflict",
            "同一任务的网元类型与已有分类现场冲突",
            detail={
                "task_id": task_id,
                "existing": snapshot["product"],
                "requested": str(resolved_product),
            },
        )
    if resolved_package_kind.value != snapshot["package_kind"]:
        raise CliMetadataError(
            "package_kind_conflict",
            "同一任务的包类型与已有分类现场冲突",
            detail={
                "task_id": task_id,
                "existing": snapshot["package_kind"],
                "requested": resolved_package_kind.value,
            },
        )
    try:
        catalog = TaskFileCatalog.build(task_dir)
    except Exception as exc:  # noqa: BLE001 - catalog 失败同样按分类门禁失败返回
        summary = f"catalog 构建失败: {exc}"
        raise _classification_diagnostic_error(summary, exc) from exc
    matched = catalog.match(rule.source_patterns)
    pattern_matches = {
        pattern: [path.as_posix() for path in catalog.match([pattern])] for pattern in rule.source_patterns
    }
    category = "logs" if rule.category == RuleCategory.LOG else rule.category.value
    summary = manifest["summary"]
    package_file = package.name if package is not None else None
    if package_file is None and existing is not None:
        package_file = (existing.get("system") or {}).get("package_file")
    return {
        "task_id": task_id,
        "package_file": package_file,
        "package_checksum": package_checksum or manifest["main"]["checksum"],
        "rule": {
            "code": rule.code,
            "name": rule.name,
            "priority": rule.priority.value,
            "rule_version": rule.rule_version,
            "has_prepare": rule.prepare is not None,
        },
        "source_patterns": list(rule.source_patterns),
        "pattern_matches": pattern_matches,
        "matched_files": [path.as_posix() for path in matched],
        "catalog_paths": [path.as_posix() for path in catalog.paths()],
        "manifest": {
            "version": manifest["version"],
            "main": manifest["main"],
            "classification": manifest["classification"],
            "path_limit": manifest["path_limit"],
            "summary": summary,
            "route_counts": dict(summary["by_route"]),
            "category_counts": dict(summary["by_category"]),
            "action_counts": dict(summary["by_action"]),
            "ignored": manifest["ignored"],
            "failures": manifest["failures"],
            "conflicts": manifest["conflicts"],
            "category": category,
            "status_counts": dict(summary["by_status"]),
        },
    }


def _classification_diagnostic_error(summary: str, exc: Exception) -> RuleDependencyError:
    """把任务现场读取失败转换为 CLI 可稳定展示的分类门禁错误。"""
    classification_code = "pkg.extract.classification"
    return RuleDependencyError(
        "classification_error",
        f"解压分类门禁失败，阻断诊断: failed_units=[{classification_code}] | {summary}",
        detail={
            "failed_units": [classification_code],
            "classification": {
                "code": classification_code,
                "name": "分类落位终态校验",
                "category": "classification",
                "status": "error",
                "summary": summary,
                "metadata": {"error": str(exc)},
            },
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="patrolx", description="PatrolX 本地开发模式")
    parser.set_defaults(task_id=None)
    sub = parser.add_subparsers(dest="cmd")
    run_parser = sub.add_parser("run", help="扫描输入目录并运行全部规则（默认 uploads/）")
    run_parser.add_argument("--task-id", default=None, help="固定任务 ID（默认按包名生成 task-<package>）")
    run_parser.add_argument("--product", default=None, help="巡检包网元类型：UMF 或 CSP")
    run_parser.add_argument(
        "--package-kind",
        default=None,
        choices=[kind.value for kind in PackageKind],
        help="任务包类型（默认读取已有任务，否则 inspection）",
    )
    run_one = sub.add_parser("run-one", help="仅重跑指定规则")
    run_one.add_argument("--rule", required=True, help="规则 code")
    run_one.add_argument("--package-dir", default=None, help="输入目录（可选）")
    run_one.add_argument("--task-id", default=None, help="固定任务 ID（默认按包名生成 task-<package>）")
    run_one.add_argument("--product", default=None, help="巡检包网元类型：UMF 或 CSP")
    run_one.add_argument(
        "--package-kind",
        default=None,
        choices=[kind.value for kind in PackageKind],
        help="任务包类型（默认读取已有任务，否则 inspection）",
    )
    explain_match_parser = sub.add_parser(
        "explain-match",
        help="解释规则解压状态与 source_patterns 匹配结果",
    )
    explain_match_parser.add_argument("--rule", required=True, help="规则 code")
    explain_match_parser.add_argument("--package-dir", default=None, help="输入目录（可选）")
    explain_match_parser.add_argument("--task-id", default=None, help="固定任务 ID（默认按包名生成 task-<package>）")
    explain_match_parser.add_argument("--product", default=None, help="巡检包网元类型：UMF 或 CSP")
    explain_match_parser.add_argument(
        "--package-kind",
        default=None,
        choices=[kind.value for kind in PackageKind],
        help="任务包类型（默认读取已有任务，否则 inspection）",
    )
    create_user_parser = sub.add_parser("create-user", help="创建认证用户（不支持在线注册）")
    create_user_parser.add_argument("--username", required=True, help="用户名")
    create_user_parser.add_argument("--password", required=True, help="密码")
    create_user_parser.add_argument("--role", default="viewer", choices=["admin", "viewer"], help="角色（默认 viewer）")
    create_default_admin_parser = sub.add_parser(
        "create-default-admin",
        help="初始化或重置默认管理员密码",
    )
    create_default_admin_parser.add_argument("--username", default="admin", help="管理员用户名（默认 admin）")
    create_default_admin_parser.add_argument("--password", default=None, help="密码；未提供时读取环境变量或交互输入")
    create_default_admin_parser.add_argument(
        "--password-env",
        default="PATROLX_INITIAL_ADMIN_PASSWORD",
        help="密码环境变量名（默认 PATROLX_INITIAL_ADMIN_PASSWORD）",
    )
    args = parser.parse_args(argv)

    if args.cmd == "run-one":
        root = Path(args.package_dir) if args.package_dir else None
        packages = find_packages(root)
        if not packages:
            raise SystemExit("未找到数据包：请将 zip/tar.gz 放入 uploads/ 根目录")
        try:
            for pkg in packages:
                lookup_task_id = args.task_id or generate_task_id(pkg.name)
                product, package_kind = _resolve_task_metadata(
                    args.product,
                    args.package_kind,
                    existing=_load_old_task(lookup_task_id),
                    task_id=lookup_task_id,
                )
                run_single_rule(
                    args.rule,
                    pkg,
                    task_id=args.task_id,
                    product=product,
                    package_kind=package_kind,
                )
        except (CliMetadataError, RuleDependencyError) as exc:
            _print_cli_error(exc)
            return 1
        return 0
    if args.cmd == "explain-match":
        root = Path(args.package_dir) if args.package_dir else None
        packages = find_packages(root)
        try:
            if packages:
                runs = [(pkg, args.task_id or generate_task_id(pkg.name), True) for pkg in packages]
            elif args.task_id and (settings.output / args.task_id / EXTRACT_MANIFEST).exists():
                runs = [(None, args.task_id, False)]
            else:
                raise SystemExit("未找到数据包或任务现场：请提供 zip/tar.gz 或已有 --task-id")
            for pkg, lookup_task_id, require_product_when_new in runs:
                product, package_kind = _resolve_task_metadata(
                    args.product,
                    args.package_kind,
                    existing=_load_old_task(lookup_task_id),
                    task_id=lookup_task_id,
                    require_product_when_new=require_product_when_new,
                )
                report = explain_match(
                    args.rule,
                    package=pkg,
                    task_id=lookup_task_id if pkg is None else args.task_id,
                    product=product,
                    package_kind=package_kind,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2))
        except (CliMetadataError, RuleDependencyError) as exc:
            _print_cli_error(exc)
            return 1
        return 0
    if args.cmd == "create-user":
        init_db()
        try:
            create_user(args.username, args.password, args.role)
        except AuthError as exc:
            print(f"错误 [{exc.code}]: {exc.message}")
            return 1
        print(f"已创建用户 {args.username}（角色：{args.role}）")
        return 0
    if args.cmd == "create-default-admin":
        init_db()
        password = args.password or os.environ.get(args.password_env) or getpass.getpass("管理员密码：")
        try:
            action = ensure_default_admin(args.username, password)
        except AuthError as exc:
            print(f"错误 [{exc.code}]: {exc.message}")
            return 1
        if action == "password_updated":
            print(f"已重置管理员密码 {args.username}")
        else:
            print(f"已创建默认管理员 {args.username}")
        return 0
    packages = find_packages()
    if not packages:
        print("未找到数据包：请将 zip/tar.gz 放入 uploads/ 根目录")
        return 1
    failed = False
    for pkg in packages:
        if args.cmd == "run":
            lookup_task_id = args.task_id or generate_task_id(pkg.name)
            try:
                product, package_kind = _resolve_task_metadata(
                    args.product,
                    args.package_kind,
                    existing=_load_old_task(lookup_task_id),
                    task_id=lookup_task_id,
                    require_product_for_existing=True,
                )
            except CliMetadataError as exc:
                _print_cli_error(exc)
                return 1
            executed = run_task(
                pkg,
                task_id=args.task_id,
                customer={"product": product} if product is not None else {},
                package_kind=package_kind,
            )
        else:
            executed = run_task(pkg, task_id=args.task_id)
        if executed is not None and executed.status == TaskStatus.FAILED:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
