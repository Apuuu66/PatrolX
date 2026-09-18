"""生成单日 App Problem Scene 样例包 tests/fixtures/sample/sample.zip。"""

import gzip
import io
import math
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "sample"
OUTPUT = SAMPLE_DIR / "sample.zip"

BASE = "ZZapp01BCN_app_Problem_scene_333/333/app Problem scene"


def _call_kpi_5_csv() -> str:
    """生成 1 天 × 6 个服务实例的呼叫 KPI 样例，覆盖早晚异常窗口与解析容错。"""
    lines = [
        "设备类型：XXX",
        "测量单元名称：呼叫会话统计",
        "服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),"
        "呼叫请求次数,呼叫请求成功次数,呼叫请求失败次数,呼叫成功率,呼叫失败率,"
        "统计峰值,最大并发,x业务请求次数,x业务请求成功次数,x业务请求失败次数",
    ]
    services = [
        ("IMS-Core", "ims-node-01", 1.00, 0.96),
        ("IMS-Core", "ims-node-02", 0.88, 0.91),
        ("Access-GW", "access-node-01", 1.16, 1.04),
        ("Access-GW", "access-node-02", 1.31, 1.12),
        ("SBC", "sbc-node-01", 1.12, 1.06),
        ("Media-FW", "media-node-01", 1.05, 0.99),
    ]
    holidays = {22, 29}
    maintenance_days = {18, 25}
    severe_degradation_days = {17, 21, 27, 31, 4, 8}
    base = datetime(2026, 8, 15)
    for slot in range(288):
        start_at = base + timedelta(minutes=slot * 5)
        end_at = start_at + timedelta(minutes=5)
        start_text = start_at.strftime("%Y-%m-%d %H:%M:%S")
        end_text = end_at.strftime("%Y-%m-%d %H:%M:%S")
        minute_of_day = slot * 5 % 1440
        day_of_month = start_at.day
        is_weekend = start_at.weekday() >= 5
        is_holiday = day_of_month in holidays
        load_season = 0.68 if is_weekend or is_holiday else 1.0
        cycle_progress = (slot / 288 - 0.5) * 0.08
        row_index = slot * len(services)

        for service_idx, (service, instance, load_factor, quality_factor) in enumerate(services):
            requests = int(
                1180
                + 640 * math.sin(2 * math.pi * (minute_of_day - 470) / 1440) * load_factor * load_season
                + 320 * math.sin(2 * math.pi * (start_at.timetuple().tm_yday - 18) / 30) * load_factor
                + 96 * math.sin(2 * math.pi * minute_of_day / 91)
                + service_idx * 68
                + cycle_progress * 1000
                + (slot % 11) * 8
            )
            requests = max(150, requests)

            failure_rate = 0.0038 + 0.0021 * abs(math.sin(2 * math.pi * minute_of_day / 175))
            # 每天早晚各设置一个异常窗口；部分日期扩展为严重劣化，便于展示月度趋势和定位。
            morning_breach = 8 * 60 + 12 <= minute_of_day < 8 * 60 + 46
            evening_breach = 20 * 60 + 27 <= minute_of_day < 21 * 60 + 8
            severe_day = day_of_month in severe_degradation_days
            if morning_breach or evening_breach:
                burst = 0.033 if morning_breach else 0.028
                if severe_day:
                    burst += 0.011
                failure_rate = burst + service_idx * 0.0038 + (slot % 5) * 0.0021
            if day_of_month in maintenance_days and service_idx == 3 and 14 * 60 <= minute_of_day < 15 * 60:
                failure_rate = 0.036
            failure_rate *= quality_factor
            failures = min(requests, max(1, round(requests * failure_rate)))
            successes = requests - failures
            success_rate = round(successes / requests * 100, 2)
            actual_failure_rate = round(failures / requests * 100, 2)

            peak = int(
                228
                + 128 * math.sin(2 * math.pi * (minute_of_day - 495) / 1440) * load_factor * load_season
                + service_idx * 17
                + (slot % 17) * 4
            )
            concurrency = int(
                152
                + 88 * math.sin(2 * math.pi * (minute_of_day - 513) / 1440) * load_factor * load_season
                + service_idx * 11
                + (slot % 13) * 3
            )
            x_requests = int(requests * 0.57 + service_idx * 21 + (slot % 7) * 10)
            x_failures = min(x_requests, 1 + (slot + service_idx * 3) % 7)
            x_successes = x_requests - x_failures

            trusted = True
            untrusted_reason = ""
            if service_idx in (3, 5) and minute_of_day % 120 == 55:
                trusted = False
                untrusted_reason = "采样窗口部分回补"

            reliability = "可信" if trusted else "不可信"
            lines.append(
                f"{service},{instance},{reliability},{untrusted_reason},"
                f"{start_text},{end_text},5,"
                f"{requests},{successes},{failures},{success_rate:.2f},{actual_failure_rate:.2f}"
                f",{peak},{concurrency},{x_requests},{x_successes},{x_failures}"
            )

            # 少量固定注入的记录：自洽异常和解析异常不中断整个文件解析。
            if row_index == 300:
                lines[-1] = lines[-1].replace(
                    f",{requests},{successes},{failures},",
                    f",{requests},{successes - 4},{failures},",
                )
            elif row_index == 900:
                lines[-1] = lines[-1].replace(
                    f",{requests},{successes},{failures},",
                    f",{requests},{successes - 9},{failures},",
                )
            elif row_index == 600:
                lines[-1] = "IMS-Core,ims-node-01,可信,,invalid-time,,5,1200,,bad-number,99.00,1.00,200,120"
            elif row_index == 1200:
                lines[-1] = "Access-GW,access-node-02,可信,,2026-09-01 10:00:00,,5,1500,1460,40,97.33,2.67,not-number"

    return "\n".join(lines) + "\n"


FILES: dict[str, str] = {
    f"{BASE}/Alarm Information/alarm_history_202609010101137101.csv": (
        "alarm_id,created_time,cleared_time,alarm_code,severity,status,object,description\n"
        "1001,2026-09-01 10:00:01,,DB_CONNECTION_POOL_EXHAUSTED,CRITICAL,未处理,app-node-01,数据库连接池耗尽\n"
        "1002,2026-09-01 10:00:04,2026-09-01 10:00:30,SCTP_LINK_DOWN,HIGH,处理中,app-node-01,SCTP链路中断\n"
        "1003,2026-09-01 10:02:11,,CPU_USAGE_HIGH,MEDIUM,未处理,pod-app-1,CPU使用率偏高\n"
    ),
    f"{BASE}/Basic Information/system_info.ini": (
        "[app]\nname=app\nlog_level=INFO\n\n[system]\nnode_id=app-node-01\nregion=gd\ncollect_time=2026-09-01T10:00:00Z\n"
    ),
    f"{BASE}/Basic Information/version.ini": ("[version]\nproduct=app\nrelease=R24.1\npatch=SP03\nbuild=20260901.01\n"),
    f"{BASE}/Traffic/call_stat_202609010101137101.txt": ("total_calls 12345\nanswer_rate 93.8\n"),
    "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv": _call_kpi_5_csv(),
}

# 保留 API 解析容错样例。
FILES.update(
    {
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
