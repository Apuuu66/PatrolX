"""alarm.flapping（030）行为测试：解析、六态、窗口证据、容错与参数重跑。"""

from __future__ import annotations

import ast
import importlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.inspectors.registry import registry
from app.services.unit_runtime import RuleContext
from tests.fixtures.make_real_package import ALARM_CSV_001, ALARM_CSV_002, ALARM_CSV_003

# 真实告警 CSV 表头（App Problem Scene 导出，12 列），直接复用样例包首行，避免口径漂移。
HEADER = ALARM_CSV_001.splitlines()[0]

# 中文告警级别 -> 契约严重度，供测试内断言与构造数据共用。
SEVERITY_ZH = {"CRITICAL": "紧急", "HIGH": "严重", "MEDIUM": "重要", "LOW": "次要"}


@pytest.fixture(autouse=True)
def _load_registry() -> None:
    """注册表按需装载全部规则，保证真实注册路径可被断言。"""
    registry.load_all()


METRIC_KEYS = [
    "alarm_groups",
    "flapping_groups",
    "uncleared_repeated_groups",
    "short_alarm_groups",
    "stable_groups",
    "observation_insufficient_groups",
    "out_of_window_groups",
    "unrecovered_after_window_groups",
    "excluded_rows",
    "duplicate_rows",
    "failed_files",
]

# 声明值必须是字符串：API 契约 InspectorInfo.params 为 list[dict[str, str]]。
PARAM_DEFAULTS: dict[str, Any] = {
    "short_alarm_sec": "300",
    "repeat_window_sec": "3600",
    "min_repeat_count": "3",
    "flap_gap_sec": "1800",
    "stable_observation_sec": "1800",
    "operation_window": "00:00-02:00",
    "operation_window_enabled": "true",
}


def alarm_row(
    alarm_id: str,
    created: str,
    cleared: str = "",
    code: str = "1050",
    severity: str = "MEDIUM",
    status: str = "",
    obj: str = "UMF核心服务",
    description: str = "演示告警",
    app_id: str = "9002",
    app_name: str = "",
    repeat_count: str = "1",
    event_type: str = "通信告警",
    clear_type: str = "",
    location: str = "",
) -> str:
    """按真实告警 CSV 表头构造单行数据。

    ``obj`` 对应真实表头的“应用名称”分组键；``status`` 仅为兼容既有测试调用保留：
    真实导出没有状态列，恢复结论只由清除时间决定。
    """
    del status
    app_name = app_name or obj
    level = SEVERITY_ZH.get(severity.upper(), severity)
    if cleared and not clear_type:
        clear_type = "自动清除"
    cells = [
        alarm_id,
        app_id,
        app_name,
        code,
        description,
        level,
        created,
        cleared,
        clear_type,
        event_type,
        repeat_count,
        location,
    ]
    escaped = ['"' + cell.replace('"', '""') + '"' if "," in cell else cell for cell in cells]
    return ",".join(escaped)


def csv_text(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def make_ctx(tmp_path: Path, files: dict[str, str]) -> RuleContext:
    """在临时任务目录写入文件并返回绑定相对路径的 RuleContext。"""
    data_dir = tmp_path / "task-030"
    data_dir.mkdir(parents=True, exist_ok=True)
    for relative, text in files.items():
        target = data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    ctx = RuleContext(task_id="task-030", data_dir=data_dir, log=lambda *args, **kwargs: None)
    ctx.files = [Path(relative) for relative in files]
    return ctx


@pytest.fixture
def flapping_params():
    """临时覆盖 alarm.flapping 的声明参数默认值，测试结束自动恢复。"""
    inspector = registry.get("alarm.flapping")
    original = [dict(item) for item in inspector.params]

    def override(**values: Any) -> None:
        keys = {item["key"] for item in inspector.params}
        unknown = set(values) - keys
        assert not unknown, f"未知参数: {sorted(unknown)}"
        for item in inspector.params:
            if item["key"] in values:
                item["default"] = values[item["key"]]

    yield override
    inspector.params[:] = original


def run_flapping(ctx: RuleContext):
    return registry.get("alarm.flapping").run(ctx)


# ---------------------------------------------------------------------------
# 基础层：注册元数据、参数表、skip 契约、零跨规则依赖（FR-001/002/015/018）
# ---------------------------------------------------------------------------


def test_rule_registered_with_contract_metadata() -> None:
    inspector = registry.get("alarm.flapping")
    assert inspector.name
    assert inspector.category.value == "alarm"
    assert inspector.priority.name == "P1"
    assert inspector.severity.value == "high"
    assert inspector.rule_version == "1.1.0"
    assert inspector.source_refs == ["alarm_all"]
    assert inspector.prepare is None
    assert {item["key"]: item["default"] for item in inspector.params} == PARAM_DEFAULTS


def test_rule_declares_contract_metric_keys() -> None:
    inspector = registry.get("alarm.flapping")
    keys = [item.key if hasattr(item, "key") else item["key"] for item in inspector.outputs_metrics]
    assert keys == METRIC_KEYS


def test_rule_has_no_cross_rule_dependencies() -> None:
    module = importlib.import_module("app.inspectors.alarm.flapping")
    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        name
        for name in imported
        if name.startswith("app.inspectors") and name not in {"app.inspectors.base", "app.inspectors.registry"}
    }
    assert forbidden == set(), f"规则不得导入其他巡检规则: {sorted(forbidden)}"
    assert "alarm.stat" not in source
    assert "result_dir" not in source
    assert "prepared_dir" not in source


def test_skip_without_matching_alarm_files(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, {})
    result = run_flapping(ctx)
    assert result.status.value == "skip"
    assert result.skip_reason and "告警" in result.skip_reason


# ---------------------------------------------------------------------------
# US1：六态判定、Finding 与元数据契约（FR-006–FR-010、FR-013、SC-002/003/007）
# ---------------------------------------------------------------------------


def group_detail(result: Any, alarm_code: str, object_name: str) -> dict[str, Any]:
    """取出结果元数据中的指定分组明细。"""
    for group in result.metadata["alarm_flapping"]["groups"]:
        if group["alarm_code"] == alarm_code and group["object"] == object_name:
            return group
    raise AssertionError(f"未找到分组 {alarm_code}/{object_name}")


def metric_value(result: Any, key: str) -> Any:
    for metric in result.metrics:
        if metric.key == key:
            return metric.value
    raise AssertionError(f"未找到指标 {key}")


def uncleared_rows(prefix: str, code: str, starts: list[str]) -> list[str]:
    """构造同一分组的未清除记录（status 字段只作展示）。"""
    return [
        alarm_row(f"{prefix}{index}", start, "", code=code, severity="CRITICAL", status="处理中", obj="UMF核心服务")
        for index, start in enumerate(starts)
    ]


def test_cleared_repeated_group_produces_high_finding(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row("1", "2026-09-02 10:00:00", "2026-09-02 10:10:00"),
                alarm_row("2", "2026-09-02 10:20:00", "2026-09-02 10:30:00"),
                alarm_row("3", "2026-09-02 10:40:00", "2026-09-02 10:50:00"),
                alarm_row("9", "2026-09-02 12:00:00", "2026-09-02 12:20:00", code="9999", obj="other"),
            )
        },
    )
    result = run_flapping(ctx)
    group = group_detail(result, "1050", "UMF核心服务")
    assert group["state"] == "cleared_repeated"
    assert group["repeated"] is True
    assert group["is_short"] is False
    assert group["min_repeat_gap_sec"] == 600
    assert group["recent_cleared_at"] == "2026-09-02T10:50:00+08:00"
    assert group["observation_insufficient"] is False
    assert result.status.value == "fail"
    assert [finding.finding_id for finding in result.findings] == ["alarm.flapping-cleared_repeated-1050-UMF核心服务"]
    finding = result.findings[0]
    assert finding.severity.value == "high"
    assert "分组 1050 / UMF核心服务" in finding.evidence
    assert "最短复发间隔 600 秒" in finding.evidence
    assert "3600" in finding.evidence


def test_single_short_alarm_produces_medium_finding(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row("1", "2026-09-01 10:00:04", "2026-09-01 10:00:30", code="SCTP_LINK_DOWN", obj="UMF核心服务"),
                alarm_row("9", "2026-09-01 12:00:00", "2026-09-01 12:20:00", code="9999", obj="other"),
            )
        },
    )
    result = run_flapping(ctx)
    group = group_detail(result, "SCTP_LINK_DOWN", "UMF核心服务")
    assert group["state"] == "cleared_short"
    assert group["is_short"] is True
    assert group["max_duration_sec"] == 26
    assert group["observation_gap_sec"] == 8370
    assert result.status.value == "warn"
    assert [finding.finding_id for finding in result.findings] == [
        "alarm.flapping-cleared_short-SCTP_LINK_DOWN-UMF核心服务"
    ]
    assert result.findings[0].severity.value == "medium"


def test_cleared_group_with_enough_observation_is_stable_and_silent(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row("1", "2026-09-01 10:00:00", "2026-09-01 10:10:00"),
                alarm_row("9", "2026-09-01 12:00:00", "2026-09-01 12:20:00", code="9999", obj="other"),
            )
        },
    )
    result = run_flapping(ctx)
    group = group_detail(result, "1050", "UMF核心服务")
    assert group["state"] == "cleared_stable"
    assert group["repeated"] is False
    assert group["is_short"] is False
    assert group["observation_insufficient"] is False
    assert group["observation_gap_sec"] == 7800
    assert result.findings == []
    # 9999/other 恰在覆盖窗末端清除，观察窗不足 -> warn；稳定分组本身不产生 Finding。
    assert result.status.value == "warn"


def test_operation_window_evidence_spans_days_without_downgrading_state(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row("1", "2026-09-01 23:30:00", "2026-09-01 23:40:00"),
                alarm_row("2", "2026-09-02 00:30:00", "2026-09-02 00:45:00"),
                alarm_row("3", "2026-09-02 02:30:00", "2026-09-02 02:40:00"),
                alarm_row("9", "2026-09-02 06:00:00", "2026-09-02 06:20:00", code="9999", obj="other"),
            )
        },
    )
    result = run_flapping(ctx)
    group = group_detail(result, "1050", "UMF核心服务")
    assert group["state"] == "cleared_stable"
    assert group["in_window_occurrences"] == 1
    assert group["out_of_window_occurrences"] == 2
    assert group["out_of_window_reappear"] is True
    assert group["unrecovered_after_window"] is False


def test_finding_order_follows_state_priority_then_recent_seen_desc(tmp_path: Path) -> None:
    rows = [
        *uncleared_rows("u1", "U_OLD", ["2026-09-02 09:00:00", "2026-09-02 09:20:00", "2026-09-02 09:40:00"]),
        *uncleared_rows("u2", "U_NEW", ["2026-09-02 10:00:00", "2026-09-02 10:20:00", "2026-09-02 10:40:00"]),
        alarm_row("r1", "2026-09-02 11:00:00", "2026-09-02 11:10:00", code="R_OLD"),
        alarm_row("r2", "2026-09-02 11:20:00", "2026-09-02 11:30:00", code="R_OLD"),
        alarm_row("r3", "2026-09-02 11:40:00", "2026-09-02 11:50:00", code="R_OLD"),
        alarm_row("r4", "2026-09-02 12:00:00", "2026-09-02 12:10:00", code="R_NEW"),
        alarm_row("r5", "2026-09-02 12:20:00", "2026-09-02 12:30:00", code="R_NEW"),
        alarm_row("r6", "2026-09-02 12:40:00", "2026-09-02 12:50:00", code="R_NEW"),
        alarm_row("s1", "2026-09-02 13:00:00", "2026-09-02 13:00:26", code="S_OLD"),
        alarm_row("s2", "2026-09-02 14:00:00", "2026-09-02 14:00:26", code="S_NEW"),
    ]
    result = run_flapping(make_ctx(tmp_path, {"alarm/a.csv": csv_text(*rows)}))
    assert [finding.finding_id for finding in result.findings] == [
        "alarm.flapping-uncleared_repeated-U_NEW-UMF核心服务",
        "alarm.flapping-uncleared_repeated-U_OLD-UMF核心服务",
        "alarm.flapping-cleared_repeated-R_NEW-UMF核心服务",
        "alarm.flapping-cleared_repeated-R_OLD-UMF核心服务",
        "alarm.flapping-cleared_short-S_NEW-UMF核心服务",
        "alarm.flapping-cleared_short-S_OLD-UMF核心服务",
    ]
    assert [finding.severity.value for finding in result.findings] == [
        "critical",
        "critical",
        "high",
        "high",
        "medium",
        "medium",
    ]
    assert result.status.value == "fail"


def test_findings_are_capped_at_twenty(tmp_path: Path) -> None:
    rows: list[str] = []
    for index in range(25):
        rows.extend(
            alarm_row(
                f"g{index}-{step}",
                f"2026-09-02 10:{index:02d}:{step * 10:02d}",
                "",
                code=f"G{index:02d}",
                severity="CRITICAL",
                status="处理中",
                obj="UMF核心服务",
            )
            for step in range(3)
        )
    result = run_flapping(make_ctx(tmp_path, {"alarm/a.csv": csv_text(*rows)}))
    assert len(result.findings) == 20
    assert result.findings[0].finding_id == "alarm.flapping-uncleared_repeated-G24-UMF核心服务"
    assert result.findings[-1].finding_id == "alarm.flapping-uncleared_repeated-G05-UMF核心服务"
    metadata = result.metadata["alarm_flapping"]
    assert metadata["totals"]["findings_truncated"] is True
    assert metadata["state_counts"]["uncleared_repeated"] == 25
    assert metric_value(result, "uncleared_repeated_groups") == 25
    assert metric_value(result, "flapping_groups") == 25


def test_finding_id_uses_unknown_placeholder_for_empty_object(tmp_path: Path) -> None:
    text = "\n".join(f"ALARM 2026-09-02 03:{minute:02d}:00 EVT-9 SCTP链路中断 HIGH 处理中" for minute in (0, 20, 40))
    result = run_flapping(make_ctx(tmp_path, {"alarm/a.txt": text + "\n"}))
    group = group_detail(result, "EVT-9", "")
    assert group["state"] == "uncleared_repeated"
    assert [finding.finding_id for finding in result.findings] == ["alarm.flapping-uncleared_repeated-EVT-9-unknown"]


def test_groups_are_truncated_at_groups_max(tmp_path: Path) -> None:
    rows = [
        alarm_row(
            f"c{index}",
            f"2026-09-02 10:{index // 60:02d}:{index % 60:02d}",
            "",
            code=f"C{index:04d}",
            status="未处理",
            obj="o",
        )
        for index in range(501)
    ]
    result = run_flapping(make_ctx(tmp_path, {"alarm/a.csv": csv_text(*rows)}))
    metadata = result.metadata["alarm_flapping"]
    assert metadata["totals"]["groups"] == 501
    assert metadata["totals"]["groups_truncated"] is True
    assert len(metadata["groups"]) == 500
    assert metadata["groups"][0]["alarm_code"] == "C0500"
    assert metadata["groups"][-1]["alarm_code"] == "C0001"
    assert metadata["state_counts"]["uncleared_single"] == 501
    assert metric_value(result, "alarm_groups") == 501
    assert result.findings == []
    assert result.status.value == "warn"


# ---------------------------------------------------------------------------
# US2：status 字段不是恢复证据，未清除反复优先输出（FR-004/006/011）
# ---------------------------------------------------------------------------


def test_uncleared_status_is_not_recovery_evidence(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                # 同分组：一条已清除 + 一条 status=已处理但无清除时间
                alarm_row("1", "2026-09-02 09:00:00", "2026-09-02 09:10:00", code="MIXED"),
                alarm_row("2", "2026-09-02 09:20:00", "", code="MIXED", status="已处理"),
                # 同分组：status=已处理/处理中但无清除时间，60 分钟内 3 次
                alarm_row("3", "2026-09-02 00:10:00", "", code="1051", status="已处理", obj="UMF核心服务"),
                alarm_row("4", "2026-09-02 00:40:00", "", code="1051", status="处理中", obj="UMF核心服务"),
                alarm_row("5", "2026-09-02 01:00:00", "", code="1051", status="已处理", obj="UMF核心服务"),
                alarm_row("9", "2026-09-02 06:00:00", "2026-09-02 06:20:00", code="ANCHOR", obj="other"),
            )
        },
    )
    result = run_flapping(ctx)
    metadata = result.metadata["alarm_flapping"]

    mixed = group_detail(result, "MIXED", "UMF核心服务")
    assert mixed["cleared_count"] == 1
    assert mixed["uncleared_count"] == 1
    assert mixed["state"] == "uncleared_single"
    assert mixed["observation_insufficient"] is True

    repeated = group_detail(result, "1051", "UMF核心服务")
    assert repeated["state"] == "uncleared_repeated"
    assert repeated["cleared_count"] == 0
    assert repeated["uncleared_count"] == 3
    assert repeated["recent_cleared_at"] is None
    assert repeated["min_repeat_gap_sec"] is None
    assert repeated["observation_gap_sec"] is None
    assert repeated["observation_insufficient"] is True
    assert repeated["unrecovered_after_window"] is True

    assert metadata["groups"][0]["alarm_code"] == "1051"
    assert result.status.value == "fail"
    assert [finding.finding_id for finding in result.findings] == ["alarm.flapping-uncleared_repeated-1051-UMF核心服务"]
    assert result.findings[0].severity.value == "critical"
    assert "窗口后仍未恢复" in result.findings[0].evidence


# ---------------------------------------------------------------------------
# US3：数据不足显式标注（FR-015/016、SC-004）
# ---------------------------------------------------------------------------


def test_row_level_anomalies_are_excluded_without_breaking_other_groups(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row("1", "not-a-time", "", code="BAD_CREATED"),
                alarm_row("2", "2026-09-02 09:00:00", "not-a-time", code="BAD_CLEARED"),
                alarm_row("3", "2026-09-02 10:00:00", "2026-09-02 09:00:00", code="BAD_ORDER"),
                alarm_row("4", "2026-09-02 09:00:00", "", code=""),
                alarm_row("5", "2026-09-02 09:00:00", "2026-09-02 09:10:00", code="OK"),
                alarm_row("6", "2026-09-02 12:00:00", "2026-09-02 12:20:00", code="ANCHOR", obj="other"),
            )
        },
    )
    result = run_flapping(ctx)
    metadata = result.metadata["alarm_flapping"]
    assert metadata["totals"]["rows"] == 6
    assert metadata["totals"]["valid_rows"] == 2
    assert metadata["totals"]["excluded_rows"] == 4
    assert metadata["totals"]["groups"] == 2
    assert metric_value(result, "excluded_rows") == 4
    notes = "；".join(metadata["notes"])
    reasons = (
        "unparseable_created_time",
        "unparseable_cleared_time",
        "cleared_before_created",
        "missing_alarm_code",
    )
    for reason in reasons:
        assert reason in notes
    assert group_detail(result, "OK", "UMF核心服务")["state"] == "cleared_stable"
    assert result.status.value == "warn"


def test_duplicates_missing_object_and_mixed_formats_are_merged(tmp_path: Path) -> None:
    duplicate = alarm_row("7", "2026-09-02 10:00:00", "", code="EVT-1", obj="")
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                duplicate,
                duplicate,
                alarm_row("8", "2026-09-02 10:20:00", "", code="EVT-1", obj=""),
            ),
            "alarm/b.txt": "\n".join(
                [
                    "ALARM 2026-09-02 10:40:00 EVT-1 文本告警 HIGH 处理中",
                    "ALARM 2026-09-02 11:00:00 EVT-1 文本告警 HIGH 处理中",
                ]
            )
            + "\n",
        },
    )
    result = run_flapping(ctx)
    metadata = result.metadata["alarm_flapping"]
    assert metadata["totals"]["duplicate_rows"] == 1
    assert metric_value(result, "duplicate_rows") == 1
    group = group_detail(result, "EVT-1", "")
    assert group["occurrence_count"] == 4
    assert group["state"] == "uncleared_repeated"
    assert {item["source_file"] for item in group["evidence_records"]} == {"alarm/a.csv", "alarm/b.txt"}
    assert result.status.value == "fail"


def test_unreadable_file_is_isolated(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/good.csv": csv_text(
                alarm_row("1", "2026-09-02 09:00:00", "2026-09-02 09:10:00"),
                alarm_row("2", "2026-09-02 12:00:00", "2026-09-02 12:20:00", code="ANCHOR", obj="other"),
            )
        },
    )
    (ctx.data_dir / "alarm/broken.csv").write_bytes(b"\x80")
    ctx.files.append(Path("alarm/broken.csv"))

    result = run_flapping(ctx)
    metadata = result.metadata["alarm_flapping"]
    assert metadata["totals"]["failed_files"] == 1
    assert metric_value(result, "failed_files") == 1
    assert any("解析失败" in note for note in metadata["notes"])
    assert group_detail(result, "1050", "UMF核心服务")["state"] == "cleared_stable"


@pytest.mark.parametrize(
    ("anchor_cleared", "expected_state"),
    [
        ("2026-09-02 09:39:59", "observation_insufficient"),
        ("2026-09-02 09:40:00", "cleared_stable"),
    ],
)
def test_observation_window_boundary_blocks_false_stable(
    tmp_path: Path, anchor_cleared: str, expected_state: str
) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row("1", "2026-09-02 09:00:00", "2026-09-02 09:10:00"),
                alarm_row("9", "2026-09-02 09:20:00", anchor_cleared, code="ANCHOR", obj="other"),
            )
        },
    )
    result = run_flapping(ctx)
    group = group_detail(result, "1050", "UMF核心服务")
    assert group["state"] == expected_state
    assert group["observation_insufficient"] is (expected_state == "observation_insufficient")


def test_all_rows_unparseable_returns_skip_with_reason_counts(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row("1", "not-a-time", "", code="X"),
                alarm_row("2", "", "2026-09-02 10:00:00", code="Y"),
            )
        },
    )
    result = run_flapping(ctx)
    assert result.status.value == "skip"
    assert result.skip_reason is not None
    assert "2" in result.skip_reason
    assert "unparseable_created_time" in result.skip_reason
    assert metric_value(result, "excluded_rows") == 2
    assert result.metadata["alarm_flapping"]["totals"]["groups"] == 0


# ---------------------------------------------------------------------------
# US4：阈值可配置、可解释、单规则重跑一致（FR-018/022/024、SC-006）
# ---------------------------------------------------------------------------


def threshold_rows() -> list[str]:
    """阈值重跑基线：未清除反复 + 已清除反复 + 单次短告警。"""
    return [
        *uncleared_rows("f1", "1051", ["2026-09-02 00:10:00", "2026-09-02 00:40:00", "2026-09-02 01:00:00"]),
        alarm_row("f2", "2026-09-02 11:00:00", "2026-09-02 11:10:00", code="1052"),
        alarm_row("f3", "2026-09-02 11:30:00", "2026-09-02 11:40:00", code="1052"),
        alarm_row("f4", "2026-09-02 11:50:00", "2026-09-02 12:00:00", code="1052"),
        alarm_row("f5", "2026-09-01 10:00:04", "2026-09-01 10:00:30", code="SCTP_LINK_DOWN", obj="UMF核心服务"),
        alarm_row("f9", "2026-09-02 12:05:30", "2026-09-02 12:20:00", code="ANCHOR", obj="other"),
    ]


def test_min_repeat_count_threshold_changes_conclusions(flapping_params, tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, {"alarm/a.csv": csv_text(*threshold_rows())})
    baseline = run_flapping(ctx)
    assert baseline.status.value == "fail"
    assert len(baseline.findings) == 3

    flapping_params(min_repeat_count=4)
    changed = run_flapping(ctx)
    assert group_detail(changed, "1051", "UMF核心服务")["state"] == "uncleared_single"
    assert group_detail(changed, "1052", "UMF核心服务")["state"] == "observation_insufficient"
    assert changed.status.value == "warn"
    assert [finding.finding_id for finding in changed.findings] == [
        "alarm.flapping-cleared_short-SCTP_LINK_DOWN-UMF核心服务"
    ]
    assert changed.metadata["alarm_flapping"]["policy"]["min_repeat_count"] == 4
    assert registry.get("alarm.flapping").rule_version == "1.1.0"

    flapping_params(min_repeat_count=3)
    restored = run_flapping(ctx)
    assert restored.status.value == "fail"
    assert len(restored.findings) == 3
    assert group_detail(restored, "1051", "UMF核心服务")["state"] == "uncleared_repeated"


def test_operation_window_can_be_disabled_without_changing_states(flapping_params, tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, {"alarm/a.csv": csv_text(*threshold_rows())})
    enabled = run_flapping(ctx)
    assert metric_value(enabled, "out_of_window_groups") >= 0
    assert group_detail(enabled, "1051", "UMF核心服务")["unrecovered_after_window"] is True
    assert group_detail(enabled, "1051", "UMF核心服务")["in_window_occurrences"] == 3

    flapping_params(operation_window_enabled=False)
    disabled = run_flapping(ctx)
    assert disabled.metadata["alarm_flapping"]["policy"]["operation_window_enabled"] is False
    for group in disabled.metadata["alarm_flapping"]["groups"]:
        assert group["in_window_occurrences"] == 0
        assert group["out_of_window_occurrences"] == 0
        assert group["out_of_window_reappear"] is False
        assert group["unrecovered_after_window"] is False
    assert [group["state"] for group in disabled.metadata["alarm_flapping"]["groups"]] == [
        group["state"] for group in enabled.metadata["alarm_flapping"]["groups"]
    ]
    assert metric_value(disabled, "out_of_window_groups") == 0
    assert metric_value(disabled, "unrecovered_after_window_groups") == 0


def test_real_export_context_fields_are_surfaced_without_affecting_state(tmp_path: Path) -> None:
    """真实导出的应用ID/定位信息/清除类型/事件类型/重复次数只作展示，不改变判定。"""
    ctx = make_ctx(
        tmp_path,
        {
            "alarm/a.csv": csv_text(
                alarm_row(
                    "1",
                    "2026-09-02 10:00:00",
                    "2026-09-02 10:00:10",
                    app_id="9002",
                    location="pod-umf-1",
                    clear_type="自动清除",
                    event_type="性能告警",
                    repeat_count="3",
                ),
                alarm_row(
                    "2",
                    "2026-09-02 10:05:00",
                    "2026-09-02 10:05:10",
                    location="pod-umf-2",
                    clear_type="手动清除",
                    event_type="性能告警",
                    repeat_count="2",
                ),
                alarm_row(
                    "3",
                    "2026-09-02 10:10:00",
                    "2026-09-02 10:10:10",
                    location="pod-umf-1",
                    clear_type="自动清除",
                    event_type="性能告警",
                    repeat_count="",
                ),
                # 无上下文字段的历史行：展示层保持空，不推断任何定位信息。
                alarm_row(
                    "9",
                    "2026-09-02 12:00:00",
                    code="9999",
                    obj="other",
                    app_id="",
                    event_type="",
                    repeat_count="",
                    location="",
                ),
            )
        },
    )
    result = run_flapping(ctx)
    group = group_detail(result, "1050", "UMF核心服务")
    assert group["state"] == "cleared_repeated"
    assert group["app_ids"] == ["9002"]
    assert group["locations"] == ["pod-umf-1", "pod-umf-2"]
    assert group["clear_types"] == ["自动清除", "手动清除"]
    assert group["event_types"] == ["性能告警"]
    assert group["source_repeat_max"] == 3
    finding = next(item for item in result.findings if item.finding_id.endswith("-1050-UMF核心服务"))
    assert "定位 pod-umf-1、pod-umf-2" in finding.evidence

    bare = group_detail(result, "9999", "other")
    assert bare["app_ids"] == []
    assert bare["locations"] == []
    assert bare["clear_types"] == []
    assert bare["event_types"] == []
    assert bare["source_repeat_max"] is None


# ---------------------------------------------------------------------------
# T031 性能看护：真实样例耗时预算、单次读取与随行数线性增长（FR-021）
# ---------------------------------------------------------------------------

PERF_BUDGET_SEC = 0.1

REAL_SAMPLE_FILES = {
    "alarm/alarm_history_202609010101137101_001.csv": ALARM_CSV_001,
    "alarm/alarm_history_202609010101137101_002.csv": ALARM_CSV_002,
    "alarm/alarm_history_202609010101137101_003.csv": ALARM_CSV_003,
}


def elapsed_min(runs: int, ctx: RuleContext) -> float:
    """取多次运行的最小耗时，削弱调度与缓存抖动。"""
    best = float("inf")
    for _ in range(runs):
        started = time.perf_counter()
        run_flapping(ctx)
        best = min(best, time.perf_counter() - started)
    return best


def synthetic_alarm_rows(group_count: int, repeats: int) -> list[str]:
    """构造 group_count 个已清除分组、每组 repeats 次出现的告警行。"""
    base = datetime(2026, 9, 2, 0, 0, 0)
    rows: list[str] = []
    counter = 0
    for index in range(group_count):
        first_seen = base + timedelta(minutes=index * 3)
        for repeat in range(repeats):
            counter += 1
            start = first_seen + timedelta(seconds=repeat * 120)
            rows.append(
                alarm_row(
                    str(10_000 + counter),
                    start.strftime("%Y-%m-%d %H:%M:%S"),
                    (start + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S"),
                    code=f"CODE_{index:04d}",
                    obj=f"pod-{index:04d}",
                )
            )
    return rows


def test_real_sample_package_stays_within_runtime_budget(tmp_path: Path) -> None:
    """真实样例包（22 行 / 3 个 CSV）内规则耗时必须留在 100ms 预算内。"""
    ctx = make_ctx(tmp_path, dict(REAL_SAMPLE_FILES))
    elapsed = elapsed_min(3, ctx)
    assert elapsed < PERF_BUDGET_SEC, (
        f"真实样例包规则耗时 {elapsed * 1000:.1f}ms，超过 {PERF_BUDGET_SEC * 1000:.0f}ms 预算"
    )


def test_alarm_files_are_read_exactly_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """单次遍历：每个匹配文件只解码一次，不做二次扫描。"""
    module = importlib.import_module("app.inspectors.alarm.flapping")
    original = module.read_text_with_fallback
    reads: list[Path] = []

    def spy(path, *args, **kwargs):
        reads.append(Path(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(module, "read_text_with_fallback", spy)
    ctx = make_ctx(tmp_path, dict(REAL_SAMPLE_FILES))
    result = run_flapping(ctx)
    assert metric_value(result, "alarm_groups") == 17
    assert sorted(reads) == sorted(tmp_path / "task-030" / relative for relative in REAL_SAMPLE_FILES)


def test_runtime_scales_linearly_with_row_count(tmp_path: Path) -> None:
    """行数放大 12 倍时耗时不得超线性劣化（单遍扫描 + 分组聚合）。"""
    small_ctx = make_ctx(tmp_path / "small", {"alarm/big.csv": csv_text(*synthetic_alarm_rows(100, 8))})
    large_ctx = make_ctx(tmp_path / "large", {"alarm/big.csv": csv_text(*synthetic_alarm_rows(100, 96))})
    small = elapsed_min(3, small_ctx)
    large = elapsed_min(3, large_ctx)
    assert metric_value(run_flapping(small_ctx), "alarm_groups") == 100
    assert metric_value(run_flapping(large_ctx), "alarm_groups") == 100
    # 12 倍数据量配 30 倍上限：留足固定开销与调度抖动余量，仍能拦截二次扫描类劣化。
    assert large < small * 30 + 0.05, (
        f"行数放大 12 倍后耗时 {small * 1000:.1f}ms → {large * 1000:.1f}ms，疑似超线性实现"
    )
