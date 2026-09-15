"""生成完整 App Problem Scene 样例包 tests/fixtures/sample/sample.zip。"""

import gzip
import io
import json
import math
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "sample"
OUTPUT = SAMPLE_DIR / "sample.zip"

BASE = "ZZapp01BCN_app_Problem_scene_333/333/app Problem scene"


def _call_kpi_5_csv() -> str:
    """生成 7 天 × 4 个服务实例的完整呼叫 KPI 样例，固定数据便于测试复核。"""
    lines = [
        "设备类型：XXX",
        "测量单元名称：呼叫会话统计",
        "服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),"
        "呼叫请求次数,呼叫请求成功次数,呼叫请求失败次数,呼叫成功率,呼叫失败率,"
        "统计峰值,最大并发,x业务请求次数,x业务请求成功次数,x业务请求失败次数",
    ]
    services = [
        ("IMS-Core", "ims-node-01", 1.00, 1.00),
        ("IMS-Core", "ims-node-02", 0.88, 0.82),
        ("Access-GW", "access-node-01", 1.16, 1.22),
        ("Access-GW", "access-node-02", 1.31, 1.08),
    ]
    base = datetime(2026, 9, 8)
    for slot in range(7 * 288):
        start_at = base + timedelta(minutes=slot * 5)
        end_at = start_at + timedelta(minutes=5)
        start_text = start_at.strftime("%Y-%m-%d %H:%M:%S")
        end_text = end_at.strftime("%Y-%m-%d %H:%M:%S")
        minute_of_day = slot * 5 % 1440
        is_weekend = start_at.weekday() >= 5

        for service_idx, (service, instance, load_factor, quality_factor) in enumerate(services):
            requests = int(
                1250
                + 640
                * math.sin(2 * math.pi * (minute_of_day - 475) / 1440)
                * load_factor
                * (0.64 if is_weekend else 1.0)
                + 95 * math.sin(2 * math.pi * minute_of_day / 91)
                + service_idx * 73
                + (slot % 11) * 9
            )
            requests = max(160, requests)

            failure_rate = 0.004 + 0.0022 * abs(math.sin(2 * math.pi * minute_of_day / 175))
            # 每天设置早晚两个异常窗口，不同实例严重度不同，便于展示趋势和越限明细。
            morning_breach = 8 * 60 + 12 <= minute_of_day < 8 * 60 + 34
            evening_breach = 20 * 60 + 27 <= minute_of_day < 20 * 60 + 58
            if morning_breach or evening_breach:
                burst = 0.031 if morning_breach else 0.027
                failure_rate = burst + service_idx * 0.0037 + (slot % 4) * 0.0022
            failure_rate *= quality_factor
            failures = min(requests, max(1, round(requests * failure_rate)))
            successes = requests - failures
            success_rate = round(successes / requests * 100, 2)
            actual_failure_rate = round(failures / requests * 100, 2)

            peak = int(
                235
                + 124
                * math.sin(2 * math.pi * (minute_of_day - 497) / 1440)
                * load_factor
                * (0.61 if is_weekend else 1.0)
                + service_idx * 18
                + (slot % 17) * 4
            )
            concurrency = int(
                158
                + 86
                * math.sin(2 * math.pi * (minute_of_day - 512) / 1440)
                * load_factor
                * (0.58 if is_weekend else 1.0)
                + service_idx * 12
                + (slot % 13) * 3
            )
            x_requests = int(requests * 0.58 + service_idx * 23 + (slot % 7) * 11)
            x_failures = min(x_requests, 1 + (slot + service_idx * 3) % 6)
            x_successes = x_requests - x_failures

            trusted = True
            untrusted_reason = ""
            if service_idx == 3 and minute_of_day % 120 == 55:
                trusted = False
                untrusted_reason = "采样窗口部分回补"

            reliability = "可信" if trusted else "不可信"
            lines.append(
                f"{service},{instance},{reliability},{untrusted_reason},"
                f"{start_text},{end_text},5,"
                f"{requests},{successes},{failures},{success_rate:.2f},{actual_failure_rate:.2f}"
                f",{peak},{concurrency},{x_requests},{x_successes},{x_failures}"
            )
    return "\n".join(lines) + "\n"


FILES: dict[str, str] = {
    f"{BASE}/Alarm Information/alarm_history_202609010101137101.csv": (
        "alarm_id,created_time,cleared_time,alarm_code,severity,status,object,description\n"
        "1001,2026-09-01 10:00:01,,DB_CONNECTION_POOL_EXHAUSTED,CRITICAL,未处理,app-node-01,数据库连接池耗尽\n"
        "1002,2026-09-01 10:00:04,2026-09-01 10:00:30,SCTP_LINK_DOWN,HIGH,处理中,app-node-01,SCTP链路中断\n"
        "1003,2026-09-01 10:02:11,,CPU_USAGE_HIGH,MEDIUM,未处理,pod-app-1,CPU使用率偏高\n"
    ),
    f"{BASE}/Alarm Information/alarm_summary_202609010101137101.json": json.dumps(
        {
            "scene_id": "333",
            "scene_name": "app Problem scene",
            "begin_time": "2026-09-01T10:00:00Z",
            "end_time": "2026-09-01T10:10:00Z",
            "total": 3,
            "unhandled": 2,
            "severity_distribution": {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1},
        },
        ensure_ascii=False,
    ),
    f"{BASE}/Basic Information/system_info.ini": (
        "[app]\nname=app\nlog_level=INFO\n\n[system]\nnode_id=app-node-01\nregion=gd\ncollect_time=2026-09-01T10:00:00Z\n"
    ),
    f"{BASE}/Basic Information/version.ini": ("[version]\nproduct=app\nrelease=R24.1\npatch=SP03\nbuild=20260901.01\n"),
    f"{BASE}/KPI/kpi_202609010101137101.csv": (
        "metric,value,unit,timestamp\n"
        "call_success_rate,93.6,%,2026-09-01T10:00:00Z\n"
        "attach_success_rate,96.8,%,2026-09-01T10:00:00Z\n"
        "setup_success_rate,95.2,%,2026-09-01T10:00:00Z\n"
    ),
    f"{BASE}/Resource/pod_cpu_mem_202609010101137101.txt": (
        "pod-app-1 cpu 890m mem 768Mi\npod-app-2 cpu 430m mem 1200Mi\npod-aaa-1 cpu 210m mem 512Mi\n"
    ),
    f"{BASE}/Traffic/call_stat_202609010101137101.txt": ("total_calls 12345\nanswer_rate 93.8\n"),
    "kpi/kpi-call-5.csv": _call_kpi_5_csv(),
}

# 保留样例包中原有的其他 KPI 文件，便于比较不同格式和解析容错。
FILES.update(
    {
        f"{BASE}/KPI/kpi-call-15.csv": (
            "呼叫会话统计\n"
            "测量周期,开始时间,结束时间,呼叫请求,请求成功,请求失败,统计峰值,最大并发\n"
            "15,2026-09-01 10:00:00,2026-09-01 10:15:00,1200,1170,30,100,88\n"
            "15,2026-09-01 10:15:00,2026-09-01 10:30:00,1350,1300,50,105,92\n"
            "15,2026-09-01 10:30:00,2026-09-01 10:45:00,1500,1440,60,120,98\n"
        ),
        f"{BASE}/KPI/kpi-api-15.csv": (
            "API 统计\n"
            "测量周期,开始时间,结束时间,请求总数,成功数\n"
            "15,2026-09-01 10:00:00,2026-09-01 10:15:00,5000,4800\n"
            "15,bad-time,2026-09-01 10:30:00,5200,4950\n"
        ),
    }
)

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
