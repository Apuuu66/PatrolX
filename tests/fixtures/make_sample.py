"""生成完整 App Problem Scene 样例包 tests/fixtures/sample/sample.zip。"""

import gzip
import io
import json
import zipfile
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "sample"
OUTPUT = SAMPLE_DIR / "sample.zip"

BASE = "ZZapp01BCN_app_Problem_scene_333/333/app Problem scene"

FILES: dict[str, str] = {
    f"{BASE}/Alarm Information/alarm_history_202609010101137101.csv": (
        "alarm_id,created_time,cleared_time,alarm_code,severity,status,object,description\n"
        "1001,2026-09-01 10:00:01,,DB_CONNECTION_POOL_EXHAUSTED,CRITICAL,未处理,app-node-01,数据库连接池耗尽\n"
        "1002,2026-09-01 10:00:04,2026-09-01 10:00:30,SCTP_LINK_DOWN,HIGH,处理中,app-node-01,SCTP链路中断\n"
        "1003,2026-09-01 10:02:11,,CPU_USAGE_HIGH,MEDIUM,未处理,pod-app-1,CPU使用率偏高\n"
    ),
    f"{BASE}/Alarm Information/alarm_summary_202609010101137101.json": json.dumps({
        "scene_id": "333",
        "scene_name": "app Problem scene",
        "begin_time": "2026-09-01T10:00:00Z",
        "end_time": "2026-09-01T10:10:00Z",
        "total": 3,
        "unhandled": 2,
        "severity_distribution": {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1},
    }, ensure_ascii=False),
    f"{BASE}/Basic Information/system_info.ini": (
        "[app]\nname=app\nlog_level=INFO\n\n[system]\nnode_id=app-node-01\nregion=gd\ncollect_time=2026-09-01T10:00:00Z\n"
    ),
    f"{BASE}/Basic Information/version.ini": (
        "[version]\nproduct=app\nrelease=R24.1\npatch=SP03\nbuild=20260901.01\n"
    ),
    f"{BASE}/KPI/kpi_202609010101137101.csv": (
        "metric,value,unit,timestamp\n"
        "call_success_rate,93.6,%,2026-09-01T10:00:00Z\n"
        "attach_success_rate,96.8,%,2026-09-01T10:00:00Z\n"
        "setup_success_rate,95.2,%,2026-09-01T10:00:00Z\n"
    ),
    f"{BASE}/Resource/pod_cpu_mem_202609010101137101.txt": (
        "pod-app-1 cpu 890m mem 768Mi\n"
        "pod-app-2 cpu 430m mem 1200Mi\n"
        "pod-aaa-1 cpu 210m mem 512Mi\n"
    ),
    f"{BASE}/Traffic/call_stat_202609010101137101.txt": (
        "total_calls 12345\nanswer_rate 93.8\n"
    ),
}

AAA_CURRENT = (
    "2026-09-01T10:05:00Z ERROR aaa auth failure count 1\n"
    "2026-09-01T10:05:01Z ERROR aaa auth failure count 2\n"
    "2026-09-01T10:05:02Z ERROR aaa auth failure count 3\n"
    "2026-09-01T10:05:03Z ERROR aaa auth failure count 4\n"
    "2026-09-01T10:05:04Z ERROR aaa auth failure count 5\n"
    "2026-09-01T10:05:05Z ERROR aaa auth failure count 6\n"
    "2026-09-01T10:05:06Z WARN  aaa retry timer exceeded\n"
)
AAA_HISTORY = "2026-09-01T10:06:00Z ERROR aaa history cached failure\n"
APP_CURRENT = (
    "2026-09-01T10:00:00Z INFO  app service started\n"
    "2026-09-01T10:00:01Z ERROR app db connection pool exhausted retry=1\n"
    "2026-09-01T10:00:02Z ERROR app db connection pool exhausted retry=2\n"
    "2026-09-01T10:00:03Z ERROR app db connection pool exhausted retry=3\n"
    "2026-09-01T10:00:04Z ERROR app db connection pool exhausted retry=4\n"
    "2026-09-01T10:00:05Z ERROR app db connection pool exhausted retry=5\n"
    "2026-09-01T10:00:06Z ERROR app db connection pool exhausted retry=6\n"
    "2026-09-01T10:00:07Z WARN  app retry timer exceeded\n"
)
APP_ERROR = (
    "2026-09-01T10:00:08Z ERROR app sctp link down\n"
    "2026-09-01T10:00:09Z ERROR app sctp reconnect failed\n"
    "        at com.patrolx.app.SctpClient.reconnect(SctpClient.java:122)\n"
    "java.net.SocketTimeoutException: sctp reconnect timed out\n"
    "2026-09-01T10:00:10Z INFO  app service stopped\n"
)
APP_HISTORY = "2026-09-01T10:07:00Z ERROR app history connection timeout\n"

SUB_PACKAGE = io.BytesIO()
with zipfile.ZipFile(SUB_PACKAGE, "w") as zf:
    zf.writestr("AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log", AAA_CURRENT)
    zf.writestr(
        "AAAService/logs/paas-192.168.2.2/aaa_service_history_20260901011314.log.gz",
        gzip.compress(AAA_HISTORY.encode("utf-8")),
    )
    zf.writestr("AppService/logs/paas-192.168.2.2/app_service_20260901011314.log", APP_CURRENT)
    zf.writestr("AppService/logs/paas-192.168.2.2/app_service_error_20260901011314.log", APP_ERROR)
    zf.writestr(
        "AppService/logs/paas-192.168.2.2/app_service_history_20260901011314.log.gz",
        gzip.compress(APP_HISTORY.encode("utf-8")),
    )


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in FILES.items():
            zf.writestr(name, content)
        zf.writestr(f"{BASE}/Service Logs (Problem)/ServiceLog_20260901011314.zip", SUB_PACKAGE.getvalue())
    print(f"已生成样例包: {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
