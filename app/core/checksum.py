"""统一的 SHA-256 校验和计算。"""

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    """分块读取文件并返回十六进制 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
