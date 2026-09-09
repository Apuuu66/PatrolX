"""生成样例数据包 tests/fixtures/sample/sample.zip（含嵌套子包），用于本地流程验证。"""

import io
import zipfile
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "sample"
OUTPUT = SAMPLE_DIR / "sample.zip"

FILES: dict[str, str] = {
    "logs/core/error_20260909.log": (
        "2026-09-09T10:00:00Z INFO  core init ok\n"
        "2026-09-09T10:00:01Z ERROR core db connection pool exhausted\n"
        "2026-09-09T10:00:02Z ERROR core db connection pool exhausted\n"
        "2026-09-09T10:00:03Z WARN  core retry timer exceeded\n"
        "2026-09-09T10:00:04Z ERROR core sctp link down\n"
        "2026-09-09T10:00:05Z INFO  core sctp link recovered\n"
    ),
    "logs/app/run.log": ("2026-09-09T10:00:00Z INFO  app started\n2026-09-09T10:00:10Z INFO  app heartbeat ok\n"),
    "kpi/kpi_20260909.csv": "metric,value\ncall_success_rate,99.2\nattach_success_rate,96.5\n",
    "alarm/alarm_export_20260909.txt": (
        "ALARM 2026-09-09 10:00:01 1001 数据库连接池耗尽 CRITICAL 未处理\n"
        "ALARM 2026-09-09 10:00:04 1002 SCTP链路中断 HIGH 处理中\n"
    ),
    "config/app.conf": "[app]\nname=PatrolX-Demo\nlog_level=INFO\n",
    "resource/pod_cpu_mem.txt": "pod-1 cpu 450m mem 512Mi\npod-2 cpu 890m mem 768Mi\npod-3 cpu 620m mem 2048Mi\n",
    "traffic/call_stat.txt": "total_calls 12345\nanswer_rate 94.8\n",
}

SUB_PACKAGE = io.BytesIO()
with zipfile.ZipFile(SUB_PACKAGE, "w") as zf:
    zf.writestr(
        "logs/aaa_service.log",
        "2026-09-09T10:05:00Z ERROR aaa auth failure count 3\n2026-09-09T10:05:01Z ERROR aaa auth failure count 4\n",
    )


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in FILES.items():
            zf.writestr(name, content)
        zf.writestr("AAAService.zip", SUB_PACKAGE.getvalue())
    print(f"已生成样例包: {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
