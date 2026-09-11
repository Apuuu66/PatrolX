"""log.filter（P0）：日志先过滤再分析——按服务/节点规范化并裁剪日志。"""

import sys
from pathlib import Path

# 支持 PyCharm 直接运行单规则文件
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "FATAL": 50, "CRITICAL": 50}
MIN_LEVEL = 30  # 默认保留 WARN 及以上
STACK_LEVEL = "STACK"
LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?)\s+"
    r"(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+(?P<message>.*)$"
)


def _is_log_file(path: Path) -> bool:
    lower = path.name.lower()
    return lower.endswith(".log") or lower.endswith(".log.gz")


def _file_service_name(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".log.gz"):
        return path.name[:-7]
    if lower.endswith(".log"):
        return path.name[:-4]
    return path.stem


def _service_node_of(logs_dir: Path, path: Path) -> tuple[str, str]:
    parts = list(path.relative_to(logs_dir).parts[:-1])
    if parts and re.match(r"(?i)^servicelog[_-]", parts[0]):
        parts = parts[1:]
    parts = [part for part in parts if part.lower() not in {"log", "logs"}]
    if not parts:
        return _file_service_name(path), ""
    return parts[0], "/".join(parts[1:])


def _read_lines(path: Path):
    if path.name.lower().endswith(".log.gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh
    else:
        with path.open("rt", encoding="utf-8", errors="replace") as fh:
            yield from fh


@dataclass(slots=True)
class ParsedLine:
    timestamp: str | None
    level: str | None
    message: str


def _parse_line(raw: str) -> ParsedLine:
    match = LOG_LINE_RE.match(raw.rstrip("\r\n"))
    if not match:
        return ParsedLine(None, None, raw.rstrip("\r\n"))
    return ParsedLine(match.group("timestamp"), match.group("level"), match.group("message"))


def _process_file(ctx: RuleContext, logs_dir: Path, path: Path, out_log, out_jsonl) -> tuple[str, str, dict]:
    service, node = _service_node_of(logs_dir, path)
    source_file = str(path.relative_to(ctx.data_dir))
    records: list[dict] = []
    total = 0
    in_stack = False

    for line_no, raw in enumerate(_read_lines(path), start=1):
        total += 1
        parsed = _parse_line(raw)
        if parsed.level:
            in_stack = LEVELS[parsed.level] >= 40
            if LEVELS[parsed.level] < MIN_LEVEL:
                continue
            record = {
                "service": service,
                "node": node,
                "source_file": source_file,
                "line_no": line_no,
                "timestamp": parsed.timestamp,
                "level": parsed.level,
                "message": raw.rstrip("\r\n"),
            }
        elif in_stack and raw.strip():
            record = {
                "service": service,
                "node": node,
                "source_file": source_file,
                "line_no": line_no,
                "timestamp": None,
                "level": STACK_LEVEL,
                "message": raw.rstrip("\r\n"),
            }
        else:
            in_stack = False
            continue

        records.append(record)
        out_jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
        out_log.write(record["message"] + "\n")

    counts = Counter(record["level"] for record in records)
    return (
        service,
        node,
        {
            "files": [
                {
                    "service": service,
                    "node": node,
                    "source_file": source_file,
                    "total_lines": total,
                    "kept_lines": len(records),
                }
            ],
            "total_lines": total,
            "kept_lines": len(records),
            "levels": dict(counts),
            "error_count": counts["ERROR"] + counts["FATAL"] + counts["CRITICAL"],
            "warn_count": counts["WARN"] + counts["WARNING"],
        },
    )


def _merge_service(target: dict, source: dict, node: str) -> None:
    target.setdefault("nodes", {})
    target["nodes"][node] = target["nodes"].get(node, 0) + source["kept_lines"]
    target.setdefault("files", []).extend(source["files"])
    for key in ("total_lines", "kept_lines", "error_count", "warn_count"):
        target[key] = target.get(key, 0) + source[key]
    target.setdefault("levels", {})
    for level, count in source["levels"].items():
        target["levels"][level] = target["levels"].get(level, 0) + count


inspector = Inspector(
    code="log.filter",
    name="日志过滤",
    category=RuleCategory.LOG,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="2.0.0",
    description="扫描 *.log 与 *.log.gz，识别 ServiceLog 服务/节点结构，保留 WARN 及以上与错误堆栈，产出过滤后数据集",
    recommendation="无日志类文件时跳过分析类规则",
    inputs=["pkg.extract.log.ready"],
    outputs_artifacts=["log.filter.artifacts.filtered_logs"],
    params=[{"key": "min_level", "label": "保留的最低日志级别", "default": "WARN"}],
)


def _run(ctx: RuleContext) -> object:
    logs_dir = ctx.data_dir / RuleCategory.LOG.value
    files = [path for path in sorted(logs_dir.rglob("*")) if path.is_file() and _is_log_file(path)]
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现日志类文件",
            skip_reason="未发现日志类文件",
        )

    out_root = ctx.rule_artifact_path(inspector.code, inspector.outputs_artifacts[0])
    out_root.mkdir(parents=True, exist_ok=True)
    services: dict[str, dict] = {}
    total_lines = kept_lines = 0

    with (
        (out_root / "filtered.log").open("w", encoding="utf-8") as out_log,
        (out_root / "filtered.jsonl").open("w", encoding="utf-8") as out_jsonl,
    ):
        for path in files:
            try:
                service, node, result = _process_file(ctx, logs_dir, path, out_log, out_jsonl)
            except (OSError, gzip.BadGzipFile) as exc:
                ctx.log("warn", "日志文件读取失败", source_file=str(path.relative_to(ctx.data_dir)), error=str(exc))
                continue
            _merge_service(services.setdefault(service, {}), result, node)
            total_lines += result["total_lines"]
            kept_lines += result["kept_lines"]

    index = {
        "files": [str(path.relative_to(ctx.data_dir)) for path in files],
        "services": services,
        "total_lines": total_lines,
        "kept_lines": kept_lines,
        "levels": {
            level: sum(service["levels"].get(level, 0) for service in services.values())
            for level in sorted({key for service in services.values() for key in service["levels"]})
        },
        "error_count": sum(service["error_count"] for service in services.values()),
        "warn_count": sum(service["warn_count"] for service in services.values()),
    }
    (out_root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    processed_files = index["files"]
    ctx.log("info", "日志过滤完成", files=processed_files, file_count=len(files), kept=kept_lines, total=total_lines)
    return make_result(
        inspector,
        status=RuleStatus.PASS,
        summary=f"日志过滤完成：{len(services)} 个服务，{len(files)} 个文件，保留 {kept_lines}/{total_lines} 行",
        metadata={
            "files": len(files),
            "service_count": len(services),
            "kept_lines": kept_lines,
            "total_lines": total_lines,
            "processed_files": processed_files,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
