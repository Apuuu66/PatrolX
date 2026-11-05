"""构造贴近真实 App Problem Scene 的样例压缩包。

真实结构参考 docs/example/zip.txt；所有成员使用固定时间戳，保证重复生成内容稳定。
样例覆盖 UMF/CSP 两类网元、多服务多节点日志、多严重级告警和多实例 KPI，用于展示巡检效果。
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import struct
import tarfile
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PACKAGE_NAME = "ZZapp01BCN_app_Problem_scene_333.zip"
NO_KPI_PACKAGE_NAME = "ZZapp01BCN_app_Problem_scene_333_without_kpi.zip"
BASE = "ZZapp01BCN_app Problem scene_333/333/app Problem scene"
UMF_SCENE_ROOT = "Outer Device/Problem 038/wrapper/UMF Problem Scene"
FIXED_DATE = (2026, 9, 18, 9, 0, 0)

# 网元类型取值来自 product 字典 code；台账筛选会先把上传值和清单值统一转为大写。
NETWORK_ELEMENT_TYPE_UMF = "umf"
NETWORK_ELEMENT_TYPE_CSP = "csp"

LST_ME_EXECUTION_TIME = "2026-09-01  10:00:00"

LST_ME_TXT = (
    f"+++    CSP/*xx*/     {LST_ME_EXECUTION_TIME}\n"
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
    "\n"
    "Domain ID  Subnet ID  ME ID  ME name       ME type  ME version  ME vendor  ME user-defined state  "
    "Location name  ME lock status  ME Country(Region) Code  ME Interface ID  ME Language  ME patch version  "
    "ME mode          Architecture Type\n"
    "1          0          0      TABLE-CSP-01  CSP      27.0.0      HUAWEI     Normal                 "
    "null           Unlocked        NULL                     CSPEdge27.0.0.13  ENG          27.0.0.13         "
    "All-in-one mode  ARM\n"
    "1          0          1      TABLE-UMF-01  umf      27.0.0      HUAWEI     Normal                 "
    "null           Unlocked        NULL                     UMF27.0.0.16      ENG          null              "
    "All-in-one mode  ARM\n"
    "(Number of results = 2)\n"
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

# 039 中英文、混合表头、重复、坏记录和编码失败样例。全部使用固定时间戳。
ALARM_ENGLISH_CSV = (
    "Serial No.,App Name,Alarm ID,Alarm Name,Alarm Severity,Raised Time,Cleared Time,"
    "Whether Cleared,Repeat Times,Location Info,Additional Information\n"
    "4001,CSP Core,7001,Active database pool exhausted,Critical,2026-09-18 09:00:00,,Not Cleared,9,"
    "Pod Name=pod-active; Located Device=node-a,Service Name=db\n"
    "4002,CSP Core,7002,Short network reset,Major,2026-09-18 09:05:00,2026-09-18 09:07:00,"
    "Normal Cleared,0,Located Device=node-b,\n"
    "4003,CSP Core,7003,Repeated authentication failure,High,2026-09-18 09:10:00,,"
    "Not Cleared,5,Pod Name=pod-active,\n"
    "4003,CSP Core,7003,Repeated authentication failure,High,2026-09-18 09:10:00,,"
    "Not Cleared,5,Pod Name=pod-active,\n"
    "4004,CSP Core,7004,Reset without stable recovery,Medium,2026-09-18 09:20:00,2026-09-18 09:21:00,"
    "Reset Cleared,1,,\n"
    "4005,CSP Core,7005,Bad raised time,Minor,not-a-time,,Not Cleared,0,Located Device=node-c,\n"
)

ALARM_CHINESE_CSV = (
    "告警流水号,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,告警重复次数,定位信息,附加信息\n"
    "4101,核心服务,7101,活动数据库连接池耗尽,紧急,2026-09-18 09:00:00,,未清除,9,"
    "Pod Name=pod-active,\n"
    "4102,核心服务,7102,短时链路闪断,严重,2026-09-18 09:05:00,2026-09-18 09:07:00,正常清除,0,节点B,\n"
    "4103,核心服务,7103,多次认证失败,重要,2026-09-18 09:10:00,,未清除,5,Pod Name=pod-active,\n"
    "4104,核心服务,7104,重置后未稳定恢复,次要,2026-09-18 09:20:00,2026-09-18 09:21:00,重置清除,1,,\n"
)

ALARM_MIXED_CSV = (
    "Serial No.,应用名称,Alarm ID,告警名称,Alarm Severity,发生时间,Cleared Time,Whether Cleared,"
    "Repeat Times,定位信息,Additional Information\n"
    "4201,混合应用,7201,混合严重告警,严重,2026-09-18T09:00:00Z,2026-09-18T09:01:00Z,"
    "Normal Cleared,2,定位设备=node-mixed,\n"
    "4202,混合应用,7202,混合未知级别,提示,2026-09-18 09:02:00,,未清除,0,Located Device=node-mixed,\n"
)

ALARM_BAD_ENCODING_BYTES = b"\xff\xfe\x00broken alarm fixture"

# US2 告警边界样例使用固定内容，便于后续断言生效路线、空文件/零记录保留和局部损坏隔离。
UMF_ALARM_HEADER = (
    "告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息\n"
)
UMF_ALARM_BOUNDARY_CSV = UMF_ALARM_HEADER + (
    "3001,9002,UMF核心服务,3001,UMF目录边界告警,重要,2026-09-18 09:00:00,,,通信告警,1,pod-umf-boundary\n"
)
CSP_ALARM_PRIMARY_CSV = (
    "告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息\n"
    "3101,9001,CSP核心服务,3101,CSP目录告警,紧急,2026-09-18 09:01:00,,,通信告警,1,pod-csp-primary\n"
)
CSP_ALARM_WITHOUT_PROBLEMS_CSV = (
    "告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息\n"
)

KPI_HEADER = (
    "服务名,实例,测量开始时间,测量结束时间,周期(分钟),"
    "呼叫请求次数,呼叫请求成功次数,呼叫请求失败次数,呼叫成功率,呼叫失败率,统计峰值,最大并发"
)
KPI_HEADER_EN = (
    "Service Name,Instance,Reliability,Cause,StarTime,EndTime,Period(Minute),"
    "Call Requests,Successful Call Requests,Failed Call Requests,Call Success Rate,"
    "Call Failure Rate,Peak Value,Max Concurrency,"
    "Number of Media Resource Creation Requests(times),"
    "Number of Data Channel Resource Update Requests(times),"
    "Media Resource Creation Success Rate(%),DC Resource Update Success Rate(%),"
    "Media Resource Creation Requests Success Rate(%),"
    "Data Channel Resource Update Requests Success Rate(%)"
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


KPI_DAILY_HEALTH_PACKAGE_NAME = "KPI_Daily_Health_20_Metrics_20261105.zip"
KPI_DAILY_HEALTH_FIXED_DATE = (2026, 11, 5, 10, 0, 0)
KPI_DAILY_HEALTH_UNITS = (
    ("MU_CALL", "Call_Statistics", "呼叫统计"),
    ("MU_HEALTH_CALL", "Health_Call", "健康呼叫统计"),
    ("MU_HEALTH_SIGNAL", "Health_Signal", "健康信令统计"),
    ("MU_HEALTH_MEDIA", "Health_Media", "健康媒体统计"),
)
KPI_DAILY_HEALTH_DISABLED_UNIT = ("MU_DISABLED_E2E", "Disabled_E2E", "停用测量单元 E2E")
KPI_DAILY_HEALTH_CURRENT_STATUSES = (
    "normal",
    "warn",
    "fail",
    "pending_config",
    "unable_to_judge",
    "not_applicable",
)
KPI_DAILY_HEALTH_TREND_STATUSES = ("improved", "stable", "worsened", "observe", "no_baseline")

# measurement_unit_id, metric_id, name_zh, direction, warning, critical, importance,
# expected_current_status, expected_trend_status, 最近 7 日值。
_KPI_DAILY_HEALTH_BASE_METRICS = (
    (
        "MU_CALL",
        "ME_CALL",
        "呼叫请求次数",
        "higher_better",
        90.0,
        80.0,
        "P1",
        "normal",
        "stable",
        (100, 100, 100, 100, 100, 100, 100),
    ),
    (
        "MU_CALL",
        "ME_MAX_USERS",
        "最大注册用户数",
        "higher_better",
        90.0,
        80.0,
        "P1",
        "normal",
        "improved",
        (100, 100, 100, 100, 100, 100, 110),
    ),
    (
        "MU_CALL",
        "ME_HEALTH_CALL_VOLUME",
        "呼叫业务量",
        "neutral",
        None,
        None,
        "normal",
        "pending_config",
        "observe",
        (100, 100, 100, 100, 100, 100, 120),
    ),
    (
        "MU_CALL",
        "ME_HEALTH_REGISTERED_USERS",
        "登记用户规模",
        "higher_better",
        90.0,
        80.0,
        "normal",
        "unable_to_judge",
        "no_baseline",
        (),
    ),
    (
        "MU_CALL",
        "ME_HEALTH_RESOURCE_POOL",
        "资源池占用",
        "lower_better",
        10.0,
        20.0,
        "normal",
        "normal",
        "improved",
        (10, 10, 10, 10, 10, 10, 9),
    ),
    (
        "MU_CALL",
        "ME_HEALTH_ALARM_COUNT",
        "告警数量",
        "lower_better",
        10.0,
        20.0,
        "P2",
        "unable_to_judge",
        "no_baseline",
        (),
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_LATENCY",
        "呼叫建立时延",
        "lower_better",
        60.0,
        80.0,
        "P1",
        "normal",
        "improved",
        (62, 62, 62, 62, 62, 62, 50),
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_ERRORS",
        "呼叫错误次数",
        "lower_better",
        10.0,
        20.0,
        "P1",
        "warn",
        "worsened",
        (12, 12, 12, 12, 12, 12, 15),
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_CONCURRENCY",
        "呼叫并发数",
        "higher_better",
        85.0,
        75.0,
        "normal",
        "normal",
        "stable",
        (96, 96, 96, 96, 96, 96, 96),
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_RECOVERY",
        "呼叫恢复次数",
        "higher_better",
        85.0,
        75.0,
        "P2",
        "normal",
        "worsened",
        (105, 105, 105, 105, 105, 105, 91),
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_QUALITY",
        "呼叫质量样本",
        "higher_better",
        95.0,
        85.0,
        "normal",
        "pending_config",
        "stable",
        (0, 0, 0, 0, 0, 0, 0),
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_SIGNAL_DROPS",
        "信令丢弃次数",
        "lower_better",
        10.0,
        20.0,
        "P1",
        "normal",
        "improved",
        (7, 7, 7, 7, 7, 7, 5),
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_SIGNAL_LOAD",
        "信令负载",
        "neutral",
        None,
        None,
        "normal",
        "pending_config",
        "observe",
        (70, 70, 70, 70, 70, 70, 80),
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_SIGNAL_LATENCY",
        "信令处理时延",
        "lower_better",
        30.0,
        50.0,
        "normal",
        "normal",
        "stable",
        (25, 25, 25, 25, 25, 25, 25),
    ),
    (
        "MU_HEALTH_MEDIA",
        "ME_HEALTH_MEDIA_LATENCY",
        "媒体处理时延",
        "lower_better",
        30.0,
        50.0,
        "normal",
        "normal",
        "stable",
        (20, 20, 20, 20, 20, 20, 20),
    ),
    (
        "MU_HEALTH_MEDIA",
        "ME_HEALTH_MEDIA_QUEUE",
        "媒体队列深度",
        "lower_better",
        100.0,
        200.0,
        "P2",
        "normal",
        "improved",
        (90, 90, 90, 90, 90, 90, 80),
    ),
)

# measurement_unit_id, metric_id, name_zh, warning, critical,
# expected_current_status, expected_trend_status,
# 最近 7 日分子/分母/原始成功率。
_KPI_DAILY_HEALTH_RATE_METRICS = (
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_RATE_1",
        "媒体资源创建成功率",
        80.0,
        70.0,
        "fail",
        "worsened",
        (122, 132, 140, 128, 145, 150, 129),
        (200, 200, 200, 200, 200, 200, 200),
        (61.0, 66.0, 70.0, 64.0, 72.5, 75.0, 64.5),
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_RATE_2",
        "媒体资源创建请求成功率",
        90.0,
        80.0,
        "not_applicable",
        "no_baseline",
        (0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0),
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ),
    (
        "MU_HEALTH_MEDIA",
        "ME_HEALTH_RATE_3",
        "DC 资源更新成功率",
        85.0,
        75.0,
        "normal",
        "improved",
        (88, 88, 88, 88, 88, 88, 90),
        (100, 100, 100, 100, 100, 100, 100),
        (88.0, 88.0, 88.0, 88.0, 88.0, 88.0, 90.0),
    ),
    (
        "MU_HEALTH_MEDIA",
        "ME_HEALTH_RATE_4",
        "数据通道资源更新请求成功率",
        75.0,
        60.0,
        "warn",
        "improved",
        (65, 65, 65, 65, 65, 65, 70),
        (100, 100, 100, 100, 100, 100, 100),
        (65.0, 65.0, 65.0, 65.0, 65.0, 65.0, 70.0),
    ),
)


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


def _english_call_kpi() -> str:
    """生成英文表头 KPI 样例，覆盖真实 App Problem Scene 的导出格式。"""
    start = datetime(2026, 9, 2)
    end = start + timedelta(minutes=15)
    lines = [
        "NE Type:UMF",
        "Measurement Unit Name:Call Session API Statistics",
        KPI_HEADER_EN,
    ]
    for index, (service, instance, _load_factor, _quality_factor) in enumerate(CALL_INSTANCES):
        resource_requests = 0 if index < 2 else 1
        resource_rates = ",,," if resource_requests == 0 else ",100.00,100.00,100.00,100.00"
        lines.append(
            f"{service},{instance},ok,,{start:%Y-%m-%d %H:%M:%S},{end:%Y-%m-%d %H:%M:%S},15,"
            f"1500,1498,2,99.87,0.13,220,110,{resource_requests},{resource_requests}{resource_rates}"
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


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    """生成成员时间戳固定的 ZIP，供分类边界夹具复用。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            _add_bytes(archive, name, content)
    return buffer.getvalue()


def _tar_gz_bytes(members: dict[str, bytes]) -> bytes:
    """生成成员与 GZIP 头时间戳固定的 TAR.GZ，供主机日志夹具复用。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mtime = 0
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    return gzip.compress(buffer.getvalue(), mtime=0)


def _us3_service_log_members() -> dict[str, bytes]:
    """构造 13 个入选原始日志、85 个轮转 GZIP 和全部排除项。"""
    members: dict[str, bytes] = {}
    selected_direct = (
        ("UMFAcc", "UMFAcc.log", 3),
        ("UmfService", "UmfService.log", 3),
        ("CacheService", "CacheService.log", 4),
        ("ResourceManageService", "ResourceManageService.log", 3),
    )
    for service, filename, count in selected_direct:
        for index in range(1, count + 1):
            member = f"{service}/logs/node-{index:02d}/pod-01/{filename}"
            members[member] = f"2026-09-18T09:00:00Z INFO {service} node-{index:02d} direct\n".encode()

    for service, prefix, count in (("UMFAcc", "UMFAcc", 42), ("UmfService", "UmfService", 43)):
        for index in range(1, count + 1):
            node = (index - 1) % 7 + 1
            pod = (index - 1) // 7 + 1
            filename = f"{prefix}_{20260918000000000 + index}.log.gz"
            member = f"{service}/logs/node-{node:02d}/pod-{pod:02d}/{filename}"
            members[member] = _gzip_bytes(f"2026-09-18T09:00:00Z INFO {service} node-{node:02d} rotated-{index:02d}\n")

    excluded = {
        "UMFAcc/logs/node-01/proxy/UMFAcc.log": b"proxy\n",
        "UMFAcc/logs/node-01/RScheck/script.sh": b"# check script\n",
        "UMFAcc/logs/node-01/rscheck_20260918.gz": b"not selected\n",
        "UMFAcc/logs/node-01/dblog.tar.gz": b"not selected\n",
        "UMFAcc/logs/node-01/UFP_other.log": b"ufp\n",
        "UMFAcc/logs/node-01/UFP_MSS_2_0.zip": b"not selected\n",
        "UMFAcc/logs/node-01/monitor_detect.log": b"monitor\n",
        "UmfService/logs/node-02/UmfService_monitor.log": b"monitor\n",
        "UmfService/logs/node-02/start/boot.log": b"start\n",
        "UmfService/logs/node-02/proxy/request.log": b"proxy\n",
        "CacheService/logs/node-03/bbox.dat.txt": b"bbox\n",
        "LocalLogReport.csv": b"report\n",
        "Unmatched/notes.txt": b"notes\n",
    }
    members.update(excluded)
    return members


def _us3_chr_members() -> dict[str, bytes]:
    """构造 3 个 CHR GZIP、报告排除项和未选成员。"""
    return {
        "nodes/paas-01/health.bil.gz": _gzip_bytes("bil paas-01\n"),
        "nodes/paas-02/health_2.bil.gz": _gzip_bytes("bil paas-02\n"),
        "nodes/paas-03/health_3.bil.gz": _gzip_bytes("bil paas-03\n"),
        "nodes/paas-01/LocalLogReport.csv": b"report\n",
        "nodes/paas-01/notes.txt": b"notes\n",
    }


def _corrupt_zip_member_crc(payload: bytes, member_name: str) -> bytes:
    """修改指定 ZIP 成员的中央目录 CRC，保留其他成员可读且输出稳定。"""
    corrupted = bytearray(payload)
    eocd_offset = payload.rfind(b"PK\x05\x06")
    if eocd_offset < 0:
        raise ValueError("ZIP 缺少中央目录结束记录")
    entry_count = struct.unpack_from("<H", payload, eocd_offset + 10)[0]
    central_offset = struct.unpack_from("<I", payload, eocd_offset + 16)[0]
    target_name = member_name.encode()

    for _ in range(entry_count):
        if payload[central_offset : central_offset + 4] != b"PK\x01\x02":
            raise ValueError("ZIP 中央目录结构无效")
        name_length = struct.unpack_from("<H", payload, central_offset + 28)[0]
        extra_length = struct.unpack_from("<H", payload, central_offset + 30)[0]
        comment_length = struct.unpack_from("<H", payload, central_offset + 32)[0]
        name_start = central_offset + 46
        if payload[name_start : name_start + name_length] == target_name:
            crc = struct.unpack_from("<I", payload, central_offset + 16)[0]
            struct.pack_into("<I", corrupted, central_offset + 16, crc ^ 1)
            return bytes(corrupted)
        central_offset += 46 + name_length + extra_length + comment_length

    raise ValueError(f"未找到 ZIP 成员: {member_name}")


def _kpi_daily_health_metric_entries() -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    for (
        unit_id,
        metric_id,
        name_zh,
        direction,
        warning_threshold,
        critical_threshold,
        importance,
        expected_current_status,
        expected_trend_status,
        _values,
    ) in _KPI_DAILY_HEALTH_BASE_METRICS:
        metrics.append(
            {
                "measurement_unit_id": unit_id,
                "metric_resource_id": metric_id,
                "name_zh": name_zh,
                "role": "base",
                "raw_columns": [name_zh],
                "direction": direction,
                "warning_threshold": warning_threshold,
                "critical_threshold": critical_threshold,
                "importance": importance,
                "expected_current_status": expected_current_status,
                "expected_trend_status": expected_trend_status,
            }
        )
    for (
        unit_id,
        metric_id,
        name_zh,
        warning_threshold,
        critical_threshold,
        expected_current_status,
        expected_trend_status,
        _numerator_values,
        _denominator_values,
        _raw_values,
    ) in _KPI_DAILY_HEALTH_RATE_METRICS:
        metrics.append(
            {
                "measurement_unit_id": unit_id,
                "metric_resource_id": metric_id,
                "name_zh": name_zh,
                "role": "derived",
                "raw_columns": [
                    f"{name_zh}分子",
                    f"{name_zh}分母",
                    name_zh,
                ],
                "direction": "higher_better",
                "warning_threshold": warning_threshold,
                "critical_threshold": critical_threshold,
                "importance": "P1",
                "expected_current_status": expected_current_status,
                "expected_trend_status": expected_trend_status,
            }
        )
    return metrics


def _kpi_daily_health_source_file(unit_id: str) -> str:
    fragment = next(fragment for candidate, fragment, _name in KPI_DAILY_HEALTH_UNITS if candidate == unit_id)
    return f"ne333_{fragment}_15_0_20261105000000.csv"


def _kpi_daily_health_csv(unit_id: str) -> str:
    base_metrics = [item for item in _KPI_DAILY_HEALTH_BASE_METRICS if item[0] == unit_id]
    rate_metrics = [item for item in _KPI_DAILY_HEALTH_RATE_METRICS if item[0] == unit_id]
    fieldnames = ["container", "测量开始时间", "测量结束时间", "周期(分钟)"]
    fieldnames.extend(str(item[2]) for item in base_metrics)
    for item in rate_metrics:
        name_zh = str(item[2])
        fieldnames.extend([f"{name_zh}分子", f"{name_zh}分母", name_zh])

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    start = datetime(*KPI_DAILY_HEALTH_FIXED_DATE)
    for index, offset in enumerate(range(6, -1, -1)):
        measured_at = start - timedelta(days=offset)
        row: dict[str, object] = {
            "container": "pod-health-a",
            "测量开始时间": measured_at.strftime("%Y-%m-%d %H:%M:%S"),
            "测量结束时间": (measured_at + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
            "周期(分钟)": 15,
        }
        for item in base_metrics:
            values = item[9]
            if values:
                row[str(item[2])] = values[index]
        for item in rate_metrics:
            name_zh = str(item[2])
            numerator_values = item[7]
            denominator_values = item[8]
            raw_values = item[9]
            row[f"{name_zh}分子"] = numerator_values[index]
            row[f"{name_zh}分母"] = denominator_values[index]
            row[name_zh] = raw_values[index]
        writer.writerow(row)
    return buffer.getvalue()


def _kpi_daily_health_manifest() -> dict[str, object]:
    metrics = _kpi_daily_health_metric_entries()
    current_counts = Counter(str(item["expected_current_status"]) for item in metrics)
    trend_counts = Counter(str(item["expected_trend_status"]) for item in metrics)
    disabled_filename = "ne333_Disabled_E2E_15_0_20261105000000.csv"
    return {
        "schema_version": 1,
        "package_kind": "kpi_daily_health",
        "data_date": "2026-11-05",
        "timezone": "Asia/Shanghai",
        "enabled_measurement_unit_ids": [item[0] for item in KPI_DAILY_HEALTH_UNITS],
        "disabled_measurement_unit_ids": [KPI_DAILY_HEALTH_DISABLED_UNIT[0]],
        "metric_count": len(metrics),
        "metrics": metrics,
        "expected_current_counts": {status: current_counts[status] for status in KPI_DAILY_HEALTH_CURRENT_STATUSES},
        "expected_trend_counts": {status: trend_counts[status] for status in KPI_DAILY_HEALTH_TREND_STATUSES},
        "boundaries": {
            "zero_denominator_metric_ids": ["ME_HEALTH_RATE_2"],
            "no_data_metric_ids": ["ME_HEALTH_REGISTERED_USERS", "ME_HEALTH_ALARM_COUNT"],
            "all_zero_unknown_metric_ids": ["ME_HEALTH_CALL_QUALITY"],
            "success_rate_evidence": {
                "metric_resource_id": "ME_HEALTH_RATE_1",
                "numerator": 129,
                "denominator": 200,
                "value": 64.5,
            },
            "disabled_measurement_unit_ids": [KPI_DAILY_HEALTH_DISABLED_UNIT[0]],
            "out_of_scope_files": [disabled_filename],
            "legacy_task_without_daily_health": True,
        },
    }


def build_kpi_daily_health_fixture(directory: Path) -> Path:
    """生成固定、幂等的 20 指标日健康样例包，覆盖当前判定与趋势关键边界。"""
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / KPI_DAILY_HEALTH_PACKAGE_NAME
    performance_buffer = io.BytesIO()
    with zipfile.ZipFile(performance_buffer, "w", zipfile.ZIP_DEFLATED) as performance:
        for unit_id, _fragment, _name_zh in KPI_DAILY_HEALTH_UNITS:
            _add_bytes(
                performance,
                _kpi_daily_health_source_file(unit_id),
                _kpi_daily_health_csv(unit_id).encode("utf-8"),
            )
        _add_bytes(
            performance,
            "ne333_Disabled_E2E_15_0_20261105000000.csv",
            (
                "container,测量开始时间,测量结束时间,周期(分钟),停用单元指标\n"
                "pod-health-a,2026-11-05 10:00:00,2026-11-05 10:15:00,15,1\n"
            ).encode(),
        )

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        _add_bytes(
            archive,
            f"{UMF_SCENE_ROOT}/Performance Measurement Results/PerfResult_20261105000000.zip",
            performance_buffer.getvalue(),
        )
        _add_bytes(
            archive,
            "KPI/daily-health-fixture-manifest.json",
            json.dumps(_kpi_daily_health_manifest(), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
    return output


def build_real_package(directory: Path, *, include_kpi: bool = True) -> Path:
    """生成固定内容的真实结构样例包；``include_kpi=False`` 生成 KPI 缺失边界包。"""
    alarm_buffer = io.BytesIO()
    with zipfile.ZipFile(alarm_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_bytes(zf, "alarm_history_202609010101137101_001.csv", ALARM_CSV_001.encode("utf-8"))
        _add_bytes(zf, "alarm_history_202609010101137101_002.csv", ALARM_CSV_002.encode("utf-8"))
        _add_bytes(zf, "alarm_history_202609010101137101_003.csv", ALARM_CSV_003.encode("utf-8"))
        _add_bytes(zf, "alarm_english_039.csv", ALARM_ENGLISH_CSV.encode("utf-8"))
        _add_bytes(zf, "alarm_chinese_039.csv", ALARM_CHINESE_CSV.encode("utf-8"))
        _add_bytes(zf, "alarm_mixed_039.csv", ALARM_MIXED_CSV.encode("utf-8"))
        _add_bytes(zf, "alarm_bad_encoding_039.csv", ALARM_BAD_ENCODING_BYTES)

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

    umf_base = "Outer Device/Problem 038/wrapper/UMF Problem Scene"
    umf_kpi_members = {
        f"ne333_Call_Session_API_Statistics_15_{index:02d}_202609180000.csv": _call_kpi(15).encode("utf-8")
        for index in range(73)
    }
    umf_kpi_members["ne333_Call_Session_API_Statistics_15_73_202609180000.csv"] = _english_call_kpi().encode("utf-8")
    umf_kpi_buffer = _zip_bytes(umf_kpi_members)
    mesh_metrics_buffer = _zip_bytes(
        {
            f"mesh-metric-{index:02d}.csv": (
                f"采集时间,指标名称,指标值\n2026-09-18 09:{index:02d}:00Z,mesh_connections,{100 + index}\n"
            ).encode()
            for index in range(14)
        }
    )
    mml_buffer = _zip_bytes(
        {
            "Config/Fragment.txt": b"ADD UMF:UNIT=1;\n",
            "Config/Parameters.cfg": b"parameter=value\n",
        }
    )
    unknown_buffer = _zip_bytes(
        {
            "PerfResult_should_not_route.csv": b"not,a,classified,kpi\nfixture,only\n",
        }
    )
    unsafe_alarm_buffer = _zip_bytes(
        {
            "../escape.csv": b"must,not,escape,classification,task,directory\n",
        }
    )
    corrupt_alarm_buffer = _corrupt_zip_member_crc(
        _zip_bytes(
            {
                "archive/valid_alarm.csv": CSP_ALARM_WITHOUT_PROBLEMS_CSV.encode("utf-8"),
                "archive/corrupted_alarm.csv": b"corrupted alarm member\n",
            }
        ),
        "archive/corrupted_alarm.csv",
    )

    directory.mkdir(parents=True, exist_ok=True)
    output = directory / (PACKAGE_NAME if include_kpi else NO_KPI_PACKAGE_NAME)
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
        if include_kpi:
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
        _add_bytes(
            zf,
            f"{umf_base}/Basic Information About the UMF/Nested/config.ini",
            b"[umf]\nname=UMF Problem Scene\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/debugging commands/Diagnostic.JSON",
            b'{"status":"synthetic","node":"umf-01"}\n',
        )
        _add_bytes(
            zf,
            f"{umf_base}/Equipment Status/equipment.csv",
            b"slot,board,status\n1,UMF-BOARD-01,normal\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/MESH Information (Problem)/mesh.txt",
            b"mesh peer umf-02 state=normal\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/System Resources/resources.txt",
            b"cpu=32% memory=41%\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/operation logs/OPERATIONLOG_HISTORY_20260918.CSV",
            b"time,user,operation\n2026-09-18T09:00:00Z,admin,query\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/MML Configurations/EXP MML.txt",
            b"LST UMF:;\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/MML Configurations/EXPMML_20260918.zip",
            mml_buffer,
        )
        if include_kpi:
            _add_bytes(
                zf,
                f"{umf_base}/Performance Measurement Results/PerfResult_20260918.zip",
                umf_kpi_buffer,
            )
        _add_bytes(
            zf,
            f"{umf_base}/MESH Application Metrics/CollectExport_20260918.zip",
            mesh_metrics_buffer,
        )
        _add_bytes(
            zf,
            f"{umf_base}/Service Logs (Problem)/ServiceLogs_20260918.zip",
            _zip_bytes(_us3_service_log_members()),
        )
        _add_bytes(
            zf,
            f"{umf_base}/CHR Information/ServiceLogs_20260918.zip",
            _zip_bytes(_us3_chr_members()),
        )
        _add_bytes(
            zf,
            f"{umf_base}/Host Debugging Logs/DEBUG.tar.gz",
            _tar_gz_bytes(
                {
                    "nodes/paas-01/DEBUG.log.gz": _gzip_bytes("debug paas-01\n"),
                    "nodes/paas-01/README.txt": b"debug readme\n",
                    "nodes/paas-02/DEBUG.log.gz": _gzip_bytes("debug paas-02\n"),
                }
            ),
        )
        _add_bytes(
            zf,
            f"{umf_base}/Host System Logs/OS.tar.gz",
            _tar_gz_bytes(
                {
                    "nodes/paas-01/OS.log.gz": _gzip_bytes("system paas-01\n"),
                    "nodes/paas-01/uptime.txt": b"up 1 day\n",
                    "nodes/paas-02/OS.log.gz": _gzip_bytes("system paas-02\n"),
                }
            ),
        )
        _add_bytes(
            zf,
            f"{umf_base}/collectandcheck.ini",
            b"[collect]\ncheck=all\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/Unlisted/custom.dat",
            b"synthetic unknown file\n",
        )
        _add_bytes(
            zf,
            f"{umf_base}/Unlisted/UnknownBundle.ZIP",
            unknown_buffer,
        )
        _add_bytes(
            zf,
            "csp-device/0/Problems/Inventory/inventory.csv",
            b"device,type\ncsp-01,CSP\n",
        )
        _add_bytes(
            zf,
            f"{BASE}/Alarm Information/boundary/umf_alarm_boundary.csv",
            UMF_ALARM_BOUNDARY_CSV.encode("utf-8"),
        )
        _add_bytes(
            zf,
            f"{BASE}/Alarm Information/boundary/umf_alarm_empty.csv",
            b"",
        )
        _add_bytes(
            zf,
            f"{BASE}/Alarm Information/boundary/umf_alarm_header_only.csv",
            UMF_ALARM_HEADER.encode("utf-8"),
        )
        _add_bytes(
            zf,
            f"{BASE}/Alarm Information/boundary/umf_alarm_zero_records.csv",
            f"{UMF_ALARM_HEADER}\n".encode(),
        )
        _add_bytes(
            zf,
            "csp-device/0/Problems/Alarm Data/current/csp_alarm_primary.csv",
            CSP_ALARM_PRIMARY_CSV.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "csp-device/0/Alarm Data/current/csp_alarm_without_problems.csv",
            CSP_ALARM_WITHOUT_PROBLEMS_CSV.encode("utf-8"),
        )
        _add_bytes(
            zf,
            "csp-device/0/Problems/Inventory/runtime-inventory.csv",
            b"component,state\ncsp-core,running\n",
        )
        _add_bytes(
            zf,
            "csp-device/configuration/service.ini",
            b"[service]\nname=csp\nmode=synthetic\n",
        )
        _add_bytes(
            zf,
            "csp-device/0/Problems/Alarm Data/archive/alarm_corrupt_member.zip",
            corrupt_alarm_buffer,
        )
        _add_bytes(
            zf,
            "csp-device/0/Alarm Data/path-security/alarms.zip",
            unsafe_alarm_buffer,
        )
    return output


def isolate_umf_scene(source: Path, target: Path) -> Path:
    """只保留一个 UMF 场景，避免多个独立场景按契约共同回退到证据根。"""
    with zipfile.ZipFile(source) as source_archive, zipfile.ZipFile(target, "w") as target_archive:
        for info in source_archive.infolist():
            if info.filename == UMF_SCENE_ROOT or info.filename.startswith(f"{UMF_SCENE_ROOT}/"):
                target_archive.writestr(info, source_archive.read(info))
    return target


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "uploads"
    uploads_path = build_real_package(target)
    print(f"已生成上传样例: {uploads_path} ({uploads_path.stat().st_size} bytes)")
