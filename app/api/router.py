"""在线模式 API 路由。"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PureWindowsPath
from pathlib import Path as FileSystemPath
from tempfile import NamedTemporaryFile
from typing import Any

import yaml
from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from app.cli import generate_task_id
from app.core.checksum import sha256_file
from app.core.config import settings
from app.core.dicts import load_dicts
from app.inspectors.registry import registry
from app.models.schemas import (
    DictItem,
    DictsResponse,
    DictUpdateRequest,
    InspectionTask,
    InspectorInfo,
    KpiDisplayStatus,
    KpiPeriodMinutes,
    KpiRecordPage,
    KpiResourceClassificationRequest,
    KpiResourceClassificationResult,
    KpiResourceImportReport,
    KpiResourceMetricPage,
    LogEntry,
    OverviewSummary,
    RerunRequest,
    RuleResult,
    SystemInspection,
    TaskCreated,
    TaskListResponse,
    TaskLogs,
)
from app.services.kpi_records import list_kpi_records
from app.services.kpi_resources import (
    KpiResourceError,
    classify_resource_metrics,
    import_resource_metrics,
    list_resource_metrics,
    read_resource_csv,
)
from app.services.overview import build_overview
from app.services.tasks import DeleteResult, TaskDeleteError, task_service

router = APIRouter(prefix="/api/v2")
DICT_NAMES = ("province", "operator", "product", "version")


class AppError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, detail: dict[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


async def _receive_upload(package_file: UploadFile) -> tuple[str, int, Path]:
    """流式落盘上传包并计算 checksum，避免为比对而修改既有任务现场。"""
    settings.uploads.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    fd, raw_name = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=settings.uploads)
    temp_path = Path(raw_name)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await package_file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise AppError("package_too_large", f"数据包超过 {settings.max_upload_mb}MB 限制", 413)
                digest.update(chunk)
                out.write(chunk)
        return digest.hexdigest(), size, temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


# ---- /api/v2 契约路由 ----


@router.post("/tasks", response_model=TaskCreated, status_code=202, operation_id="createTaskV2")
async def create_task_v2(
    response: Response,
    package_file: UploadFile = File(...),
    name: str | None = Form(None),
    version: str | None = Form(None),
    province: str | None = Form(None),
    operator: str | None = Form(None),
    product: str | None = Form(None),
) -> TaskCreated:
    filename = PureWindowsPath(package_file.filename or "package.zip").name or "package.zip"
    if len(filename.encode("utf-8")) > 255:
        raise AppError("invalid_filename", "数据包文件名过长，请限制在 255 字节内", 400)
    if not filename.lower().endswith((".zip", ".tar", ".gz", ".tgz")):
        raise AppError("invalid_package", "仅支持 zip/tar.gz 数据包", 400)

    task_id = generate_task_id(filename)
    temp_path: Path | None = None
    created: TaskCreated | None = None
    try:
        checksum, size, temp_path = await _receive_upload(package_file)
        if size == 0:
            raise AppError("invalid_package", "数据包不能为空", 400)
        if size > settings.max_upload_mb * 1024 * 1024:
            raise AppError("package_too_large", f"数据包超过 {settings.max_upload_mb}MB 限制", 413)

        if task_service.exists(task_id):
            existing = settings.uploads / task_id / filename
            existing_checksum = sha256_file(existing) if existing.exists() else None
            if existing_checksum != checksum:
                raise AppError(
                    "package_checksum_conflict",
                    "同名任务已存在，但数据包 checksum 不同",
                    409,
                )
            response.headers["Location"] = f"/api/v2/tasks/{task_id}"
            return TaskCreated(task_id=task_id)

        created = task_service.reserve(
            filename,
            name,
            province,
            operator,
            version,
            product=product,
        )
        task_dir = settings.uploads / created.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(temp_path, task_dir / filename)
        response.headers["Location"] = f"/api/v2/tasks/{created.task_id}"
        task_service.submit(created.task_id)
        return created
    except Exception:
        if created is not None:
            task_service.discard(created.task_id)
            shutil.rmtree(settings.uploads / created.task_id, ignore_errors=True)
            shutil.rmtree(settings.output / created.task_id, ignore_errors=True)
        raise
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.get("/overview", response_model=OverviewSummary, operation_id="getOverviewV2")
def get_overview_v2() -> OverviewSummary:
    return build_overview()


@router.get("/tasks", response_model=TaskListResponse, operation_id="listTasksV2")
def list_tasks_v2(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
) -> TaskListResponse:
    items, total = task_service.list_tasks(page, page_size, status)
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/tasks/{task_id}", response_model=InspectionTask, operation_id="getTaskV2")
def get_task_v2(task_id: str = PathParam()) -> InspectionTask:
    task = task_service.get(task_id)
    if task is None:
        raise AppError("not_found", "任务不存在", 404)
    system = task.system
    if system is None:
        return task
    return task.model_copy(
        update={
            "system": system.model_copy(
                update={
                    "rules": [
                        rule.model_copy(update={"metadata": {}, "metrics": [], "findings": []}) for rule in system.rules
                    ]
                }
            )
        }
    )


@router.delete("/tasks/{task_id}", status_code=204, operation_id="deleteTaskV2")
def delete_task_v2(task_id: str = PathParam()) -> Response:
    try:
        result = task_service.delete(task_id)
    except TaskDeleteError as exc:
        raise AppError(
            "task_delete_failed",
            f"任务删除失败: {exc.reason}",
            500,
            detail={
                "task_id": exc.task_id,
                "locations": exc.locations,
                "failed_path": exc.failed_path,
                "path_length": exc.path_length,
                "path_limit": exc.path_limit,
            },
        ) from exc
    if result == DeleteResult.BUSY:
        raise AppError("task_busy", "任务正在排队或执行，不能删除", 409)
    if result == DeleteResult.NOT_FOUND:
        raise AppError("not_found", "任务不存在", 404)
    return Response(status_code=204)


@router.post("/tasks/{task_id}/rerun", response_model=TaskCreated, status_code=202, operation_id="rerunTaskV2")
def rerun_task_v2(task_id: str = PathParam(), body: RerunRequest | None = None) -> TaskCreated:
    codes = body.rule_codes if body else None
    if codes:
        registry.load_all()
        registered = set(registry.codes())
        unknown = [code for code in codes if code not in registered]
        if unknown:
            raise AppError("unknown_rule", f"规则不存在: {', '.join(unknown)}", 400)
    if not task_service.rerun(task_id, codes):
        raise AppError("not_found", "任务不存在或数据包缺失", 404)
    return TaskCreated(task_id=task_id)


@router.get("/tasks/{task_id}/report", response_class=HTMLResponse, operation_id="getReportV2")
def get_report_v2(task_id: str = PathParam()) -> HTMLResponse:
    report = settings.output / task_id / "report.html"
    if not report.exists():
        raise AppError("not_found", "报告未生成", 404)
    return HTMLResponse(report.read_text(encoding="utf-8"))


@router.get("/tasks/{task_id}/logs", response_model=TaskLogs, operation_id="getTaskLogsV2")
def get_task_logs_v2(task_id: str = PathParam()) -> TaskLogs:
    log_file = settings.output / task_id / "execution.log"
    if not log_file.exists():
        raise AppError("not_found", "执行日志未生成", 404)
    entries: list[LogEntry] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            entries.append(
                LogEntry(
                    ts=raw["ts"],
                    level=raw["level"],
                    message=raw["message"],
                    rule_code=raw.get("rule_code"),
                    detail={k: v for k, v in raw.items() if k not in ("ts", "level", "message", "rule_code")},
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            # 损坏的历史日志行不阻断任务诊断，API 返回仍可读取的日志前缀。
            continue
    return TaskLogs(task_id=task_id, entries=entries)


KPI_SERIES_MAX_POINTS = 200


def _bounded_kpi_list(items: list[Any], max_items: int = KPI_SERIES_MAX_POINTS) -> list[Any]:
    """为展示接口均匀抽稀长列表；完整数据仍保留在规则结果文件中。"""
    if len(items) <= max_items:
        return items
    step = -(-len(items) // max_items)
    sampled = items[::step]
    if sampled[-1] is not items[-1]:
        sampled.append(items[-1])
    return sampled


def _load_system_json(task_id: str) -> SystemInspection:
    path = settings.output / task_id / "system.json"
    if path.exists():
        try:
            return SystemInspection.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValidationError) as exc:
            raise AppError("corrupt_data", "系统结果文件损坏或不可读，请重跑该任务", 503) from exc
    task = task_service.get(task_id)
    if task and task.system:
        return task.system
    raise AppError("not_found", "系统结果未生成", 404)


@router.get("/tasks/{task_id}/system", response_model=SystemInspection, operation_id="getSystemV2")
def get_system_v2(
    task_id: str = PathParam(),
    exclude_details: bool = False,
) -> SystemInspection:
    system = _load_system_json(task_id)
    if not exclude_details:
        return system
    return system.model_copy(
        update={
            "rules": [rule.model_copy(update={"metadata": {}, "metrics": [], "findings": []}) for rule in system.rules]
        }
    )


@router.get("/tasks/{task_id}/rules/{rule_code}", response_model=RuleResult, operation_id="getRuleResultV2")
def get_rule_result_v2(
    task_id: str = PathParam(),
    rule_code: str = PathParam(),
    exclude_records: bool = False,
) -> RuleResult:
    system = _load_system_json(task_id)
    rule = next((item for item in system.rules if item.code == rule_code), None)
    if rule is None:
        raise AppError("not_found", f"规则结果不存在: {rule_code}", 404)
    if not exclude_records:
        return rule
    projected = rule.model_copy()
    metadata = dict(projected.metadata)
    if metadata.get("version", 0) >= 2:
        kpi_files = []
        for kpi_file in metadata.get("kpi_files", []):
            if isinstance(kpi_file, dict):
                kpi_file = {**kpi_file, "records": []}
            kpi_files.append(kpi_file)
        metadata["kpi_files"] = kpi_files

        kpi_results = []
        for result in metadata.get("kpi_results", []):
            if not isinstance(result, dict):
                kpi_results.append(result)
                continue
            result = dict(result)
            series = result.get("series")
            if isinstance(series, list):
                result["series"] = _bounded_kpi_list(series)
            provenance = result.get("provenance")
            if isinstance(provenance, dict):
                cross_reference = provenance.get("direct_cross_reference")
                if isinstance(cross_reference, list):
                    result["provenance"] = {
                        **provenance,
                        "direct_cross_reference": _bounded_kpi_list(cross_reference),
                    }
            kpi_results.append(result)
        metadata["kpi_results"] = kpi_results
    projected.metadata = metadata
    return projected


@router.get(
    "/tasks/{task_id}/rules/{rule_code}/kpi/records",
    response_model=KpiRecordPage,
    operation_id="listKpiRecordsV2",
)
def list_kpi_records_v2(
    task_id: str = PathParam(),
    rule_code: str = PathParam(),
    metric_key: str | None = Query(default=None),
    source_file: str | None = Query(default=None),
    period_minutes: KpiPeriodMinutes | None = Query(default=None),
    status: KpiDisplayStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> KpiRecordPage:
    try:
        return list_kpi_records(
            task_id,
            rule_code,
            metric_key=metric_key,
            source_file=source_file,
            period_minutes=period_minutes,
            status=status,
            page=page,
            page_size=page_size,
        )
    except KeyError as exc:
        raise AppError("not_found", "规则结果不存在", 404) from exc


def _kpi_resource_config_dir() -> Path:
    """返回 KPI 资源库使用的配置目录。"""
    return settings.config / "kpi"


def _save_resource_upload(resource_csv: UploadFile) -> FileSystemPath:
    """把上传 CSV 落盘到临时文件，复用统一的 CSV 编码解析。"""
    suffix = FileSystemPath(resource_csv.filename or "resource.csv").suffix or ".csv"
    with NamedTemporaryFile(prefix="kpi-resource-", suffix=suffix, delete=False) as handle:
        temporary_path = FileSystemPath(handle.name)
        resource_csv.file.seek(0)
        shutil.copyfileobj(resource_csv.file, handle)
    return temporary_path


@router.get(
    "/kpi/resource-metrics",
    response_model=KpiResourceMetricPage,
    operation_id="listKpiResourceMetricsV2",
)
def list_kpi_resource_metrics_v2(
    search: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> KpiResourceMetricPage:
    try:
        return list_resource_metrics(
            config_dir=_kpi_resource_config_dir(),
            search=search,
            domain=domain,
            page=page,
            page_size=page_size,
        )
    except KpiResourceError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@router.post(
    "/kpi/resource-metrics",
    response_model=KpiResourceImportReport,
    operation_id="importKpiResourceMetricsV2",
)
async def import_kpi_resource_metrics_v2(resource_csv: UploadFile = File(...)) -> KpiResourceImportReport:
    temporary_path: FileSystemPath | None = None
    try:
        temporary_path = _save_resource_upload(resource_csv)
        report = import_resource_metrics(read_resource_csv(temporary_path), config_dir=_kpi_resource_config_dir())
        return KpiResourceImportReport.model_validate(report)
    except KpiResourceError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@router.put(
    "/kpi/resource-metrics/classification",
    response_model=KpiResourceClassificationResult,
    operation_id="classifyKpiResourceMetricsV2",
)
def classify_kpi_resource_metrics_v2(body: KpiResourceClassificationRequest) -> KpiResourceClassificationResult:
    try:
        result = classify_resource_metrics(
            body.metric_keys,
            domain=body.domain,
            expected_revision=body.expected_revision,
            config_dir=_kpi_resource_config_dir(),
        )
        return KpiResourceClassificationResult.model_validate(result)
    except KpiResourceError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@router.get("/inspectors", response_model=list[InspectorInfo], operation_id="listInspectorsV2")
def list_inspectors_v2(category: str | None = None, include_hidden: bool = False) -> list[InspectorInfo]:
    registry.load_all()
    rules = registry.all(include_hidden=include_hidden)
    if category:
        rules = [r for r in rules if r.category.value == category]
    return [
        InspectorInfo(
            code=r.code,
            name=r.name,
            category=r.category,
            severity=r.severity,
            priority=r.priority,
            rule_version=r.rule_version,
            hidden=r.hidden,
            description=r.description,
            recommendation=r.recommendation,
            source_patterns=list(r.source_patterns or []),
            outputs={
                "metrics": [m.__dict__ if hasattr(m, "__dict__") else m for m in r.outputs_metrics],
            },
            params=r.params,
        )
        for r in rules
    ]


@router.get("/dicts", response_model=DictsResponse, operation_id="listDictsV2")
def list_dicts_v2() -> DictsResponse:
    return load_dicts()


@router.put("/dicts/{dict_name}", response_model=list[DictItem], operation_id="updateDictV2")
def update_dict_v2(dict_name: str = PathParam(), body: DictUpdateRequest | None = None) -> list[DictItem]:
    if dict_name not in DICT_NAMES:
        raise AppError("invalid_dict", f"字典不存在: {dict_name}", 400)
    if body is None:
        raise AppError("bad_request", "缺少字典项", 400)
    path = settings.config / "dicts.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get(dict_name, [])
    replaced = False
    for item in items:
        if item["code"] == body.code:
            item["name"] = body.name
            replaced = True
            break
    if not replaced:
        items.append({"code": body.code, "name": body.name})
    raw[dict_name] = items
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return [DictItem(code=i["code"], name=i["name"]) for i in items]
