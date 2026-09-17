"""KPI 领域规则的文件识别、结果契约、阈值、隔离测试。"""

from pathlib import Path

import pytest

from app.inspectors.registry import registry
from app.models.schemas import RuleStatus
from app.services.executor import Executor, RuleContext
from app.services.scanning import match_paths


def _ctx(tmp_path: Path, files: dict[str, str]) -> RuleContext:
    data = tmp_path / "data"
    for relative, content in files.items():
        path = data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    logs: list[dict] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append({"level": level, "message": message, **(detail or {})})

    ctx = RuleContext(task_id="kpi-test", data_dir=data, log=log)
    ctx.files = [Path(relative) for relative in files]
    ctx.logs = logs
    return ctx


def _run_rule(code: str, ctx: RuleContext):
    registry.load_all()
    return registry.get(code).run(ctx)


def _kpi_content(objects: list[str], rows: list[list[object]], measurement: str) -> str:
    header = [
        "服务名",
        "实例",
        "可信度",
        "不可信原因",
        "测量开始时间",
        "测量结束时间",
        "周期(分钟)",
        *objects,
    ]
    lines = [
        "设备类型：XXX",
        f"测量单元名称：{measurement}",
        ",".join(header),
    ]
    for row in rows:
        period, start_at, end_at, *values = row
        data = ["BasicKpi", "", "可信", "", str(start_at), str(end_at), str(period), *values]
        lines.append(",".join(str(value) for value in data))
    return "\n".join(lines) + "\n"


_CALL_ROW = [15, "2026-09-01 10:00:00", "2026-09-01 10:15:00"]
_GOOD_CALL = _kpi_content(
    ["呼叫请求次数", "呼叫请求成功次数", "呼叫请求失败次数", "统计峰值", "最大并发"],
    [[*_CALL_ROW, 1200, 1195, 5, 100, 88]],
    "呼叫会话统计",
)


def test_kpi_source_patterns_match_only_own_domain_and_period(tmp_path: Path) -> None:
    files = {
        "kpi/kpi-api-5.csv": _kpi_content(["请求总数"], [[*_CALL_ROW, 1]], "API 统计"),
        "kpi/nested/kpi-media-15.csv": _kpi_content(["媒体请求"], [[*_CALL_ROW, 2]], "媒体统计"),
        "kpi/deep/ne333_Call_Session_API_Statistics_60_0_202609020000.csv": _GOOD_CALL,
        "kpi/kpi-other-15.csv": "ignored\n",
        "kpi/ne333_Call_Session_API_Statistics_20_0_202609020000.csv": "ignored\n",
        "kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv.bak": "ignored\n",
    }
    ctx = _ctx(tmp_path, files)
    registry.load_all()
    executor = Executor(registry)

    assert [p.as_posix() for p in match_paths([Path("kpi/kpi-api-5.csv")], [r"^kpi/kpi-api-5\.csv$"])] == [
        "kpi/kpi-api-5.csv"
    ]
    expected = {
        rule.code: [path.as_posix() for path in executor._matched_files(registry.get(rule.code), ctx)]
        for rule in (registry.get("kpi.api"), registry.get("kpi.media"), registry.get("kpi.call"))
    }
    assert expected["kpi.api"] == ["kpi/kpi-api-5.csv"]
    assert expected["kpi.media"] == ["kpi/nested/kpi-media-15.csv"]
    assert expected["kpi.call"] == ["kpi/deep/ne333_Call_Session_API_Statistics_60_0_202609020000.csv"]


def test_kpi_rules_exclude_dot_main_and_prepared_files(tmp_path: Path) -> None:
    files = {
        ".main/kpi/kpi-api-15.csv": _GOOD_CALL,
        "prepared/kpi.api/kpi-api-15.csv": _GOOD_CALL,
    }
    ctx = _ctx(tmp_path, files)
    registry.load_all()
    executor = Executor(registry)
    for code in ("kpi.api", "kpi.media", "kpi.call"):
        assert executor._matched_files(registry.get(code), ctx) == []


def test_kpi_rules_skip_without_own_files(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"other/readme.txt": "text"})
    for code, missing in (
        ("kpi.api", "API"),
        ("kpi.media", "媒体统计"),
        ("kpi.call", "呼叫"),
    ):
        result = _run_rule(code, ctx)
        assert result.status == RuleStatus.SKIP
        assert missing in result.summary


def test_kpi_api_passes_and_keeps_traceability(tmp_path: Path) -> None:
    content = _kpi_content(
        ["请求总数", "成功数"],
        [
            [5, "2026-09-01 10:00:00", "2026-09-01 10:05:00", 100, 99],
            [5, "2026-09-01 10:05:00", "2026-09-01 10:10:00", 110, 108],
        ],
        "API 统计",
    )
    ctx = _ctx(tmp_path, {"kpi/kpi-api-5.csv": content})
    result = _run_rule("kpi.api", ctx)
    assert result.status == RuleStatus.PASS
    assert [metric.value for metric in result.metrics] == [1, 2, 2, 0]
    file = result.metadata["kpi_files"][0]
    assert file["path"] == "kpi/kpi-api-5.csv"
    assert file["period_minutes"] == 5
    assert file["objects"] == ["请求总数", "成功数"]
    assert file["records"][0]["start_at"] == "2026-09-01T02:00:00+00:00"
    assert file["records"][0]["values"] == {"请求总数": 100.0, "成功数": 99.0}


def test_kpi_api_aggregates_files_and_isolates_bad_file(tmp_path: Path) -> None:
    good = _kpi_content(
        ["请求总数"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 10]],
        "API 统计",
    )
    bad = _kpi_content(["请求总数"], [], "API 统计")
    bad += "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15\n"
    ctx = _ctx(
        tmp_path,
        {"kpi/kpi-api-15.csv": good, "kpi/sub/kpi-api-15.csv": bad},
    )
    result = _run_rule("kpi.api", ctx)
    assert result.status == RuleStatus.FAIL
    assert [metric.value for metric in result.metrics] == [2, 1, 2, 1]
    assert [file["path"] for file in result.metadata["kpi_files"]] == [
        "kpi/kpi-api-15.csv",
        "kpi/sub/kpi-api-15.csv",
    ]
    assert result.findings
    assert result.findings[0].source_file == "kpi/sub/kpi-api-15.csv"


def test_kpi_media_aggregates_periods_without_threshold_findings(tmp_path: Path) -> None:
    five = _kpi_content(
        ["媒体请求"],
        [[5, "2026-09-01 10:00:00", "2026-09-01 10:05:00", 20]],
        "媒体统计",
    )
    sixty = _kpi_content(
        ["媒体请求"],
        [[60, "2026-09-01 10:00:00", "2026-09-01 11:00:00", 30]],
        "媒体统计",
    )
    ctx = _ctx(
        tmp_path,
        {"kpi/kpi-media-5.csv": five, "kpi/nested/kpi-media-60.csv": sixty},
    )
    result = _run_rule("kpi.media", ctx)
    assert result.status == RuleStatus.PASS
    assert [metric.value for metric in result.metrics] == [2, 2, 2, 0]
    assert [file["period_minutes"] for file in result.metadata["kpi_files"]] == [5, 60]
    assert not result.findings


def test_kpi_media_fails_on_period_mismatch(tmp_path: Path) -> None:
    content = _kpi_content(
        ["媒体请求"],
        [[5, "2026-09-01 10:00:00", "2026-09-01 10:05:00", 20]],
        "媒体统计",
    )
    ctx = _ctx(tmp_path, {"kpi/kpi-media-60.csv": content})
    result = _run_rule("kpi.media", ctx)
    assert result.status == RuleStatus.FAIL
    assert result.metadata["kpi_files"][0]["records"][0]["errors"][0]["code"] == "period_mismatch"


def test_kpi_call_threshold_pass_and_capacity_are_display_only(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": _GOOD_CALL})
    result = _run_rule("kpi.call", ctx)
    assert result.status == RuleStatus.PASS
    values = {metric.key: metric.value for metric in result.metrics}
    assert values["success_rate_min"] == pytest.approx(1195 / 1200 * 100)
    assert values["failure_rate_max"] == pytest.approx(5 / 1200 * 100)
    assert values["success_breach_count"] == 0
    assert values["failure_breach_count"] == 0
    assert values["capacity_metric_count"] == 2
    assert values["capacity_unknown_count"] == 0
    record = result.metadata["kpi_files"][0]["records"][0]
    assert [item["metric"] for item in record["capacity_values"]] == [
        "stat_peak",
        "max_concurrency",
    ]


def test_kpi_call_passes_when_rates_are_not_derivable(tmp_path: Path) -> None:
    content = _kpi_content(
        ["统计峰值", "最大并发"],
        [[15, "2026-09-01 10:00:00", "2026-09-01 10:15:00", 10, 8]],
        "呼叫会话统计",
    )
    ctx = _ctx(tmp_path, {"kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": content})
    result = _run_rule("kpi.call", ctx)
    assert result.status == RuleStatus.PASS
    values = {metric.key: metric.value for metric in result.metrics}
    assert values["success_rate_min"] == "N/A"
    assert values["failure_rate_max"] == "N/A"
    assert values["capacity_metric_count"] == 2


def test_kpi_call_formula_has_priority_and_rates_are_cross_reference_only(tmp_path: Path) -> None:
    content = _kpi_content(
        ["呼叫请求次数", "呼叫请求成功次数", "呼叫请求失败次数", "呼叫成功率", "呼叫失败率"],
        [[*_CALL_ROW, 100, 90, 10, 80, 20]],
        "呼叫会话统计",
    )
    ctx = _ctx(tmp_path, {"kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": content})
    result = _run_rule("kpi.call", ctx)
    assert result.status == RuleStatus.FAIL
    record = result.metadata["kpi_files"][0]["records"][0]
    assert record["values"]["呼叫成功率"] == 80.0
    assert record["derived"]["call_success_rate"] == 90.0
    assert record["derived"]["call_failure_rate"] == 10.0


def test_kpi_call_reports_consistency_and_parsing_separately(tmp_path: Path) -> None:
    inconsistent = _kpi_content(
        ["呼叫请求次数", "呼叫请求成功次数", "呼叫请求失败次数"],
        [[*_CALL_ROW, 100, 99, 1]],
        "呼叫会话统计",
    ).replace("100,99,1", "100,98,1")
    broken = _kpi_content(["呼叫请求次数"], [[*_CALL_ROW, "bad"]], "呼叫会话统计")
    ctx = _ctx(
        tmp_path,
        {
            "kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": inconsistent,
            "kpi/sub/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": broken,
        },
    )
    result = _run_rule("kpi.call", ctx)
    assert result.status == RuleStatus.FAIL
    values = {metric.key: metric.value for metric in result.metrics}
    assert values["consistency_error_count"] == 1
    assert values["parse_error_count"] == 1
    kinds = {finding.title for finding in result.findings}
    assert "呼叫数量自洽异常" in kinds
    assert "KPI 数据解析错误" in kinds
    consistency_finding = next(f for f in result.findings if f.title == "呼叫数量自洽异常")
    assert "呼叫请求成功次数" in consistency_finding.evidence


def test_kpi_call_config_error_is_not_silently_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.config_dir", tmp_path / "missing.yaml")
    ctx = _ctx(tmp_path, {"kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": _GOOD_CALL})
    result = _run_rule("kpi.call", ctx)
    assert result.status == RuleStatus.ERROR
    assert result.summary == "KPI 配置加载失败"


def test_kpi_domains_remain_isolated(tmp_path: Path) -> None:
    bad_api = _kpi_content(["请求总数"], [], "API 统计")
    bad_api += "bad-row\n"
    files = {
        "kpi/kpi-api-15.csv": bad_api,
        "kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": _GOOD_CALL,
    }
    ctx = _ctx(tmp_path, files)
    api_result = _run_rule("kpi.api", ctx)
    call_result = _run_rule("kpi.call", ctx)
    media_result = _run_rule("kpi.media", ctx)
    assert api_result.status == RuleStatus.FAIL
    assert call_result.status == RuleStatus.PASS
    assert media_result.status == RuleStatus.SKIP
    assert media_result.skip_reason


def test_kpi_domain_errors_do_not_change_other_domain_results(tmp_path: Path) -> None:
    broken_api = _kpi_content(["请求总数"], [], "API 统计")
    broken_api += "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15\n"
    broken_media = _kpi_content(["媒体请求"], [], "媒体统计")
    broken_media += "BasicKpi,,可信,,2026-09-01 10:00:00,2026-09-01 10:15:00,15\n"
    files = {
        "kpi/kpi-api-15.csv": broken_api,
        "kpi/kpi-media-15.csv": broken_media,
        "kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv": _GOOD_CALL,
    }
    ctx = _ctx(tmp_path, files)
    api = _run_rule("kpi.api", ctx)
    media = _run_rule("kpi.media", ctx)
    call = _run_rule("kpi.call", ctx)

    assert api.status == RuleStatus.FAIL
    assert media.status == RuleStatus.FAIL
    assert call.status == RuleStatus.PASS
    assert call.findings == []
    assert [metric.value for metric in call.metrics] == [
        1,
        1,
        0,
        0,
        pytest.approx(1195 / 1200 * 100),
        pytest.approx(5 / 1200 * 100),
        0,
        0,
        2,
        0,
    ]
    assert [file["path"] for file in call.metadata["kpi_files"]] == [
        "kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv"
    ]


def test_all_kpi_domains_skip_without_any_kpi_files(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"logs/app.log": "text"})
    for code in ("kpi.api", "kpi.media", "kpi.call"):
        result = _run_rule(code, ctx)
        assert result.status == RuleStatus.SKIP
        assert result.skip_reason


@pytest.mark.parametrize("code", ["kpi.api", "kpi.media", "kpi.call"])
def test_kpi_rule_version_bumped_for_real_csv_format(code: str) -> None:
    registry.load_all()
    assert registry.get(code).rule_version == "1.2.0"
