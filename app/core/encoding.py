"""输入文本解码的共享回退策略。"""

from __future__ import annotations

from pathlib import Path

# utf-8-sig 可同时处理 UTF-8 BOM 和普通 UTF-8；gb18030 是 GB2312/GBK 的超集。
TEXT_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "gb18030")


def decode_text_with_fallback(data: bytes) -> tuple[str, str]:
    """按全局回退顺序解码文本输入，返回内容和实际编码。"""
    last_error: UnicodeDecodeError | None = None
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is None:  # pragma: no cover - TEXT_ENCODINGS 恒非空
        raise ValueError("未配置文本编码")
    raise last_error


def read_text_with_fallback(path: str | Path) -> tuple[str, str]:
    """读取文本文件并返回内容和实际编码。"""
    return decode_text_with_fallback(Path(path).read_bytes())
