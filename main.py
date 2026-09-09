"""PatrolX 统一入口（项目根目录）。

- `python main.py`：本地离线全流程（扫描 uploads/ → 解压 → 运行全部规则 → 契约数据与报告）。
- `uvicorn app.main:app`：在线 API 服务。
"""

from app.main import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
