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


def read_records(path: Path) -> Iterator[dict]:
    """流式读取规范化日志记录。"""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)
