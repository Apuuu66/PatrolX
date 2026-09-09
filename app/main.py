"""PatrolX 统一入口。

- 直接执行 `python main.py`：本地离线全流程（M1 落地）。
- 作为模块导入（`uvicorn app.main:app`）：FastAPI 在线服务。
"""

import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from app import __version__
from app.api.router import AppError, router
from app.core.logging import configure_logging, get_logger
from app.core.metrics import render_metrics
from app.models.schemas import Error

_logging_configured = False


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
    app.include_router(router)

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

    @app.exception_handler(AppError)
    async def app_error_handler(_request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=Error(code=exc.code, message=exc.message).model_dump(),
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
    """本地离线全流程入口（M1 实现：扫描 uploads/ → 解压 → 运行全部规则 → 契约数据与报告）。"""
    from app.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
