"""规则单元测试：source_patterns 直读、正常/告警/无数据处理。"""

import gzip
from pathlib import Path

from app.inspectors.registry import registry
from app.models.schemas import RuleStatus
from app.services.executor import RuleContext


def _ctx(tmp_path: Path, files: dict[str, str]) -> RuleContext:
    data = tmp_path / "data"
    for rel, content in files.items():
        path = data / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel.lower().endswith(".gz"):
            path.write_bytes(gzip.compress(content.encode("utf-8")))
        else:
            path.write_text(content, encoding="utf-8")
    logs: list[dict] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append({"level": level, "message": message, **(detail or {})})

    ctx = RuleContext(
        task_id="t1",
        data_dir=data,
        log=log,
    )
    ctx.files = [Path(rel) for rel in files]
    ctx.logs = logs
    return ctx


def _run_rule(code: str, ctx: RuleContext):
    registry.load_all()
    rule = registry.get(code)
    if rule.prepare is not None:
        rule.prepare.run(ctx)
    return rule.run(ctx)


def test_alarm_stat_fail(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {"alarm/a.txt": "ALARM 2026-09-09 10:00:01 1001 数据库连接池耗尽 CRITICAL 未处理\n"},
    )
    result = _run_rule("alarm.stat", ctx)
    assert result.status == RuleStatus.FAIL
    assert result.metrics[0].value == 1


def test_config_check_missing_warn(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"config/app.conf": "[app]\nname=PatrolX\n"})
    result = _run_rule("config.check", ctx)
    assert result.status == RuleStatus.WARN
    assert result.metrics[1].value == 1  # missing


def test_config_check_accepts_keys_across_files(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "config/system_info.ini": "[app]\nname=app\nlog_level=INFO\n",
            "config/version.ini": "[version]\nrelease=R24.1\n",
        },
    )
    result = _run_rule("config.check", ctx)
    assert result.status == RuleStatus.PASS
    assert result.metrics[1].value == 0


def test_resource_check_warn_for_container_csv(tmp_path: Path) -> None:
    content = (
        "服务名,实例,测量开始时间,测量结束时间,周期(分钟),容器CPU使用率,容器内存使用率\n"
        "IMS-Core,ims-node-01,2026-09-02 00:00:00,2026-09-02 00:05:00,5,86.40,91.20\n"
    )
    ctx = _ctx(tmp_path, {"resource/Container_Metric_Unit_5.csv": content})
    result = _run_rule("resource.check", ctx)
    assert result.status == RuleStatus.WARN


def test_traffic_stat_skip(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {})
    result = _run_rule("traffic.stat", ctx)
    assert result.status == RuleStatus.SKIP


def test_alarm_stat_csv_created_and_cleared_time(tmp_path: Path) -> None:
    csv_text = (
        "alarm_id,created_time,cleared_time,alarm_code,severity,status,object,description\n"
        "1001,2026-09-01 10:00:01,,DB_DOWN,CRITICAL,未处理,node-1,数据库连接池耗尽\n"
        "1002,2026-09-01 10:00:04,2026-09-01 10:00:30,SCTP_DOWN,HIGH,处理中,node-1,SCTP链路中断\n"
    )
    ctx = _ctx(tmp_path, {"alarm/alarm_history.csv": csv_text})
    result = _run_rule("alarm.stat", ctx)
    assert result.status == RuleStatus.FAIL
    assert result.metrics[0].value == 2
    assert result.metrics[1].value == 1
    assert result.metadata["severity_distribution"] == {"CRITICAL": 1, "HIGH": 1}


def test_log_filter_only_reads_final_plain_logs(tmp_path: Path) -> None:
    plain = "2026-09-01T10:00:00Z ERROR app db down\n"
    ctx = _ctx(tmp_path, {"logs/paas-192.168.2.2/app.log": plain})
    gz_path = ctx.data_dir / "logs/paas-192.168.2.2/app_history.log.gz"
    gz_path.write_bytes(gzip.compress(plain.encode("utf-8")))

    result = _run_rule("log.filter", ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["files"] == 1
    assert result.metrics[1].value == 1


def test_log_filter_builds_service_index_for_service_log_layout(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:00Z INFO  app service started\n"
        "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
        "        at com.patrolx.app.DbPool.acquire(DbPool.java:88)\n"
    )
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log": app,
            "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log": aaa,
        },
    )

    result = _run_rule("log.filter", ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["service_count"] == 2
    assert result.metadata["processed_files"] == [
        "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log",
        "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log",
    ]
    assert result.metadata["levels"] == {"ERROR": 2, "STACK": 1}
    assert result.metadata["files"] == 2
    assert result.metadata["service_count"] == 2


def test_log_filter_keeps_python_traceback_after_error(tmp_path: Path) -> None:
    plain = (
        "2026-09-01T10:06:00Z ERROR app worker failed\n"
        "Traceback (most recent call last):\n"
        '  File "/opt/app/worker.py", line 42, in run\n'
        "    call_remote()\n"
        "ConnectionError: remote unavailable\n"
    )
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc_error_20260901011314.log": plain,
        },
    )

    result = _run_rule("log.filter", ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["levels"] == {"ERROR": 1, "STACK": 4}


def _logged_processed_files(ctx, code: str) -> list[str] | None:
    return next(
        (entry["files"] for entry in reversed(ctx.logs) if entry.get("rule_code") == code and "files" in entry),
        None,
    )


def test_service_errors_warn_on_hot_service(tmp_path: Path) -> None:
    lines = [
        f"2026-09-01T10:00:{second:02d}Z ERROR app db connection pool exhausted retry={second}"
        for second in range(1, 7)
    ]
    plain = "\n".join(lines) + "\n"
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 1\n"
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log": plain,
            "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log": aaa,
        },
    )
    result = _run_rule("log.service_errors", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[0].value == 2
    assert result.metrics[2].value == 6
    assert result.findings[0].title.startswith("UMFAcc 服务错误集中")
    assert result.metadata["processed_files"]
    assert result.metadata["processed_files"] == _logged_processed_files(ctx, "log.service_errors")


def test_fault_pattern_matches_real_operational_cases(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:01Z ERROR app db connection pool exhausted retry=1\n"
        "2026-09-01T10:00:02Z ERROR app db connection pool exhausted retry=2\n"
        "2026-09-01T10:00:03Z ERROR app sctp link down\n"
        "2026-09-01T10:00:04Z ERROR app sctp reconnect failed\n"
    )
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 1\n"
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log": app,
            "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log": aaa,
        },
    )
    result = _run_rule("log.fault_pattern", ctx)

    assert result.status == RuleStatus.FAIL
    assert result.metrics[0].value == 4
    assert result.metrics[1].value == 2
    assert result.metadata["pattern_counts"]["db_connection_pool_exhausted"] == 2
    assert any(finding.title.startswith("UMFAcc 数据库连接池耗尽") for finding in result.findings)
    assert result.metadata["processed_files"]
    assert result.metadata["processed_files"] == _logged_processed_files(ctx, "log.fault_pattern")


def test_repeat_error_detects_database_pool_storm(tmp_path: Path) -> None:
    lines = [
        f"2026-09-01T10:00:{second:02d}Z ERROR app db connection pool exhausted id={second}" for second in range(1, 9)
    ]
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log": "\n".join(lines) + "\n",
        },
    )
    result = _run_rule("log.repeat_error", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[1].value == 8
    assert result.findings[0].title.startswith("UMFAcc 重复错误：")
    assert result.metadata["processed_files"]
    assert result.metadata["processed_files"] == _logged_processed_files(ctx, "log.repeat_error")


def test_stacktrace_groups_by_service_and_type(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:01Z ERROR app request failed\n"
        "        at com.patrolx.app.Service.run(Service.java:31)\n"
        "java.lang.NullPointerException: service unavailable\n"
    )
    aaa = (
        "2026-09-01T10:05:00Z ERROR aaa worker failed\n"
        "Traceback (most recent call last):\n"
        "OutOfMemoryError: Java heap space\n"
    )
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc_error_20260901011314.log": app,
            "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService_error_20260901011314.log": aaa,
        },
    )
    result = _run_rule("log.stacktrace", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[0].value == 2
    assert result.metrics[1].value == 2
    assert "UMFAcc" in result.metadata["service_counts"]
    assert result.metadata["processed_files"]
    assert result.metadata["processed_files"] == _logged_processed_files(ctx, "log.stacktrace")


def test_umf_acc_rule_detects_pool_and_sctp_errors(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
        "2026-09-01T10:00:02Z ERROR app db connection pool exhausted\n"
        "2026-09-01T10:00:04Z ERROR app sctp link down\n"
    )
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log": app,
            "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log": aaa,
        },
    )
    result = _run_rule("log.umf_acc", ctx)

    assert result.status == RuleStatus.FAIL
    assert result.summary == "UMFAcc 存在数据库连接池耗尽"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("error_count", 3),
        ("pool_exhausted_count", 2),
        ("sctp_error_count", 1),
    ]
    assert [finding.title for finding in result.findings] == [
        "UMFAcc 数据库连接池耗尽",
        "UMFAcc SCTP 链路异常",
    ]
    assert result.metadata["processed_files"] == [
        "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log"
    ]


def test_umf_acc_rule_skips_when_service_missing(tmp_path: Path) -> None:
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log": aaa,
        },
    )
    result = _run_rule("log.umf_acc", ctx)

    assert result.status == RuleStatus.SKIP
    assert result.skip_reason == "未发现 UMFAcc 日志"


def test_umf_service_rule_detects_auth_and_retry_issues(tmp_path: Path) -> None:
    app = "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
    aaa = (
        "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
        "2026-09-01T10:05:01Z ERROR aaa auth failure count 4\n"
        "2026-09-01T10:05:02Z WARN  aaa retry timer exceeded\n"
    )
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log": app,
            "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log": aaa,
        },
    )
    result = _run_rule("log.umf_service", ctx)

    assert result.status == RuleStatus.WARN
    assert result.summary == "UmfService 存在认证失败"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("error_count", 2),
        ("auth_failure_count", 2),
        ("retry_timer_count", 1),
    ]
    assert result.findings[0].title == "UmfService 认证失败"
    assert result.metadata["processed_files"] == [
        "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log"
    ]


def test_umf_service_rule_skips_when_service_missing(tmp_path: Path) -> None:
    app = "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
    ctx = _ctx(
        tmp_path,
        {
            "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log": app,
        },
    )
    result = _run_rule("log.umf_service", ctx)

    assert result.status == RuleStatus.SKIP
    assert result.skip_reason == "未发现 UmfService 日志"


def test_ccc_service_rule_passes_when_all_ten_nodes_start(tmp_path: Path) -> None:
    files: dict[str, str] = {
        "logs/ServiceLog_20260901011314/UMFAcc/logs/paas-other/UMFAcc.log": (
            "2026-09-01T10:00:00Z ERROR app unrelated error\n"
        )
    }
    for index in range(10):
        node = f"paas-192.168.2.{index}"
        files[f"logs/ServiceLog_20260901011314/CCC/logs/{node}/ccc_service.log"] = (
            f"2026-09-01T10:00:{index:02d}Z INFO  CCC node {node} start success\n"
        )
    ctx = _ctx(tmp_path, files)

    result = _run_rule("log.ccc_service", ctx)

    assert result.status == RuleStatus.PASS
    assert result.summary == "CCC 所有节点启动正常"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("node_count", 10),
        ("startup_success_node_count", 10),
        ("startup_failure_node_count", 0),
    ]
    assert result.findings == []
    assert result.metadata["processed_files"] == [
        f"logs/ServiceLog_20260901011314/CCC/logs/paas-192.168.2.{index}/ccc_service.log" for index in range(10)
    ]


def test_ccc_service_rule_fails_when_any_node_has_no_start_success(tmp_path: Path) -> None:
    files: dict[str, str] = {}
    for index in range(10):
        node = f"paas-192.168.2.{index}"
        message = (
            f"2026-09-01T10:00:{index:02d}Z INFO  CCC node {node} start success"
            if index != 7
            else f"2026-09-01T10:00:{index:02d}Z ERROR CCC node {node} start failed"
        )
        files[f"logs/ServiceLog_20260901011314/CCC/logs/{node}/ccc_service.log"] = message + "\n"
    ctx = _ctx(tmp_path, files)

    result = _run_rule("log.ccc_service", ctx)

    assert result.status == RuleStatus.FAIL
    assert result.summary == "CCC 存在节点启动异常"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("node_count", 10),
        ("startup_success_node_count", 9),
        ("startup_failure_node_count", 1),
    ]
    assert [finding.details for finding in result.findings] == ["节点 paas-192.168.2.7 未出现 start success"]
    assert result.findings[0].evidence == "CCC node paas-192.168.2.7 start failed"


def test_ddd_service_rule_fails_on_ping_failures(tmp_path: Path) -> None:
    files: dict[str, str] = {}
    failed_nodes = {3, 7}
    for index in range(10):
        node = f"paas-192.168.2.{index}"
        message = (
            f"2026-09-01T10:00:{index:02d}Z ERROR DDD node {node} ping failed"
            if index in failed_nodes
            else f"2026-09-01T10:00:{index:02d}Z INFO  DDD node {node} ping success"
        )
        files[f"logs/ServiceLog_20260901011314/DDD/logs/{node}/ddd_service.log"] = message + "\n"
    ctx = _ctx(tmp_path, files)

    result = _run_rule("log.ddd_service", ctx)

    assert result.status == RuleStatus.FAIL
    assert result.summary == "DDD 存在 ping 失败"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("ping_failure_count", 2),
        ("affected_node_count", 2),
    ]
    assert [finding.details for finding in result.findings] == [
        "节点 paas-192.168.2.3 命中 1 条 ping 失败日志",
        "节点 paas-192.168.2.7 命中 1 条 ping 失败日志",
    ]


def test_ddd_service_rule_passes_without_ping_failure(tmp_path: Path) -> None:
    files: dict[str, str] = {}
    for index in range(10):
        node = f"paas-192.168.2.{index}"
        files[f"logs/ServiceLog_20260901011314/DDD/logs/{node}/ddd_service.log"] = (
            f"2026-09-01T10:00:{index:02d}Z INFO  DDD node {node} ping success\n"
        )
    ctx = _ctx(tmp_path, files)

    result = _run_rule("log.ddd_service", ctx)

    assert result.status == RuleStatus.PASS
    assert result.summary == "DDD 未发现 ping 失败"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("ping_failure_count", 0),
        ("affected_node_count", 0),
    ]
    assert result.findings == []


def test_ccc_and_ddd_service_rules_skip_when_service_missing(tmp_path: Path) -> None:
    files = {
        "logs/ServiceLog_20260901011314/UmfService/logs/paas-192.168.2.2/UmfService.log": (
            "2026-09-01T10:00:00Z INFO  UmfService start success\n"
        )
    }
    ctx = _ctx(tmp_path, files)

    ccc = _run_rule("log.ccc_service", ctx)
    ddd = _run_rule("log.ddd_service", ctx)

    assert ccc.status == RuleStatus.SKIP
    assert ccc.skip_reason == "未发现 CCC 日志"
    assert ddd.status == RuleStatus.SKIP
    assert ddd.skip_reason == "未发现 DDD 日志"


def test_resource_check_supports_container_csv_by_column_names(tmp_path: Path) -> None:
    content = (
        "设备类型：XXX\n"
        "测量单元名称：容器指标单元\n"
        "实例,周期(分钟),测量开始时间,容器内存使用率,服务名,容器CPU使用率,测量结束时间\n"
        "ims-node-01,5,2026-09-02 00:00:00,91.20,IMS-Core,86.40,2026-09-02 00:05:00\n"
    )
    ctx = _ctx(tmp_path, {"resource/Container_Metric_Unit_5.csv": content})
    result = _run_rule("resource.check", ctx)

    assert result.status == RuleStatus.WARN
    assert [(metric.key, metric.value) for metric in result.metrics] == [("high_cpu", 1), ("high_mem", 1)]
    assert {finding.title for finding in result.findings} == {
        "IMS-Core/ims-node-01 CPU使用率偏高",
        "IMS-Core/ims-node-01 内存使用率偏高",
    }
