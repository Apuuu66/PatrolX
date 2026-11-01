"""构建局点设备台账解析测试用的代表样例包。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

LST_ME_FILENAME = "LST ME.txt"
HEADER_TIME_PREFIX = "+++    CSP/*××××××××××××*/     "
HEADER_TIME_SAMPLE = "2025-05-26  14:40:36"
HEADER_TIME_INVALID = "2025-02-30  14:40:36"
HEADER_TIME_FUTURE = "2099-01-01  00:00:00"
TABULAR_COLUMNS = (
    "Domain ID",
    "Subnet ID",
    "ME ID",
    "ME name",
    "ME type",
    "ME version",
    "ME vendor",
    "ME user-defined state",
    "Location name",
    "ME lock status",
    "ME Country(Region) Code",
    "ME Interface ID",
    "ME Language",
    "ME patch version",
    "ME mode",
    "Architecture Type",
)
TABULAR_DEFAULTS = {
    "Domain ID": "1",
    "Subnet ID": "0",
    "ME ID": "0",
    "ME name": "CSP-NE-001",
    "ME type": "CSP",
    "ME version": "27.0.0",
    "ME vendor": "HUAWEI",
    "ME user-defined state": "Normal",
    "Location name": "null",
    "ME lock status": "Unlocked",
    "ME Country(Region) Code": "NULL",
    "ME Interface ID": "CSPEdge27.0.0.13",
    "ME Language": "ENG",
    "ME patch version": "27.0.0.13",
    "ME mode": "All-in-one mode",
    "Architecture Type": "ARM",
}


def header_time_line(value: str) -> str:
    """返回携带执行时间的头部行原文。"""
    return f"{HEADER_TIME_PREFIX}{value}"


def lst_me_content(
    device_name: str = "NJ-AGG-001",
    version: str | None = "V900R016C10SPC200",
    *,
    device_key: str = "NE name",
    version_key: str = "Software version",
    network_element_type: str = "UMF2020",
    type_key: str = "ME type",
    encoding: str = "utf-8",
    header_time: str | None = None,
    header_lines: list[str] | None = None,
) -> bytes:
    """生成键值风格的 LST ME.txt 内容。

    ``header_time`` 为 ``None`` 时不输出执行时间行，输出与既有样例完全一致；
    传入原文（``YYYY-MM-DD  HH:MM:SS``）时在文件顶部写入携带执行时间的头部行。
    """
    lines = [*header_lines] if header_lines else []
    if header_time is not None:
        lines.append(header_time_line(header_time))
    lines.extend([f"{device_key}: {device_name}", f"{type_key}: {network_element_type}"])
    if version is not None:
        lines.append(f"{version_key}: {version}")
    return ("\n".join(lines) + "\n").encode(encoding)


def multi_device_lst_me_content(
    records: list[dict[str, str | None]],
    *,
    encoding: str = "utf-8",
    header_time: str | None = None,
    header_lines: list[str] | None = None,
) -> bytes:
    """生成包含多台设备的 LST ME.txt；None 字段表示该行缺失。

    ``header_time`` / ``header_lines`` 与 :func:`lst_me_content` 同义，默认不输出头部行。
    """
    lines: list[str] = [*header_lines] if header_lines else []
    if header_time is not None:
        lines.append(header_time_line(header_time))
    for record in records:
        if record.get("device_name") is not None:
            lines.append(f"NE name: {record['device_name']}")
        if record.get("network_element_type") is not None:
            lines.append(f"ME type: {record['network_element_type']}")
        if record.get("version") is not None:
            lines.append(f"Software version: {record['version']}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode(encoding)


def tabular_lst_me_content(
    rows: list[dict[str, str]] | None = None,
    *,
    encoding: str = "utf-8",
    header_time: str | None = None,
) -> bytes:
    """生成与真实 ``LST ME`` 导出一致的表头加数据行格式。

    行字段以两个及以上空格分隔；未提供的列使用代表性的固定默认值。
    """
    effective_rows = rows or [
        {"ME name": "CSP-NE-001", "ME type": "CSP", "ME version": "27.0.0", "ME patch version": "27.0.0.13"},
        {"ME name": "UMF-NE-001", "ME type": "UMF", "ME version": "27.0.0", "ME patch version": "27.0.0.16"},
    ]
    lines: list[str] = []
    if header_time is not None:
        lines.append(header_time_line(header_time))
    lines.extend(
        [
            "O&M    #304",
            "%%/*MEID=0*/LST ME:;%%",
            "RETCODE = 0  Operation succeeded",
            "",
            "The result is as follows",
            "------------------------",
            "  ".join(TABULAR_COLUMNS),
            "",
        ]
    )
    for row in effective_rows:
        values = [row.get(column, TABULAR_DEFAULTS[column]) for column in TABULAR_COLUMNS]
        lines.append("  ".join(values))
    lines.extend(["", f"(Number of results = {len(effective_rows)})", "", "---    END"])
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
