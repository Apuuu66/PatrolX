"""离线生成 Git 权威 KPI 目录 JSON 的命令行工具。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.inspectors.kpi.catalog import KpiCatalogError, load_kpi_catalog

EXPECTED_HEADER = ["资源id", "中文描述", "英文描述"]


class KpiCatalogGeneratorError(Exception):
    """资源 CSV 或规则引用校验失败。"""


def _read_resource_csv(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        file_bytes = path.read_bytes()
        text = file_bytes.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise KpiCatalogGeneratorError(f"资源 CSV 读取或解码失败: {exc}") from exc
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration as exc:
        raise KpiCatalogGeneratorError("资源 CSV 不能为空") from exc
    if header != EXPECTED_HEADER:
        raise KpiCatalogGeneratorError("资源 CSV 表头必须是 资源id,中文描述,英文描述")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for line_number, row in enumerate(reader, start=2):
        if len(row) != 3:
            raise KpiCatalogGeneratorError(f"第 {line_number} 行: 资源 CSV 必须有三列")
        resource_id, name_zh, name_en = (value.strip() for value in row)
        context = f"第 {line_number} 行 {resource_id or '<empty>'}"
        if (
            not resource_id.startswith(("ME_", "UNIT_"))
            or not all(ch.isalnum() or ch == "_" for ch in resource_id[3:])
            or not resource_id[3:]
        ):
            raise KpiCatalogGeneratorError(f"{context}: 资源 ID 必须以 ME_ 或 UNIT_ 开头且仅包含 A-Z/a-z/0-9/_")
        key = resource_id.lower()
        if resource_id in seen_ids or key in seen_keys:
            raise KpiCatalogGeneratorError(f"{context}: 资源 ID 或稳定 key 重复")
        if not name_zh or not name_en:
            raise KpiCatalogGeneratorError(f"{context}: 中文名称和英文名称不能为空")
        seen_ids.add(resource_id)
        seen_keys.add(key)
        rows.append({"resource_id": resource_id, "key": key, "name_zh": name_zh, "name_en": name_en})
    return rows, hashlib.sha256(file_bytes).hexdigest()


def _load_existing_rules(output: Path | None) -> dict[str, Any]:
    if output is None or not output.exists():
        return {
            "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 1000, "max_records": 200000}},
            "metric_rules": [],
            "thresholds": [],
            "capacity_rules": [],
            "display_rules": [],
        }
    try:
        raw = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KpiCatalogGeneratorError(f"既有 KPI Git JSON 读取失败: {exc}") from exc
    rules = raw.get("rules")
    if not isinstance(rules, dict) or not isinstance(rules.get("common"), dict):
        raise KpiCatalogGeneratorError("既有 KPI Git JSON 缺少 rules.common")
    rules.setdefault("metric_rules", [])
    rules.setdefault("thresholds", [])
    rules.setdefault("capacity_rules", [])
    rules.setdefault("display_rules", [])
    return rules


def generate_kpi_catalog(csv_path: Path, output_path: Path) -> None:
    """读取资源 CSV，保留既有规则并原子写出确定性 JSON。"""
    rows, source_hash = _read_resource_csv(csv_path)
    metrics = [row for row in rows if row["resource_id"].startswith("ME_")]
    units = [row for row in rows if row["resource_id"].startswith("UNIT_")]
    metrics.sort(key=lambda row: row["key"])
    units.sort(key=lambda row: row["key"])
    for metric in metrics:
        metric["unit_key"] = None
    payload = {
        "schema_version": 1,
        "source_csv_sha256": source_hash,
        "metrics": metrics,
        "units": units,
        "rules": _load_existing_rules(output_path),
    }
    # 临时文件写入后再用加载器做完整校验，避免非法输入产生部分输出。
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        load_kpi_catalog(temp_path)
        temp_path.replace(output_path)
    except KpiCatalogError as exc:
        temp_path.unlink(missing_ok=True)
        raise KpiCatalogGeneratorError(f"生成结果校验失败: {exc}") from exc
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 KPI Git 权威目录 JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="从资源 CSV 生成")
    generate.add_argument("--csv", required=True)
    generate.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        generate_kpi_catalog(Path(args.csv), Path(args.output))
    except KpiCatalogGeneratorError as exc:
        print(f"错误: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
