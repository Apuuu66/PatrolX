"""构建局点设备台账解析测试用的代表样例包。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

LST_ME_FILENAME = "LST ME.txt"


def lst_me_content(
    device_name: str = "NJ-AGG-001",
    version: str | None = "V900R016C10SPC200",
    *,
    device_key: str = "NE name",
    version_key: str = "Software version",
    encoding: str = "utf-8",
) -> bytes:
    """生成键值风格的 LST ME.txt 内容。"""
    lines = [f"{device_key}: {device_name}"]
    if version is not None:
        lines.append(f"{version_key}: {version}")
    return ("\n".join(lines) + "\n").encode(encoding)


def make_inventory_zip(
    path: Path,
    *,
    content: bytes | None = None,
    member_path: str = f"config/{LST_ME_FILENAME}",
    include_lst_me: bool = True,
) -> Path:
    """创建最小巡检包；默认包含台账来源文件。"""
    payload = content if content is not None else lst_me_content()
    with zipfile.ZipFile(path, "w") as archive:
        if include_lst_me:
            archive.writestr(member_path, payload)
        archive.writestr("config/readme.txt", "inventory fixture\n")
    return path


def make_log_supplement_zip(
    path: Path,
    *,
    content: bytes | None = None,
    include_lst_me: bool = False,
) -> Path:
    """创建显式日志补充包样例；默认不含台账来源文件。"""
    with zipfile.ZipFile(path, "w") as archive:
        if include_lst_me:
            archive.writestr(f"config/{LST_ME_FILENAME}", content or lst_me_content())
        archive.writestr("logs/service.log", "service log\n")
        if content is not None:
            archive.writestr("extra.txt", content)
    return path


def zip_bytes(*, content: bytes | None = None, include_lst_me: bool = True) -> bytes:
    """在内存中构造上传用 zip。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if include_lst_me:
            archive.writestr(f"config/{LST_ME_FILENAME}", content or lst_me_content())
        archive.writestr("config/readme.txt", "inventory fixture\n")
    return buffer.getvalue()
