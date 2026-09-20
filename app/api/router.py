"""在线模式 API 路由。"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any

import yaml
from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
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
    KpiCapacityRulePageV4,
    KpiCapacityRuleRequestV4,
    KpiCapacityRuleV4,
    KpiClassificationAuditPageV3,
    KpiClassificationCluePageV4,
    KpiClueStatusV4,
    KpiCommonConfigRequestV4,
    KpiCommonConfigV4,
    KpiConfigAuditPageV4,
    KpiConfigAuditV4,
    KpiConfigDeleteResultV4,
    KpiConfigEntityTypeV4,
    KpiDisplayRulePageV4,
    KpiDisplayRuleRequestV4,
    KpiDisplayRuleV4,
    KpiDisplayStatus,
    KpiMetricRulePageV4,
    KpiMetricRuleRequestV4,
    KpiMetricRuleV4,
    KpiPeriodMinutes,
    KpiRecordPage,
    KpiRegisteredDomainV4,
    KpiResourceClassificationRequestV3,
    KpiResourceClassificationResultV3,
    KpiResourceMetricPageV3,
    KpiSourceTypeV4,
    KpiTaskCatalogSnapshot,
    KpiThresholdPageV4,
    KpiThresholdRequestV4,
    KpiThresholdV4,
    LogEntry,
    LoginRequestV1,
    LoginResponseV1,
    OverviewSummary,
    RebuildRequest,
    RerunRequest,
    RuleResult,
    SystemInspection,
    TaskCreated,
    TaskListResponse,
    TaskLogs,
    UserInfoV1,
)
from app.services.auth import AuthError, AuthSession, get_current_user, login, logout, require_role
from app.services.kpi_classification_clues import KpiClassificationClueError, list_classification_clues
from app.services.kpi_config import (
    KpiConfigError,
    create_threshold,
    delete_capacity_rule,
    delete_display_rule,
    delete_metric_rule,
    delete_threshold,
    get_common_config,
    get_metric_rule,
    get_threshold,
    list_capacity_rules,
    list_config_audits,
    list_display_rules,
    list_metric_rules,
    list_thresholds,
    update_common_config,
    update_threshold,
    upsert_capacity_rule,
    upsert_display_rule,
    upsert_metric_rule,
)
from app.services.kpi_records import list_kpi_records
from app.services.kpi_resources import (
    KpiResourceError,
    classify_resource_metrics,
    list_classification_audits,
    list_resource_metrics,
)
from app.services.overview import build_overview
from app.services.tasks import DeleteResult, TaskDeleteError, TaskRebuildError, task_service

v1_router = APIRouter(prefix="/api/v1")
router = APIRouter(prefix="/api/v2")
v3_router = APIRouter(prefix="/api/v3")
v4_router = APIRouter(prefix="/api/v4")
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


def _convert_kpi_config_error(exc: KpiConfigError) -> AppError:
    return AppError(exc.code, exc.message, exc.status_code, exc.detail)


def _convert_kpi_clue_error(exc: KpiClassificationClueError) -> AppError:
    return AppError(exc.code, exc.message, exc.status_code)


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
def rerun_task_v2(
    task_id: str = PathParam(),
    body: RerunRequest | None = None,
) -> TaskCreated:
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


@router.post(
    "/tasks/{task_id}/rebuild",
    response_model=TaskCreated,
    status_code=202,
    operation_id="rebuildTaskV2",
)
def rebuild_task_v2(
    response: Response,
    body: RebuildRequest,
    task_id: str = PathParam(),
) -> TaskCreated:
    try:
        accepted = task_service.rebuild(task_id, body)
    except TaskRebuildError as exc:
        raise AppError(exc.code, exc.message, exc.status_code) from exc
    if not accepted:
        raise AppError("not_found", "任务不存在", 404)
    response.headers["Location"] = f"/api/v2/tasks/{task_id}"
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


@v3_router.get(
    "/kpi/resource-metrics",
    response_model=KpiResourceMetricPageV3,
    operation_id="listKpiResourceMetricsV3",
)
def list_kpi_resource_metrics_v3(
    search: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    include_missing: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> KpiResourceMetricPageV3:
    try:
        return list_resource_metrics(
            search=search,
            domain=domain,
            include_missing=include_missing,
            page=page,
            page_size=page_size,
        )
    except KpiResourceError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@v3_router.put(
    "/kpi/resource-metrics/classification",
    response_model=KpiResourceClassificationResultV3,
    operation_id="classifyKpiResourceMetricsV3",
)
def classify_kpi_resource_metrics_v3(
    body: KpiResourceClassificationRequestV3, _auth: AuthSession = Depends(require_role("admin"))
) -> KpiResourceClassificationResultV3:
    try:
        result = classify_resource_metrics(
            body.metric_keys,
            domain=body.domain,
            operator=body.operator,
        )
        return KpiResourceClassificationResultV3.model_validate(result)
    except KpiResourceError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@v3_router.get(
    "/kpi/resource-metrics/classification-audits",
    response_model=KpiClassificationAuditPageV3,
    operation_id="listKpiClassificationAuditsV3",
)
def list_kpi_classification_audits_v3(
    metric_key: str | None = Query(default=None),
    operator: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> KpiClassificationAuditPageV3:
    try:
        return list_classification_audits(
            metric_key=metric_key,
            operator=operator,
            domain=domain,
            page=page,
            page_size=page_size,
        )
    except KpiResourceError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@v3_router.get(
    "/tasks/{task_id}/kpi/catalog-snapshot",
    response_model=KpiTaskCatalogSnapshot,
    operation_id="getKpiCatalogSnapshotV3",
)
def get_kpi_catalog_snapshot_v3(task_id: str = PathParam()) -> KpiTaskCatalogSnapshot:
    if not (settings.output / task_id / "task.json").is_file():
        raise AppError("not_found", "任务不存在", 404)
    snapshot_path = settings.output / task_id / "kpi" / "kpi_catalog_snapshot.json"
    if not snapshot_path.is_file():
        raise AppError("kpi_snapshot_missing", "任务 KPI 配置快照缺失", 409)
    try:
        return KpiTaskCatalogSnapshot.model_validate_json(snapshot_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise AppError("kpi_snapshot_invalid", "任务 KPI 配置快照损坏", 500) from exc


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
def update_dict_v2(
    dict_name: str = PathParam(),
    body: DictUpdateRequest | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> list[DictItem]:
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


# ---- /api/v4 KPI 动态口径配置契约路由 ----


@v4_router.get("/kpi/config/metric-rules", response_model=KpiMetricRulePageV4, operation_id="listKpiMetricRulesV4")
def list_kpi_metric_rules_v4(
    search: str | None = None,
    source_type: KpiSourceTypeV4 | None = None,
    domain: KpiRegisteredDomainV4 | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> KpiMetricRulePageV4:
    return list_metric_rules(
        search=search,
        source_type=source_type.value if source_type else None,
        domain=domain.value if domain else None,
        page=page,
        page_size=page_size,
    )


@v4_router.get(
    "/kpi/config/metric-rules/{metric_key}", response_model=KpiMetricRuleV4, operation_id="getKpiMetricRuleV4"
)
def get_kpi_metric_rule_v4(metric_key: str = PathParam()) -> KpiMetricRuleV4:
    try:
        return get_metric_rule(metric_key)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.put(
    "/kpi/config/metric-rules/{metric_key}", response_model=KpiMetricRuleV4, operation_id="upsertKpiMetricRuleV4"
)
def upsert_kpi_metric_rule_v4(
    metric_key: str = PathParam(),
    body: KpiMetricRuleRequestV4 | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiMetricRuleV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        return upsert_metric_rule(metric_key, body)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.delete(
    "/kpi/config/metric-rules/{metric_key}",
    response_model=KpiConfigDeleteResultV4,
    operation_id="deleteKpiMetricRuleV4",
)
def delete_kpi_metric_rule_v4(
    metric_key: str = PathParam(),
    operator: str = Query(min_length=1),
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiConfigDeleteResultV4:
    try:
        return delete_metric_rule(metric_key, operator)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.get("/kpi/config/thresholds", response_model=KpiThresholdPageV4, operation_id="listKpiThresholdsV4")
def list_kpi_thresholds_v4(
    domain: KpiRegisteredDomainV4 | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> KpiThresholdPageV4:
    return list_thresholds(domain=domain.value if domain else None, search=search, page=page, page_size=page_size)


@v4_router.post(
    "/kpi/config/thresholds", response_model=KpiThresholdV4, status_code=202, operation_id="createKpiThresholdV4"
)
def create_kpi_threshold_v4(
    response: Response, body: KpiThresholdRequestV4 | None = None, _auth: AuthSession = Depends(require_role("admin"))
) -> KpiThresholdV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        item = create_threshold(body)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc
    response.headers["Location"] = f"/api/v4/kpi/config/thresholds/{item.id}"
    return item


@v4_router.get("/kpi/config/thresholds/{threshold_id}", response_model=KpiThresholdV4, operation_id="getKpiThresholdV4")
def get_kpi_threshold_v4(threshold_id: int = PathParam()) -> KpiThresholdV4:
    try:
        return get_threshold(threshold_id)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.put(
    "/kpi/config/thresholds/{threshold_id}", response_model=KpiThresholdV4, operation_id="updateKpiThresholdV4"
)
def update_kpi_threshold_v4(
    threshold_id: int = PathParam(),
    body: KpiThresholdRequestV4 | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiThresholdV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        return update_threshold(threshold_id, body)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.delete(
    "/kpi/config/thresholds/{threshold_id}",
    response_model=KpiConfigDeleteResultV4,
    operation_id="deleteKpiThresholdV4",
)
def delete_kpi_threshold_v4(
    threshold_id: int = PathParam(),
    operator: str = Query(min_length=1),
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiConfigDeleteResultV4:
    try:
        return delete_threshold(threshold_id, operator)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.get(
    "/kpi/config/capacity-rules", response_model=KpiCapacityRulePageV4, operation_id="listKpiCapacityRulesV4"
)
def list_kpi_capacity_rules_v4(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)
) -> KpiCapacityRulePageV4:
    return list_capacity_rules(page=page, page_size=page_size)


@v4_router.post(
    "/kpi/config/capacity-rules",
    response_model=KpiCapacityRuleV4,
    status_code=202,
    operation_id="createKpiCapacityRuleV4",
)
def create_kpi_capacity_rule_v4(
    response: Response,
    body: KpiCapacityRuleRequestV4 | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiCapacityRuleV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        item = upsert_capacity_rule(body)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc
    response.headers["Location"] = f"/api/v4/kpi/config/capacity-rules/{item.id}"
    return item


@v4_router.put(
    "/kpi/config/capacity-rules/{capacity_rule_id}",
    response_model=KpiCapacityRuleV4,
    operation_id="updateKpiCapacityRuleV4",
)
def update_kpi_capacity_rule_v4(
    capacity_rule_id: int = PathParam(),
    body: KpiCapacityRuleRequestV4 | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiCapacityRuleV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        return upsert_capacity_rule(body, capacity_rule_id)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.delete(
    "/kpi/config/capacity-rules/{capacity_rule_id}",
    response_model=KpiConfigDeleteResultV4,
    operation_id="deleteKpiCapacityRuleV4",
)
def delete_kpi_capacity_rule_v4(
    capacity_rule_id: int = PathParam(),
    operator: str = Query(min_length=1),
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiConfigDeleteResultV4:
    try:
        return delete_capacity_rule(capacity_rule_id, operator)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.get("/kpi/config/display-rules", response_model=KpiDisplayRulePageV4, operation_id="listKpiDisplayRulesV4")
def list_kpi_display_rules_v4(
    domain: KpiRegisteredDomainV4 | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> KpiDisplayRulePageV4:
    return list_display_rules(domain=domain.value if domain else None, page=page, page_size=page_size)


@v4_router.post(
    "/kpi/config/display-rules",
    response_model=KpiDisplayRuleV4,
    status_code=202,
    operation_id="createKpiDisplayRuleV4",
)
def create_kpi_display_rule_v4(
    response: Response, body: KpiDisplayRuleRequestV4 | None = None, _auth: AuthSession = Depends(require_role("admin"))
) -> KpiDisplayRuleV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        item = upsert_display_rule(body)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc
    response.headers["Location"] = f"/api/v4/kpi/config/display-rules/{item.id}"
    return item


@v4_router.put(
    "/kpi/config/display-rules/{display_rule_id}",
    response_model=KpiDisplayRuleV4,
    operation_id="updateKpiDisplayRuleV4",
)
def update_kpi_display_rule_v4(
    display_rule_id: int = PathParam(),
    body: KpiDisplayRuleRequestV4 | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiDisplayRuleV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        return upsert_display_rule(body, display_rule_id)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.delete(
    "/kpi/config/display-rules/{display_rule_id}",
    response_model=KpiConfigDeleteResultV4,
    operation_id="deleteKpiDisplayRuleV4",
)
def delete_kpi_display_rule_v4(
    display_rule_id: int = PathParam(),
    operator: str = Query(min_length=1),
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiConfigDeleteResultV4:
    try:
        return delete_display_rule(display_rule_id, operator)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.get("/kpi/config/common", response_model=KpiCommonConfigV4, operation_id="getKpiCommonConfigV4")
def get_kpi_common_config_v4() -> KpiCommonConfigV4:
    try:
        return get_common_config()
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.put("/kpi/config/common", response_model=KpiCommonConfigV4, operation_id="updateKpiCommonConfigV4")
def update_kpi_common_config_v4(
    body: KpiCommonConfigRequestV4 | None = None, _auth: AuthSession = Depends(require_role("admin"))
) -> KpiCommonConfigV4:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        return update_common_config(body)
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc


@v4_router.get("/kpi/config/audits", response_model=KpiConfigAuditPageV4, operation_id="listKpiConfigAuditsV4")
def list_kpi_config_audits_v4(
    entity_type: KpiConfigEntityTypeV4 | None = None,
    operator: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> KpiConfigAuditPageV4:
    try:
        rows, total, version = list_config_audits(
            entity_type=entity_type.value if entity_type else None,
            operator=operator,
            page=page,
            page_size=page_size,
        )
    except KpiConfigError as exc:
        raise _convert_kpi_config_error(exc) from exc
    items = [KpiConfigAuditV4.model_validate(row, from_attributes=True) for row in rows]
    return KpiConfigAuditPageV4(items=items, total=total, page=page, page_size=page_size, rule_config_version=version)


@v4_router.get(
    "/tasks/{task_id}/kpi/classification-clues",
    response_model=KpiClassificationCluePageV4,
    operation_id="listKpiClassificationCluesV4",
)
def list_kpi_classification_clues_v4(
    task_id: str = PathParam(),
    clue_status: KpiClueStatusV4 | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> KpiClassificationCluePageV4:
    try:
        return list_classification_clues(
            task_id,
            clue_status=clue_status.value if clue_status else None,
            search=search,
            page=page,
            page_size=page_size,
        )
    except KpiClassificationClueError as exc:
        raise _convert_kpi_clue_error(exc) from exc


# --- Auth (v1) ---


@v1_router.post("/auth/login", response_model=LoginResponseV1, operation_id="loginV1")
def auth_login(body: LoginRequestV1) -> LoginResponseV1:
    try:
        result = login(body.username, body.password)
    except AuthError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return LoginResponseV1(**result)


@v1_router.post("/auth/logout", operation_id="logoutV1")
def auth_logout(authorization: str | None = Header(None)) -> dict:
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    try:
        logout(token)
    except AuthError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return {"ok": True}


@v1_router.get("/auth/me", response_model=UserInfoV1, operation_id="getMeV1")
def auth_me(user=Depends(get_current_user)) -> UserInfoV1:
    return UserInfoV1(username=user.username, role=user.role)
