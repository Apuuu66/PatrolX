"""KPI CSV 共享解析、配置校验和结果聚合 helper。

三条领域规则（kpi.api / kpi.media / kpi.call）共用此模块的纯函数，
但不建立规则间依赖；本模块不是规则，不产生跨规则输入。
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zoneinfo
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.inspectors.kpi.catalog import (
    KpiAggregationResult,
    KpiCatalogError,
    KpiConfig,
    KpiDomainConfig,
    KpiMetricDefinition,
    KpiThreshold,
    aggregate_kpi_metric,
    evaluate_kpi_threshold,
    load_kpi_catalog,
    normalize_metric_name,
)

KpiConfigError = KpiCatalogError
__all__ = [
    "KpiConfigError",
    "KpiConfig",
    "KpiThreshold",
    "load_kpi_catalog",
    "match_metric_name",
    "normalize_metric_name",
]

VALID_PERIODS = {5, 15, 30, 60}
# 展示和分析优先采用更稳定的 15 分钟粒度；缺失时按可用粒度兜底。
KPI_PERIOD_PRIORITY = (15, 5, 30, 60)
VALID_SEMANTICS = {"peak", "concurrency", "gauge"}
VALID_CAPACITY_STATUS = {"confirmed", "unknown"}
VALID_DIRECTIONS = {"min", "max"}

# 文件名解析
_FILENAME_RE = re.compile(
    r"^kpi/(?:.*/)?(?:kpi-(?P<domain>api|media)-(?P<period>5|15|30|60)"
    r"|(?:[^/]+_)?Call_Session_API_Statistics_(?P<call_period>5|15|30|60)(?:_0_[^/]+)?)\.csv$"
)


@dataclass(slots=True)
class KpiError:
    """KPI 解析错误。"""

    code: str
    line_number: int | None = None
    column: str | None = None
    message: str = ""
    value: str | float | None = None
    path: str = ""


@dataclass(slots=True)
class KpiCapacityValue:
    """容量型指标值。"""

    source_name: str
    metric: str
    value: float
    status: str  # confirmed | unknown
    semantics: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class KpiRecord:
    """一条 KPI 数据记录。"""

    line_number: int
    period_minutes: int
    start_at: datetime
    end_at: datetime
    values: dict[str, float] = field(default_factory=dict)
    errors: list[KpiError] = field(default_factory=list)
    derived: dict[str, float] | None = None
    capacity_values: list[KpiCapacityValue] | None = None


@dataclass(slots=True)
class KpiCsvFile:
    """一个已解析的 KPI CSV 文件。"""

    path: str
    domain: str
    period_minutes: int
    measurement_set: str | None = None
    status: str = "ok"  # ok | failed
    errors: list[KpiError] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    records: list[KpiRecord] = field(default_factory=list)

    @property
    def record_count(self) -> int:
        return sum(not record.errors for record in self.records)

    @property
    def parse_error_count(self) -> int:
        return len(self.errors) + sum(len(r.errors) for r in self.records)


def parse_kpi_path(relative_path: str) -> tuple[str, int] | None:
    """从任务相对路径解析 domain 和 period_minutes，不匹配返回 None。"""
    match = _FILENAME_RE.fullmatch(relative_path)
    if match is None:
        return None
    if match.group("domain") is None:
        return "call", int(match.group("call_period"))
    return match.group("domain"), int(match.group("period"))


def load_kpi_config(config_path: Path | None = None) -> KpiConfig:
    """读取并校验目录化 KPI 规则配置。"""
    return load_kpi_catalog(config_path or settings.config / "kpi")


def _sha256_prefix(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


_INVALID_TIME = datetime(1970, 1, 1, tzinfo=UTC)


def finding_id(*, domain: str, kind: str, path: str, line_number: int | None = None) -> str:
    """生成确定性 finding_id。"""
    prefix = f"kpi.{domain}:{kind}:{_sha256_prefix(path)}"
    if line_number is not None:
        return f"{prefix}:{line_number}"
    return prefix


def parse_time(text: str, tz: zoneinfo.ZoneInfo) -> datetime:
    """解析 CSV 时间字符串为 UTC datetime。"""
    text = text.strip()
    # 支持 ISO 8601 和 "YYYY-MM-DD HH:MM:SS" 格式
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            naive = datetime.strptime(text, fmt)
            return naive.replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            continue
    # 尝试 fromisoformat（支持带时区偏移/Z）
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(UTC)
    except ValueError:
        raise ValueError(f"无法解析时间: {text}") from None


def match_metric_name(source_name: str, domain_config: KpiDomainConfig) -> str | None:
    """按“指标名 + 单位”的真实列名做最长前缀匹配，返回稳定 key。"""
    normalized = normalize_metric_name(source_name)
    best_key: str | None = None
    best_length = 0
    for name, key in domain_config.alias_index.items():
        if not name or not normalized.startswith(name):
            continue
        if len(name) > best_length:
            best_key = key
            best_length = len(name)
    return best_key


def _stable_record_values(record: KpiRecord, domain_config: KpiDomainConfig) -> dict[str, float]:
    """把源列名最长前缀归一到稳定 key；未登记列不进入已登记指标输入。"""
    values: dict[str, float] = {}
    for source_name, value in record.values.items():
        key = match_metric_name(source_name, domain_config)
        if key is not None:
            values[key] = value
    return values


def _record_metric_value(
    definition: KpiMetricDefinition,
    stable_values: dict[str, float],
) -> tuple[float | None, KpiAggregationResult | None]:
    """按目录定义获取单条记录值；公式优先，不用直接同语义列覆盖。"""
    if definition.source_type == "derived":
        result = aggregate_kpi_metric(definition, {key: [value] for key, value in stable_values.items()})
        return (result.main_value if result.value_available else None), result
    return stable_values.get(definition.key), None


def _unclassified_metrics(
    files: list[KpiCsvFile],
    domain_config: KpiDomainConfig,
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for kpi_file in files:
        registered = {name for name in kpi_file.objects if match_metric_name(name, domain_config)}
        unclassified = [name for name in kpi_file.objects if name not in registered]
        for name in unclassified:
            item = grouped.setdefault(
                name,
                {
                    "source_name": name,
                    "source_files": [],
                    "record_count": 0,
                    "sample_values": [],
                    "reason": "metric_not_registered",
                },
            )
            if kpi_file.path not in item["source_files"]:
                item["source_files"].append(kpi_file.path)  # type: ignore[union-attr]
            for record in kpi_file.records:
                if name in record.values:
                    item["record_count"] += 1  # type: ignore[operator]
                    if len(item["sample_values"]) < 5:  # type: ignore[operator]
                        item["sample_values"].append(record.values[name])  # type: ignore[union-attr]
    return list(grouped.values())


def _group_metric_records(
    definition: KpiMetricDefinition,
    files: list[KpiCsvFile],
    domain_config: KpiDomainConfig,
) -> dict[tuple[datetime, datetime, int], dict[str, list[float]]]:
    """按时间窗口归并记录；同一窗口的多行服务/实例数据属于同一个采样点。"""
    grouped: dict[tuple[datetime, datetime, int], dict[str, list[float]]] = {}
    for kpi_file in files:
        for record in kpi_file.records:
            stable_values = _stable_record_values(record, domain_config)
            if definition.source_type == "derived":
                keys = [definition.key]
                if definition.formula is not None:
                    formula = definition.formula
                    keys = [formula.numerator, formula.denominator, *formula.denominator_fallback_inputs]
            else:
                keys = [definition.key]
            for key in dict.fromkeys(keys):
                if key in stable_values:
                    group_key = (record.start_at, record.end_at, record.period_minutes)
                    grouped.setdefault(group_key, {}).setdefault(key, []).append(stable_values[key])
    return grouped


def _build_metric_series(
    definition: KpiMetricDefinition,
    files: list[KpiCsvFile],
    domain_config: KpiDomainConfig,
) -> list[dict[str, object]]:
    """生成按时间窗口聚合的趋势序列。"""
    series: list[dict[str, object]] = []
    for (start_at, end_at, period_minutes), input_values in _group_metric_records(
        definition, files, domain_config
    ).items():
        aggregate = aggregate_kpi_metric(definition, input_values)
        if aggregate.value_available and aggregate.main_value is not None:
            series.append(
                {
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "period_minutes": period_minutes,
                    "value": aggregate.main_value,
                }
            )
    return series


def _source_names_by_metric_key(
    files: list[KpiCsvFile],
    domain_config: KpiDomainConfig,
) -> dict[str, list[str]]:
    """按稳定 key 归集真实 CSV 列名，供输入溯源展示。"""
    source_names: dict[str, list[str]] = {}
    for kpi_file in files:
        for source_name in kpi_file.objects:
            metric_key = match_metric_name(source_name, domain_config)
            if metric_key is None:
                continue
            names = source_names.setdefault(metric_key, [])
            if source_name not in names:
                names.append(source_name)
    return source_names


def build_kpi_metadata(
    domain: str,
    files: list[KpiCsvFile],
    config: KpiConfig,
) -> dict[str, object]:
    """生成目录化 KPI 元数据；历史结果不会被迁移或重算。"""
    domain_config = config.domains[domain]
    records = [record for kpi_file in files for record in kpi_file.records]
    source_names_by_key = _source_names_by_metric_key(files, domain_config)
    stable_records = [_stable_record_values(record, domain_config) for record in records]
    metric_results: list[dict[str, object]] = []
    threshold = domain_config.thresholds

    for definition in domain_config.metrics.values():
        input_values: dict[str, list[float]] = {}
        if definition.source_type == "derived":
            keys = [definition.key]
            if definition.formula is not None:
                formula = definition.formula
                keys = [formula.numerator, formula.denominator, *formula.denominator_fallback_inputs]
            for key in dict.fromkeys(keys):
                input_values[key] = [values[key] for values in stable_records if key in values]
        else:
            input_values[definition.key] = [
                values[definition.key] for values in stable_records if definition.key in values
            ]

        aggregate = aggregate_kpi_metric(definition, input_values)
        for input_provenance in aggregate.provenance["inputs"]:
            key = input_provenance.get("key")
            if isinstance(key, str):
                input_provenance["source_names"] = list(source_names_by_key.get(key, []))
        item_threshold = threshold.get(definition.key)
        series = _build_metric_series(definition, files, domain_config)
        breach_count = sum(
            evaluate_kpi_threshold(
                point["value"] if isinstance(point["value"], (int, float)) else None,
                item_threshold,
                point["period_minutes"] if isinstance(point["period_minutes"], int) else 0,
            )
            == "fail"
            for point in series
        )

        main_status = evaluate_kpi_threshold(aggregate.main_value, item_threshold, 0)
        direct_cross_reference: list[dict[str, object]] = []
        if definition.source_type == "derived":
            for kpi_file in files:
                for record in kpi_file.records:
                    stable_values = _stable_record_values(record, domain_config)
                    if definition.key in stable_values:
                        direct_cross_reference.append(
                            {
                                "source_name": next(
                                    name
                                    for name in record.values
                                    if match_metric_name(name, domain_config) == definition.key
                                ),
                                "source_file": kpi_file.path,
                                "value": stable_values[definition.key],
                            }
                        )
        aggregate.provenance["direct_cross_reference"] = direct_cross_reference
        metric_results.append(
            {
                "key": definition.key,
                "main_value": aggregate.main_value,
                "value_available": aggregate.value_available,
                "unavailable_reason": aggregate.unavailable_reason,
                "display_status": main_status,
                "unit": definition.unit,
                "aggregation": aggregate.actual_aggregation,
                "threshold": None
                if item_threshold is None
                else {
                    "metric": item_threshold.metric,
                    "label": item_threshold.label,
                    "direction": item_threshold.direction,
                    "unit": item_threshold.unit,
                    "default": item_threshold.default,
                    "periods": item_threshold.periods,
                },
                "breach_count": breach_count,
                "series": series,
                "source_files": [kpi_file.path for kpi_file in files if kpi_file.record_count],
                "provenance": aggregate.provenance,
            }
        )

    return {
        "version": 2,
        "domain": domain,
        "config_source": "deploy/config/kpi",
        "input_timezone": config.input_timezone,
        "metric_catalog": [item.as_metadata() for item in domain_config.metrics.values()],
        "kpi_results": metric_results,
        "unclassified_metrics": _unclassified_metrics(files, domain_config),
        "kpi_files": [
            {
                "path": kpi_file.path,
                "domain": kpi_file.domain,
                "period_minutes": kpi_file.period_minutes,
                "measurement_set": kpi_file.measurement_set,
                "status": kpi_file.status,
                "objects": kpi_file.objects,
                "record_count": kpi_file.record_count,
                "parse_error_count": kpi_file.parse_error_count,
                "errors": [
                    {
                        "code": error.code,
                        "line_number": error.line_number,
                        "column": error.column,
                        "message": error.message,
                        "value": error.value,
                    }
                    for error in kpi_file.errors
                ],
                "records": [
                    {
                        "line_number": record.line_number,
                        "period_minutes": record.period_minutes,
                        "start_at": record.start_at.isoformat(),
                        "end_at": record.end_at.isoformat(),
                        "values": record.values,
                        "derived": record.derived,
                        "capacity_values": [
                            {
                                "source_name": capacity.source_name,
                                "metric": capacity.metric,
                                "value": capacity.value,
                                "status": capacity.status,
                                "semantics": capacity.semantics,
                                "reason": capacity.reason,
                            }
                            for capacity in (record.capacity_values or [])
                        ]
                        or None,
                        "errors": [
                            {
                                "code": error.code,
                                "line_number": error.line_number,
                                "column": error.column,
                                "message": error.message,
                                "value": error.value,
                            }
                            for error in record.errors
                        ],
                    }
                    for record in kpi_file.records
                ],
            }
            for kpi_file in files
        ],
    }


def parse_csv_file(
    path: Path,
    relative_path: str,
    domain: str,
    period_minutes: int,
    config: KpiConfig,
    record_budget: int | None = None,
) -> KpiCsvFile:
    """解析单个 KPI CSV 文件，返回结构化结果。行级错误不中断后续行。"""
    kpi_file = KpiCsvFile(
        path=relative_path,
        domain=domain,
        period_minutes=period_minutes,
    )
    tz = config.tzinfo
    budgets = config.budgets

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="io_error",
                message=f"无法读取文件: {exc}",
                path=relative_path,
            )
        )
        return kpi_file

    if file_size > budgets["max_file_bytes"]:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="resource_limit_exceeded",
                message=f"文件大小 {file_size} 超过预算 {budgets['max_file_bytes']}",
                path=relative_path,
            )
        )
        return kpi_file

    try:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="decode_error",
                message=f"解码失败: {exc}",
                path=relative_path,
            )
        )
        return kpi_file

    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    row_count = 0
    for row in reader:
        row_count += 1
        if row_count > budgets["max_rows_per_file"]:
            kpi_file.errors.append(
                KpiError(
                    code="resource_limit_exceeded",
                    message=f"行数超过预算 {budgets['max_rows_per_file']}",
                    line_number=row_count,
                    path=relative_path,
                )
            )
            kpi_file.status = "failed"
            break
        rows.append(row)

    if not rows:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="empty_file",
                message="文件为空",
                path=relative_path,
            )
        )
        return kpi_file

    # 真实导出文件允许在表头前出现元数据行；表头按列名定位，不依赖固定行号。
    metadata: dict[str, str] = {}
    header_row_idx: int | None = None
    required_header_columns = {"测量开始时间", "测量结束时间", "周期(分钟)"}
    for row_idx, row in enumerate(rows):
        if required_header_columns.issubset({cell.strip() for cell in row}):
            header_row_idx = row_idx
            break

        non_empty_cells = [cell.strip() for cell in row if cell.strip()]
        if not non_empty_cells:
            continue
        metadata_cell = non_empty_cells[0]
        has_fullwidth_separator = "：" in metadata_cell
        if len(non_empty_cells) == 1 and any(sep in metadata_cell for sep in (":", "：")):
            separator = "：" if has_fullwidth_separator else ":"
            key, value = metadata_cell.split(separator, 1)
            metadata[key.strip()] = value.strip()

    if header_row_idx is None:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="invalid_header",
                message="缺少 KPI 表头，表头必须包含 测量开始时间/测量结束时间/周期(分钟)",
                path=relative_path,
            )
        )
        return kpi_file

    header_row_number = header_row_idx + 1
    measurement_set = metadata.get("测量单元名称", "").strip()
    if not measurement_set:
        kpi_file.errors.append(
            KpiError(
                code="missing_measurement_set",
                message="缺少测量单元名称元数据",
                line_number=1,
                path=relative_path,
            )
        )
        kpi_file.status = "failed"
    kpi_file.measurement_set = measurement_set or None

    header = [cell.strip() for cell in rows[header_row_idx]]
    if len(header) < 4:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="column_count_mismatch",
                message=f"表头行列数不足（{len(header)} < 4）",
                line_number=header_row_number,
                path=relative_path,
            )
        )
        return kpi_file

    try:
        start_idx = header.index("测量开始时间")
        end_idx = header.index("测量结束时间")
        period_idx = header.index("周期(分钟)")
    except ValueError:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="invalid_header",
                message="表头必须包含 测量开始时间/测量结束时间/周期(分钟)",
                line_number=header_row_number,
                path=relative_path,
            )
        )
        return kpi_file

    objects = header[period_idx + 1 :]
    if len(objects) != len(set(objects)):
        seen: set[str] = set()
        duplicates: list[str] = []
        for obj in objects:
            if obj in seen and obj not in duplicates:
                duplicates.append(obj)
            seen.add(obj)
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="duplicate_object",
                message=f"测量对象存在重复名称: {duplicates}",
                line_number=header_row_number,
                path=relative_path,
            )
        )
        return kpi_file

    if len(objects) + 3 > budgets["max_columns_per_file"]:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="resource_limit_exceeded",
                message=f"列数 {len(header)} 超过预算 {budgets['max_columns_per_file']}",
                line_number=header_row_number,
                path=relative_path,
            )
        )
        return kpi_file

    kpi_file.objects = objects

    # 获取容量配置
    cap_cfg = config.capacity_metrics.get(domain, {})

    # 表头之后均为数据行；表头之前的列（如服务名、实例、可信度）不作为指标。
    total_records = 0
    for line_idx, row in enumerate(rows[header_row_idx + 1 :], start=header_row_number + 1):
        if not row or all(not cell.strip() for cell in row):
            continue  # 跳过空行

        if record_budget is not None and total_records >= record_budget:
            kpi_file.errors.append(
                KpiError(
                    code="resource_limit_exceeded",
                    message=f"记录数超过预算 {config.budgets['max_records_per_domain']}",
                    line_number=line_idx,
                    path=relative_path,
                )
            )
            kpi_file.status = "failed"
            break

        if len(row) != len(header):
            kpi_file.records.append(
                KpiRecord(
                    line_number=line_idx,
                    period_minutes=period_minutes,
                    start_at=_INVALID_TIME,
                    end_at=_INVALID_TIME,
                    errors=[
                        KpiError(
                            code="column_count_mismatch",
                            message=f"列数 {len(row)} 与表头 {len(header)} 不一致",
                            line_number=line_idx,
                            path=relative_path,
                        )
                    ],
                )
            )
            kpi_file.status = "failed"
            continue

        # 解析周期
        period_text = row[period_idx].strip()
        try:
            row_period = int(period_text)
        except ValueError:
            kpi_file.records.append(
                KpiRecord(
                    line_number=line_idx,
                    period_minutes=period_minutes,
                    start_at=_INVALID_TIME,
                    end_at=_INVALID_TIME,
                    errors=[
                        KpiError(
                            code="invalid_period",
                            message=f"周期值不可解析: {period_text}",
                            line_number=line_idx,
                            column="周期(分钟)",
                            value=period_text,
                            path=relative_path,
                        )
                    ],
                )
            )
            kpi_file.status = "failed"
            continue

        if row_period != period_minutes:
            kpi_file.records.append(
                KpiRecord(
                    line_number=line_idx,
                    period_minutes=row_period,
                    start_at=_INVALID_TIME,
                    end_at=_INVALID_TIME,
                    errors=[
                        KpiError(
                            code="period_mismatch",
                            message=f"行周期 {row_period} 与文件名周期 {period_minutes} 不一致",
                            line_number=line_idx,
                            column="周期(分钟)",
                            value=row_period,
                            path=relative_path,
                        )
                    ],
                )
            )
            kpi_file.status = "failed"
            continue

        # 解析时间
        record_errors: list[KpiError] = []
        start_at: datetime | None = None
        end_at: datetime | None = None
        try:
            start_at = parse_time(row[start_idx], tz)
        except ValueError as exc:
            record_errors.append(
                KpiError(
                    code="invalid_time",
                    message=str(exc),
                    line_number=line_idx,
                    column="测量开始时间",
                    value=row[start_idx],
                    path=relative_path,
                )
            )
        try:
            end_at = parse_time(row[end_idx], tz)
        except ValueError as exc:
            record_errors.append(
                KpiError(
                    code="invalid_time",
                    message=str(exc),
                    line_number=line_idx,
                    column="测量结束时间",
                    value=row[end_idx],
                    path=relative_path,
                )
            )

        if start_at is not None and end_at is not None:
            expected_end = start_at + timedelta(minutes=period_minutes)
            if end_at != expected_end:
                record_errors.append(
                    KpiError(
                        code="time_range_mismatch",
                        message=f"结束时间 {end_at.isoformat()} 不等于开始时间 + {period_minutes} 分钟",
                        line_number=line_idx,
                        column="测量结束时间",
                        path=relative_path,
                    )
                )

        if start_at is None:
            start_at = _INVALID_TIME
        if end_at is None:
            end_at = start_at + timedelta(minutes=period_minutes)

        # 解析指标值
        values: dict[str, float] = {}
        for col_idx, obj_name in enumerate(objects):
            cell = row[period_idx + 1 + col_idx].strip()
            if not cell:
                record_errors.append(
                    KpiError(
                        code="invalid_value",
                        message=f"指标 {obj_name} 值为空",
                        line_number=line_idx,
                        column=obj_name,
                        path=relative_path,
                    )
                )
                continue
            try:
                values[obj_name] = float(cell)
            except ValueError:
                record_errors.append(
                    KpiError(
                        code="invalid_value",
                        message=f"指标 {obj_name} 值不可解析: {cell}",
                        line_number=line_idx,
                        column=obj_name,
                        value=cell,
                        path=relative_path,
                    )
                )

        # 识别容量指标
        capacity_values: list[KpiCapacityValue] = []
        for obj_name in objects:
            if obj_name in cap_cfg:
                spec = cap_cfg[obj_name]
                val = values.get(obj_name)
                if val is not None:
                    capacity_values.append(
                        KpiCapacityValue(
                            source_name=obj_name,
                            metric=spec["metric"],
                            value=val,
                            status=spec["status"],
                            semantics=spec["semantics"],
                            reason="capacity_semantics_unknown" if spec["status"] == "unknown" else None,
                        )
                    )

        record = KpiRecord(
            line_number=line_idx,
            period_minutes=row_period,
            start_at=start_at,
            end_at=end_at,
            values=values,
            errors=record_errors,
            capacity_values=capacity_values or None,
        )
        kpi_file.records.append(record)
        total_records += 1

        if record_errors:
            kpi_file.status = "failed"

    return kpi_file


def parse_all_files(
    ctx_files: list[Path],
    data_dir: Path,
    domain: str,
    config: KpiConfig,
) -> list[KpiCsvFile]:
    """批量解析匹配文件，只使用最高优先级周期。

    周期优先级为 15 → 5 → 30 → 60；同一优先级下的多个文件仍一起聚合。
    按路径排序，单个文件失败不影响其他文件。
    """
    targets: list[tuple[Path, str, int]] = []
    periods: set[int] = set()
    for path in sorted(ctx_files, key=lambda p: p.as_posix()):
        relative = path.relative_to(data_dir).as_posix() if path.is_relative_to(data_dir) else path.as_posix()
        parsed = parse_kpi_path(relative)
        if parsed is None or parsed[0] != domain:
            continue
        targets.append((path, relative, parsed[1]))
        periods.add(parsed[1])

    preferred_period = next((period for period in KPI_PERIOD_PRIORITY if period in periods), None)
    targets = [target for target in targets if target[2] == preferred_period]

    if len(targets) > config.budgets["max_files_per_domain"]:
        error_file = KpiCsvFile(
            path="<resource-budget>",
            domain=domain,
            period_minutes=0,
            status="failed",
            errors=[
                KpiError(
                    code="resource_limit_exceeded",
                    message=(f"文件数 {len(targets)} 超过预算 {config.budgets['max_files_per_domain']}"),
                    path="<resource-budget>",
                )
            ],
        )
        return [error_file]

    remaining_records = config.budgets["max_records_per_domain"]
    results: list[KpiCsvFile] = []
    for path, relative, period in targets:
        parsed_file = parse_csv_file(
            path,
            relative,
            domain,
            period,
            config,
            record_budget=max(remaining_records, 0),
        )
        results.append(parsed_file)
        remaining_records -= parsed_file.record_count
        if remaining_records <= 0:
            break
    return results
