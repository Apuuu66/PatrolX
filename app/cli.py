"""本地开发模式 CLI：python main.py 一键离线全流程 / 单规则调试。"""

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.archive import is_archive
from app.core.checksum import sha256_file
from app.core.config import settings
from app.core.metrics import TASKS_TOTAL
from app.inspectors.pkg import EXTRACT_MANIFEST
from app.inspectors.registry import registry
from app.models.db import init_db
from app.models.schemas import (
    InspectionTask,
    RuleStatus,
    SystemInspection,
    SystemStatus,
    TaskMode,
    TaskStats,
    TaskStatus,
    TaskTrigger,
)
from app.services import store
from app.services.auth import AuthError, create_user, ensure_default_admin
from app.services.executor import Executor, RuleContext
from app.services.extraction import WORK_CATEGORIES
from app.services.kpi_catalog import KpiSnapshotError, load_task_kpi_config
from app.services.kpi_resources import classify_resource_metrics
from app.services.report import render_report


def _now() -> datetime:
    return datetime.now(UTC)


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


def _make_log_fn(task_id: str):
    log_path = settings.output / task_id / "execution.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(level: str, message: str, detail: dict | None = None) -> None:
        entry = {"ts": store.now_utc(), "level": level, "message": message, **(detail or {})}
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        suffix = f" {detail}" if detail else ""
        print(f"[{level.upper():5}] {message}{suffix}")

    return log


def _new_context(task_id: str, package: Path, package_checksum: str | None = None) -> RuleContext:
    task_dir = settings.output / task_id
    return RuleContext(
        task_id=task_id,
        data_dir=task_dir,
        log=_make_log_fn(task_id),
        package_path=package,
        package_checksum=package_checksum,
        result_dir=task_dir / "rules",
        prepared_dir=task_dir / "prepared",
    )


def _rebuild_system(
    task_id: str,
    package_name: str,
    customer: dict,
    version: str | None,
) -> SystemInspection:
    """单规则重跑后重建 system.json（保持摘要一致）。"""
    plan = Executor(registry).inspect_plan()
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
) -> InspectionTask:
    registry.load_all()
    task_id = task_id or generate_task_id(package.name)
    store.append_log(
        settings.output,
        task_id,
        "info",
        "任务开始执行",
        package_file=package.name,
        name=name or package.name,
        mode=mode.value,
        trigger=trigger.value,
    )
    ctx = _new_context(task_id, package)
    executor = Executor(registry)
    results = executor.run_all(ctx, after_extract=lambda: load_task_kpi_config(task_id))
    main_result = results.get("pkg.extract.main")
    if main_result is not None and main_result.status == RuleStatus.ERROR:
        store.save_rule_result(settings.output, task_id, main_result)
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
        task = InspectionTask(
            task_id=task_id,
            name=name or package.name,
            mode=mode,
            status=TaskStatus.FAILED,
            trigger=trigger,
            created_at=_now(),
            completed_at=_now(),
            stats=stats,
            system=system,
        )
        store.save_system(settings.output, task_id, system)
        store.save_task_meta(settings.output, task)
        return task
        store.append_log(
            settings.output,
            task_id,
            "error",
            "主包解压失败，任务失败",
            error=main_result.summary,
        )
        TASKS_TOTAL.labels(result="failed", mode=mode.value).inc()
        print(f"\n任务 {task_id} 失败：主包解压失败 | 日志: {settings.output / task_id / 'execution.log'}")
        return task
    executor.assign_order(results)
    ordered = [results[code] for code in executor.plan() if code in results]
    for result in ordered:
        store.save_rule_result(settings.output, task_id, result)
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
    store.save_system(settings.output, task_id, system)
    stats = TaskStats(
        total=summary.total,
        pass_=summary.pass_,
        warn=summary.warn,
        fail=summary.fail,
        error=summary.error,
        skip=summary.skip,
        systems=1,
    )
    task = InspectionTask(
        task_id=task_id,
        name=name or package.name,
        mode=mode,
        status=TaskStatus.COMPLETED,
        trigger=trigger,
        created_at=created_at or _now(),
        completed_at=_now(),
        stats=stats,
        system=system,
    )
    store.save_task_meta(settings.output, task)
    report = render_report(settings.output, task_id, system, completed_at=task.completed_at)
    TASKS_TOTAL.labels(result="completed", mode=mode.value).inc()
    store.append_log(
        settings.output,
        task_id,
        "info",
        "任务完成",
        stats=task.stats.model_dump(by_alias=True, mode="json"),
        report=str(report),
    )
    print(
        f"\n任务 {task_id} 完成：pass={summary.pass_} warn={summary.warn} fail={summary.fail} "
        f"error={summary.error} skip={summary.skip} | 报告: {report} "
        f"| 日志: {settings.output / task_id / 'execution.log'}"
    )
    return task


def run_incremental_rebuild(
    rule_codes: list[str],
    *,
    package: Path | None = None,
    task_id: str | None = None,
    package_checksum: str | None = None,
) -> list[str]:
    """强制重建解压现场后只执行指定普通规则及其私有 prepare。"""
    if not rule_codes:
        raise ValueError("增量重建必须指定至少一条普通规则")
    registry.load_all()
    package = package or latest_package()
    task_id = task_id or generate_task_id(package.name)
    task_dir = settings.output / task_id
    snapshot_path = task_dir / "kpi" / "kpi_catalog_snapshot.json"
    if not snapshot_path.is_file():
        raise KpiSnapshotError(f"任务 KPI 配置快照缺失: {snapshot_path}")
    try:
        snapshot_bytes = snapshot_path.read_bytes()
        json.loads(snapshot_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise KpiSnapshotError(f"任务 KPI 配置快照损坏: {snapshot_path}: {exc}") from exc

    checksum = package_checksum or sha256_file(package)
    ctx = _new_context(task_id, package, checksum)
    executor = Executor(registry)

    # 只删除解压 manifest 和工作分类目录；规则结果、prepared 数据与任务元数据保留。
    extraction_manifest = task_dir / EXTRACT_MANIFEST
    extraction_manifest.unlink(missing_ok=True)
    for category in WORK_CATEGORIES:
        shutil.rmtree(task_dir / category, ignore_errors=True)

    extraction = executor.run_rule("pkg.extract.main", ctx)
    store.save_rule_result(settings.output, task_id, extraction)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(snapshot_bytes)
    load_task_kpi_config(task_id)

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

    old = _load_old_task(task_id)
    customer = (old or {}).get("system", {}).get("customer") or {}
    version = (old or {}).get("system", {}).get("version")
    system = _rebuild_system(task_id, package.name, customer, version)
    store.save_system(settings.output, task_id, system)
    if old is not None:
        current_meta = store.load_task_meta(settings.output, task_id)
        base = current_meta or InspectionTask.model_validate(old)
        completed = base.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "completed_at": _now(),
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
        store.save_task_meta(settings.output, completed)
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
    return rule_codes


def run_single_rule(
    code: str,
    package: Path | None = None,
    task_id: str | None = None,
    package_checksum: str | None = None,
) -> None:
    registry.load_all()
    package = package or latest_package()
    task_id = task_id or generate_task_id(package.name)
    task_path = settings.output / task_id / "task.json"
    snapshot_path = settings.output / task_id / "kpi" / "kpi_catalog_snapshot.json"
    if task_path.exists() and not snapshot_path.exists():
        raise KpiSnapshotError(f"任务 KPI 配置快照缺失: {snapshot_path}")
    ctx = _new_context(task_id, package, package_checksum)
    executor = Executor(registry)
    if not (settings.output / task_id / EXTRACT_MANIFEST).exists():
        extraction = executor.run_rule("pkg.extract.main", ctx)
        store.save_rule_result(settings.output, task_id, extraction)
    load_task_kpi_config(task_id)
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
    old = _load_old_task(task_id) or {}
    customer = old.get("system", {}).get("customer") or {}
    version = old.get("system", {}).get("version")
    system = _rebuild_system(task_id, package.name, customer, version)
    store.save_system(settings.output, task_id, system)
    if old:
        old["completed_at"] = store.now_utc()
        old["stats"] = {
            "total": system.summary.total,
            "pass": system.summary.pass_,
            "warn": system.summary.warn,
            "fail": system.summary.fail,
            "error": system.summary.error,
            "skip": system.summary.skip,
            "systems": 1,
        }
        old["system"] = system.model_dump(by_alias=True, mode="json")
        task_path = settings.output / task_id / "task.json"
        task_tmp = task_path.with_name(f".task.json.{os.getpid()}.tmp")
        task_tmp.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        task_tmp.replace(task_path)
    report = render_report(settings.output, task_id, system, completed_at=store.now_utc())
    result = executor.collected[code]
    print(
        f"规则 {code}: {result.status.value} | {result.summary or ''} | "
        f"耗时 {result.duration_ms}ms | 现场: output/{task_id}/ | 报告: {report}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="patrolx", description="PatrolX 本地开发模式")
    parser.set_defaults(task_id=None)
    sub = parser.add_subparsers(dest="cmd")
    run_parser = sub.add_parser("run", help="扫描输入目录并运行全部规则（默认 uploads/）")
    run_parser.add_argument("--task-id", default=None, help="固定任务 ID（默认按包名生成 task-<package>）")
    run_one = sub.add_parser("run-one", help="仅重跑指定规则")
    run_one.add_argument("--rule", required=True, help="规则 code")
    run_one.add_argument("--package-dir", default=None, help="输入目录（可选）")
    run_one.add_argument("--task-id", default=None, help="固定任务 ID（默认按包名生成 task-<package>）")
    classify_kpi = sub.add_parser("classify-kpi", help="分类 KPI 基础指标")
    classify_kpi.add_argument("--metric-key", required=True, help="KPI 指标稳定 key")
    classify_kpi.add_argument("--domain", required=True, help="业务域：call/api/media/unclassified")
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
        for pkg in packages:
            run_single_rule(args.rule, pkg, task_id=args.task_id)
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
    if args.cmd == "classify-kpi":
        init_db()
        result = classify_resource_metrics([args.metric_key], domain=args.domain, operator="cli")
        print(
            f"已分类 {','.join(result['metric_keys'])} 到 {result['domain']}，修订：{result['classification_version']}"
        )
        return 0

    packages = find_packages()
    if not packages:
        print("未找到数据包：请将 zip/tar.gz 放入 uploads/ 根目录")
        return 1
    for pkg in packages:
        run_task(pkg, task_id=args.task_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
