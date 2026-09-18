"""KPI 资源指标库：资源 CSV 登记、查询和在线业务域分类。

资源文件是用户提供的离线全集快照；本服务只生成基础指标信息。
业务域归属必须通过在线分类显式确认，不会自动生成阈值、公式或告警。
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.inspectors.kpi.catalog import KpiCatalogError, KpiConfig, load_kpi_catalog, normalize_metric_name

RESOURCE_REGISTRY_FILE = "resource_metrics.yaml"
RESOURCE_AUDIT_FILE = "resource_metrics_audit.jsonl"
RESOURCE_HEADER = ("资源id", "中文描述", "英文描述")
RESOURCE_METRIC_PREFIX = "ME_"
RESOURCE_UNIT_PREFIX = "UNIT_"
RESOURCE_ID_RE = re.compile(r"ME_[A-Za-z0-9_]+")
MAX_RESOURCE_CSV_ROWS = 100_000
VALID_DOMAINS = ("call", "api", "media")
RESOURCE_DOMAINS = ("unclassified", *VALID_DOMAINS)
_METRIC_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ENGLISH_PLACEHOLDERS = {"对应英文", "对应英文名", "待补充", "todo", "tbd", "n/a", "na", "-"}

_LATENCY_KEYWORDS = ("响应时延", "响应时间", "时延", "延迟", "耗时")
_CAPACITY_KEYWORDS = ("峰值", "最大", "并发", "在线数", "连接数")
_COUNT_KEYWORDS = ("次数", "数量", "总数", "请求数", "请求成功", "请求失败")
_RATE_KEYWORDS = ("成功率", "失败率", "比例", "占比", "率")


class KpiResourceError(Exception):
    """KPI 资源指标库操作失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


@dataclass(slots=True)
class ResourceMetric:
    """资源系统登记的基础 KPI 指标。"""

    key: str
    resource_id: str
    name_zh: str
    name_en: str
    metric_type: str
    semantic_group: str
    display_role: str
    unit: str
    source_type: str
    aggregation: dict[str, Any]
    domain: str | None
    imported_at: str
    updated_at: str

    def basic_fields(self) -> dict[str, Any]:
        """返回可写入域配置的基础定义字段。"""
        return {
            "key": self.key,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "metric_type": self.metric_type,
            "semantic_group": self.semantic_group,
            "display_role": self.display_role,
            "unit": self.unit,
            "source_type": self.source_type,
            "aggregation": dict(self.aggregation),
        }

    def to_dict(self) -> dict[str, Any]:
        """转换为 API 输出结构；未分类使用统一筛选值。"""
        return {
            "key": self.key,
            "resource_id": self.resource_id,
            **self.basic_fields(),
            "domain": self.domain or "unclassified",
            "imported_at": self.imported_at,
            "updated_at": self.updated_at,
        }

    def to_storage_dict(self) -> dict[str, Any]:
        """转换为 YAML 存储结构；未分类保持 null。"""
        return {
            **self.to_dict(),
            "domain": self.domain,
        }


@dataclass(slots=True)
class ResourceRegistry:
    """资源指标库文件状态。"""

    revision: int
    metrics: dict[str, ResourceMetric]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "revision": self.revision,
            "metrics": {key: metric.to_storage_dict() for key, metric in self.metrics.items()},
        }


_LOCK = threading.RLock()


def utc_now_text() -> str:
    """生成 UTC ISO-8601 时间文本。"""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _registry_path(config_dir: Path) -> Path:
    return config_dir / RESOURCE_REGISTRY_FILE


def _audit_path(config_dir: Path) -> Path:
    return config_dir / RESOURCE_AUDIT_FILE


def _atomic_write_yaml(path: Path, value: Any) -> None:
    """在同一目录使用临时文件原子替换 YAML。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(value, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def load_resource_registry(config_dir: Path | None = None) -> ResourceRegistry:
    """读取并校验资源指标库；文件不存在时返回空库。"""
    directory = Path(config_dir or "deploy/config/kpi")
    path = _registry_path(directory)
    if not path.exists():
        return ResourceRegistry(revision=0, metrics={})
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise KpiResourceError("invalid_resource_registry", f"资源指标库读取失败: {exc}", 500) from exc
    if not isinstance(raw, dict):
        raise KpiResourceError("invalid_resource_registry", "资源指标库顶层必须是字典", 500)
    revision = raw.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise KpiResourceError("invalid_resource_registry", "资源指标库 revision 非法", 500)
    metrics_raw = raw.get("metrics", {})
    if not isinstance(metrics_raw, dict):
        raise KpiResourceError("invalid_resource_registry", "资源指标库 metrics 必须是字典", 500)

    metrics: dict[str, ResourceMetric] = {}
    for key, value in metrics_raw.items():
        if not isinstance(key, str) or not isinstance(value, dict) or value.get("key") != key:
            raise KpiResourceError("invalid_resource_registry", f"资源指标 key 不一致: {key}", 500)
        missing = {"key", "resource_id", "name_zh", "name_en", "metric_type", "imported_at", "updated_at"} - set(value)
        if missing:
            raise KpiResourceError("invalid_resource_registry", f"资源指标 {key} 缺少字段: {sorted(missing)}", 500)
        domain = value.get("domain")
        if domain is not None and domain not in VALID_DOMAINS:
            raise KpiResourceError("invalid_resource_registry", f"资源指标 {key} domain 非法", 500)
        metrics[key] = ResourceMetric(
            key=key,
            resource_id=str(value["resource_id"]),
            name_zh=str(value["name_zh"]),
            name_en=str(value["name_en"]),
            metric_type=str(value["metric_type"]),
            semantic_group=str(value.get("semantic_group", "other")),
            display_role=str(value.get("display_role", "context")),
            unit=str(value.get("unit", "值")),
            source_type=str(value.get("source_type", "raw")),
            aggregation=dict(value.get("aggregation", {"kind": "max"})),
            domain=domain,
            imported_at=str(value["imported_at"]),
            updated_at=str(value["updated_at"]),
        )
    return ResourceRegistry(revision=revision, metrics=metrics)


def read_resource_csv(path: Path) -> list[list[str]]:
    """读取资源 CSV；优先 UTF-8，兼容历史 GBK 系导出。"""
    path = Path(path)
    if not path.is_file():
        raise KpiResourceError("invalid_resource_csv", f"资源 CSV 不存在: {path}")
    rows: list[list[str]] | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                rows = list(csv.reader(handle))
            break
        except UnicodeDecodeError:
            continue
        except (OSError, csv.Error) as exc:
            raise KpiResourceError("invalid_resource_csv", f"资源 CSV 读取失败: {exc}") from exc
    if rows is None:
        raise KpiResourceError("invalid_resource_csv", "无法识别资源 CSV 编码")
    if len(rows) > MAX_RESOURCE_CSV_ROWS + 1:
        raise KpiResourceError("resource_csv_too_large", f"资源 CSV 行数超过 {MAX_RESOURCE_CSV_ROWS} 上限", 413)
    return rows


def _infer_metric_type(name: str) -> tuple[str, str, float | None, str, str]:
    """按中文语义做基础类型推断；不做业务域推断。"""
    if any(keyword in name for keyword in _RATE_KEYWORDS):
        return "rate", "last", None, "quality", "%"
    if any(keyword in name for keyword in _LATENCY_KEYWORDS):
        return "latency", "percentile", 0.95, "latency", "ms"
    if any(keyword in name for keyword in _CAPACITY_KEYWORDS):
        return "capacity", "max", None, "capacity", "个"
    if any(keyword in name for keyword in _COUNT_KEYWORDS):
        return "count", "sum", None, "traffic", "次"
    return "gauge", "max", None, "other", "值"


def _split_name_unit(name: str) -> tuple[str, str | None, str | None]:
    """拆分中文描述末尾括号中的单位。"""
    for opening, closing in (("（", "）"), ("(", ")")):
        if not name.endswith(closing):
            continue
        index = name.rfind(opening)
        if index <= 0:
            continue
        unit = name[index + 1 : -1].strip()
        if not unit:
            return name.strip(), None, "empty_unit"
        return name[:index].strip(), unit, None
    return name.strip(), None, None


def _english_name(value: str, name_zh: str) -> str:
    normalized = normalize_metric_name(value)
    if not value.strip() or normalized in _ENGLISH_PLACEHOLDERS:
        return f"TODO: {name_zh}"
    return value.strip()


def parse_resource_rows(rows: Sequence[Sequence[str]]) -> dict[str, Any]:
    """解析 CSV 行；全局结构错误直接失败，单行错误进入报告。"""
    if not rows:
        raise KpiResourceError("invalid_resource_csv", "资源 CSV 为空")
    header = tuple(cell.strip() for cell in rows[0][: len(RESOURCE_HEADER)])
    if header != RESOURCE_HEADER:
        raise KpiResourceError(
            "invalid_resource_csv",
            "资源 CSV 表头必须为: " + ",".join(RESOURCE_HEADER),
            detail={"expected": list(RESOURCE_HEADER), "actual": list(header)},
        )

    candidates: dict[str, ResourceMetric] = {}
    invalid_rows: list[dict[str, Any]] = []
    skipped_units = 0
    row_count = 0
    imported_at = utc_now_text()

    for line_number, row in enumerate(rows[1:], start=2):
        if not row or all(not str(cell).strip() for cell in row):
            continue
        row_count += 1
        resource_id = str(row[0]).strip()
        name_zh = str(row[1]).strip() if len(row) > 1 else ""
        english = str(row[2]).strip() if len(row) > 2 else ""

        if not resource_id:
            invalid_rows.append({"line_number": line_number, "reason": "missing_resource_id"})
            continue
        if resource_id.startswith(RESOURCE_UNIT_PREFIX):
            skipped_units += 1
            continue
        if not resource_id.startswith(RESOURCE_METRIC_PREFIX):
            invalid_rows.append(
                {"line_number": line_number, "resource_id": resource_id, "reason": "unsupported_resource_id"}
            )
            continue
        key = resource_id.lower()
        if not RESOURCE_ID_RE.fullmatch(resource_id) or not _METRIC_KEY_RE.fullmatch(key):
            invalid_rows.append(
                {"line_number": line_number, "resource_id": resource_id, "reason": "invalid_resource_id"}
            )
            continue
        if not name_zh:
            invalid_rows.append({"line_number": line_number, "resource_id": resource_id, "reason": "missing_name_zh"})
            continue
        name, unit, unit_error = _split_name_unit(name_zh)
        if unit_error:
            invalid_rows.append({"line_number": line_number, "resource_id": resource_id, "reason": unit_error})
            continue

        metric_type, aggregation, quantile, group, default_unit = _infer_metric_type(name)
        metric = ResourceMetric(
            key=key,
            resource_id=resource_id,
            name_zh=name,
            name_en=_english_name(english, name),
            metric_type=metric_type,
            semantic_group=group,
            display_role="context",
            unit=unit or default_unit,
            source_type="raw",
            aggregation={"kind": aggregation, **({"quantile": quantile} if quantile is not None else {})},
            domain=None,
            imported_at=imported_at,
            updated_at=imported_at,
        )
        existing = candidates.get(key)
        if existing is not None:
            if existing.basic_fields() != metric.basic_fields():
                raise KpiResourceError(
                    "resource_id_conflict",
                    f"资源 ID 重复且内容冲突: {resource_id}",
                    409,
                    detail={"line_number": line_number, "resource_id": resource_id},
                )
            continue
        candidates[key] = metric

    return {
        "candidates": candidates,
        "invalid_rows": invalid_rows,
        "row_count": row_count,
        "skipped_units": skipped_units,
    }


def _append_audit(config_dir: Path, entry: dict[str, Any]) -> None:
    """追加一条 JSON 审计记录。"""
    path = _audit_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def import_resource_metrics(
    rows: Sequence[Sequence[str]],
    *,
    config_dir: Path | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """登记资源 CSV 中的基础指标；所有指标保持未分类。"""
    directory = Path(config_dir or "deploy/config/kpi")
    parsed = parse_resource_rows(rows)
    candidates: dict[str, ResourceMetric] = parsed["candidates"]
    registry_path = _registry_path(directory)
    now = utc_now_text()

    with _LOCK:
        registry = load_resource_registry(directory)
        if expected_revision is not None and registry.revision != expected_revision:
            raise KpiResourceError(
                "resource_revision_conflict",
                "资源指标库已被其他操作更新，请刷新后重试",
                409,
                detail={"expected_revision": expected_revision, "actual_revision": registry.revision},
            )
        before = registry_path.read_bytes() if registry_path.exists() else None
        missing_registered = len(set(registry.metrics) - set(candidates))
        new_keys = set(candidates) - set(registry.metrics)
        try:
            for key, metric in candidates.items():
                current = registry.metrics.get(key)
                if current is None:
                    registry.metrics[key] = metric
                    continue
                current.name_zh = metric.name_zh
                current.name_en = metric.name_en
                current.metric_type = metric.metric_type
                current.semantic_group = metric.semantic_group
                current.display_role = metric.display_role
                current.unit = metric.unit
                current.source_type = metric.source_type
                current.aggregation = metric.aggregation
                current.updated_at = now

            changed = bool(candidates) or not registry_path.exists()
            if changed:
                registry.revision += 1
                _atomic_write_yaml(registry_path, registry.to_dict())
                _append_audit(
                    directory,
                    {
                        "operated_at": now,
                        "operation": "import",
                        "result": "success",
                        "revision": registry.revision,
                        "summary": {
                            "row_count": parsed["row_count"],
                            "new_metrics": len(new_keys),
                            "updated_metrics": len(candidates) - len(new_keys),
                            "skipped_units": parsed["skipped_units"],
                            "invalid_rows": len(parsed["invalid_rows"]),
                            "missing_registered": missing_registered,
                        },
                    },
                )
        except Exception as exc:
            if before is None:
                registry_path.unlink(missing_ok=True)
            else:
                registry_path.write_bytes(before)
            if isinstance(exc, KpiResourceError):
                raise
            raise KpiResourceError("resource_registry_write_failed", f"资源指标库保存失败: {exc}", 500) from exc

    return {
        "revision": registry.revision,
        "summary": {
            "row_count": parsed["row_count"],
            "new_metrics": len(new_keys),
            "updated_metrics": len(candidates) - len(new_keys),
            "skipped_units": parsed["skipped_units"],
            "skipped_rows": 0,
            "invalid_rows": len(parsed["invalid_rows"]),
            "missing_registered": missing_registered,
        },
        "invalid_rows": parsed["invalid_rows"],
    }


def list_resource_metrics(
    *,
    config_dir: Path | None = None,
    search: str | None = None,
    domain: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询资源指标，支持资源 ID/中英文名模糊搜索与业务域筛选。"""
    directory = Path(config_dir or "deploy/config/kpi")
    if domain is not None and domain not in RESOURCE_DOMAINS:
        raise KpiResourceError("bad_request", f"非法资源指标域: {domain}")
    with _LOCK:
        registry = load_resource_registry(directory)

    normalized_search = normalize_metric_name(search or "")
    selected = list(registry.metrics.values())
    if domain is not None:
        expected = None if domain == "unclassified" else domain
        selected = [metric for metric in selected if metric.domain == expected]
    if normalized_search:
        selected = [
            metric
            for metric in selected
            if any(
                normalized_search in normalize_metric_name(value)
                for value in (metric.resource_id, metric.name_zh, metric.name_en)
            )
        ]
    selected.sort(key=lambda metric: (metric.resource_id.casefold(), metric.key))
    total = len(selected)
    start = (page - 1) * page_size
    items = selected[start : start + page_size]
    summary = {name: 0 for name in RESOURCE_DOMAINS}
    for metric in registry.metrics.values():
        summary["unclassified" if metric.domain is None else str(metric.domain)] += 1
    return {
        "items": [metric.to_dict() for metric in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": summary,
        "revision": registry.revision,
    }


def _domain_metrics_raw(config_dir: Path, domain: str) -> list[dict[str, Any]]:
    path = config_dir / f"{domain}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    metrics = raw.get("metrics", [])
    if not isinstance(metrics, list) or not all(isinstance(item, dict) for item in metrics):
        raise KpiResourceError("invalid_kpi_config", f"{domain}.metrics 必须是字典列表", 500)
    return metrics


def _write_domain_metrics(config_dir: Path, domain: str, metrics: list[dict[str, Any]]) -> None:
    path = config_dir / f"{domain}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw["metrics"] = metrics
    _atomic_write_yaml(path, raw)


def _referenced_domains(catalog: KpiConfig, key: str) -> set[str]:
    """扫描公式、阈值和容量声明中的指标引用。"""
    referenced: set[str] = set()
    for domain, config in catalog.domains.items():
        if any(
            metric.formula is not None
            and key
            in {metric.formula.numerator, metric.formula.denominator, *metric.formula.denominator_fallback_inputs}
            for metric in config.metrics.values()
        ):
            referenced.add(domain)
        if key in config.thresholds:
            referenced.add(domain)
        if any(value.get("metric") == key for value in config.capacity_metrics.values()):
            referenced.add(domain)
    return referenced


_BASIC_DEFINITION_FIELDS = (
    "key",
    "name_zh",
    "name_en",
    "metric_type",
    "semantic_group",
    "display_role",
    "unit",
    "source_type",
    "aggregation",
)


def _basic_metric_fields(value: dict[str, Any]) -> dict[str, Any]:
    return {field: value.get(field) for field in _BASIC_DEFINITION_FIELDS}


def classify_resource_metrics(
    metric_keys: Sequence[str],
    *,
    domain: str,
    expected_revision: int,
    config_dir: Path | None = None,
) -> dict[str, Any]:
    """把一批资源指标原子分类到一个业务域，并同步域配置。"""
    directory = Path(config_dir or "deploy/config/kpi")
    keys = list(dict.fromkeys(metric_keys))
    if not keys:
        raise KpiResourceError("bad_request", "metric_keys 不能为空")
    if domain not in VALID_DOMAINS:
        raise KpiResourceError("bad_request", f"目标域必须是 {'/'.join(VALID_DOMAINS)}")

    with _LOCK:
        registry = load_resource_registry(directory)
        if registry.revision != expected_revision:
            raise KpiResourceError(
                "resource_revision_conflict",
                "资源指标库已被其他操作更新，请刷新后重试",
                409,
                detail={"expected_revision": expected_revision, "actual_revision": registry.revision},
            )
        missing = [key for key in keys if key not in registry.metrics]
        if missing:
            raise KpiResourceError(
                "resource_metric_not_found",
                "资源指标不存在: " + ", ".join(missing),
                404,
                detail={"metric_keys": missing},
            )

        try:
            catalog = load_kpi_catalog(directory)
        except KpiCatalogError as exc:
            raise KpiResourceError("invalid_kpi_config", f"KPI 配置校验失败: {exc}", 500) from exc

        affected_domains: set[str] = {domain}
        for key in keys:
            metric = registry.metrics[key]
            source_domains = {name for name, config in catalog.domains.items() if key in config.metrics}
            if len(source_domains) > 1:
                raise KpiResourceError(
                    "resource_metric_conflict",
                    f"资源指标在多个域配置中重复: {key}",
                    409,
                    detail={"metric_key": key, "domains": sorted(source_domains)},
                )
            if source_domains:
                source = next(iter(source_domains))
                if source != domain and source in _referenced_domains(catalog, key):
                    raise KpiResourceError(
                        "resource_metric_referenced",
                        f"指标 {key} 已被 {source} 域公式、阈值或容量声明引用，请先解除引用",
                        409,
                        detail={"metric_key": key, "domain": source},
                    )
                affected_domains.add(source)
            if domain in source_domains:
                existing = catalog.domains[domain].metrics[key]
                expected = _basic_metric_fields(metric.to_dict())
                actual = _basic_metric_fields(existing.__dict__)
                if expected != actual:
                    raise KpiResourceError(
                        "resource_metric_conflict",
                        f"指标 {key} 与 {domain} 域现有定义冲突",
                        409,
                        detail={"metric_key": key, "domain": domain},
                    )
            affected_domains.add(domain)

        snapshots: dict[Path, bytes | None] = {}
        now = utc_now_text()
        try:
            for target in sorted(affected_domains):
                path = directory / f"{target}.yaml"
                snapshots[path] = path.read_bytes() if path.exists() else None
                snapshots[_registry_path(directory)] = (
                    _registry_path(directory).read_bytes() if _registry_path(directory).exists() else None
                )

            for target in sorted(affected_domains):
                if target not in VALID_DOMAINS:
                    continue
                metrics_raw = _domain_metrics_raw(directory, target)
                if target == domain:
                    for key in keys:
                        metric = registry.metrics[key]
                        definition = metric.basic_fields()
                        if not any(item.get("key") == key for item in metrics_raw):
                            metrics_raw.append(definition)
                else:
                    metrics_raw = [item for item in metrics_raw if item.get("key") not in set(keys)]
                _write_domain_metrics(directory, target, metrics_raw)

            load_kpi_catalog(directory)
            for key in keys:
                registry.metrics[key].domain = domain
                registry.metrics[key].updated_at = now
            registry.revision += 1
            _atomic_write_yaml(_registry_path(directory), registry.to_dict())
            _append_audit(
                directory,
                {
                    "operated_at": now,
                    "operation": "classification",
                    "domain": domain,
                    "metric_keys": keys,
                    "result": "success",
                    "revision": registry.revision,
                },
            )
        except Exception as exc:
            for path, content in snapshots.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            if isinstance(exc, KpiResourceError):
                raise
            raise KpiResourceError("resource_classification_write_failed", f"分类保存失败: {exc}", 500) from exc

    return {"revision": registry.revision, "domain": domain, "metric_keys": keys}
