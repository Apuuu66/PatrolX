"""v1 路由实现（在线模式）。"""

import json
import shutil

import yaml
from fastapi import APIRouter, File, Form, UploadFile
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse, Response

from app.cli import generate_task_id
from app.core.config import settings
from app.core.dicts import load_dicts
from app.inspectors.registry import registry
from app.models.schemas import (
    DictItem,
    DictsResponse,
    DictUpdateRequest,
    InspectionTask,
    InspectorInfo,
    LogEntry,
    OverviewSummary,
    RerunRequest,
    RuleResult,
    SystemInspection,
    TaskCreated,
    TaskListResponse,
    TaskLogs,
)
from app.services.overview import build_overview
from app.services.tasks import task_service

router = APIRouter(prefix="/api/v1")
DICT_NAMES = ("province", "operator", "product", "version")


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@router.post("/tasks", response_model=TaskCreated, status_code=202, operation_id="createTask")
async def create_task(
    package_file: UploadFile = File(...),
    name: str | None = Form(None),
    version: str | None = Form(None),
    province: str | None = Form(None),
    operator: str | None = Form(None),
    product: str | None = Form(None),
    force: bool = False,
) -> TaskCreated:
    filename = (package_file.filename or "package.zip").rsplit("/", 1)[-1]
    if not filename.lower().endswith((".zip", ".tar", ".gz", ".tgz")):
        raise AppError("invalid_package", "仅支持 zip/tar.gz 数据包", 400)
    task_id = generate_task_id(filename)
    if task_service.exists(task_id):
        if not force:
            raise AppError("duplicate_package", "已存在相同包的任务", 409)
        task_service.delete(task_id)
    created = task_service.reserve(filename, name, province, operator, version, product=product)
    task_dir = settings.uploads / created.task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    dest = task_dir / filename
    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    with dest.open("wb") as out:
        while chunk := await package_file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                shutil.rmtree(task_dir, ignore_errors=True)
                task_service.discard(created.task_id)
                raise AppError("package_too_large", f"数据包超过 {settings.max_upload_mb}MB 限制", 413)
            out.write(chunk)
    task_service.submit(created.task_id)
    return created


@router.get("/overview", response_model=OverviewSummary, operation_id="getOverview")
def get_overview() -> OverviewSummary:
    return build_overview()


@router.get("/tasks", response_model=TaskListResponse, operation_id="listTasks")
def list_tasks(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> TaskListResponse:
    items, total = task_service.list_tasks(page, page_size, status)
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/tasks/{task_id}", response_model=InspectionTask, operation_id="getTask")
def get_task(task_id: str = PathParam()) -> InspectionTask:
    task = task_service.get(task_id)
    if task is None:
        raise AppError("not_found", "任务不存在", 404)
    return task


@router.delete("/tasks/{task_id}", status_code=204, operation_id="deleteTask")
def delete_task(task_id: str = PathParam()) -> Response:
    if not task_service.delete(task_id):
        raise AppError("not_found", "任务不存在", 404)
    return Response(status_code=204)


@router.post("/tasks/{task_id}/rerun", response_model=TaskCreated, status_code=202, operation_id="rerunTask")
def rerun_task(task_id: str = PathParam(), body: RerunRequest | None = None) -> TaskCreated:
    codes = body.rule_codes if body else None
    if codes:
        registry.load_all()
        unknown = [c for c in codes if c not in registry.codes()]
        if unknown:
            raise AppError("unknown_rule", f"规则不存在: {', '.join(unknown)}", 404)
    if not task_service.rerun(task_id, codes):
        raise AppError("not_found", "任务不存在或数据包缺失", 404)
    return TaskCreated(task_id=task_id)


@router.get("/tasks/{task_id}/report", response_class=HTMLResponse, operation_id="getReport")
def get_report(task_id: str = PathParam()) -> HTMLResponse:
    report = settings.output / task_id / "report.html"
    if not report.exists():
        raise AppError("not_found", "报告未生成", 404)
    return HTMLResponse(report.read_text(encoding="utf-8"))


@router.get("/tasks/{task_id}/logs", response_model=TaskLogs, operation_id="getTaskLogs")
def get_task_logs(task_id: str = PathParam()) -> TaskLogs:
    log_file = settings.output / task_id / "execution.log"
    if not log_file.exists():
        raise AppError("not_found", "执行日志不存在", 404)
    entries = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
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
    return TaskLogs(task_id=task_id, entries=entries)


def _load_system_json(task_id: str) -> SystemInspection:
    path = settings.output / task_id / "system.json"
    if not path.exists():
        raise AppError("not_found", "系统结果未生成", 404)
    return SystemInspection.model_validate(json.loads(path.read_text(encoding="utf-8")))


@router.get("/tasks/{task_id}/system", response_model=SystemInspection, operation_id="getSystem")
def get_system(task_id: str = PathParam()) -> SystemInspection:
    return _load_system_json(task_id)


@router.get("/tasks/{task_id}/rules/{rule_code}", response_model=RuleResult, operation_id="getRuleResult")
def get_rule_result(task_id: str = PathParam(), rule_code: str = PathParam()) -> RuleResult:
    system = _load_system_json(task_id)
    for rule in system.rules:
        if rule.code == rule_code:
            return rule
    raise AppError("not_found", f"规则结果不存在: {rule_code}", 404)


@router.get("/inspectors", response_model=list[InspectorInfo], operation_id="listInspectors")
def list_inspectors(category: str | None = None, include_hidden: bool = False) -> list[InspectorInfo]:
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


@router.get("/dicts", response_model=DictsResponse, operation_id="listDicts")
def list_dicts() -> DictsResponse:
    return load_dicts()


@router.put("/dicts/{dict_name}", response_model=list[DictItem], operation_id="updateDict")
def update_dict(dict_name: str = PathParam(), body: DictUpdateRequest | None = None) -> list[DictItem]:
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
