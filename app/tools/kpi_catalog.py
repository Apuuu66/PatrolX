"""KPI 资源 CSV 离线导入工具。

该工具只维护 `base/metrics.json` 和 `base/units.json`；规则文件始终由人工维护。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from app.inspectors.kpi.catalog import KpiCatalogError, load_kpi_catalog


class KpiCatalogGeneratorError(Exception):
    """资源 CSV 离线导入错误。"""


EXPECTED_HEADER = ["资源id", "中文描述", "英文描述"]
BASE_FILES = ("base/metrics.json", "base/units.json")
RULE_FILES = (
    "rules/common.json",
    "rules/metric-rules.json",
    "rules/thresholds.json",
    "rules/capacity-rules.json",
    "rules/display-rules.json",
)


def _read_resource_csv(csv_path: Path) -> tuple[list[dict[str, str]], str]:
    """解析并校验资源 CSV；返回稳定排序数据与字节 SHA-256。"""
    try:
        file_bytes = csv_path.read_bytes()
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

    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for line_number, row in enumerate(reader, start=2):
        if len(row) != 3:
            raise KpiCatalogGeneratorError(f"第 {line_number} 行: 资源 CSV 必须有三列")
        resource_id, name_zh, name_en = (value.strip() for value in row)
        context = f"第 {line_number} 行 {resource_id or '<empty>'}"
        suffix = resource_id[3:] if resource_id.startswith(("ME_", "UNIT_")) else ""
        if not suffix or not all(ch.isalnum() or ch == "_" for ch in suffix):
            raise KpiCatalogGeneratorError(f"{context}: 资源 ID 必须以 ME_ 或 UNIT_ 开头且仅包含 A-Z/a-z/0-9/_")
        key = resource_id.lower()
        if resource_id in seen_ids or key in {item["key"] for item in rows}:
            raise KpiCatalogGeneratorError(f"{context}: 资源 ID 或稳定 key 重复")
        if not name_zh or not name_en:
            raise KpiCatalogGeneratorError(f"{context}: 中文名称和英文名称不能为空")
        seen_ids.add(resource_id)
        rows.append({"resource_id": resource_id, "key": key, "name_zh": name_zh, "name_en": name_en})

    rows.sort(key=lambda item: item["key"])
    return rows, hashlib.sha256(file_bytes).hexdigest()


def _render_json(payload: object) -> bytes:
    """生成 UTF-8、LF、缩进 2 和换行结尾的确定性 JSON。"""
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _validate_candidate(data_dir: Path, candidate_files: dict[str, bytes]) -> None:
    """在临时目录中聚合校验候选基础文件和既有规则文件。"""
    try:
        data_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise KpiCatalogGeneratorError(f"KPI 拆分配置目录已存在: {data_dir}") from exc
    try:
        for relative, content in candidate_files.items():
            path = data_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        load_kpi_catalog(data_dir)
    except (KpiCatalogError, OSError) as exc:
        raise KpiCatalogGeneratorError(f"生成结果校验失败: {exc}") from exc
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def generate_kpi_catalog(csv_path: Path, data_dir: Path) -> None:
    """从资源 CSV 完整替换基础指标和预留单位，且不改写规则文件。"""
    rows, source_hash = _read_resource_csv(csv_path)
    metrics = [dict(item, unit_key=None) for item in rows if item["resource_id"].startswith("ME_")]
    units = [dict(item) for item in rows if item["resource_id"].startswith("UNIT_")]
    candidate_files = {
        "base/metrics.json": _render_json({"schema_version": 1, "source_csv_sha256": source_hash, "metrics": metrics}),
        "base/units.json": _render_json({"schema_version": 1, "units": units}),
    }
    for relative in RULE_FILES:
        source_path = data_dir / relative
        try:
            candidate_files[relative] = source_path.read_bytes()
        except OSError as exc:
            raise KpiCatalogGeneratorError(f"既有规则文件读取失败: {relative}: {exc}") from exc

    staging_root = Path(tempfile.mkdtemp(prefix=".kpi-import.", dir=data_dir.parent))
    candidate_dir = staging_root / "candidate"
    _validate_candidate(candidate_dir, candidate_files)

    previous: dict[str, bytes] = {}
    replaced: list[str] = []
    try:
        for relative in BASE_FILES:
            target = data_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            previous[relative] = target.read_bytes()
            temp_path = target.with_name(f".{target.name}.tmp")
            temp_path.write_bytes(candidate_files[relative])
            temp_path.replace(target)
            replaced.append(relative)
    except (OSError, KpiCatalogError) as exc:
        for relative in reversed(replaced):
            target = data_dir / relative
            temp_path = target.with_name(f".{target.name}.tmp")
            temp_path.write_bytes(previous[relative])
            temp_path.replace(target)
        raise KpiCatalogGeneratorError(f"基础配置写入失败: {exc}") from exc
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线导入 KPI 资源 CSV")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="从资源 CSV 生成基础配置")
    generate.add_argument("--csv", required=True)
    generate.add_argument("--data-dir", required=True)
    args = parser.parse_args(argv)
    try:
        generate_kpi_catalog(Path(args.csv), Path(args.data_dir))
    except KpiCatalogGeneratorError as exc:
        print(f"错误: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
