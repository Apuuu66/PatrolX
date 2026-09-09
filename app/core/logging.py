"""structlog 结构化日志配置：生产 JSON、开发彩色控制台，统一访问日志与业务日志。"""

import logging
import os
import sys

import structlog


def _resolve_level(env: str) -> str:
    level = os.environ.get("PATROLX_LOG_LEVEL", "DEBUG" if env == "dev" else "INFO")
    return level.upper()


def configure_logging() -> None:
    env = os.environ.get("PATROLX_ENV", "dev")
    json_logs = os.environ.get("PATROLX_LOG_JSON", "0") == "1"
    level = _resolve_level(env)
    if json_logs or env == "production":
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    logging.basicConfig(stream=sys.stderr, level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "patrolx") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
