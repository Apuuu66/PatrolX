"""log.app_service（P1）：AppService 专属日志巡检。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.log.common import log_service_processed_files, service_records
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result
from app.services.prepare import prepared_dir

SERVICE_NAME = "AppService"
ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL"}
POOL_FAIL_COUNT = 2
SCTP_FAIL_COUNT = 3

inspector = Inspector(
    code="log.app_service",
    name="AppService 日志巡检",
    category=RuleCategory.LOG,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.1.0",
    description="检查 AppService 的数据库连接池耗尽与 SCTP 链路错误",
    recommendation="优先检查数据库连接池配置、数据库负载和 SCTP 链路状态",
    source_patterns=[r"^logs/.*\.(log|log\.gz)$"],
    outputs_metrics=[
        {"key": "error_count", "label": "错误条数", "unit": "条"},
        {"key": "pool_exhausted_count", "label": "连接池耗尽条数", "unit": "条"},
        {"key": "sctp_error_count", "label": "SCTP 错误条数", "unit": "条"},
    ],
)


def _prepare(ctx: RuleContext) -> object:
    """归一化 AppService 日志并写入规则私有 prepared 数据。"""
    records, source_files = service_records(ctx, SERVICE_NAME)
    owner_dir = prepared_dir(ctx, inspector.code)
    owner_dir.mkdir(parents=True, exist_ok=True)
    path = owner_dir / "app_service_records.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    (owner_dir / "source_files.json").write_text(json.dumps(source_files, ensure_ascii=False), encoding="utf-8")
    return None


def _read_prepared_records(ctx: RuleContext) -> list[dict]:
    path = prepared_dir(ctx, inspector.code) / "app_service_records.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_prepared_source_files(ctx: RuleContext) -> list[str]:
    path = prepared_dir(ctx, inspector.code) / "source_files.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _run(ctx: RuleContext) -> object:
    records = _read_prepared_records(ctx)
    if ctx.files and not records:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 AppService 日志",
            skip_reason="未发现 AppService 日志",
        )
    if not ctx.files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现匹配源文件",
            skip_reason="source_patterns 未匹配到文件",
        )
    if not records:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 AppService 日志",
            skip_reason="未发现 AppService 日志",
        )

    source_files: list[str] = []
    for record in records:
        source_file = record.get("source_file")
        if source_file and source_file not in source_files:
            source_files.append(source_file)
    processed_files = log_service_processed_files(ctx, inspector.code, _read_prepared_source_files(ctx))
    pool_records = [record for record in records if "connection pool exhausted" in record["message"].lower()]
    sctp_records = [record for record in records if "sctp" in record["message"].lower()]
    error_count = sum(record.get("level") in ERROR_LEVELS for record in records)

    findings: list[Finding] = []
    if pool_records:
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-pool-exhausted",
                title="AppService 数据库连接池耗尽",
                severity=Severity.HIGH,
                source_file=pool_records[0]["source_file"],
                evidence=pool_records[0]["message"],
                details=f"命中 {len(pool_records)} 条连接池耗尽日志",
                recommendation=inspector.recommendation,
            )
        )
    if sctp_records:
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-sctp-error",
                title="AppService SCTP 链路异常",
                severity=Severity.HIGH,
                source_file=sctp_records[0]["source_file"],
                evidence=sctp_records[0]["message"],
                details=f"命中 {len(sctp_records)} 条 SCTP 错误日志",
                recommendation=inspector.recommendation,
            )
        )

    if len(pool_records) >= POOL_FAIL_COUNT or len(sctp_records) >= SCTP_FAIL_COUNT:
        status = RuleStatus.FAIL
        summary = "AppService 存在数据库连接池耗尽" if pool_records else "AppService 存在 SCTP 链路异常"
    elif pool_records or sctp_records:
        status = RuleStatus.WARN
        summary = "AppService 存在需关注日志"
    else:
        status = RuleStatus.PASS
        summary = "AppService 日志正常"

    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "error_count", "label": "错误条数", "value": error_count, "unit": "条"},
            {"key": "pool_exhausted_count", "label": "连接池耗尽条数", "value": len(pool_records), "unit": "条"},
            {"key": "sctp_error_count", "label": "SCTP 错误条数", "value": len(sctp_records), "unit": "条"},
        ],
        findings=findings,
        metadata={"processed_files": processed_files},
    )


inspector.run = _run
inspector.prepare = PrepareSpec(code="prepare.log.app_service", owner_code=inspector.code, run=_prepare)
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
