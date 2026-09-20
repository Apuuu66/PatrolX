"""任务内 KPI 按需分类线索服务。

线索只来自任务执行时的快照和规则结果，不使用最新数据库状态重写历史任务。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.inspectors.kpi.catalog import match_longest_prefix, normalize_metric_name
from app.models.schemas import (
    KpiClassificationCluePageV4,
    KpiClassificationClueV4,
    KpiClueStatusV4,
)

MAX_SAMPLE_VALUES = 5


class KpiClassificationClueError(Exception):
    """任务 KPI 分类线索读取错误。"""

    def __init__(self, code: str, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _snapshot_path(task_id: str) -> Path:
    return settings.output / task_id / "kpi" / "kpi_catalog_snapshot.json"


def _load_snapshot(task_id: str) -> dict[str, Any]:
    path = _snapshot_path(task_id)
    if not path.is_file():
        raise KpiClassificationClueError("kpi_snapshot_missing", "任务 KPI 配置快照缺失", 409)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KpiClassificationClueError("kpi_snapshot_invalid", "任务 KPI 配置快照损坏", 500) from exc


def _candidate(metric: dict[str, Any]) -> dict[str, str]:
    return {
        "metric_key": str(metric["key"]),
        "name_zh": str(metric.get("name_zh", "")),
        "name_en": str(metric.get("name_en", "")),
    }


def _alias_index(metrics: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    aliases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        for value in (metric.get("name_zh"), metric.get("name_en"), metric.get("key")):
            if isinstance(value, str) and value:
                aliases.setdefault(normalize_metric_name(value), []).append(metric)
    return aliases


def _unique_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({metric["key"]: metric for metric in metrics}.values())


def list_classification_clues(
    task_id: str,
    *,
    clue_status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> KpiClassificationCluePageV4:
    """解析任务规则结果中的真实 CSV 列，并返回可处理的分类线索。"""
    snapshot = _load_snapshot(task_id)
    base_index = _alias_index(snapshot.get("base_metrics", []))
    effective_index = _alias_index(snapshot.get("metrics", []))
    clue_map: dict[tuple[str, str], KpiClassificationClueV4] = {}
    rules_dir = settings.output / task_id / "rules"
    rule_paths = sorted(rules_dir.glob("kpi.*.json")) if rules_dir.is_dir() else []

    for rule_path in rule_paths:
        try:
            raw = json.loads(rule_path.read_text(encoding="utf-8"))
            metadata = raw.get("metadata", {})
            domain = str(metadata.get("domain", "") or rule_path.stem.removeprefix("kpi."))
            rule_code = f"kpi.{domain}"
            kpi_files = metadata.get("kpi_files", [])
        except (OSError, json.JSONDecodeError, AttributeError):
            # 单个历史规则结果损坏时不阻断其他线索。
            continue
        if not isinstance(kpi_files, list):
            continue

        for kpi_file in kpi_files:
            if not isinstance(kpi_file, dict):
                continue
            source_file = str(kpi_file.get("path", ""))
            records = [record for record in kpi_file.get("records", []) if isinstance(record, dict)]
            for source_name in kpi_file.get("objects", []):
                if not isinstance(source_name, str) or not source_name:
                    continue
                identity = (rule_code, source_name)
                if identity not in clue_map:
                    normalized = normalize_metric_name(source_name)
                    base_matches = _unique_metrics(match_longest_prefix(normalized, base_index) or [])
                    effective_matches = _unique_metrics(match_longest_prefix(normalized, effective_index) or [])
                    matched = base_matches[0] if len(base_matches) == 1 else None
                    if len(base_matches) > 1:
                        status = KpiClueStatusV4.AMBIGUOUS
                    elif matched is None:
                        status = KpiClueStatusV4.UNREGISTERED
                    elif effective_matches:
                        status = KpiClueStatusV4.CLASSIFIED
                    else:
                        status = KpiClueStatusV4.UNCLASSIFIED
                    clue_map[identity] = KpiClassificationClueV4(
                        source_name=source_name,
                        metric_key=str(matched["key"]) if matched else None,
                        candidates=[
                            _candidate(metric) for metric in sorted(base_matches, key=lambda item: item["key"])
                        ],
                        clue_status=status,
                        rule_code=rule_code,
                        domain=domain,
                        record_count=0,
                    )
                clue = clue_map[identity]
                if source_file and source_file not in clue.source_files:
                    clue.source_files.append(source_file)
                for record in records:
                    values = record.get("values", {})
                    if not isinstance(values, dict) or source_name not in values:
                        continue
                    clue.record_count += 1
                    if len(clue.sample_values) < MAX_SAMPLE_VALUES:
                        clue.sample_values.append(values[source_name])
                if len(base_matches) > 1:
                    clue.resolution_note = "匹配到多个基础指标，请先人工确认唯一指标"
                elif clue.clue_status == KpiClueStatusV4.UNCLASSIFIED:
                    clue.resolution_note = "基础指标已登记，但任务快照中尚未分类"
                elif clue.clue_status == KpiClueStatusV4.CLASSIFIED:
                    clue.resolution_note = "已分类；如刚变更配置，请手动重跑受影响规则"
                elif clue.clue_status == KpiClueStatusV4.UNREGISTERED:
                    clue.resolution_note = "未匹配到基础资源，请先离线导入基础指标"

    all_items = list(clue_map.values())
    summary = dict(Counter(item.clue_status for item in all_items))
    items = all_items
    if clue_status:
        items = [item for item in items if item.clue_status == clue_status]
    if search:
        needle = search.casefold()
        items = [
            item
            for item in items
            if needle in item.source_name.casefold()
            or needle in (item.metric_key or "").casefold()
            or any(
                needle in candidate["name_zh"].casefold() or needle in candidate["name_en"].casefold()
                for candidate in item.candidates
            )
        ]
    items.sort(key=lambda item: (item.rule_code, item.source_name))
    total = len(items)
    start = (page - 1) * page_size
    return KpiClassificationCluePageV4(
        items=items[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
        summary=summary,
    )
