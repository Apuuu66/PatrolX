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
    max_total_bytes = 3 * 1024 * 1024 * 1024  # 3 GiB
    max_depth = 8

    def __init__(self) -> None:
        self.files = 0
        self.bytes = 0

    def charge_file(self, path: Path) -> int:
        """登记一个已落位普通文件，并按输出大小累计任务字节。"""
        size = path.stat().st_size
        if self.files + 1 > self.max_files:
            raise ArchiveError(
                "任务累计文件数超限",
                "task_file_count_exceeded",
                count=self.files + 1,
                limit=self.max_files,
            )
        if self.bytes + size > self.max_total_bytes:
            message = (
                f"任务累计解压总量超限：单任务累计解压上限 {format_bytes(self.max_total_bytes)}，"
                "请减少包内容或拆分数据包"
            )
            raise ArchiveError(
                message,
                "total_bytes_exceeded",
                bytes=self.bytes + size,
                limit=self.max_total_bytes,
            )
        self.files += 1
        self.bytes += size
        return size

    def charge_gzip_chunk(self, size: int) -> None:
        """按 gzip 输出块累计任务字节。"""
        self.bytes += size
        if self.bytes > self.max_total_bytes:
            message = (
                f"任务累计解压总量超限：单任务累计解压上限 {format_bytes(self.max_total_bytes)}，"
                "请减少包内容或拆分数据包"
            )
            raise ArchiveError(message, "total_bytes_exceeded", bytes=self.bytes, limit=self.max_total_bytes)
