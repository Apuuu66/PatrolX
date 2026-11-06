"""API 层统一业务错误。"""

from __future__ import annotations


class AppError(Exception):
    """可安全映射为统一错误响应的业务异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail
