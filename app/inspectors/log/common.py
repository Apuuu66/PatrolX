"""日志分析规则的共享 artifact 读取辅助。"""

import json
from collections.abc import Iterator
from pathlib import Path

from app.services.executor import RuleContext

FILTER_KEY = "log.filter.artifacts.filtered_logs"


def filtered_path(ctx: RuleContext) -> Path | None:
    """返回 filtered.jsonl 路径；依赖产物缺失时返回 None。"""
    artifact = ctx.inputs.get(FILTER_KEY)
    if artifact is None:
        return None
    path = Path(artifact.path) / "filtered.jsonl"
    return path if path.exists() else None


def processed_files(path: Path) -> list[str]:
    """从 log.filter 索引读取全部已扫描的源文件名。"""
    index_path = path.parent / "index.json"
    if not index_path.exists():
        return []
    return list(json.loads(index_path.read_text(encoding="utf-8")).get("files", []))


def log_processed_files(ctx: RuleContext, path: Path, rule_code: str) -> list[str]:
    """读取并打印规则处理过的源文件，便于确认扫描范围。"""
    files = processed_files(path)
    ctx.log(
        "info",
        "日志规则处理文件",
        rule_code=rule_code,
        file_count=len(files),
        files=files,
    )
    return files


def read_records(path: Path) -> Iterator[dict]:
    """流式读取规范化日志记录。"""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)
