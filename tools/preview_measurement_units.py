#!/usr/bin/env python3
"""预览固定目录下的测量单元资源 CSV；只读取和分析，不写数据库。"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.encoding import read_text_with_fallback
from app.services.kpi_measurement_units import resource_kind

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESOURCE_DIR = PROJECT_ROOT / "local_run" / "resource_metrics"
REQUIRED = {"资源id", "中文描述", "英文描述"}


def preview_file(path: str | Path, limit: int = 50) -> dict[str, Any]:
    """解析单个资源 CSV 并返回导入前的分类预览。"""
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


def _csv_files(directory: Path) -> list[Path]:
    """按文件名顺序返回目录顶层 CSV 文件。"""
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".csv"),
        key=lambda path: path.name,
    )


def preview_directory(directory: str | Path = DEFAULT_RESOURCE_DIR, limit: int = 50) -> dict[str, Any]:
    """预览固定目录下全部顶层资源 CSV；单个文件失败不影响其他文件。"""
    resource_dir = Path(directory)
    files: list[dict[str, Any]] = []
    total_rows = 0
    kinds: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    file_count = 0

    if not resource_dir.exists() or not resource_dir.is_dir():
        return {
            "directory": str(resource_dir),
            "valid": False,
            "reason": "目录不存在",
            "file_count": 0,
            "total_rows": 0,
            "kinds": {},
            "statuses": {},
            "files": [],
        }

    for path in _csv_files(resource_dir):
        file_count += 1
        try:
            result = preview_file(path, limit)
        except (OSError, UnicodeError) as exc:
            result = {"file": str(path), "valid": False, "reason": f"读取失败: {exc}", "rows": []}
        files.append(result)
        if not result.get("valid"):
            continue
        total_rows += int(result["total_rows"])
        kinds.update(result["kinds"])
        statuses.update(result["statuses"])

    return {
        "directory": str(resource_dir),
        "valid": True,
        "file_count": file_count,
        "total_rows": total_rows,
        "kinds": dict(kinds),
        "statuses": dict(statuses),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="预览固定目录下的测量单元资源 CSV；不导入数据库")
    parser.add_argument("--dir", default=str(DEFAULT_RESOURCE_DIR), help="资源 CSV 目录（默认 local_run/resource_metrics）")
    parser.add_argument("--limit", type=int, default=50, help="每个文件最多展示的行数（默认 50）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    result = preview_directory(args.dir, args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"目录: {result['directory']}")
        if not result.get("valid"):
            print(f"预览失败: {result.get('reason')}")
            return 1

        print(f"文件数: {result['file_count']}")
        print(f"总行数: {result['total_rows']}")
        print(
            "分类: "
            f"MU={result['kinds'].get('mu', 0)}, "
            f"ME={result['kinds'].get('me', 0)}, "
            f"UNIT={result['kinds'].get('unit', 0)}"
        )
        print(
            "状态: "
            f"可导入={result['statuses'].get('importable', 0)}, "
            f"跳过={result['statuses'].get('unsupported_prefix', 0)}, "
            f"错误={result['statuses'].get('invalid_resource', 0)}"
        )
        print("\n文件明细:")
        for file_result in result["files"]:
            if not file_result.get("valid"):
                print(f"  {file_result['file']}: 失败 - {file_result.get('reason')}")
                continue
            print(
                f"  {file_result['file']}: 行 {file_result['total_rows']}, "
                f"可导入 {file_result['statuses'].get('importable', 0)}, "
                f"编码 {file_result['encoding']}"
            )
            for row in file_result["rows"]:
                print(
                    f"    行 {row['line_number']}: {row['status']:<18} "
                    f"{row['resource_id'] or '-'} | {row['name_zh'] or '-'} | {row['name_en'] or '-'}"
                )
            if file_result["truncated"]:
                print(f"    ... 已截断，仅显示前 {file_result['preview_limit']} 行")

    if not result.get("valid") or any(not item.get("valid") for item in result["files"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
