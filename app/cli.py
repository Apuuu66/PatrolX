"""本地开发模式 CLI：python main.py 一键离线全流程 / 单规则调试（PyCharm 运行入口）。"""

import argparse
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from app.core.archive import is_archive
from app.core.config import settings
from app.core.metrics import TASKS_TOTAL
from app.inspectors.registry import registry
from app.models.schemas import (
    InspectionTask,
    SystemInspection,
    SystemStatus,
    TaskMode,
    TaskStats,
    TaskStatus,
    TaskTrigger,
)
from app.services import store
from app.services.artifacts import ArtifactStore
from app.services.executor import Executor, RuleContext
from app.services.report import render_report


def _now() -> datetime:
    return datetime.now(UTC)


def new_task_id() -> str:
    """任务 ID：时间戳前缀（可读、可排序）+ 随机后缀（防并发/同秒碰撞）。"""
    return f"task-{_now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def clean_system_id(package_name: str) -> str:
    """包名去扩展名 + 非法字符清洗（保证目录安全）。"""
    stem = re.sub(r"\.(zip|tar\.gz|tgz|tar)$", "", package_name.lower())
    name = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return name or "system"


def generate_task_id(package_name: str) -> str:
    """统一任务 ID：同一包 → 同一任务 → 同一输出目录（在线/离线一致）。"""
    return f"task-{clean_system_id(package_name)}"


def find_packages(root: Path | None = None) -> list[Path]:
    base = root or Path(os.environ.get("PATROLX_PACKAGE_DIR", settings.uploads))
    base.mkdir(parents=True, exist_ok=True)
    packages = [p for p in sorted(base.iterdir()) if p.is_file() and is_archive(p)]
    if not packages:
        fallback = settings.base_dir / "tests/fixtures/sample/sample.zip"
        if fallback.exists():
            return [fallback]
    return packages


def latest_package() -> Path:
    packages = find_packages()
    if not packages:
        raise SystemExit("未找到数据包：请将 zip/tar.gz 放入 uploads/ 根目录，或设置 PATROLX_PACKAGE_DIR")
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


def _new_context(task_id: str, system_id: str, package: Path) -> RuleContext:
    sys_dir = settings.output / task_id / system_id
    artifacts = ArtifactStore(sys_dir / "artifacts")
    return RuleContext(
        task_id=task_id,
        system_id=system_id,
        data_dir=sys_dir,
        artifacts=artifacts,
        log=_make_log_fn(task_id),
        package_path=package,
        result_dir=sys_dir / "rules",
    )


def _persist(task_id: str, system_id: str, results: dict[str, object]) -> None:
    for _code, result in results.items():
        store.save_rule_result(settings.output, task_id, system_id, result)


def _rebuild_system(
    task_id: str,
    system_id: str,
    package_name: str,
    customer: dict,
    version: str | None,
) -> SystemInspection:
    """单规则重跑后重建 system.json（保持摘要一致）。"""
    plan = Executor(registry).plan()
    codes = [c for c in plan if (settings.output / task_id / system_id / "rules" / f"{c}.json").exists()]
    results = [store.load_rule_result(settings.output, task_id, system_id, c) for c in codes]
    results = [r for r in results if r is not None]
    for index, result in enumerate(results):
        result.execution_order = index
    summary = store.compute_summary(results)
    return SystemInspection(
        system_id=system_id,
        package_file=package_name,
        status=SystemStatus.COMPLETED,
        summary=summary,
        rules=results,
        customer=customer,
        version=version,
    )


def run_task(
    package: Path,
    *,
    name: str | None = None,
    customer: dict[str, str] | None = None,
    version: str | None = None,
    task_id: str | None = None,
    mode: TaskMode = TaskMode.LOCAL,
    trigger: TaskTrigger = TaskTrigger.CLI,
) -> InspectionTask:
    registry.load_all()
    task_id = task_id or generate_task_id(package.name)
    system_id = clean_system_id(package.name)
    store.append_log(
        settings.output,
        task_id,
        "info",
        "任务开始执行",
        package_file=package.name,
        name=name or package.name,
        system_id=system_id,
        mode=mode.value,
        trigger=trigger.value,
    )
    ctx = _new_context(task_id, system_id, package)
    executor = Executor(registry)
    results = executor.run_all(ctx)
    executor.assign_order(results)
    ordered = [results[c] for c in executor.plan() if c in results]
    summary = store.compute_summary(ordered)
    system = SystemInspection(
        system_id=system_id,
        system_name=name or system_id,
        package_file=package.name,
        status=SystemStatus.COMPLETED,
        summary=summary,
        rules=ordered,
        customer=customer or {},
        version=version,
    )
    for r in ordered:
        store.save_rule_result(settings.output, task_id, system_id, r)
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
        created_at=_now(),
        completed_at=_now(),
        stats=stats,
        system=system,
    )
    store.save_task_meta(settings.output, task)
    report = render_report(settings.output, task_id, system)
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
        f"error={summary.error} skip={summary.skip} | 报告: {report}"
    )
    return task


def run_single_rule(
    code: str,
    system_id: str | None = None,
    package: Path | None = None,
    task_id: str | None = None,
) -> None:
    registry.load_all()
    package = package or latest_package()
    task_id = task_id or generate_task_id(package.name)
    sid = system_id or clean_system_id(package.name)
    ctx = _new_context(task_id, sid, package)
    executor = Executor(registry)
    executor.run_rule_with_deps(code, ctx)
    _persist(task_id, sid, executor.collected)
    customer, version = {}, None
    old_task = settings.output / task_id / "task.json"
    if old_task.exists():
        import json

        old = json.loads(old_task.read_text(encoding="utf-8"))
        customer = old.get("system", {}).get("customer") or {}
        version = old.get("system", {}).get("version")
    system = _rebuild_system(task_id, sid, package.name, customer, version)
    store.save_system(settings.output, task_id, system)
    if old_task.exists():
        import json

        old = json.loads(old_task.read_text(encoding="utf-8"))
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
        old_task.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    result = executor.collected[code]
    print(
        f"规则 {code}: {result.status.value} | {result.summary or ''} | "
        f"耗时 {result.duration_ms}ms | 现场: output/{task_id}/{sid}/"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="patrolx", description="PatrolX 本地开发模式")
    # `python main.py` 不带子命令时也必须存在 task_id 默认值。
    parser.set_defaults(task_id=None)
    sub = parser.add_subparsers(dest="cmd")
    run_parser = sub.add_parser("run", help="扫描输入目录并运行全部规则（默认 uploads/）")
    run_parser.add_argument("--task-id", default=None, help="固定任务 ID（默认按包名生成 task-<system_id>）")
    run_one = sub.add_parser("run-one", help="仅重跑指定规则（依赖自动补跑）")
    run_one.add_argument("--rule", required=True, help="规则 code")
    run_one.add_argument("--system-id", default=None, help="限定系统（可选）")
    run_one.add_argument("--package-dir", default=None, help="输入目录（可选）")
    run_one.add_argument("--task-id", default=None, help="固定任务 ID（默认按包名生成 task-<system_id>）")
    args = parser.parse_args(argv)

    if args.cmd == "run-one":
        root = Path(args.package_dir) if args.package_dir else None
        packages = find_packages(root)
        if not packages:
            raise SystemExit("未找到数据包：请将 zip/tar.gz 放入 uploads/ 根目录，或设置 PATROLX_PACKAGE_DIR")
        for pkg in packages:
            run_single_rule(args.rule, args.system_id, pkg, task_id=args.task_id)
        return 0

    packages = find_packages()
    if not packages:
        print("未找到数据包：请将 zip/tar.gz 放入 uploads/ 根目录，或设置 PATROLX_PACKAGE_DIR")
        return 1
    for pkg in packages:
        run_task(pkg, task_id=args.task_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
