#!/usr/bin/env python3
"""阶段内并行基准：确定性生成日志大包，对比串行与 4 并行墙钟、峰值内存。

脚本只读取本地生成的数据包，不连接被检系统、不修改原始上传包：

```bash
python bench/parallel_bench.py --generate-only --out /tmp/patrolx-bench
python bench/parallel_bench.py --files 16 --rows 40000 --out /tmp/patrolx-bench
```

输出为 JSON：规则阶段墙钟（PREPARE + INSPECT 阶段之和）、加速比与父子峰值内存；
`--check` 时按 SC-001（`parallel_wall_s ≤ serial_wall_s × 0.5`）返回退出码。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import multiprocessing
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

MESSAGE_POOL = [
    "会话建立完成 session={session} node={node}",
    "周期性心跳正常 sequence={seq}",
    "缓存刷新完成 entries={seq} cost={seq}ms",
    "db connection pool exhausted after {seq} retries",
    "auth failure for user u{seq} from 10.0.0.{seq}",
    "connection timeout to peer 10.1.0.{seq}",
    "sctp link down peer=10.2.0.{seq}",
    "业务处理失败 cause=upstream busy code=E{seq}",
    "sctp reconnect failed peer=10.3.0.{seq}",
    "OutOfMemoryError heap space exhausted at slice {seq}",
]
LEVELS = ["INFO", "INFO", "INFO", "INFO", "WARN", "ERROR", "ERROR"]


def build_package(out_dir: Path, *, files: int, rows: int, seed: int) -> Path:
    """生成确定性的 `logs/**/*.log` 目录并打包为 zip；同名包可重复生成。"""
    data_dir = out_dir / "data"
    shutil.rmtree(data_dir, ignore_errors=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    for index in range(files):
        site = f"site{index % 4:02d}"
        node = f"node{index:02d}"
        target = data_dir / "logs" / site / f"{node}.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            for line_no in range(rows):
                message = rng.choice(MESSAGE_POOL).format(session=f"{line_no:06d}", seq=line_no % 97, node=node)
                level = rng.choice(LEVELS)
                fh.write(f"2026-10-08T10:{line_no % 60:02d}:{line_no % 60:02d}.000Z {level} {message}\n")
                if level == "ERROR" and line_no % 11 == 0:
                    fh.write("  at com.example.Service.handle(Service.java:118)\n")
    name = f"bench-{files}f-{rows}r-{seed}.zip"
    package = out_dir / name
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(data_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(data_dir).as_posix())
    return package


def _log_fn(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(level: str, message: str, detail: dict | None = None) -> None:
        entry = {"ts": time.time(), "level": level, "message": message, **(detail or {})}
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return log


def _process_tree_rss_bytes() -> int:
    """当前进程与直接子进程的 RSS 合计（KB → 字节）；用于采样真实并发峰值内存。"""
    pids = [os.getpid(), *[child.pid for child in multiprocessing.active_children() if child.pid]]
    try:
        completed = subprocess.run(
            ["ps", "-o", "rss=", "-p", ",".join(str(pid) for pid in pids)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:  # pragma: no cover - 无 ps 平台
        return 0
    total_kb = 0
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            total_kb += int(stripped)
    return total_kb * 1024


@contextlib.contextmanager
def _rss_sampler(interval: float = 0.05):
    """后台采样进程树 RSS 峰值，避免用“各进程峰值之和”高估并发内存。"""
    samples: list[int] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(interval):
            samples.append(_process_tree_rss_bytes())

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    samples.append(_process_tree_rss_bytes())
    try:
        yield samples
    finally:
        samples.append(_process_tree_rss_bytes())
        stop.set()
        thread.join(timeout=1.0)


def _stage_entries(log_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not log_path.exists():
        return entries
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        entry = json.loads(raw)
        if entry.get("message") == "stage_parallel_done":
            entries.append(entry)
    return entries


def run_mode(package: Path, run_root: Path, *, mode: str, task_id: str) -> dict[str, Any]:
    """在独立任务目录内跑一次完整巡检，返回规则阶段墙钟与峰值内存。"""
    from app.inspectors.registry import registry
    from app.services.executor import Executor, RuleContext
    from app.services.parallel import ParallelPolicy

    task_dir = run_root / mode / task_id
    shutil.rmtree(task_dir, ignore_errors=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    log_path = task_dir / "execution.log"
    ctx = RuleContext(
        task_id=task_id,
        data_dir=task_dir,
        log=_log_fn(log_path),
        package_path=package,
        result_dir=task_dir / "rules",
        prepared_dir=task_dir / "prepared",
    )
    policy = ParallelPolicy(enabled=mode == "parallel")
    executor = Executor(registry, None, policy=policy)
    started = time.monotonic()
    with _rss_sampler() as samples:
        executor.run_all(ctx)
    total_wall_ms = int((time.monotonic() - started) * 1000)
    aggregate_peak = max(samples, default=0)
    stages = _stage_entries(log_path)
    rule_wall_ms = sum(int(entry["wall_ms"]) for entry in stages if entry.get("stage") in {"PREPARE", "INSPECT"})
    return {
        "mode": mode,
        "rule_wall_ms": rule_wall_ms,
        "rule_wall_s": round(rule_wall_ms / 1000, 3),
        "total_wall_s": round(total_wall_ms / 1000, 3),
        "stages": [
            {
                "stage": entry.get("stage"),
                "mode": entry.get("mode"),
                "reason": entry.get("reason"),
                "workers": entry.get("workers"),
                "pending_units": entry.get("pending_units"),
                "matched_bytes": entry.get("matched_bytes"),
                "wall_ms": entry.get("wall_ms"),
                "slowest_unit_ms": entry.get("slowest_unit_ms"),
                "parent_peak_rss_bytes": entry.get("parent_peak_rss_bytes"),
                "children_peak_rss_bytes": entry.get("children_peak_rss_bytes"),
            }
            for entry in stages
        ],
        "aggregate_peak_rss_bytes": aggregate_peak,
        "stage_parent_peak_rss_bytes": sum(
            int(entry.get("parent_peak_rss_bytes", 0)) for entry in stages if entry.get("stage") == "INSPECT"
        ),
        "stage_children_peak_rss_bytes": sum(int(entry.get("children_peak_rss_bytes", 0)) for entry in stages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="单包巡检阶段内并行基准")
    parser.add_argument("--files", type=int, default=16, help="日志文件数（默认 16）")
    parser.add_argument("--rows", type=int, default=40000, help="单个日志文件行数（默认 40000，约 88MB/16 文件）")
    parser.add_argument("--seed", type=int, default=20261008, help="内容随机种子（默认固定，保证可复现）")
    parser.add_argument("--out", type=Path, default=Path("/tmp/patrolx-bench"), help="基准工作目录")
    parser.add_argument("--generate-only", action="store_true", help="只生成数据包，不执行对比")
    parser.add_argument("--check", action="store_true", help="按 SC-001 校验，未达标时返回退出码 1")
    args = parser.parse_args()

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    package = build_package(out_dir, files=args.files, rows=args.rows, seed=args.seed)
    size_mb = round(package.stat().st_size / 1024 / 1024, 1)
    print(f"generated package: {package} ({size_mb}MB)")
    if args.generate_only:
        return 0

    os.environ.setdefault("PATROLX_OUTPUT_DIR", str(out_dir / "output"))
    os.environ.setdefault("PATROLX_UPLOADS_DIR", str(out_dir / "uploads"))
    os.environ.setdefault("PATROLX_SQLITE_PATH", str(out_dir / "patrolx.db"))
    os.environ.setdefault("PATROLX_CONFIG_DIR", str(REPO_ROOT / "deploy" / "config"))
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from app.inspectors.registry import registry

    registry.load_all()
    run_root = out_dir / "runs"
    serial = run_mode(package, run_root, mode="serial", task_id=f"task-{package.stem}-serial")
    parallel = run_mode(package, run_root, mode="parallel", task_id=f"task-{package.stem}-parallel")
    speedup = round(serial["rule_wall_s"] / parallel["rule_wall_s"], 2) if parallel["rule_wall_s"] else 0.0
    peak_ratio = (
        round(parallel["aggregate_peak_rss_bytes"] / serial["aggregate_peak_rss_bytes"], 2)
        if serial["aggregate_peak_rss_bytes"]
        else 0.0
    )
    report = {
        "package": str(package),
        "package_size_mb": size_mb,
        "files": args.files,
        "rows_per_file": args.rows,
        "seed": args.seed,
        "serial": serial,
        "parallel": parallel,
        "speedup": speedup,
        "peak_rss_ratio": peak_ratio,
        "sc001_pass": parallel["rule_wall_s"] <= serial["rule_wall_s"] * 0.5,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.check and not report["sc001_pass"]:
        print("SC-001 未达标：并行墙钟未达到串行基线的 50%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
