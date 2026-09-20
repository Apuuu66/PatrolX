#!/usr/bin/env python3
"""创建默认管理员；目标管理员已存在时直接重置密码。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["create-default-admin", *sys.argv[1:]]))
