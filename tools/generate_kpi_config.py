#!/usr/bin/env python3
"""扫描 KPI CSV，并把未登记指标生成/合并到目录化 KPI 配置。

默认只生成草稿或打印预览；传入 --apply 后才修改 deploy/config/kpi 下的领域配置。
工具只做新增，不修改、不删除既有指标、阈值和容量配置。

用法示例：
    python tools/generate_kpi_config.py --input local_run/sample.zip --output-dir drafts/kpi
    python tools/generate_kpi_config.py --output-dir drafts/kpi
    python tools/generate_kpi_config.py --input local_run/sample.zip --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from app.cli import generate_task_id
from app.core.archive import is_archive
from app.core.config import settings
from app.inspectors.kpi.catalog import load_kpi_catalog
from app.inspectors.kpi.common import match_metric_name, normalize_metric_name
from app.services.kpi_resources import (
    RESOURCE_HEADER,
    import_resource_metrics,
    load_resource_registry,
    parse_resource_rows,
    read_resource_csv,
)

FILE_NAME_RE = re.compile(r"^kpi-(?P<domain>api|media|call)-(?P<period>5|15|30|60)\.csv$", re.IGNORECASE)
HEADER_ALIASES: dict[str, set[str]] = {
    "start": {"测量开始时间", "开始时间", "start_time", "start time"},
    "end": {"测量结束时间", "结束时间", "end_time", "end time"},
    "period": {"周期(分钟)", "测量周期", "period_minutes", "period minutes", "period"},
}
MAX_SAMPLE_VALUES = 5
DEFAULT_RESOURCE_DIR = Path("local_run/resource_metrics")

USAGE_EXAMPLES = """\
用法示例：
  python tools/generate_kpi_config.py --input local_run/sample.zip --output-dir drafts/kpi

  python tools/generate_kpi_config.py --output-dir drafts/kpi

  python tools/generate_kpi_config.py --input local_run/sample.zip --apply
"""

_LATENCY_KEYWORDS = ("响应时延", "响应时间", "时延", "延迟", "耗时")
_CAPACITY_KEYWORDS = ("峰值", "最大", "并发", "在线数", "连接数")
_COUNT_KEYWORDS = ("次数", "数量", "总数", "请求数", "请求成功", "请求失败")
_RATE_KEYWORDS = ("成功率", "失败率", "比例", "占比", "率")

_EN_TERMS: tuple[tuple[str, str], ...] = (
    ("响应时间", "Response Time"),
    ("请求总数", "Request Total Count"),
    ("平均时延", "Average Latency"),
    ("媒体请求", "Media Request"),
    ("媒体成功", "Media Success"),
    ("媒体失败", "Media Failure"),
    ("响应时延", "Response Latency"),
    ("成功率", "Success Rate"),
    ("失败率", "Failure Rate"),
    ("请求成功", "Request Success"),
    ("请求失败", "Request Failure"),
    ("请求次数", "Request Count"),
    ("并发数", "Concurrency"),
    ("最大并发", "Max Concurrency"),
    ("统计峰值", "Stat Peak"),
    ("时延", "Latency"),
    ("延迟", "Delay"),
    ("耗时", "Duration"),
    ("数量", "Count"),
    ("总数", "Total Count"),
    ("次数", "Count"),
    ("成功", "Success"),
    ("失败", "Failure"),
    ("峰值", "Peak"),
    ("最大", "Max"),
    ("在线数", "Online Count"),
    ("连接数", "Connection Count"),
    ("并发", "Concurrency"),
    ("注册", "Registration"),
    ("会话", "Session"),
    ("业务", "Service"),
    ("呼叫", "Call"),
    ("请求", "Request"),
    ("统计", "Stat"),
)


def _read_csv_rows(path: Path) -> tuple[list[list[str]], str]:
    """优先读取 UTF-8；历史导出可能使用 GBK 系编码。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.reader(handle)), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别 CSV 编码: {path}")


def _resource_csv_paths(path: Path) -> list[Path]:
    """解析资源字典输入；文件返回单文件，目录递归收集所有 CSV。"""
    if path.is_file():
        return [path]
    if path.is_dir():
        paths = sorted(path.rglob("*.csv"), key=lambda item: item.as_posix())
        if paths:
            return paths
        raise ValueError(f"资源目录中没有 CSV: {path}")
    raise ValueError(f"资源字典输入不存在: {path}")


def _combine_resource_rows(paths: list[Path]) -> list[list[str]]:
    """合并多个资源 CSV；每个文件都必须使用资源字典表头。"""
    combined: list[list[str]] = []
    for index, path in enumerate(paths):
        rows = read_resource_csv(path)
        if not rows:
            raise ValueError(f"资源 CSV 为空: {path}")
        header = tuple(cell.strip() for cell in rows[0][: len(RESOURCE_HEADER)])
        if header != RESOURCE_HEADER:
            raise ValueError(f"资源 CSV 表头必须为: {','.join(RESOURCE_HEADER)}: {path}")
        combined.extend(rows if index == 0 else rows[1:])
    return combined


def _match_header_columns(row: list[str]) -> dict[str, int] | None:
    """按列名语义识别表头；同一结构字段重复出现时视为非法。"""
    matched: dict[str, int] = {}
    for index, cell in enumerate(row):
        normalized = normalize_metric_name(cell)
        for role, aliases in HEADER_ALIASES.items():
            if normalized not in aliases:
                continue
            if role in matched:
                return None
            matched[role] = index
            break
    return matched if set(matched) == set(HEADER_ALIASES) else None


def _parse_csv_file(path: Path, relative_path: str) -> dict[str, Any]:
    """解析 KPI CSV 元数据、表头和数值样例；表头由列名语义识别。"""
    rows, encoding = _read_csv_rows(path)
    parsed: dict[str, Any] = {
        "path": relative_path,
        "encoding": encoding,
        "metadata": {},
        "objects": [],
        "row_count": 0,
        "numeric_samples": {},
        "numeric_counts": {},
        "errors": [],
    }
    if not rows:
        parsed["errors"].append({"code": "empty_file", "message": "文件为空", "line_number": 1})
        return parsed

    header_index: int | None = None
    header_columns: dict[str, int] = {}
    metadata: dict[str, str] = {}
    for row_index, row in enumerate(rows):
        matched = _match_header_columns(row)
        if matched is not None:
            header_index = row_index
            header_columns = matched
            break
        non_empty = [cell.strip() for cell in row if cell.strip()]
        if len(non_empty) == 1 and any(separator in non_empty[0] for separator in ("：", ":")):
            separator = "：" if "：" in non_empty[0] else ":"
            key, value = non_empty[0].split(separator, 1)
            metadata[key.strip()] = value.strip()

    if header_index is None or not header_columns:
        parsed["errors"].append(
            {
                "code": "invalid_header",
                "message": "缺少有效 KPI 表头，必须能按列名识别开始时间、结束时间和周期",
                "line_number": len(rows),
            }
        )
        return parsed

    parsed["metadata"] = metadata
    header = [cell.strip() for cell in rows[header_index]]
    object_start = max(header_columns.values()) + 1
    objects = header[object_start:]
    parsed["header"] = header
    parsed["header_columns"] = header_columns
    parsed["objects"] = objects
    samples: dict[str, list[float]] = {name: [] for name in objects}
    counts: dict[str, int] = {name: 0 for name in objects}
    for row in rows[header_index + 1 :]:
        if not row or all(not cell.strip() for cell in row):
            continue
        parsed["row_count"] += 1
        for offset, name in enumerate(objects):
            column_index = object_start + offset
            if column_index >= len(row) or not row[column_index].strip():
                continue
            try:
                value = float(row[column_index])
            except ValueError:
                continue
            counts[name] += 1
            if len(samples[name]) < MAX_SAMPLE_VALUES:
                samples[name].append(value)
    parsed["numeric_samples"] = samples
    parsed["numeric_counts"] = counts
    return parsed


def _infer_metric_type(name: str) -> tuple[str, str, float | None, str, str]:
    """按名称做保守类型推断，返回 type/aggregation/quantile/group/unit。"""
    if any(keyword in name for keyword in _RATE_KEYWORDS):
        return "rate", "last", None, "quality", "%"
    if any(keyword in name for keyword in _LATENCY_KEYWORDS):
        return "latency", "percentile", 0.95, "latency", "ms"
    if any(keyword in name for keyword in _CAPACITY_KEYWORDS):
        return "capacity", "max", None, "capacity", "个"
    if any(keyword in name for keyword in _COUNT_KEYWORDS):
        return "count", "sum", None, "traffic", "次"
    return "gauge", "max", None, "other", "值"


def _split_metric_name_unit(name: str) -> tuple[str, str | None]:
    """拆分中文指标名末尾括号中的单位，兼容中英文括号。"""
    for opening, closing in (("（", "）"), ("(", ")")):
        if not name.endswith(closing):
            continue
        index = name.rfind(opening)
        if index <= 0:
            continue
        unit = name[index + 1 : -1].strip()
        if unit:
            return name[:index].strip(), unit
    return name.strip(), None


def _translate_name(name: str) -> str:
    """用内置术语生成英文名；无法完整翻译时保留 TODO 标记。"""
    translated = name
    for zh, en in _EN_TERMS:
        translated = translated.replace(zh, en)
    if any("\u4e00" <= char <= "\u9fff" for char in translated):
        return f"TODO: {name}"
    return translated


def _next_key(domain: str, index: int, used_keys: set[str]) -> str:
    """生成稳定且不冲突的草稿指标 key。"""
    while True:
        key = f"{domain}_metric_{index:03d}"
        index += 1
        if key not in used_keys:
            used_keys.add(key)
            return key


def _candidate_to_metric(candidate: dict[str, Any], key: str, reserved_names: set[str]) -> dict[str, Any]:
    name = str(candidate.get("name_zh") or candidate["source_name"])
    metric_type, aggregation, quantile, group, default_unit = _infer_metric_type(name)
    provided_english_name = candidate.get("english_name")
    english_name = str(provided_english_name).strip() if provided_english_name else _translate_name(name)
    if normalize_metric_name(english_name) in reserved_names:
        english_name = f"TODO: {name}"
    else:
        reserved_names.add(normalize_metric_name(english_name))
    metric: dict[str, Any] = {
        "key": key,
        "name_zh": name,
        "name_en": english_name,
        "metric_type": metric_type,
        "semantic_group": group,
        "display_role": "context",
        "unit": str(candidate.get("unit") or default_unit),
        "source_type": "raw",
        "aggregation": {"kind": aggregation},
    }
    if quantile is not None:
        metric["aggregation"]["quantile"] = quantile
    return metric


def _match_registered_name(
    name: str, candidates_by_name: dict[str, dict[str, Any]], alias_index: dict[str, str]
) -> str | None:
    """按最长前缀匹配已登记名或新增候选名，兼容“指标名 + 单位”。"""
    normalized = normalize_metric_name(name)
    best_key: str | None = None
    best_length = 0
    for candidate_name, normalized_name in [
        (candidate["source_name"], normalize_metric_name(candidate["source_name"]))
        for candidate in candidates_by_name.values()
    ] + list(alias_index.items()):
        if normalized_name and normalized.startswith(normalized_name) and len(normalized_name) > best_length:
            best_key = str(candidate_name) if candidate_name in candidates_by_name else alias_index[str(candidate_name)]
            best_length = len(normalized_name)
    return best_key


def _ratio_formula(
    name: str,
    candidates_by_name: dict[str, dict[str, Any]],
    alias_index: dict[str, str],
) -> dict[str, Any] | None:
    """仅在总数、成功/失败计数明确存在时生成派生公式。"""
    rate_match = re.fullmatch(r"(.*?)(成功率|失败率)", name)
    if not rate_match:
        return None
    base, rate_kind = rate_match.groups()
    numerator_name = f"{base}{'成功次数' if rate_kind == '成功率' else '失败次数'}"
    denominator_name = f"{base}次数"
    success_name = f"{base}成功次数"
    failure_name = f"{base}失败次数"

    def input_key(source_name: str) -> str | None:
        matched = _match_registered_name(source_name, candidates_by_name, alias_index)
        if matched is None:
            return None
        candidate = candidates_by_name.get(matched)
        if candidate is not None:
            return str(candidate["key"])
        return alias_index.get(normalize_metric_name(matched))

    numerator = input_key(numerator_name)
    denominator = input_key(denominator_name)
    if numerator is None or denominator is None:
        return None

    fallback_inputs: list[str] = []
    for fallback_name in (success_name, failure_name):
        key = input_key(fallback_name)
        if key is not None and key not in fallback_inputs:
            fallback_inputs.append(key)
    formula: dict[str, Any] = {
        "kind": "ratio",
        "numerator": numerator,
        "denominator": denominator,
        "scale": 100,
    }
    if fallback_inputs:
        formula["denominator_fallback"] = {"kind": "sum", "inputs": fallback_inputs}
    return formula


def _build_domain_config(domain: str, domain_report: dict[str, Any], alias_index: dict[str, str]) -> dict[str, Any]:
    """把扫描报告转换成可加载的领域配置草稿。"""
    used_keys = set(alias_index.values())
    reserved_names = set(alias_index)
    candidates_by_name: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(domain_report["metrics"], start=1):
        resource_key = candidate.get("resource_key")
        if (
            isinstance(resource_key, str)
            and re.fullmatch(r"[a-z][a-z0-9_]*", resource_key)
            and resource_key not in used_keys
        ):
            candidate["key"] = resource_key
            used_keys.add(resource_key)
        else:
            candidate["key"] = _next_key(domain, index, used_keys)
        candidates_by_name[str(candidate["source_name"])] = candidate

    metrics = [
        _candidate_to_metric(candidate, str(candidate["key"]), reserved_names) for candidate in domain_report["metrics"]
    ]
    for metric in metrics:
        formula = _ratio_formula(str(metric["name_zh"]), candidates_by_name, alias_index)
        if formula is None:
            continue
        metric.update(
            {
                "metric_type": "rate",
                "semantic_group": "quality",
                "display_role": "highlight",
                "unit": "%",
                "source_type": "derived",
                "aggregation": {"kind": "ratio_from_inputs"},
                "formula": formula,
            }
        )
    return {
        "domain": domain,
        "metrics": metrics,
        "thresholds": {},
        "capacity_metrics": {},
    }


def scan_resource_csv(
    path: Path,
    *,
    config_dir: Path = Path("deploy/config/kpi"),
) -> dict[str, Any]:
    """解析资源全集 CSV，返回基础指标预览；不写入配置。"""
    paths = _resource_csv_paths(path)
    rows = _combine_resource_rows(paths)
    parsed = parse_resource_rows(rows)
    registry = load_resource_registry(config_dir)
    candidates = parsed["candidates"]
    new_keys = set(candidates) - set(registry.metrics)
    invalid_rows = parsed["invalid_rows"]
    return {
        "mode": "resource",
        "input_path": path.as_posix(),
        "config_dir": config_dir.as_posix(),
        "summary": {
            "csv_files": len(paths),
            "row_count": parsed["row_count"],
            "new_metrics": len(new_keys),
            "updated_metrics": len(candidates) - len(new_keys),
            "skipped_units": parsed["skipped_units"],
            "invalid_rows": len(invalid_rows),
            "missing_registered": len(set(registry.metrics) - set(candidates)),
            "total_metrics": len(candidates),
        },
        "metrics": [metric.to_dict() for metric in candidates.values()],
        "invalid_rows": invalid_rows,
    }


def write_resource_preview(report: dict[str, Any], output_dir: Path) -> Path:
    """把资源基础指标写入独立预览文件；不生成领域草稿。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "resource_metrics.draft.yaml"
    _atomic_write_yaml(
        path,
        {
            "version": 1,
            "revision": 0,
            "metrics": {item["key"]: item for item in report["metrics"]},
        },
    )
    return path


def _print_resource_report(report: dict[str, Any], as_json: bool) -> None:
    """输出资源 CSV 扫描报告。"""
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(
        "资源扫描完成: rows={row_count}, new={new_metrics}, updated={updated_metrics}, "
        "units={skipped_units}, invalid={invalid_rows}".format(**report["summary"])
    )
    for metric in report["metrics"]:
        print(f"  + {metric['resource_id']} {metric['name_zh']} [{metric['metric_type']}]")
    for item in report["invalid_rows"]:
        print(f"  ! line={item['line_number']} {item.get('resource_id', '-')} ({item['reason']})")


def scan_kpi_csv(
    input_dir: Path,
    *,
    config_dir: Path = Path("deploy/config/kpi"),
    domains: set[str] | None = None,
) -> dict[str, Any]:
    """递归扫描 kpi-{domain}-{period}.csv，返回未登记指标草稿报告。"""
    if not input_dir.is_dir():
        raise ValueError(f"KPI 输入目录不存在: {input_dir}")
    config = load_kpi_catalog(config_dir)
    selected_domains = set(domains or config.domains.keys())
    targets: list[tuple[Path, str, str, int]] = []
    for path in sorted(input_dir.rglob("*.csv")):
        match = FILE_NAME_RE.fullmatch(path.name)
        if match is None:
            continue
        domain = match.group("domain").lower()
        if domain in selected_domains:
            targets.append((path, path.relative_to(input_dir).as_posix(), domain, int(match.group("period"))))
    if not targets:
        raise ValueError(f"未找到 KPI CSV 文件: {input_dir}")

    domain_reports: dict[str, dict[str, Any]] = {}
    for domain in sorted({item[2] for item in targets}):
        domain_reports[domain] = {
            "files": [],
            "file_errors": [],
            "row_count": 0,
            "registered_metrics": [],
            "metrics": [],
            "invalid_metrics": [],
        }
        report = domain_reports[domain]
        domain_config = config.domains[domain]
        candidates: dict[str, dict[str, Any]] = {}
        registered: set[str] = set()
        for path, relative_path, target_domain, period in (item for item in targets if item[2] == domain):
            parsed = _parse_csv_file(path, relative_path)
            report["files"].append(
                {
                    "path": relative_path,
                    "domain": target_domain,
                    "period": period,
                    "encoding": parsed["encoding"],
                    "metadata": parsed["metadata"],
                    "row_count": parsed["row_count"],
                }
            )
            report["file_errors"].extend({**error, "path": relative_path} for error in parsed["errors"])
            report["row_count"] += int(parsed["row_count"])
            for name in parsed["objects"]:
                if match_metric_name(name, domain_config):
                    if name not in registered:
                        registered.add(name)
                        report["registered_metrics"].append(name)
                    continue
                candidate = candidates.setdefault(
                    name,
                    {
                        "source_name": name,
                        "source_files": [],
                        "periods": [],
                        "record_count": 0,
                        "sample_values": [],
                    },
                )
                if relative_path not in candidate["source_files"]:
                    candidate["source_files"].append(relative_path)
                if period not in candidate["periods"]:
                    candidate["periods"].append(period)
                values = parsed["numeric_samples"].get(name, [])
                candidate["record_count"] += int(parsed["numeric_counts"].get(name, 0))
                for value in values:
                    if len(candidate["sample_values"]) < MAX_SAMPLE_VALUES:
                        candidate["sample_values"].append(value)

        for name, candidate in candidates.items():
            if not candidate["sample_values"]:
                candidate["reason"] = "no_numeric_sample"
                report["invalid_metrics"].append(candidate)
            else:
                metric_type, aggregation, quantile, semantic_group, unit = _infer_metric_type(name)
                candidate.update(
                    {
                        "metric_type": metric_type,
                        "aggregation": {
                            "kind": aggregation,
                            **({"quantile": quantile} if quantile is not None else {}),
                        },
                        "semantic_group": semantic_group,
                        "unit": unit,
                    }
                )
                report["metrics"].append(candidate)

    return {
        "input_dir": input_dir.as_posix(),
        "config_dir": config_dir.as_posix(),
        "summary": {
            "csv_files": len(targets),
            "domains": sorted(domain_reports),
            "new_metrics": sum(len(item["metrics"]) for item in domain_reports.values()),
            "registered_metrics": sum(len(item["registered_metrics"]) for item in domain_reports.values()),
            "invalid_metrics": sum(len(item["invalid_metrics"]) for item in domain_reports.values()),
        },
        "domains": domain_reports,
    }


def build_drafts(report: dict[str, Any], config: Any) -> dict[str, dict[str, Any]]:
    """构建各领域配置草稿。"""
    drafts: dict[str, dict[str, Any]] = {}
    for domain, domain_report in report["domains"].items():
        if domain_report["metrics"]:
            drafts[domain] = _build_domain_config(domain, domain_report, config.domains[domain].alias_index)
    return drafts


def write_drafts(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    """把草稿写到 output_dir；输出目录不应放在 KPI 配置目录内。"""
    config = load_kpi_catalog(Path(report["config_dir"]))
    drafts = build_drafts(report, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for domain, draft in drafts.items():
        path = output_dir / f"{domain}.draft.yaml"
        path.write_text(yaml.safe_dump(draft, sort_keys=False, allow_unicode=True), encoding="utf-8")
        paths[domain] = path
    return paths


def _atomic_write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        yaml.safe_dump(value, handle, sort_keys=False, allow_unicode=True)
        temporary = Path(handle.name)
    temporary.replace(path)


def apply_report(report: dict[str, Any], config_dir: Path) -> list[Path]:
    """把报告中的新增指标合并到现有领域配置，并做最终加载校验。"""
    config = load_kpi_catalog(config_dir)
    drafts = build_drafts(report, config)
    changed: list[Path] = []
    for domain, draft in drafts.items():
        path = config_dir / f"{domain}.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("metrics"), list):
            raise ValueError(f"KPI 配置格式非法，拒绝合并: {path}")
        existing_keys = {
            str(item["key"]) for item in raw["metrics"] if isinstance(item, dict) and isinstance(item.get("key"), str)
        }
        existing_names = {
            normalize_metric_name(str(value))
            for item in raw["metrics"]
            if isinstance(item, dict)
            for value in (item.get("name_zh"), item.get("name_en"))
            if isinstance(value, str)
        }
        appended = False
        for metric in draft["metrics"]:
            source_name = str(metric["name_zh"])
            if metric["key"] in existing_keys or normalize_metric_name(source_name) in existing_names:
                continue
            raw["metrics"].append(metric)
            appended = True
        if appended:
            _atomic_write_yaml(path, raw)
            changed.append(path)
    load_kpi_catalog(config_dir)
    return changed


def _print_report(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(
        "扫描完成: files={csv_files}, domains={domains}, new={new_metrics}, "
        "registered={registered_metrics}, invalid={invalid_metrics}".format(**report["summary"])
    )
    for domain, item in report["domains"].items():
        print(
            f"\n[{domain}] rows={item['row_count']} new={len(item['metrics'])} "
            f"registered={len(item['registered_metrics'])}"
        )
        for metric in item["metrics"]:
            print(f"  + {metric['source_name']}")
        for metric in item["invalid_metrics"]:
            print(f"  ! {metric['source_name']} ({metric['reason']})")
        for error in item["file_errors"]:
            print(f"  x {error['path']}: {error['message']}")


def resolve_input_dir(path: Path, output_root: Path | None = None) -> Path:
    """解析 KPI 输入；压缩包入参自动定位对应任务的 kpi 解压目录。"""
    if path.is_dir():
        return path
    if path.is_file() and is_archive(path):
        task_dir = (output_root or settings.output) / generate_task_id(path.name)
        input_dir = task_dir / "kpi"
        if not input_dir.is_dir():
            raise ValueError(f"任务 KPI 解压目录不存在: {input_dir}；请先执行 python main.py")
        return input_dir
    raise ValueError(f"KPI 输入不存在或不是支持的数据包: {path}")


def _expand_cli_path(path: Path) -> Path:
    """展开 CLI 路径中的用户目录；Windows/Unix 分隔符交给 pathlib 处理。"""
    return path.expanduser()


def _default_resource_dir() -> Path:
    """返回项目根下的默认资源目录，避免受执行命令时工作目录影响。"""
    return settings.local_run / "resource_metrics"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="扫描 KPI CSV 并生成未登记指标配置",
        epilog=USAGE_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="KPI CSV 输入目录；也可传 local_run/<package>.zip 定位 output/<task_id>/kpi",
    )
    parser.add_argument(
        "--resource-csv",
        type=Path,
        help=f"资源字典 CSV 或目录（资源id,中文描述,英文描述），默认 {DEFAULT_RESOURCE_DIR.as_posix()}/",
    )
    parser.add_argument("--config-dir", type=Path, default=settings.config / "kpi", help="KPI 配置目录")
    parser.add_argument("--output-dir", type=Path, help="草稿输出目录，默认打印预览")
    parser.add_argument("--domain", action="append", choices=("call", "api", "media"), help="只处理指定领域，可重复")
    parser.add_argument("--apply", action="store_true", help="合并新增指标到配置目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)
    if args.resource_csv is not None:
        args.resource_csv = _expand_cli_path(args.resource_csv)
        if args.input is not None:
            parser.error("--input 和 --resource-csv 不能同时使用")
    else:
        if args.input is None:
            args.resource_csv = _default_resource_dir()
            args.resource_csv = _expand_cli_path(args.resource_csv)
            args.resource_csv.mkdir(parents=True, exist_ok=True)
        else:
            args.input = _expand_cli_path(args.input)
    args.config_dir = _expand_cli_path(args.config_dir)
    if args.output_dir is not None:
        args.output_dir = _expand_cli_path(args.output_dir)
    if args.apply and args.output_dir is not None:
        parser.error("--apply 和 --output-dir 不能同时使用")
    try:
        if args.resource_csv is not None:
            report = scan_resource_csv(args.resource_csv, config_dir=args.config_dir)
            if args.apply:
                import_resource_metrics(
                    _combine_resource_rows(_resource_csv_paths(args.resource_csv)),
                    config_dir=args.config_dir,
                )
            elif args.output_dir is not None:
                path = write_resource_preview(report, args.output_dir)
                _print_resource_report(report, args.json)
                print(f"draft: {path.as_posix()}")
                return 0
            _print_resource_report(report, args.json)
            if args.apply:
                print(f"updated: {(args.config_dir / 'resource_metrics.yaml').as_posix()}")
            return 0
        else:
            input_dir = resolve_input_dir(args.input)
            report = scan_kpi_csv(
                input_dir, config_dir=args.config_dir, domains=set(args.domain) if args.domain else None
            )
        if args.apply:
            changed = apply_report(report, args.config_dir)
            _print_report(report, args.json)
            for path in changed:
                print(f"updated: {path.as_posix()}")
        elif args.output_dir is not None:
            paths = write_drafts(report, args.output_dir)
            _print_report(report, args.json)
            for path in paths.values():
                print(f"draft: {path.as_posix()}")
        elif args.json:
            _print_report(report, True)
        else:
            _print_report(report, False)
            drafts = build_drafts(report, load_kpi_catalog(args.config_dir))
            for domain, draft in drafts.items():
                print(f"\n# {domain}.draft.yaml")
                print(yaml.safe_dump(draft, sort_keys=False, allow_unicode=True), end="")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
