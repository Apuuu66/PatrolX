"""构造贴近真实 App Problem Scene 的样例压缩包。

真实结构参考 docs/example/zip.txt；所有成员使用固定时间戳，保证重复生成内容稳定。
"""

from __future__ import annotations

import gzip
import io
import math
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

PACKAGE_NAME = "ZZapp01BCN_app_Problem_scene_333.zip"
BASE = "ZZapp01BCN_app_Problem scene_333/333/app Problem scene"
FIXED_DATE = (2026, 9, 18, 9, 0, 0)

ALARM_CSV_001 = (
    "alarm_id,created_time,cleared_time,alarm_code,severity,status,object,description\n"
    "1001,2026-09-01 10:00:01,,DB_CONNECTION_POOL_EXHAUSTED,CRITICAL,未处理,app-node-01,数据库连接池耗尽\n"
    "1002,2026-09-01 10:00:04,2026-09-01 10:00:30,SCTP_LINK_DOWN,HIGH,处理中,app-node-01,SCTP链路中断\n"
    "1003,2026-09-01 10:02:11,,CPU_USAGE_HIGH,MEDIUM,未处理,pod-app-1,CPU使用率偏高\n"
)
ALARM_CSV_002 = (
    "alarm_id,created_time,cleared_time,alarm_code,severity,status,object,description\n"
    "1004,2026-09-01 10:03:01,,SERVICE_UNAVAILABLE,CRITICAL,未处理,app-node-02,服务不可用\n"
    "1005,2026-09-01 10:04:04,2026-09-01 10:05:30,LICENSE_EXPIRED,HIGH,处理中,app-node-02,许可证即将过期\n"
    "1006,2026-09-01 10:05:11,,DISK_USAGE_HIGH,MEDIUM,未处理,app-node-02,磁盘使用率偏高\n"
)

KPI_HEADER = (
    "服务名,实例,测量开始时间,测量结束时间,周期(分钟),"
    "呼叫请求次数,呼叫请求成功次数,呼叫请求失败次数,呼叫成功率,呼叫失败率,统计峰值,最大并发"
)


def _call_kpi(period: int) -> str:
    """生成 3 天多周期呼叫 KPI 序列，保留明确的日周期波动。"""
    slots = 3 * 24 * 60 // period
    lines = [
        "设备类型：XXX",
        "测量单元名称：呼叫会话统计",
        KPI_HEADER,
    ]
    services = [
        ("IMS-Core", "ims-node-01", 1.00, 1.05),
        ("Access-GW", "access-node-01", 1.22, 0.82),
    ]
    for slot in range(slots):
        start = datetime(2026, 9, 2) + timedelta(minutes=slot * period)
        end = start + timedelta(minutes=period)
        minute_of_day = slot * period % 1440
        for service_idx, (service, instance, load_factor, quality_factor) in enumerate(services):
            requests = int(
                1180
                + 520 * math.sin(2 * math.pi * (minute_of_day - 490) / 1440) * load_factor
                + 48 * math.sin(2 * math.pi * slot / 37)
                + service_idx * 180
            )
            requests = max(240, requests)

            # 失败率保留明显波动但低于阈值，样例用于观察趋势而非制造告警。
            failure_rate = 0.0012 + 0.0042 * abs(math.sin(2 * math.pi * minute_of_day / 173))
            failures = min(requests, max(1, round(requests * failure_rate * quality_factor)))
            successes = requests - failures
            success_rate = round(successes / requests * 100, 2)
            actual_failure_rate = round(failures / requests * 100, 2)
            peak = int(120 + 72 * math.sin(2 * math.pi * (minute_of_day - 495) / 1440) * load_factor + service_idx * 22)
            concurrency = int(
                82 + 48 * math.sin(2 * math.pi * (minute_of_day - 513) / 1440) * load_factor + service_idx * 14
            )
            lines.append(
                f"{service},{instance},{start:%Y-%m-%d %H:%M:%S},{end:%Y-%m-%d %H:%M:%S},{period},"
                f"{requests},{successes},{failures},{success_rate:.2f},{actual_failure_rate:.2f},"
                f"{peak},{concurrency}"
            )
    return "\n".join(lines) + "\n"


def _container_resource(period: int) -> str:
    start = datetime(2026, 9, 2)
    end = start + timedelta(minutes=period)
    return (
        "设备类型：XXX\n"
        "测量单元名称：容器指标单元\n"
        "服务名,实例,测量开始时间,测量结束时间,周期(分钟),"
        "容器CPU使用率,容器CPU使用率峰值,容器内存使用率,容器内存使用率峰值\n"
        f"IMS-Core,ims-node-01,{start:%Y-%m-%d %H:%M:%S},{end:%Y-%m-%d %H:%M:%S},{period},"
        "86.40,92.10,91.20,94.80\n"
        f"Access-GW,access-node-01,{start:%Y-%m-%d %H:%M:%S},{end:%Y-%m-%d %H:%M:%S},{period},"
        "42.10,55.30,48.60,62.40\n"
    )


UMF_LOG = (
    "2026-09-01T10:00:00Z INFO  umf service started\n"
    "2026-09-01T10:05:00Z ERROR umf auth failure count 3\n"
    "2026-09-01T10:05:01Z ERROR umf auth failure count 4\n"
    "2026-09-01T10:05:02Z ERROR umf auth failure count 5\n"
    "2026-09-01T10:05:03Z WARN  umf retry timer exceeded\n"
)
UMF_HISTORY = "2026-09-01T10:06:00Z ERROR umf history cached failure\n"
UMFACC_LOG = (
    "2026-09-01T10:00:00Z INFO  umf acc service started\n"
    "2026-09-01T10:00:01Z ERROR umf acc db connection pool exhausted retry=1\n"
    "2026-09-01T10:00:02Z ERROR umf acc db connection pool exhausted retry=2\n"
    "2026-09-01T10:00:03Z ERROR umf acc sctp link down\n"
    "2026-09-01T10:00:04Z ERROR umf acc sctp reconnect failed\n"
)
UMFACC_HISTORY = "2026-09-01T10:07:00Z ERROR umf acc history connection timeout\n"


def _add_bytes(zf: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, content)


def build_real_package(directory: Path) -> Path:
    """在 directory 下生成固定内容的真实结构样例包，返回包路径。"""
    alarm_buffer = io.BytesIO()
    with zipfile.ZipFile(alarm_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_bytes(zf, "alarm_history_202609010101137101_001.csv", ALARM_CSV_001.encode("utf-8"))
        _add_bytes(zf, "alarm_history_202609010101137101_002.csv", ALARM_CSV_002.encode("utf-8"))

    perf_buffer = io.BytesIO()
    with zipfile.ZipFile(perf_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for period in (5, 15, 30, 60):
            _add_bytes(
                zf,
                f"ne333_Call_Session_API_Statistics_{period}_0_202609020000.csv",
                _call_kpi(period).encode("utf-8"),
            )
        for period in (5, 15):
            _add_bytes(
                zf,
                f"ne333_Container_Metric_Unit_{period}_0_202609020000.csv",
                _container_resource(period).encode("utf-8"),
            )

    service_buffer = io.BytesIO()
    with zipfile.ZipFile(service_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_bytes(
            zf,
            "UmfService/logs/paas-192.168.2.2/UmfService.log",
            UMF_LOG.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "UmfService/logs/paas-192.168.2.2/UmfService_20260901011314.log.gz",
            gzip.compress(UMF_HISTORY.encode("utf-8")),
        )
        _add_bytes(
            zf,
            "UMFAcc/logs/paas-192.168.2.2/UMFAcc.log",
            UMFACC_LOG.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "UMFAcc/logs/paas-192.168.2.2/UMFAcc_20260901011314.log.gz",
            gzip.compress(UMFACC_HISTORY.encode("utf-8")),
        )

    directory.mkdir(parents=True, exist_ok=True)
    output = directory / PACKAGE_NAME
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_bytes(
            zf,
            f"{BASE}/Alarm Information/alarm_history_202609010101137101.zip",
            alarm_buffer.getvalue(),
        )
        _add_bytes(
            zf,
            f"{BASE}/Basic Information/system_info.ini",
            b"[app]\nname=app\nlog_level=INFO\n\n[system]\nnode_id=app-node-01\nregion=gd\ncollect_time=2026-09-01T10:00:00Z\n",
        )
        _add_bytes(
            zf,
            f"{BASE}/Basic Information/version.ini",
            b"[version]\nproduct=app\nrelease=R24.1\npatch=SP03\nbuild=20260901.01\n",
        )
        _add_bytes(
            zf,
            f"{BASE}/KPI/PerfResult_202609010101137101.zip",
            perf_buffer.getvalue(),
        )
        _add_bytes(
            zf,
            f"{BASE}/Service Logs (Problem)/ServiceLog_20260901011314.zip",
            service_buffer.getvalue(),
        )
    return output


if __name__ == "__main__":
    uploads_path = build_real_package(Path.cwd() / "uploads")
    print(f"已生成上传样例: {uploads_path} ({uploads_path.stat().st_size} bytes)")
