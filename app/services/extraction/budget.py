"""解压过程日志协议与任务级累计预算。"""

from pathlib import Path
from typing import Protocol

from app.core.archive import ArchiveError, format_bytes


class ExtractionLogger(Protocol):
    """解压过程日志回调；与规则上下文日志签名一致。"""

    def __call__(self, level: str, message: str, **detail: object) -> None: ...


def _log_extract(
    log: ExtractionLogger | None,
    level: str,
    message: str,
    **detail: object,
) -> None:
    """写入解压过程日志；未传入回调时保持静默。"""
    if log is not None:
        log(level, message, **detail)


class ExtractionBudget:
    """任务级累计解压预算；固定限额，避免单个安全包叠加耗尽资源。"""

    max_files = 200_000
    max_total_bytes = 3 * 1024 * 1024 * 1024  # 3GB
    max_depth = 8

    def __init__(self) -> None:
        self.files = 0
        self.bytes = 0

    def charge_file(self, path: Path) -> int:
        self.files += 1
        if self.files > self.max_files:
            raise ArchiveError("任务累计文件数超限")
        size = path.stat().st_size
        self.bytes += size
        if self.bytes > self.max_total_bytes:
            raise ArchiveError(
                f"任务累计解压总量超限：单任务累计解压上限 {format_bytes(self.max_total_bytes)}，"
                "请减少包内容或拆分数据包"
            )
        return size

    def charge_gzip_chunk(self, size: int) -> None:
        self.bytes += size
        if self.bytes > self.max_total_bytes:
            raise ArchiveError(
                f"任务累计解压总量超限：单任务累计解压上限 {format_bytes(self.max_total_bytes)}，"
                "请减少包内容或拆分数据包"
            )
