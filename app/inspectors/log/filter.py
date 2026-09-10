"""log.filter（P0）：日志先过滤再分析——按级别裁剪，产出过滤后数据集。"""

import sys
from pathlib import Path

# 支持 PyCharm 直接运行单规则文件
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import gzip
import json
from collections import Counter

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "FATAL": 50, "CRITICAL": 50}
MIN_LEVEL = 30  # 默认保留 WARN 及以上
LOGGING_EXT = {".log", ".trace", ".txt"}


def _is_log_file(path: Path) -> bool:
    return path.suffix.lower() in LOGGING_EXT or path.name.lower().endswith(".log.gz")


def _read_text(path: Path) -> str:
    if path.name.lower().endswith(".log.gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8", errors="replace")


inspector = Inspector(
    code="log.filter",
    name="日志过滤",
    category=RuleCategory.LOG,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="1.0.1",
    description="扫描日志类文件，按级别裁剪并规范化，产出过滤后数据集与统计索引",
    recommendation="无日志类文件时跳过分析类规则",
    outputs_artifacts=["log.filter.artifacts.filtered_logs"],
    params=[{"key": "min_level", "label": "保留的最低日志级别", "default": "WARN"}],
)


def _level_of(line: str) -> tuple[str | None, int]:
    for lv in LEVELS:
        if f" {lv} " in line or line.startswith(f"{lv} ") or f"[{lv}]" in line:
            return lv, LEVELS[lv]
    return None, 0


def _run(ctx: RuleContext) -> object:
    logs_dir = ctx.data_dir / RuleCategory.LOG.value
    files = [p for p in sorted(logs_dir.rglob("*")) if p.is_file() and _is_log_file(p)]
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现日志类文件",
            skip_reason="未发现日志类文件",
        )

    out_root = ctx.rule_artifact_path(inspector.code, inspector.outputs_artifacts[0])
    out_root.mkdir(parents=True, exist_ok=True)
    level_counts: Counter[str] = Counter()
    total_lines = 0
    kept_lines = 0
    with (out_root / "filtered.log").open("w", encoding="utf-8") as out:
        for path in files:
            try:
                text = _read_text(path)
            except (OSError, gzip.BadGzipFile):
                continue
            for line in text.splitlines():
                total_lines += 1
                lv, _ = _level_of(line)
                if lv:
                    level_counts[lv] += 1
                if lv and LEVELS[lv] >= MIN_LEVEL:
                    out.write(line + "\n")
                    kept_lines += 1

    index = {
        "files": [str(p.relative_to(ctx.data_dir)) for p in files],
        "total_lines": total_lines,
        "kept_lines": kept_lines,
        "levels": dict(level_counts),
        "error_count": level_counts["ERROR"] + level_counts["FATAL"] + level_counts["CRITICAL"],
        "warn_count": level_counts["WARN"] + level_counts["WARNING"],
    }
    (out_root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    ctx.log("info", "日志过滤完成", files=len(files), kept=kept_lines, total=total_lines)
    return make_result(
        inspector,
        status=RuleStatus.PASS,
        summary=f"日志过滤完成：{len(files)} 个文件，保留 {kept_lines}/{total_lines} 行",
        metadata={"files": len(files), "kept_lines": kept_lines, "total_lines": total_lines},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
