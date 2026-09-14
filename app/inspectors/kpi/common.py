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
from typing import Any

import yaml

CONFIG_RELATIVE_PATH = "deploy/config/kpi_rules.yaml"
VALID_PERIODS = {5, 15, 30, 60}
VALID_SEMANTICS = {"peak", "concurrency", "gauge"}
VALID_CAPACITY_STATUS = {"confirmed", "unknown"}
VALID_DIRECTIONS = {"min", "max"}

# 文件名解析
_FILENAME_RE = re.compile(r"^kpi/(?P<dir_prefix>(?:.*/)?)kpi-(?P<domain>api|media|call)-(?P<period>5|15|30|60)\.csv$")


class KpiConfigError(Exception):
    """KPI 配置缺失或非法。"""


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


@dataclass(slots=True)
class KpiThreshold:
    """一个阈值配置。"""

    metric: str
    label: str
    direction: str  # min | max
    unit: str
    default: float
    periods: dict[str, float]


@dataclass(slots=True)
class KpiConfig:
    """KPI 规则配置。"""

    version: int
    input_timezone: str
    aliases: dict[str, dict[str, str]]
    capacity_metrics: dict[str, dict[str, dict[str, Any]]]
    limits: dict[str, dict[str, KpiThreshold]]
    budgets: dict[str, int]

    @property
    def tzinfo(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.input_timezone)


def parse_kpi_path(relative_path: str) -> tuple[str, int] | None:
    """从任务相对路径解析 domain 和 period_minutes，不匹配返回 None。"""
    match = _FILENAME_RE.fullmatch(relative_path)
    if match is None:
        return None
    return match.group("domain"), int(match.group("period"))


def load_kpi_config(config_path: Path | None = None) -> KpiConfig:
    """读取并校验 KPI 规则配置文件。"""
    resolved = config_path or Path(CONFIG_RELATIVE_PATH)
    if not resolved.is_file():
        raise KpiConfigError(f"配置文件不存在: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        raise KpiConfigError(f"配置文件读取或解析失败: {exc}") from exc
    if not isinstance(raw, dict):
        raise KpiConfigError("配置文件顶层必须是字典")

    version = raw.get("version")
    if version != 1:
        raise KpiConfigError(f"不支持的配置版本: {version}")

    input_tz = raw.get("input_timezone")
    if not isinstance(input_tz, str) or not input_tz.strip():
        raise KpiConfigError("input_timezone 缺失或非法")
    try:
        zoneinfo.ZoneInfo(input_tz)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise KpiConfigError(f"非法时区: {input_tz}") from exc

    aliases_raw = raw.get("aliases")
    if not isinstance(aliases_raw, dict):
        raise KpiConfigError("aliases 缺失或非法")
    aliases: dict[str, dict[str, str]] = {}
    for domain, mapping in aliases_raw.items():
        if not isinstance(domain, str) or not isinstance(mapping, dict):
            raise KpiConfigError(f"aliases.{domain} 非法")
        aliases[domain] = {}
        for source, key in mapping.items():
            if not isinstance(source, str) or not isinstance(key, str):
                raise KpiConfigError(f"aliases.{domain}.{source} 非法")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
                raise KpiConfigError(f"aliases.{domain}.{source} 稳定 key 非法: {key}")
            aliases[domain][source] = key

    capacity_raw = raw.get("capacity_metrics")
    if not isinstance(capacity_raw, dict):
        raise KpiConfigError("capacity_metrics 缺失或非法")
    capacity_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for domain, entries in capacity_raw.items():
        if not isinstance(domain, str) or not isinstance(entries, dict):
            raise KpiConfigError(f"capacity_metrics.{domain} 非法")
        capacity_metrics[domain] = {}
        for source, spec in entries.items():
            if not isinstance(source, str) or not isinstance(spec, dict):
                raise KpiConfigError(f"capacity_metrics.{domain}.{source} 非法")
            metric = spec.get("metric")
            if not isinstance(metric, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", metric):
                raise KpiConfigError(f"capacity_metrics.{domain}.{source}.metric 非法: {metric}")
            semantics = spec.get("semantics")
            status = spec.get("status")
            if status not in VALID_CAPACITY_STATUS:
                raise KpiConfigError(f"capacity_metrics.{domain}.{source}.status 非法: {status}")
            if status == "confirmed" and semantics not in VALID_SEMANTICS:
                raise KpiConfigError(f"capacity_metrics.{domain}.{source}.semantics 必填（confirmed）: {semantics}")
            if status == "unknown":
                semantics = None
            capacity_metrics[domain][source] = {
                "metric": metric,
                "semantics": semantics,
                "status": status,
            }

    # 别名稳定 key 与容量 metric key 不得冲突
    for domain in aliases:
        alias_keys = set(aliases[domain].values())
        cap_keys = {e["metric"] for e in capacity_metrics.get(domain, {}).values()}
        overlap = alias_keys & cap_keys
        if overlap:
            raise KpiConfigError(f"aliases 与 capacity_metrics key 冲突 ({domain}): {overlap}")

    limits_raw = raw.get("limits")
    if not isinstance(limits_raw, dict):
        raise KpiConfigError("limits 缺失或非法")
    limits: dict[str, dict[str, KpiThreshold]] = {}
    for domain, metrics in limits_raw.items():
        if not isinstance(domain, str) or not isinstance(metrics, dict):
            raise KpiConfigError(f"limits.{domain} 非法")
        limits[domain] = {}
        for metric, spec in metrics.items():
            if not isinstance(metric, str) or not isinstance(spec, dict):
                raise KpiConfigError(f"limits.{domain}.{metric} 非法")
            label = spec.get("label")
            direction = spec.get("direction")
            unit = spec.get("unit")
            default = spec.get("default")
            periods_raw = spec.get("periods")
            if not isinstance(label, str) or not label.strip():
                raise KpiConfigError(f"limits.{domain}.{metric}.label 非法")
            if direction not in VALID_DIRECTIONS:
                raise KpiConfigError(f"limits.{domain}.{metric}.direction 非法: {direction}")
            if not isinstance(unit, str):
                raise KpiConfigError(f"limits.{domain}.{metric}.unit 非法")
            if isinstance(default, bool) or not isinstance(default, (int, float)):
                raise KpiConfigError(f"limits.{domain}.{metric}.default 非法: {default}")
            periods: dict[str, float] = {}
            if periods_raw is not None:
                if not isinstance(periods_raw, dict):
                    raise KpiConfigError(f"limits.{domain}.{metric}.periods 非法")
                for period_key, val in periods_raw.items():
                    if period_key not in {"5", "15", "30", "60"}:
                        raise KpiConfigError(f"limits.{domain}.{metric}.periods key 非法: {period_key}")
                    if not isinstance(val, (int, float)):
                        raise KpiConfigError(f"limits.{domain}.{metric}.periods[{period_key}] 非法")
                    periods[period_key] = float(val)
            limits[domain][metric] = KpiThreshold(
                metric=metric,
                label=label,
                direction=direction,
                unit=unit,
                default=float(default),
                periods=periods,
            )

    budgets_raw = raw.get("budgets")
    if not isinstance(budgets_raw, dict):
        raise KpiConfigError("budgets 缺失或非法")
    budget_keys = {
        "max_file_bytes",
        "max_rows_per_file",
        "max_columns_per_file",
        "max_files_per_domain",
        "max_records_per_domain",
    }
    budgets: dict[str, int] = {}
    for key in budget_keys:
        val = budgets_raw.get(key)
        if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise KpiConfigError(f"budgets.{key} 必须为正整数: {val}")
        budgets[key] = val

    call_aliases = aliases.get("call", {})
    required_aliases = {"呼叫请求", "请求成功", "请求失败", "呼叫成功率", "呼叫失败率"}
    missing_aliases = required_aliases - set(call_aliases)
    if missing_aliases:
        raise KpiConfigError(f"aliases.call 缺少必需映射: {sorted(missing_aliases)}")
    if len(set(call_aliases.values())) != len(call_aliases):
        raise KpiConfigError("aliases.call 存在重复稳定 key")
    call_limits = limits.get("call", {})
    required_limits = {"call_success_rate", "call_failure_rate"}
    missing_limits = required_limits - set(call_limits)
    if missing_limits:
        raise KpiConfigError(f"limits.call 缺少必需阈值: {sorted(missing_limits)}")

    return KpiConfig(
        version=1,
        input_timezone=input_tz,
        aliases=aliases,
        capacity_metrics=capacity_metrics,
        limits=limits,
        budgets=budgets,
    )


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

    # 第 1 行：测量集名称
    measurement_set = rows[0][0].strip() if rows[0] else ""
    if not measurement_set:
        kpi_file.errors.append(
            KpiError(
                code="missing_measurement_set",
                message="第 1 行测量集名称为空",
                line_number=1,
                path=relative_path,
            )
        )
        kpi_file.status = "failed"
    kpi_file.measurement_set = measurement_set or None

    # 第 2 行：测量对象
    if len(rows) < 2:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="missing_object_row",
                message="缺少第 2 行测量对象",
                path=relative_path,
            )
        )
        return kpi_file

    header = [cell.strip() for cell in rows[1]]
    if len(header) < 4:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="column_count_mismatch",
                message=f"测量对象行列数不足（{len(header)} < 4）",
                line_number=2,
                path=relative_path,
            )
        )
        return kpi_file

    if header[:3] != ["测量周期", "开始时间", "结束时间"]:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="invalid_header",
                message="测量对象行前 3 列必须为 测量周期/开始时间/结束时间",
                line_number=2,
                path=relative_path,
            )
        )
        return kpi_file

    objects = header[3:]
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
                line_number=2,
                path=relative_path,
            )
        )
        return kpi_file

    if len(objects) + 3 > budgets["max_columns_per_file"]:
        kpi_file.status = "failed"
        kpi_file.errors.append(
            KpiError(
                code="resource_limit_exceeded",
                message=f"列数 {len(objects) + 3} 超过预算 {budgets['max_columns_per_file']}",
                line_number=2,
                path=relative_path,
            )
        )
        return kpi_file

    kpi_file.objects = objects

    # 获取容量配置和别名
    cap_cfg = config.capacity_metrics.get(domain, {})

    # 第 3 行起：数据行
    total_records = 0
    for line_idx, row in enumerate(rows[2:], start=3):
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
        period_text = row[0].strip()
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
                            column="测量周期",
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
                            column="测量周期",
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
            start_at = parse_time(row[1], tz)
        except ValueError as exc:
            record_errors.append(
                KpiError(
                    code="invalid_time",
                    message=str(exc),
                    line_number=line_idx,
                    column="开始时间",
                    value=row[1],
                    path=relative_path,
                )
            )
        try:
            end_at = parse_time(row[2], tz)
        except ValueError as exc:
            record_errors.append(
                KpiError(
                    code="invalid_time",
                    message=str(exc),
                    line_number=line_idx,
                    column="结束时间",
                    value=row[2],
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
                        column="结束时间",
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
            cell = row[3 + col_idx].strip()
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
    """批量解析匹配文件，按路径排序，单个文件失败不影响其他文件。"""
    targets: list[tuple[Path, str, int]] = []
    for path in sorted(ctx_files, key=lambda p: p.as_posix()):
        relative = path.relative_to(data_dir).as_posix() if path.is_relative_to(data_dir) else path.as_posix()
        parsed = parse_kpi_path(relative)
        if parsed is None or parsed[0] != domain:
            continue
        targets.append((path, relative, parsed[1]))

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
