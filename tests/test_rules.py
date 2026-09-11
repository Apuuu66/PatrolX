"""六类示例规则单测（正常、告警、无数据处理）。"""

import gzip
import json
from pathlib import Path

from app.inspectors.registry import registry
from app.models.schemas import RuleStatus
from app.services.artifacts import ArtifactStore
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
        system_id="s1",
        data_dir=data,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        log=log,
    )
    ctx.logs = logs
    return ctx


def _run_rule(code: str, ctx: RuleContext):
    registry.load_all()
    inspector = registry.get(code)
    result = inspector.run(ctx)
    for key in inspector.outputs_artifacts:
        path = ctx.rule_artifact_path(inspector.code, key)
        if path.exists():
            ctx.artifacts.save(key, inspector, path)
    return result


def test_kpi_threshold_warn(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"kpi/kpi.csv": "metric,value\ncall_success_rate,99.2\nattach_success_rate,96.5\n"})
    result = _run_rule("kpi.threshold", ctx)
    assert result.status == RuleStatus.WARN
    assert result.findings and "attach_success_rate" in result.findings[0].finding_id


def test_kpi_threshold_skip(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {})
    result = _run_rule("kpi.threshold", ctx)
    assert result.status == RuleStatus.SKIP
    assert result.skip_reason


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


def test_resource_check_warn(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"resource/pod.txt": "pod-1 cpu 900m mem 512Mi\n"})
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


def test_log_filter_reads_plain_and_gzip_logs(tmp_path: Path) -> None:
    plain = "2026-09-01T10:00:00Z ERROR app db down\n"
    log_dir = tmp_path / "data/log/paas-192.168.2.2"
    log_dir.mkdir(parents=True)
    (log_dir / "app.log").write_text(plain, encoding="utf-8")
    (log_dir / "app_history.log.gz").write_bytes(gzip.compress(plain.encode("utf-8")))
    ctx = _ctx(tmp_path, {})
    result = _run_rule("log.filter", ctx)
    assert result.status == RuleStatus.PASS
    assert result.metadata["files"] == 2
    assert result.metadata["total_lines"] == 2


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
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": app,
            "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log.gz": aaa,
        },
    )

    result = _run_rule("log.filter", ctx)
    root = Path(ctx.artifacts.get("log.filter.artifacts.filtered_logs").path)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))

    assert result.status == RuleStatus.PASS
    assert result.metadata["service_count"] == 2
    assert result.metadata["processed_files"] == [
        "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log.gz",
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log",
    ]
    assert set(index["services"]) == {"AAAService", "AppService"}
    assert index["services"]["AppService"]["error_count"] == 1
    assert index["services"]["AppService"]["nodes"] == {"paas-192.168.2.2": 2}
    assert index["services"]["AAAService"]["error_count"] == 1
    records = [json.loads(line) for line in (root / "filtered.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {record["service"] for record in records} == {"AAAService", "AppService"}
    app_records = [record for record in records if record["service"] == "AppService"]
    assert [record["level"] for record in app_records] == ["ERROR", "STACK"]
    assert app_records[0]["node"] == "paas-192.168.2.2"
    assert "DbPool.acquire" in app_records[1]["message"]


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
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/"
            "app_service_error_20260901011314.log": plain,
        },
    )

    result = _run_rule("log.filter", ctx)
    root = Path(ctx.artifacts.get("log.filter.artifacts.filtered_logs").path)
    records = [json.loads(line) for line in (root / "filtered.jsonl").read_text(encoding="utf-8").splitlines()]

    assert result.status == RuleStatus.PASS
    assert [record["level"] for record in records] == ["ERROR", "STACK", "STACK", "STACK", "STACK"]


def _load_filter_artifact(ctx) -> None:
    artifact = ctx.artifacts.get("log.filter.artifacts.filtered_logs")
    ctx.inputs[artifact.key] = artifact


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
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": plain,
            "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log": aaa,
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.service_errors", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[0].value == 2
    assert result.metrics[2].value == 6
    assert result.findings[0].title.startswith("AppService 服务错误集中")
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
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": app,
            "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log": aaa,
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.fault_pattern", ctx)

    assert result.status == RuleStatus.FAIL
    assert result.metrics[0].value == 4
    assert result.metrics[1].value == 2
    assert result.metadata["pattern_counts"]["db_connection_pool_exhausted"] == 2
    assert any(finding.title.startswith("AppService 数据库连接池耗尽") for finding in result.findings)
    assert result.metadata["processed_files"]
    assert result.metadata["processed_files"] == _logged_processed_files(ctx, "log.fault_pattern")


def test_repeat_error_detects_database_pool_storm(tmp_path: Path) -> None:
    lines = [
        f"2026-09-01T10:00:{second:02d}Z ERROR app db connection pool exhausted id={second}" for second in range(1, 9)
    ]
    ctx = _ctx(
        tmp_path,
        {
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": "\n".join(
                lines
            )
            + "\n",
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.repeat_error", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[1].value == 8
    assert result.findings[0].title.startswith("AppService 重复错误：")
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
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_error_20260901011314.log": app,
            "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_error_20260901011314.log": aaa,
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.stacktrace", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[0].value == 2
    assert result.metrics[1].value == 2
    assert "AppService" in result.metadata["service_counts"]
    assert result.metadata["processed_files"]
    assert result.metadata["processed_files"] == _logged_processed_files(ctx, "log.stacktrace")


def test_app_service_rule_detects_pool_and_sctp_errors(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
        "2026-09-01T10:00:02Z ERROR app db connection pool exhausted\n"
        "2026-09-01T10:00:04Z ERROR app sctp link down\n"
    )
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
    ctx = _ctx(
        tmp_path,
        {
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service.log": app,
            "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service.log": aaa,
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.app_service", ctx)

    assert result.status == RuleStatus.FAIL
    assert result.summary == "AppService 存在数据库连接池耗尽"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("error_count", 3),
        ("pool_exhausted_count", 2),
        ("sctp_error_count", 1),
    ]
    assert [finding.title for finding in result.findings] == [
        "AppService 数据库连接池耗尽",
        "AppService SCTP 链路异常",
    ]
    assert result.metadata["processed_files"] == [
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service.log"
    ]


def test_app_service_rule_skips_when_service_missing(tmp_path: Path) -> None:
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
    ctx = _ctx(
        tmp_path,
        {
            "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service.log": aaa,
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.app_service", ctx)

    assert result.status == RuleStatus.SKIP
    assert result.skip_reason == "未发现 AppService 日志"


def test_aaa_service_rule_detects_auth_and_retry_issues(tmp_path: Path) -> None:
    app = "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
    aaa = (
        "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
        "2026-09-01T10:05:01Z ERROR aaa auth failure count 4\n"
        "2026-09-01T10:05:02Z WARN  aaa retry timer exceeded\n"
    )
    ctx = _ctx(
        tmp_path,
        {
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service.log": app,
            "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service.log": aaa,
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.aaa_service", ctx)

    assert result.status == RuleStatus.WARN
    assert result.summary == "AAAService 存在认证失败"
    assert [(metric.key, metric.value) for metric in result.metrics] == [
        ("error_count", 2),
        ("auth_failure_count", 2),
        ("retry_timer_count", 1),
    ]
    assert result.findings[0].title == "AAAService 认证失败"
    assert result.metadata["processed_files"] == [
        "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service.log"
    ]


def test_aaa_service_rule_skips_when_service_missing(tmp_path: Path) -> None:
    app = "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
    ctx = _ctx(
        tmp_path,
        {
            "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service.log": app,
        },
    )
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.aaa_service", ctx)

    assert result.status == RuleStatus.SKIP
    assert result.skip_reason == "未发现 AAAService 日志"
