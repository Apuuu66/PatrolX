"""PatrolX 统一入口。

- 直接执行 `python main.py`：运行 `local_run/` 目录下全部本地调试数据包。
- 作为模块导入（`uvicorn app.main:app`）：FastAPI 在线服务。
"""

import time

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app import __version__
from app.api.router import AppError, router, v1_router, v3_router, v4_router
from app.core.logging import configure_logging, get_logger
from app.core.metrics import render_metrics
from app.models.schemas import Error
from app.services.auth import AuthError

_logging_configured = False


def _validation_detail(exc: RequestValidationError) -> dict[str, object]:
    """将 Pydantic 校验错误转换为可 JSON 化的统一 detail。"""
    errors = [
        {
            "loc": [str(item) for item in error.get("loc", [])],
            "msg": str(error.get("msg", "校验失败")),
            "type": str(error.get("type", "value_error")),
        }
        for error in exc.errors()
    ]
    return {"errors": errors}


def create_app() -> FastAPI:
    global _logging_configured
    if not _logging_configured:
        configure_logging()
        _logging_configured = True
    log = get_logger("patrolx.access")

    app = FastAPI(
        title="PatrolX API",
        version="1.0.0",
        description="PatrolX 巡检系统接口契约（离线巡检：任务/系统/规则/字典）",
    )
    app.include_router(v1_router)
    app.include_router(router)
    app.include_router(v3_router)
    app.include_router(v4_router)

    @app.middleware("http")
    async def access_log(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    @app.exception_handler(AuthError)
    async def auth_error_handler(_request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(AppError)
    async def app_error_handler(_request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=Error(code=exc.code, message=exc.message, detail=exc.detail).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=Error(
                code="validation_error",
                message="请求参数校验失败",
                detail=_validation_detail(exc),
            ).model_dump(),
        )

    @app.get("/healthz", tags=["system"], operation_id="healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/metrics", tags=["system"], operation_id="metrics")
    def metrics() -> Response:
        data, content_type = render_metrics()
        return Response(content=data, media_type=content_type)

    return app


app = create_app()


def main() -> int:
    """本地调试入口：扫描 local_run/ 并逐个执行全部数据包。"""
    from app.local_run import run_local_packages

    return run_local_packages()


if __name__ == "__main__":
    raise SystemExit(main())
