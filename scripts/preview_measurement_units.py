#!/usr/bin/env python3
"""预览测量单元资源 CSV；只读取和分析，不写数据库。"""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.core.encoding import read_text_with_fallback
from app.services.kpi_measurement_units import resource_kind

REQUIRED = {"资源id", "中文描述", "英文描述"}


def preview(path: str | Path, limit: int = 50) -> dict[str, Any]:
    """解析资源 CSV 并返回导入前的分类预览。"""
    csv_path = Path(path)
    raw, encoding = read_text_with_fallback(csv_path)
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        return {"file": str(csv_path), "encoding": encoding, "valid": False, "reason": "缺少表头", "rows": []}

    normalized_header = [name.strip() for name in reader.fieldnames]
    reader.fieldnames = normalized_header
    if not REQUIRED.issubset(set(normalized_header)):
        return {
            "file": str(csv_path),
            "encoding": encoding,
            "valid": False,
            "reason": "表头必须是资源id/中文描述/英文描述",
            "header": normalized_header,
            "rows": [],
        }

    kinds: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for line_number, row in enumerate(reader, start=2):
        resource_id = str(row.get("资源id") or "").strip()
        name_zh = str(row.get("中文描述") or "").strip()
        name_en = str(row.get("英文描述") or "").strip()
        kind = resource_kind(resource_id)
        if kind is None:
            status = "unsupported_prefix"
        elif not name_zh or not name_en:
            status = "invalid_resource"
        else:
            status = "importable"

        if kind:
            kinds[kind] += 1
        statuses[status] += 1
        detail = {
            "line_number": line_number,
            "resource_id": resource_id or None,
            "kind": kind,
            "name_zh": name_zh or None,
            "name_en": name_en or None,
            "status": status,
        }
        if len(rows) < limit:
            rows.append(detail)

    return {
        "file": str(csv_path),
        "encoding": encoding,
        "valid": True,
        "header": normalized_header,
        "total_rows": sum(statuses.values()),
        "kinds": dict(kinds),
        "statuses": dict(statuses),
        "preview_limit": limit,
        "rows": rows,
        "truncated": sum(statuses.values()) > len(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="预览测量单元资源 CSV；不导入数据库")
    parser.add_argument("file", help="资源 CSV 文件路径")
    parser.add_argument("--limit", type=int, default=50, help="最多展示的行数（默认 50）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    try:
        result = preview(args.file, args.limit)
    except (OSError, UnicodeError) as exc:
        print(f"读取失败: {exc}", file=__import__('sys').stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"文件: {result['file']}")
    print(f"编码: {result['encoding']}")
    if not result.get("valid"):
        print(f"预览失败: {result.get('reason')}")
        return 1

    print(f"总行数: {result['total_rows']}")
    print(f"分类: MU={result['kinds'].get('mu', 0)}, ME={result['kinds'].get('me', 0)}, UNIT={result['kinds'].get('unit', 0)}")
    print(f"状态: 可导入={result['statuses'].get('importable', 0)}, 跳过={result['statuses'].get('unsupported_prefix', 0)}, 错误={result['statuses'].get('invalid_resource', 0)}")
    print("\n明细:")
    for row in result["rows"]:
        print(
            f"  行 {row['line_number']}: {row['status']:<18} "
            f"{row['resource_id'] or '-'} | {row['name_zh'] or '-'} | {row['name_en'] or '-'}"
        )
    if result["truncated"]:
        print(f"  ... 已截断，仅显示前 {result['preview_limit']} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
