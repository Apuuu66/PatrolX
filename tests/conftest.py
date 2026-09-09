"""测试隔离：运行时目录与 SQLite 指向临时目录。"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="patrolx-test-"))
os.environ["PATROLX_OUTPUT_DIR"] = str(_TMP / "output")
os.environ["PATROLX_UPLOADS_DIR"] = str(_TMP / "uploads")
os.environ["PATROLX_SQLITE_PATH"] = str(_TMP / "patrolx.db")
os.environ["PATROLX_CONFIG_DIR"] = "deploy/config"
