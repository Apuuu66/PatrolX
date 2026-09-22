"""在线模式 API 路由。"""

import hashlib
import io
import json
import os
import shutil
import tempfile
from pathlib import Path, PureWindowsPath

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
    KpiMeasurementBindingList,
    KpiMeasurementBindingStatusRequest,
    KpiMeasurementDerived,
    KpiMeasurementDerivedCreateRequest,
    KpiMeasurementEnabledRequest,
    KpiMeasurementImportResult,
    KpiMeasurementUnitList,
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
    UserCreateRequestV1,
    UserInfoV1,
    UserListResponseV1,
    UserPasswordRequestV1,
    UserRoleRequestV1,
    UserV1,
)
from app.services.auth import (
    AuthError,
    AuthSession,
    create_user,
    delete_user,
    get_current_user,
    list_users,
    login,
    logout,
    require_role,
    reset_user_password,
    update_user_role,
)
from app.services.kpi_measurement_units import (
    KpiMeasurementError,
    create_measurement_derived,
    import_resource_csv,
    list_measurement_bindings,
    list_measurement_units,
    set_measurement_binding_status,
    set_measurement_unit_enabled,
)
from app.services.overview import build_overview
from app.services.store import load_rule_result
from app.services.tasks import DeleteResult, TaskDeleteError, TaskRebuildError, task_service

v1_router = APIRouter(prefix="/api/v1")
router = APIRouter(prefix="/api/v2")
v3_router = APIRouter(prefix="/api/v3")
v4_router = APIRouter(prefix="/api/v4")
v5_router = APIRouter(prefix="/api/v5")
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
) -> RuleResult:
    registry.load_all()
    if rule_code not in {rule.code for rule in registry.all()}:
        raise AppError("not_found", "规则结果不存在", 404)
    rule = load_rule_result(settings.output, task_id, rule_code)
    if rule is None:
        try:
            system = _load_system_json(task_id)
            rule = next((item for item in system.rules if item.code == rule_code), None)
        except AppError:
            rule = None
    if rule is None:
        raise AppError("not_found", "规则结果不存在", 404)
    return rule


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


# --- Measurement units (v5) ---


@v5_router.post(
    "/kpi/measurement-units/import",
    response_model=KpiMeasurementImportResult,
    operation_id="importKpiMeasurementUnitsV5",
)
async def import_kpi_measurement_units_v5(
    file: UploadFile = File(), _auth: AuthSession = Depends(require_role("admin"))
) -> KpiMeasurementImportResult:
    content = await file.read()
    try:
        result = import_resource_csv(io.BytesIO(content))
    except KpiMeasurementError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return KpiMeasurementImportResult.model_validate(result)


@v5_router.get(
    "/kpi/measurement-units",
    response_model=KpiMeasurementUnitList,
    operation_id="listKpiMeasurementUnitsV5",
)
def list_kpi_measurement_units_v5(
    search: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> KpiMeasurementUnitList:
    result = list_measurement_units(search=search, enabled=enabled)
    start = (page - 1) * page_size
    items = result["items"][start : start + page_size]
    return KpiMeasurementUnitList(total=result["total"], items=items)


@v5_router.patch(
    "/kpi/measurement-units/{resource_id}",
    response_model=dict,
    operation_id="setKpiMeasurementUnitEnabledV5",
)
def set_kpi_measurement_unit_enabled_v5(
    resource_id: str = PathParam(),
    body: KpiMeasurementEnabledRequest | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> dict:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        return set_measurement_unit_enabled(resource_id, body.enabled)
    except KpiMeasurementError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@v5_router.get(
    "/kpi/measurement-bindings",
    response_model=KpiMeasurementBindingList,
    operation_id="listKpiMeasurementBindingsV5",
)
def list_kpi_measurement_bindings_v5(
    measurement_unit_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> KpiMeasurementBindingList:
    result = list_measurement_bindings(measurement_unit_id, status, search)
    start = (page - 1) * page_size
    items = result["items"][start : start + page_size]
    return KpiMeasurementBindingList(total=result["total"], items=items)


@v5_router.patch(
    "/kpi/measurement-bindings/{binding_id}",
    response_model=dict,
    operation_id="setKpiMeasurementBindingStatusV5",
)
def set_kpi_measurement_binding_status_v5(
    binding_id: int = PathParam(),
    body: KpiMeasurementBindingStatusRequest | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> dict:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        return set_measurement_binding_status(binding_id, body.status, body.enabled)
    except KpiMeasurementError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@v5_router.post(
    "/kpi/measurement-derived",
    response_model=KpiMeasurementDerived,
    status_code=201,
    operation_id="createKpiMeasurementDerivedV5",
)
def create_kpi_measurement_derived_v5(
    body: KpiMeasurementDerivedCreateRequest | None = None,
    _auth: AuthSession = Depends(require_role("admin")),
) -> KpiMeasurementDerived:
    if body is None:
        raise AppError("invalid_request", "请求体不能为空", 400)
    try:
        result = create_measurement_derived(
            body.measurement_unit_id,
            body.metric_resource_id,
            body.numerator_metric_id,
            body.denominator_metric_id,
        )
    except KpiMeasurementError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return KpiMeasurementDerived.model_validate(result)


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


@v1_router.get("/users", response_model=UserListResponseV1, operation_id="listUsersV1")
def list_users_v1(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _auth: AuthSession = Depends(require_role("admin")),
) -> UserListResponseV1:
    try:
        return UserListResponseV1(**list_users(page, page_size))
    except AuthError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc


@v1_router.post("/users", response_model=UserV1, status_code=201, operation_id="createUserV1")
def create_user_v1(
    body: UserCreateRequestV1,
    _auth: AuthSession = Depends(require_role("admin")),
) -> UserV1:
    try:
        user = create_user(body.username, body.password, body.role)
    except AuthError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return UserV1(**user)


@v1_router.patch("/users/{username}", response_model=UserV1, operation_id="updateUserV1")
def update_user_v1(
    body: UserRoleRequestV1,
    username: str = PathParam(),
    auth: AuthSession = Depends(require_role("admin")),
) -> UserV1:
    try:
        user = update_user_role(username, body.role, auth.username)
    except AuthError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return UserV1(**user)


@v1_router.put("/users/{username}/password", response_model=UserV1, operation_id="resetUserPasswordV1")
def reset_user_password_v1(
    body: UserPasswordRequestV1,
    username: str = PathParam(),
    _auth: AuthSession = Depends(require_role("admin")),
) -> UserV1:
    try:
        user = reset_user_password(username, body.new_password)
    except AuthError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return UserV1(**user)


@v1_router.delete("/users/{username}", status_code=204, operation_id="deleteUserV1")
def delete_user_v1(
    username: str = PathParam(),
    auth: AuthSession = Depends(require_role("admin")),
) -> Response:
    try:
        delete_user(username, auth.username)
    except AuthError as exc:
        raise AppError(exc.code, exc.message, exc.status_code, exc.detail) from exc
    return Response(status_code=204)
