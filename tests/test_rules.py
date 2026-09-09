"""六类示例规则单测（正常、告警、无数据处理）。"""

import gzip
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
        path.write_text(content, encoding="utf-8")
    return RuleContext(
        task_id="t1",
        system_id="s1",
        data_dir=data,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        log=lambda level, message, detail=None: None,
    )


def _run_rule(code: str, ctx: RuleContext):
    registry.load_all()
    return registry.get(code).run(ctx)


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
