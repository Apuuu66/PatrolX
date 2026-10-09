"""构造贴近真实 App Problem Scene 的样例压缩包。

真实结构参考 docs/example/zip.txt；所有成员使用固定时间戳，保证重复生成内容稳定。
样例覆盖 UMF/CSP 两类网元、多服务多节点日志、多严重级告警和多实例 KPI，用于展示巡检效果。
"""

from __future__ import annotations

import gzip
import io
import math
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

PACKAGE_NAME = "ZZapp01BCN_app_Problem_scene_333.zip"
BASE = "ZZapp01BCN_app Problem scene_333/333/app Problem scene"
FIXED_DATE = (2026, 9, 18, 9, 0, 0)

# 网元类型取值必须与 deploy/config/dicts.yaml 的 product 字典 code 一致：
# 台账筛选是规范化后的全等比较，不做大小写转换。
NETWORK_ELEMENT_TYPE_UMF = "umf"
NETWORK_ELEMENT_TYPE_CSP = "csp"

LST_ME_TXT = (
    "%%LST ME:;%%\n"
    "RETCODE = 0  操作成功\n"
    "\n"
    "查询结果\n"
    "--------\n"
    "网元名称: UMF-SZ-01\n"
    f"网元类型: {NETWORK_ELEMENT_TYPE_UMF}\n"
    "软件版本: UMF V100R003C10SPC200\n"
    "\n"
    "网元名称: CSP-SZ-01\n"
    f"网元类型: {NETWORK_ELEMENT_TYPE_CSP}\n"
    "软件版本: CSP V200R001C10SPC100\n"
    "\n"
    "网元名称: CSP-SZ-02\n"
    f"网元类型: {NETWORK_ELEMENT_TYPE_CSP}\n"
    "\n"
    "(结果个数 = 3)\n"
    "---    END\n"
)

# 告警 CSV 表头与真实 App Problem Scene 导出一致（《告警流水号》12 列）：
# 告警流水号、应用ID、应用名称、告警ID、告警名称、告警级别、
# 发生时间、清除时间、清除类型、事件类型、告警重复次数、定位信息。
# 告警级别为中文口径（紧急/严重/重要/次要），解析侧归一化为 CRITICAL/HIGH/MEDIUM/LOW。
ALARM_CSV_001 = (
    "告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息\n"
    "1001,9001,CSP核心服务,1001,数据库连接池耗尽,紧急,2026-09-01 10:00:01,,,通信告警,1,paas-192.168.2.2\n"
    "1002,9002,UMF核心服务,1002,SCTP链路中断,严重,2026-09-01 10:00:04,2026-09-01 10:00:30,自动清除,通信告警,1,"
    "umf-node-01\n"
    "1003,9002,UMF核心服务,1003,CPU使用率偏高,重要,2026-09-01 10:02:11,,,性能告警,1,pod-umf-1\n"
    "1004,9002,UMF核心服务,1004,认证失败次数激增,严重,2026-09-01 10:03:21,2026-09-01 10:12:00,手动清除,安全告警,1,"
    "umf-node-01\n"
    "1005,9002,UMF核心服务,1005,磁盘使用率偏高,次要,2026-09-01 10:04:35,,,性能告警,1,pod-umf-2\n"
    "1006,9001,CSP核心服务,1006,服务不可用,紧急,2026-09-01 10:05:02,2026-09-01 10:20:00,手动清除,业务告警,1,"
    "csp-node-01\n"
    "1007,9002,UMF核心服务,1007,内存使用率偏高,重要,2026-09-01 10:06:47,,,性能告警,1,csp-node-01\n"
)
ALARM_CSV_002 = (
    "告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息\n"
    "1008,9001,CSP核心服务,1008,SCTP链路中断,严重,2026-09-01 10:09:12,,,通信告警,1,csp-node-01\n"
    "1009,9001,CSP核心服务,1009,容器重启次数偏高,严重,2026-09-01 10:11:33,2026-09-01 10:24:10,自动清除,进程告警,1,"
    "pod-csp-1\n"
    "1010,9001,CSP核心服务,1010,文件句柄使用率偏高,次要,2026-09-01 10:13:20,2026-09-01 10:31:05,自动清除,性能告警,"
    "1,pod-csp-2\n"
    "1011,9002,UMF核心服务,1011,数据库连接池耗尽,紧急,2026-09-01 10:15:08,,,通信告警,1,umf-node-02\n"
    "1012,9002,UMF核心服务,1012,许可证即将过期,严重,2026-09-01 10:17:41,,,许可告警,1,umf-node-02\n"
    "1013,9002,UMF核心服务,1013,消息队列积压,重要,2026-09-01 10:19:55,,,性能告警,1,pod-umf-3\n"
)

# 030 告警闪断样例：未清除反复、已清除反复、操作窗跨界的窗口外再现、观察窗不足与稳定恢复。
# 行序固定：1050×2（文件行 2–3）、1051×3（行 4–6）、1052×3（行 7–9）、1053×1（行 10）。
ALARM_CSV_003 = (
    "告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息\n"
    "2001,9002,UMF核心服务,1050,操作窗内出现后窗口外再现,重要,2026-09-02 00:30:00,2026-09-02 00:45:00,自动清除,"
    "性能告警,2,pod-umf-9\n"
    "2002,9002,UMF核心服务,1050,操作窗内出现后窗口外再现,重要,2026-09-02 02:30:00,2026-09-02 02:40:00,自动清除,"
    "性能告警,2,pod-umf-9\n"
    "2003,9002,UMF核心服务,1051,未清除且反复,紧急,2026-09-02 00:10:00,,,通信告警,3,pod-umf-9\n"
    "2004,9002,UMF核心服务,1051,未清除且反复,紧急,2026-09-02 00:40:00,,,通信告警,3,pod-umf-9\n"
    "2005,9002,UMF核心服务,1051,未清除且反复,紧急,2026-09-02 01:00:00,,,通信告警,3,pod-umf-9\n"
    "2006,9002,UMF核心服务,1052,清除后反复闪断,严重,2026-09-02 11:00:00,2026-09-02 11:10:00,自动清除,通信告警,3,"
    "pod-umf-9\n"
    "2007,9002,UMF核心服务,1052,清除后反复闪断,严重,2026-09-02 11:30:00,2026-09-02 11:40:00,自动清除,通信告警,3,"
    "pod-umf-9\n"
    "2008,9002,UMF核心服务,1052,清除后反复闪断,严重,2026-09-02 11:50:00,2026-09-02 12:00:00,自动清除,通信告警,3,"
    "pod-umf-9\n"
    "2009,9002,UMF核心服务,1053,清除后观察窗不足,重要,2026-09-02 12:00:00,2026-09-02 12:05:30,自动清除,通信告警,1,"
    "pod-umf-9\n"
)

KPI_HEADER = (
    "服务名,实例,测量开始时间,测量结束时间,周期(分钟),"
    "呼叫请求次数,呼叫请求成功次数,呼叫请求失败次数,呼叫成功率,呼叫失败率,统计峰值,最大并发"
)

# 服务 / 实例组合：UMF 与 CSP 各一台主用节点，外加一台 UMF 备用接入节点。
CALL_INSTANCES = [
    ("UMF-Core", "umf-node-01", 1.00, 1.05),
    ("UMF-Access", "umf-node-02", 1.22, 0.82),
    ("CSP-Core", "csp-node-01", 0.86, 0.70),
]

CONTAINER_INSTANCES = [
    ("UMF-Core", "umf-node-01", "86.40,92.10,91.20,94.80"),
    ("UMF-Access", "umf-node-02", "42.10,55.30,48.60,62.40"),
    ("CSP-Core", "csp-node-01", "88.90,95.60,87.30,91.50"),
]


def _call_kpi(period: int) -> str:
    """生成 3 天多周期呼叫 KPI 序列，保留明确的日周期波动。"""
    slots = 3 * 24 * 60 // period
    lines = [
        "设备类型：XXX",
        "测量单元名称：呼叫会话统计",
        KPI_HEADER,
    ]
    for slot in range(slots):
        start = datetime(2026, 9, 2) + timedelta(minutes=slot * period)
        end = start + timedelta(minutes=period)
        minute_of_day = slot * period % 1440
        for service_idx, (service, instance, load_factor, quality_factor) in enumerate(CALL_INSTANCES):
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
    lines = [
        "设备类型：XXX",
        "测量单元名称：容器指标单元",
        "服务名,实例,测量开始时间,测量结束时间,周期(分钟),"
        "容器CPU使用率,容器CPU使用率峰值,容器内存使用率,容器内存使用率峰值",
    ]
    for service, instance, metrics in CONTAINER_INSTANCES:
        lines.append(f"{service},{instance},{start:%Y-%m-%d %H:%M:%S},{end:%Y-%m-%d %H:%M:%S},{period},{metrics}")
    return "\n".join(lines) + "\n"


UMF_LOG = (
    "2026-09-01T10:00:00Z INFO  umf service started\n"
    "2026-09-01T10:05:00Z ERROR umf auth failure count 3\n"
    "2026-09-01T10:05:01Z ERROR umf auth failure count 4\n"
    "2026-09-01T10:05:02Z ERROR umf auth failure count 5\n"
    "2026-09-01T10:05:03Z WARN  umf retry timer exceeded\n"
)
UMF_LOG_STANDBY = (
    "2026-09-01T10:00:02Z INFO  umf service started on standby node\n"
    "2026-09-01T10:06:10Z WARN  umf retry timer exceeded\n"
    "2026-09-01T10:06:11Z ERROR umf auth failure count 6\n"
    "2026-09-01T10:06:12Z ERROR umf auth failure count 7\n"
    "2026-09-01T10:06:13Z ERROR umf auth failure count 8\n"
)
UMF_HISTORY = "2026-09-01T10:07:00Z ERROR umf history cached failure\n"
UMFACC_LOG = (
    "2026-09-01T10:00:00Z INFO  umf acc service started\n"
    "2026-09-01T10:00:01Z ERROR umf acc db connection pool exhausted retry=1\n"
    "2026-09-01T10:00:02Z ERROR umf acc db connection pool exhausted retry=2\n"
    "2026-09-01T10:00:03Z ERROR umf acc sctp link down\n"
    "2026-09-01T10:00:04Z ERROR umf acc sctp reconnect failed\n"
)
UMFACC_LOG_STANDBY = (
    "2026-09-01T10:00:02Z INFO  umf acc service started on standby node\n"
    "2026-09-01T10:01:10Z ERROR umf acc connection timeout to database\n"
    "2026-09-01T10:01:12Z ERROR umf acc sctp link down standby\n"
)
UMFACC_HISTORY = "2026-09-01T10:08:00Z ERROR umf acc history connection timeout\n"
CSP_LOG = (
    "2026-09-01T10:00:00Z INFO  csp service started\n"
    "2026-09-01T10:02:30Z WARN  csp policy reload slower than expected\n"
    "2026-09-01T10:03:00Z ERROR csp out of memory while loading policy cache\n"
)
CSP_LOG_STANDBY = (
    "2026-09-01T10:00:01Z INFO  csp service started on standby node\n"
    "2026-09-01T10:04:20Z ERROR csp connection timeout to config service\n"
)
CSP_HISTORY = "2026-09-01T10:09:00Z WARN  csp history policy reload retried\n"


def _add_bytes(zf: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, content)


def _gzip_bytes(text: str) -> bytes:
    """压缩历史日志；固定 mtime 保证重复生成内容稳定。"""
    return gzip.compress(text.encode("utf-8"), mtime=0)


def build_real_package(directory: Path) -> Path:
    """在 directory 下生成固定内容的真实结构样例包，返回包路径。"""
    alarm_buffer = io.BytesIO()
    with zipfile.ZipFile(alarm_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_bytes(zf, "alarm_history_202609010101137101_001.csv", ALARM_CSV_001.encode("utf-8"))
        _add_bytes(zf, "alarm_history_202609010101137101_002.csv", ALARM_CSV_002.encode("utf-8"))
        _add_bytes(zf, "alarm_history_202609010101137101_003.csv", ALARM_CSV_003.encode("utf-8"))

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
            "CspService/logs/paas-192.168.2.2/CspService.log",
            CSP_LOG.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "CspService/logs/paas-192.168.2.2/CspService_20260901011314.log.gz",
            _gzip_bytes(CSP_HISTORY),
        )
        _add_bytes(
            zf,
            "CspService/logs/paas-192.168.2.3/CspService.log",
            CSP_LOG_STANDBY.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "UmfService/logs/paas-192.168.2.2/UmfService.log",
            UMF_LOG.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "UmfService/logs/paas-192.168.2.2/UmfService_20260901011314.log.gz",
            _gzip_bytes(UMF_HISTORY),
        )
        _add_bytes(
            zf,
            "UmfService/logs/paas-192.168.2.3/UmfService.log",
            UMF_LOG_STANDBY.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "UMFAcc/logs/paas-192.168.2.2/UMFAcc.log",
            UMFACC_LOG.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "UMFAcc/logs/paas-192.168.2.2/UMFAcc_20260901011314.log.gz",
            _gzip_bytes(UMFACC_HISTORY),
        )
        _add_bytes(
            zf,
            "UMFAcc/logs/paas-192.168.2.3/UMFAcc.log",
            UMFACC_LOG_STANDBY.encode("utf-8"),
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
            f"{BASE}/Basic Information/LST ME.txt",
            LST_ME_TXT.encode("utf-8"),
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
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "uploads"
    uploads_path = build_real_package(target)
    print(f"已生成上传样例: {uploads_path} ({uploads_path.stat().st_size} bytes)")
