"""日志规则共享的源文件直读与解析辅助。"""

import gzip
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.services.executor import RuleContext

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "FATAL": 50, "CRITICAL": 50}
LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?)\s+"
    r"(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+(?P<message>.*)$"
)


@dataclass(slots=True)
class ParsedLine:
    timestamp: str | None
    level: str | None
    message: str


def parse_line(raw: str) -> ParsedLine:
    match = LOG_LINE_RE.match(raw.rstrip("\r\n"))
    if not match:
        return ParsedLine(None, None, raw.rstrip("\r\n"))
    return ParsedLine(match.group("timestamp"), match.group("level"), match.group("message"))


def log_files(ctx: RuleContext) -> list[Path]:
    """返回 source_patterns 已匹配的日志文件；测试直调时回退扫描 logs/。"""
    if ctx.files:
        return [ctx.data_dir / path if not path.is_absolute() else path for path in ctx.files]
    root = ctx.data_dir / "logs"
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".log", ".gz"})


def _read_lines(path: Path) -> Iterator[str]:
    if path.name.lower().endswith(".log.gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh
    else:
        with path.open("rt", encoding="utf-8", errors="replace") as fh:
            yield from fh


def read_records(ctx: RuleContext) -> list[dict]:
    """直接读取匹配日志，解析等级、服务、节点并保留任务相对来源。"""
    records: list[dict] = []
    for path in log_files(ctx):
        source_file = path.relative_to(ctx.data_dir).as_posix() if path.is_relative_to(ctx.data_dir) else path.name
        service = path.stem.removesuffix("_history").removesuffix(".log")
        node = ""
        relative_parts = (
            path.relative_to(ctx.data_dir).parts[:-1] if path.is_relative_to(ctx.data_dir) else path.parts[:-1]
        )
        # ServiceLog_* 是子包容器，其后的第一个目录才是业务服务名；
        # 业务服务目录下的 logs/ 之后是节点名。
        layout_parts = list(relative_parts)
        if layout_parts and layout_parts[0].lower() in {"logs", "log"}:
            layout_parts.pop(0)
        if layout_parts and layout_parts[0].lower().startswith("servicelog_"):
            layout_parts.pop(0)
            if layout_parts:
                service = layout_parts.pop(0)
                node = "/".join(part for part in layout_parts if part.lower() not in {"logs", "log"})
        elif layout_parts:
            service = layout_parts[0]
            node = "/".join(part for part in layout_parts[1:] if part.lower() not in {"logs", "log"})
        in_stack = False
        for line_no, raw in enumerate(_read_lines(path), start=1):
            parsed = parse_line(raw)
            if parsed.level:
                level = parsed.level
                in_stack = parsed.level in {"ERROR", "FATAL", "CRITICAL"}
            else:
                if not in_stack:
                    continue
                level = "STACK"
            records.append(
                {
                    "timestamp": parsed.timestamp,
                    "level": level,
                    "message": parsed.message,
                    "service": service,
                    "node": node,
                    "source_file": source_file,
                    "line_no": line_no,
                }
            )
    return records


def service_records(ctx: RuleContext, service: str) -> tuple[list[dict], list[str]]:
    """读取指定服务的源日志记录，并按首次出现顺序返回源文件列表。"""
    all_records = read_records(ctx)
    records = [record for record in all_records if record.get("service") == service]
    source_files: list[str] = []
    for record in records:
        source_file = record.get("source_file")
        if source_file and source_file not in source_files:
            source_files.append(source_file)
    return records, source_files


def log_processed_files(ctx: RuleContext, rule_code: str, files: list[str]) -> list[str]:
    """记录规则实际消费的源文件，便于确认扫描范围。"""
    ctx.log("info", "日志规则处理文件", rule_code=rule_code, file_count=len(files), files=files)
    return files


def log_service_processed_files(ctx: RuleContext, rule_code: str, files: list[str]) -> list[str]:
    return log_processed_files(ctx, rule_code, files)
